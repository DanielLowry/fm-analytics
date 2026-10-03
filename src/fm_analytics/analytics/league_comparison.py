"""Evidence-aware league ordering and team/player drilldown models."""
from __future__ import annotations

from dataclasses import dataclass, replace

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_matrix import RoleMatrix, build_role_matrix
from fm_analytics.analytics.role_scoring import ScoreBand
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


@dataclass(frozen=True)
class LeaguePlayerRanking:
    player: Player
    best_role: PlayerRoleFit | None
    score: ScoreBand | None


def rank_team_players(team: LeagueTeamReport, catalogue: FootballCatalogue, *,
                      position: str = "", role_key: str = "", sort: str = "central"):
    if role_key and role_key not in catalogue.roles:
        raise ValueError("unknown player role")
    if sort not in {"central", "lower", "upper", "name", "uncertainty"}:
        raise ValueError("unknown player sort")
    rankings = []
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
        rankings.append(LeaguePlayerRanking(player, fits[0] if fits else None, score))
    def key(row):
        value = row.player.name.casefold() if sort == "name" else (
            -(row.score.upper - row.score.lower if sort == "uncertainty" else getattr(row.score, sort))
            if row.score else 0)
        return row.score is None, value, row.player.id
    return tuple(sorted(rankings, key=key))


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


def build_league_report(
    capture: LeagueCapture,
    catalogue: FootballCatalogue,
    *,
    tactic_keys: tuple[str, ...] | None = None,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> LeagueReport:
    teams = []
    required = {a.name for role in catalogue.roles.values() for a in role.attributes}
    for roster in capture.teams:
        assumptions = set()
        knowledge = [0, 0, 0, 0]
        players = []
        for player in roster.squad.players:
            for name in required:
                observation = player.attributes.get(name)
                index = 3 if observation is None else {"known": 0, "range": 1, "unknown": 2}[observation.visibility]
                knowledge[index] += 1
            selection = PlayerSelectionInput.from_player(player)
            is_owned = capture.game.controlled_club and roster.squad.club.id == capture.game.controlled_club.id
            if selection.availability == "unknown" and not is_owned:
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
        teams.append(LeagueTeamReport(roster, comparison, build_role_matrix(players, catalogue),
                                      tuple(sorted(assumptions)), tuple(knowledge)))
    comparable = [team for team in teams if team.score is not None]
    owned = next((team for team in comparable if capture.game.controlled_club
                  and team.roster.squad.club.id == capture.game.controlled_club.id), None)
    ranked = []
    for team in teams:
        if team.score is None:
            ranked.append(team)
            continue
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
        ranked.append(replace(team, rank_lower=best, rank_upper=worst, relative_to_us=relative))
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
