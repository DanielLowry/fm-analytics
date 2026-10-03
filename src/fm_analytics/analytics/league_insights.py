"""What a league comparison means for the manager: what to learn, what changed.

Everything here reads a finished `LeagueTeamReport`; nothing re-runs the scorer.

**What to scout next.** A club's ceiling is its best XI with every uncertain
attribute at the top of its range. Put one starter at the bottom of his range
instead, and let his slot go to whichever is better: him at his worst or the
best squad player outside that XI at his best. The team formula (`xi_selection.
_tactic_fit` times the balance multiplier) then gives how much of the ceiling
rests on what we do not know about him. A full re-selection could only recover
more, so the figure is "up to". Symmetrically, putting a player at the top of
his range in the floor XI (a starter in his own slot, a reserve in whichever
slot he lifts most) gives "at least" how far the floor could rise. Those two
bounds say whether learning that one player *could* settle the club's
comparison with us: never that it will.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import AttributeContribution, RoleScoreCache, ScoreBand
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    TacticEvaluation,
)
from fm_analytics.analytics.xi_selection import score_player_for_slot
from fm_analytics.domain import Visibility

CANNOT_REACH = "could show they cannot reach your score"
ABOVE = "could show they are above you"
MINIMUM_POINTS = 0.05  # below this a player's uncertainty cannot move a club's score
ATTRIBUTES_SHOWN = 4


def _team_score(evaluation: TacticEvaluation, values: Sequence[float]) -> float:
    """`_balanced_player_score` times the balance multiplier, for one scenario."""
    slots = len(evaluation.tactic.slots)
    return evaluation.tactic_balance_multiplier * (sum(sqrt(value) for value in values) / slots) ** 2


def slot_alternatives(
    evaluation: TacticEvaluation,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy,
    familiarity_policy: FamiliarityPolicy,
    role_score_cache: RoleScoreCache | None = None,
) -> dict[str, tuple[SlotAssignment, ...]]:
    """Per slot of this XI: every squad player outside it who could play that job.

    Scored exactly as selection scores them, in the role the XI chose there.
    """
    if not evaluation.assignments:
        return {}
    view = catalogue.for_tactic(evaluation.tactic.key)
    used = {item.player_id for item in evaluation.assignments}
    alternatives = {}
    for assignment in evaluation.assignments:
        options = []
        for player in players:
            if player.id in used:
                continue
            option = score_player_for_slot(
                player, assignment.slot, view, readiness_policy=readiness_policy,
                familiarity_policy=familiarity_policy, role_key=assignment.intrinsic_role_score.role_key,
                role_score_cache=role_score_cache, tactic_key=evaluation.tactic.key,
            )
            if option is not None:
                options.append(option)
        alternatives[assignment.slot.key] = tuple(options)
    return alternatives


def _with(evaluation: TacticEvaluation, end: str, slot_key: str, value: float) -> float:
    values = [value if item.slot.key == slot_key else getattr(item.selection_score, end) for item in evaluation.assignments]
    return _team_score(evaluation, values)


def _ceiling_stakes(evaluation: TacticEvaluation, alternatives) -> dict[str, tuple[float, SlotAssignment]]:
    """Per starter: up to how much of the ceiling rests on him (best alternative allowed)."""
    stakes = {}
    for assignment in evaluation.assignments:
        cover = max((option.selection_score.upper for option in alternatives.get(assignment.slot.key, ())), default=0.0)
        worst = max(assignment.selection_score.lower, cover)
        stakes[assignment.player_id] = (max(0.0, evaluation.score.upper - _with(evaluation, "upper", assignment.slot.key, worst)),
                                        assignment)
    return stakes


def _floor_stakes(evaluation: TacticEvaluation, alternatives) -> dict[str, tuple[float, SlotAssignment]]:
    """Per player: at least how far the floor rises if he is at his best."""
    stakes = {}
    candidates = [(item.slot.key, item) for item in evaluation.assignments]
    candidates += [(slot_key, option) for slot_key, options in alternatives.items() for option in options]
    for slot_key, option in candidates:
        rise = _with(evaluation, "lower", slot_key, option.selection_score.upper) - evaluation.score.lower
        if rise > stakes.get(option.player_id, (0.0, None))[0]:
            stakes[option.player_id] = (rise, option)
    return stakes


@dataclass(frozen=True)
class ScoutingPriority:
    club_id: str
    club_name: str
    player_id: str
    player_name: str
    job: str  # position and role in the XI the figures come from
    ceiling_at_stake: float  # up to this many ceiling points rest on him
    floor_at_stake: float  # learning he is at his best lifts the floor at least this far
    only_in_best_case: bool  # in the ceiling XI but not the conservative one
    settles: str  # "" when he alone cannot settle the comparison with us
    attributes: tuple[AttributeContribution, ...]

    @property
    def at_stake(self) -> float:
        """The figure that matters: the end that could settle the comparison, else the larger."""
        if self.settles == CANNOT_REACH:
            return self.ceiling_at_stake
        if self.settles == ABOVE:
            return self.floor_at_stake
        return max(self.ceiling_at_stake, self.floor_at_stake)


def scouting_priorities(team, ours: ScoreBand | None) -> tuple[ScoutingPriority, ...]:
    """Players whose unknowns move this club's range, most decisive first.

    `ours` is our own team band, or None for our own club or when we cannot be
    compared (then nothing can be said to settle anything).
    """
    if team.score is None:
        return ()
    upper, lower = team.comparison.upper.selected, team.comparison.lower.selected
    central_ids = {item.player_id for item in team.comparison.central.selected.assignments}
    ceiling = _ceiling_stakes(upper, team.alternatives.get("upper", {}))
    floor = _floor_stakes(lower, team.alternatives.get("lower", {}))
    club = team.roster.squad.club
    rows = []
    for player_id in ceiling.keys() | floor.keys():
        down, in_ceiling = ceiling.get(player_id, (0.0, None))
        up, in_floor = floor.get(player_id, (0.0, None))
        if max(down, up) < MINIMUM_POINTS:
            continue
        assignment = in_ceiling if in_ceiling is not None and down >= up else in_floor or in_ceiling
        settles = ""
        if ours is not None:
            if team.score.upper >= ours.lower and team.score.upper - down < ours.lower:
                settles = CANNOT_REACH
            elif team.score.lower <= ours.upper and team.score.lower + up > ours.upper:
                settles = ABOVE
        gaps = assignment.intrinsic_role_score.information_gaps[:ATTRIBUTES_SHOWN]
        rows.append(ScoutingPriority(
            club.id, club.name, player_id, assignment.player_name,
            f"{assignment.slot.position} · {assignment.intrinsic_role_score.role_name}",
            round(down, 2), round(up, 2), player_id not in central_ids, settles, gaps,
        ))
    return tuple(sorted(rows, key=lambda row: (not row.settles, -row.at_stake, row.player_id)))


def league_priorities(report, *, limit: int = 10) -> tuple[ScoutingPriority, ...]:
    """The league-wide shortlist: decisive players first, then the largest stakes."""
    rows = [row for team in report.teams for row in team.priorities]
    return tuple(sorted(rows, key=lambda row: (not row.settles, -row.at_stake, row.club_id, row.player_id))[:limit])


def knowledge_level(observations: Sequence) -> str:
    """'known', 'partly known' or 'unknown' for one player's role inputs (None: uncaptured)."""
    known = [obs is not None and obs.visibility is Visibility.KNOWN for obs in observations]
    unknown = [obs is None or obs.visibility is Visibility.UNKNOWN for obs in observations]
    if all(known):
        return "known"
    return "unknown" if all(unknown) else "partly known"


def coverage(observations: Sequence) -> tuple[int, int, int, int]:
    """(exact, ranged, unknown, uncaptured) counts over one player's role inputs."""
    counts = [0, 0, 0, 0]
    for observation in observations:
        index = 3 if observation is None else {"known": 0, "range": 1, "unknown": 2}[observation.visibility]
        counts[index] += 1
    return tuple(counts)


@dataclass(frozen=True)
class XIDifference:
    tactic: str  # the other XI's system, "" when it is the same system
    players_in: tuple[str, ...]
    players_out: tuple[str, ...]

    @property
    def same(self) -> bool:
        return not (self.tactic or self.players_in or self.players_out)


def xi_difference(reference: TacticEvaluation, other: TacticEvaluation) -> XIDifference:
    names = {item.player_id: item.player_name for item in (*reference.assignments, *other.assignments)}
    before = {item.player_id for item in reference.assignments}
    after = {item.player_id for item in other.assignments}
    return XIDifference(
        other.tactic.name if other.tactic.key != reference.tactic.key else "",
        tuple(sorted(names[key] for key in after - before)),
        tuple(sorted(names[key] for key in before - after)),
    )


@dataclass(frozen=True)
class TeamSummary:
    """What one read concluded about one club; kept to explain the next read."""

    club_id: str
    club_name: str
    status: str
    score: ScoreBand | None
    tactic: str
    xi: tuple[tuple[str, str], ...]  # (player id, name) in the conservative XI
    game_date: date

    @classmethod
    def of(cls, team, game_date: date) -> TeamSummary:
        central = team.comparison.central.selected
        return cls(team.roster.squad.club.id, team.roster.squad.club.name, str(team.comparison.status),
                   team.score, central.tactic.name if team.score else "",
                   tuple(sorted((item.player_id, item.player_name) for item in central.assignments)), game_date)

    def to_document(self) -> dict:
        score = self.score
        return {"clubId": self.club_id, "clubName": self.club_name, "status": self.status,
                "score": [score.lower, score.central, score.upper] if score else None,
                "tactic": self.tactic, "xi": [list(pair) for pair in self.xi], "gameDate": self.game_date.isoformat()}

    @classmethod
    def from_document(cls, raw: Mapping) -> TeamSummary:
        score = raw.get("score")
        return cls(raw["clubId"], raw["clubName"], raw["status"], ScoreBand(*score) if score else None,
                   raw["tactic"], tuple(tuple(pair) for pair in raw["xi"]), date.fromisoformat(raw["gameDate"]))


@dataclass(frozen=True)
class TeamChange:
    since: date
    previous: ScoreBand | None
    current: ScoreBand | None
    previous_status: str
    tactic: str  # the new conservative system, "" when unchanged
    players_in: tuple[str, ...]
    players_out: tuple[str, ...]


def team_change(previous: TeamSummary, current: TeamSummary) -> TeamChange | None:
    """How a club's result moved since an earlier read; None when it did not."""
    before, after = dict(previous.xi), dict(current.xi)
    change = TeamChange(
        previous.game_date, previous.score, current.score, previous.status if previous.status != current.status else "",
        current.tactic if current.tactic != previous.tactic and current.score and previous.score else "",
        tuple(sorted(after[key] for key in after.keys() - before.keys())),
        tuple(sorted(before[key] for key in before.keys() - after.keys())),
    )
    unchanged = (previous.score == current.score and not change.previous_status and not change.tactic
                 and not change.players_in and not change.players_out)
    return None if unchanged else change
