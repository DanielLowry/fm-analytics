"""Evidence-aware league ordering and team/player drilldown models."""
from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Mapping, MutableMapping

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.league_insights import (
    ScoutingPriority,
    TeamChange,
    TeamSummary,
    coverage,
    knowledge_level,
    scouting_priorities,
    slot_alternatives,
    team_change,
)
from fm_analytics.analytics.role_matrix import RoleMatrix, build_role_matrix
from fm_analytics.analytics.role_scoring import RoleScoreCache, ScoreBand
from fm_analytics.analytics.role_matrix import PlayerRoleFit
from fm_analytics.domain.models import Player
from fm_analytics.analytics.team_comparison import TeamXIComparison, compare_team_xi
from fm_analytics.analytics.xi_models import FamiliarityPolicy, PlayerSelectionInput, ReadinessPolicy, TacticFitPolicy
from fm_analytics.domain.leagues import LeagueCapture, LeagueRoster


@dataclass(frozen=True)
class LeagueTeamReport:
    roster: LeagueRoster
    comparison: TeamXIComparison
    roles: RoleMatrix
    assumptions: tuple[str, ...]
    knowledge_counts: tuple[int, int, int, int] = (0, 0, 0, 0)
    rank_lower: int | None = None
    rank_upper: int | None = None
    relative_to_us: str = "Not comparable"
    # (known, partly known, unknown) starters in the conservative XI.
    starters: tuple[int, int, int] = (0, 0, 0)
    priorities: tuple[ScoutingPriority, ...] = ()
    change: TeamChange | None = None
    # Per scenario ("upper", "lower"), per slot: who outside that XI could play it.
    alternatives: Mapping[str, Mapping[str, tuple]] = field(default_factory=dict)

    @property
    def score(self) -> ScoreBand | None:
        return self.comparison.score


@dataclass(frozen=True)
class LeagueReport:
    capture: LeagueCapture
    tactic_keys: tuple[str, ...]
    teams: tuple[LeagueTeamReport, ...]

    @property
    def comparable_count(self) -> int:
        return sum(team.score is not None for team in self.teams)

    @property
    def complete_roster_count(self) -> int:
        return sum(team.roster.roster_complete for team in self.teams)

    def summaries(self) -> dict[str, TeamSummary]:
        return {team.roster.squad.club.id: TeamSummary.of(team, self.capture.game.game_date) for team in self.teams}


@dataclass(frozen=True)
class LeaguePlayerRanking:
    player: Player
    best_role: PlayerRoleFit | None
    score: ScoreBand | None
    # (exact, ranged, unknown, uncaptured) over every role-scoring attribute.
    coverage: tuple[int, int, int, int] = (0, 0, 0, 0)


def _required(catalogue: FootballCatalogue) -> list[str]:
    return sorted({a.name for role in catalogue.roles.values() for a in role.attributes})


def rank_team_players(team: LeagueTeamReport, catalogue: FootballCatalogue, *,
                      position: str = "", role_key: str = "", sort: str = "central"):
    if role_key and role_key not in catalogue.roles:
        raise ValueError("unknown player role")
    if sort not in {"central", "lower", "upper", "name", "uncertainty"}:
        raise ValueError("unknown player sort")
    rankings = []
    required = _required(catalogue)
    for player in team.roster.squad.players:
        if position and position not in player.positions:
            continue
        fits = tuple(fit for fit in team.roles.player_profiles[player.id].fits
                     if (not role_key or fit.role_key == role_key) and
                     (not position or position in catalogue.roles[fit.role_key].eligible_positions))
        if role_key and not fits:
            continue
        score = ScoreBand(max(fit.role_score.score.lower for fit in fits),
                          max(fit.role_score.score.central for fit in fits),
                          max(fit.role_score.score.upper for fit in fits)) if fits else None
        rankings.append(LeaguePlayerRanking(player, fits[0] if fits else None, score,
                                            coverage([player.attributes.get(name) for name in required])))
    def key(row):
        value = row.player.name.casefold() if sort == "name" else (
            -(row.score.upper - row.score.lower if sort == "uncertainty" else getattr(row.score, sort))
            if row.score else 0)
        return row.score is None, value, row.player.id
    return tuple(sorted(rankings, key=key))


def player_information_gaps(team: LeagueTeamReport, player_id: str, *, limit: int = 6):
    """The uncertain inputs that most move this player's best role score."""
    best = team.roles.player_profiles[player_id].best
    return best.role_score.information_gaps[:limit] if best else ()


def team_information_gaps(team: LeagueTeamReport, *, limit: int = 6):
    gaps = {}
    for scenario in (team.comparison.central, team.comparison.upper):
        for assignment in scenario.selected.assignments:
            for gap in assignment.intrinsic_role_score.information_gaps:
                if gap.uncertainty_span <= 0:
                    continue
                key = (assignment.player_id, gap.attribute)
                if key not in gaps or gap.uncertainty_span > gaps[key][1].uncertainty_span:
                    gaps[key] = (assignment, gap)
    return tuple(sorted(gaps.values(), key=lambda pair: (-pair[1].uncertainty_span,
                                                        pair[0].player_id, pair[1].attribute))[:limit])


def _canonical(value):
    """A JSON-ready form that is the same in every process (sets sorted, enums by value).

    Only fields that take part in equality are included: the rest are caches
    (such as a catalogue's derived per-tactic views), not content.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: _canonical(getattr(value, item.name)) for item in dataclasses.fields(value) if item.compare}
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, enum.Enum):
        return value.value
    return value


def model_fingerprint(catalogue: FootballCatalogue, policies) -> str:
    """The scoring model's content: every role and tactic, not just the catalogue's
    version name (a tactic edit need not change it), plus the selection policies."""
    document = json.dumps(_canonical((catalogue, tuple(policies))), sort_keys=True, default=str)
    return hashlib.sha256(document.encode()).hexdigest()


def _team_key(roster: LeagueRoster, owned: bool, model: str, tactic_keys) -> str:
    """Everything one club's result depends on, and nothing else (not the date)."""
    document = {"model": model, "tactics": list(tactic_keys or ()),
                "owned": owned, "roster": roster.roster_complete, "positions": roster.positions_complete,
                "players": [player.to_dict() for player in roster.squad.players]}
    return hashlib.sha256(json.dumps(document, sort_keys=True, default=str).encode()).hexdigest()


def _team_report(roster, owned, catalogue, required, tactic_keys, readiness_policy, familiarity_policy, fit_policy):
    assumptions = set()
    knowledge = [0, 0, 0, 0]
    players = []
    for player in roster.squad.players:
        for index, count in enumerate(coverage([player.attributes.get(name) for name in required])):
            knowledge[index] += count
        selection = PlayerSelectionInput.from_player(player)
        if selection.availability == "unknown" and not owned:
            assumptions.add("Unknown availability is provisionally treated as available")
            selection = replace(selection, availability="available")
        if selection.condition_percent is None or selection.match_fitness_percent is None:
            assumptions.add(f"Unknown condition/sharpness uses the existing {readiness_policy.unknown_percent}% fallback")
        if any(position not in selection.position_familiarity for position in selection.positions):
            assumptions.add("Missing position familiarity uses the existing eligibility fallback")
        players.append(selection)
    comparison = compare_team_xi(players, catalogue, roster_complete=roster.roster_complete,
                                 positions_complete=roster.positions_complete, tactic_keys=tactic_keys,
                                 readiness_policy=readiness_policy, familiarity_policy=familiarity_policy,
                                 fit_policy=fit_policy)
    # Keep the three chosen systems, not full recommendation bundles for
    # every tactic at every club. Full role evidence remains in the matrix.
    comparison = replace(comparison, **{key: replace(getattr(comparison, key),
                         evaluations=(getattr(comparison, key).selected,))
                         for key in ("lower", "central", "upper")})
    levels = [knowledge_level([c.observation if c.supplied else None for c in item.intrinsic_role_score.contributions])
              for item in comparison.central.selected.assignments] if comparison.score else []
    alternatives = {}
    if comparison.score:
        cache = RoleScoreCache()
        alternatives = {scenario: slot_alternatives(getattr(comparison, scenario).selected, players, catalogue,
                                                    readiness_policy=readiness_policy,
                                                    familiarity_policy=familiarity_policy, role_score_cache=cache)
                        for scenario in ("upper", "lower")}
    return LeagueTeamReport(roster, comparison, build_role_matrix(players, catalogue), tuple(sorted(assumptions)),
                            tuple(knowledge), starters=tuple(levels.count(level) for level in
                                                             ("known", "partly known", "unknown")),
                            alternatives=alternatives)


def build_league_report(
    capture: LeagueCapture,
    catalogue: FootballCatalogue,
    *,
    tactic_keys: tuple[str, ...] | None = None,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    team_cache: MutableMapping[str, LeagueTeamReport] | None = None,
    previous: Mapping[str, TeamSummary] | None = None,
) -> LeagueReport:
    """Every club's best-XI range, ordering, scouting priorities and change.

    `team_cache` reuses a club's result whenever nothing it depends on has
    changed since an earlier read (a new game date alone does not count), so a
    fresh read recomputes only the clubs whose squad or knowledge moved.
    `previous` is an earlier read's `LeagueReport.summaries()`, to explain what
    changed; it is the caller's job to pass one from the same save and scope.
    """
    teams = []
    required = _required(catalogue)
    policies = (readiness_policy, familiarity_policy, fit_policy)
    model = model_fingerprint(catalogue, policies) if team_cache is not None else ""
    controlled = capture.game.controlled_club.id if capture.game.controlled_club else None
    for roster in capture.teams:
        owned = roster.squad.club.id == controlled
        key = _team_key(roster, owned, model, tactic_keys)
        cached = team_cache.get(key) if team_cache is not None else None
        if cached is None:
            cached = _team_report(roster, owned, catalogue, required, tactic_keys, *policies)
            if team_cache is not None:
                team_cache[key] = cached
        teams.append(replace(cached, roster=roster))
    comparable = [team for team in teams if team.score is not None]
    owned = next((team for team in comparable if team.roster.squad.club.id == controlled), None)
    ranked = []
    for team in teams:
        is_owned = team.roster.squad.club.id == controlled
        if team.score is not None:
            best = 1 + sum(other.score.lower > team.score.upper for other in comparable)
            worst = 1 + sum(other is not team and other.score.upper > team.score.lower for other in comparable)
            relative = "Not comparable"
            if owned is not None:
                if team is owned:
                    relative = "Your club"
                elif team.score.lower > owned.score.upper:
                    relative = "Above us under assumptions" if team.assumptions or owned.assumptions else "Clearly above us"
                elif team.score.upper < owned.score.lower:
                    relative = "Below us under assumptions" if team.assumptions or owned.assumptions else "Clearly below us"
                else:
                    relative = "Overlapping"
            team = replace(team, rank_lower=best, rank_upper=worst, relative_to_us=relative)
        team = replace(team, priorities=scouting_priorities(team, None if is_owned or owned is None else owned.score))
        earlier = (previous or {}).get(team.roster.squad.club.id)
        if earlier is not None:
            team = replace(team, change=team_change(earlier, TeamSummary.of(team, capture.game.game_date)))
        ranked.append(team)
    return LeagueReport(capture, tuple(catalogue.tactics) if tactic_keys is None else tactic_keys,
                        tuple(order_teams(ranked, "central")))


def order_teams(teams, sort: str):
    if sort not in {"central", "lower", "upper", "uncertainty", "name"}:
        raise ValueError("unknown league sort")
    return sorted(teams, key=lambda team: (
        team.score is None,
        team.roster.squad.club.name.casefold() if sort == "name" else
        -(team.score.upper - team.score.lower if sort == "uncertainty" else getattr(team.score, sort)) if team.score else 0,
        team.roster.squad.club.id,
    ))
