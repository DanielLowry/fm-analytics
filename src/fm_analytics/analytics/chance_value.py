"""What a shot is worth, from what FM's match screens show.

FM20 shows no expected goals, and the value between 0 and 1 its archive keeps
beside each shot is never read (docs/match-analysis-plan.md). What FM does show
is every shot, where each one was going, and which were clear-cut chances.
That is enough to say what a set of chances was worth: a shot is worth how
often shots of its kind were scored in the matches the rates are counted from.
There are three kinds: a clear-cut chance, any other shot, and a penalty. FM
keeps only the penalties that were scored (a missed one is just a clear-cut
chance in its record), so a history cannot say how often a penalty goes in;
one is worth football's usual three in four.

From those values come how likely each number of goals is (each shot scoring
or not independently of the others), and so how often luck alone leaves goals
as far from what the chances were worth as they are. `match_chances` uses this
to judge one match; nothing here changes a score.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from fm_analytics.analytics.match_timeline import GOAL_SHOT_WINDOW, goal_shots
from fm_analytics.domain.matches import MatchEvent, MatchRecord

PENALTY_VALUE = 0.75


@dataclass(frozen=True)
class ClassifiedShot:
    side: str
    player_short_id: int
    kind: str  # "penalty", "clear_cut" or "other"
    heading: str  # MatchShot.heading: "on_goal", "wide" or "over"
    goal: bool
    clock: str

    @property
    def on_goal(self) -> bool:
        return self.heading == "on_goal"


def own_goals_for(match: MatchRecord, side: str) -> int:
    """Own goals that count for `side`: scored by the other side, whose side the event carries."""
    return sum(1 for event in match.detail.events if event.kind == "own_goal" and event.side != side)


def _clear_cut_shots(match: MatchRecord, goals: Mapping[int, MatchEvent]) -> set[int]:
    """Which shots (by index) were clear-cut chances: the goal one became, else its player's
    other shot nearest its minute."""
    shots = match.detail.shots
    goal_shot = {
        (event.side, event.player_short_id, event.minute, event.added_time): index for index, event in goals.items()
    }
    found: set[int] = set()
    for event in match.detail.events:
        if event.kind != "clear_cut_chance" or event.player_short_id is None:
            continue
        index = goal_shot.get((event.side, event.player_short_id, event.minute, event.added_time))
        if index is None:
            minute = event.minute + event.added_time
            candidates = [
                (abs(shot.fm_minute - minute), position)
                for position, shot in enumerate(shots)
                if position not in found and position not in goals
                and shot.side == event.side and shot.player_short_id == event.player_short_id
                and abs(shot.fm_minute - minute) <= GOAL_SHOT_WINDOW
            ]
            index = min(candidates)[1] if candidates else None
        if index is not None:
            found.add(index)
    return found


def classify_shots(match: MatchRecord) -> tuple[ClassifiedShot, ...] | None:
    """Every shot with its kind and whether it scored; None unless the shots account for the match.

    That is: FM listed every shot its stats panel counts for both sides, and
    every goal but an own goal is one of them. 133 of the save's 135 clear-cut
    chances and all 172 goals from shots are found this way (10 October 2026).
    """
    detail = match.detail
    if detail is None or match.after_extra_time or not detail.shots:
        return None
    goals = goal_shots(match)
    chances = _clear_cut_shots(match, goals)
    shots = tuple(
        ClassifiedShot(
            side=shot.side,
            player_short_id=shot.player_short_id,
            kind=(
                "penalty" if index in goals and goals[index].kind == "penalty"
                else "clear_cut" if index in chances else "other"
            ),
            heading=shot.heading,
            goal=index in goals,
            clock=shot.clock(),
        )
        for index, shot in enumerate(detail.shots)
    )
    for side in ("home", "away"):
        own = [shot for shot in shots if shot.side == side]
        if len(own) != detail.team(side).get("shots"):
            return None
        if sum(shot.goal for shot in own) + own_goals_for(match, side) != match.goals(side):
            return None
    return shots


@dataclass(frozen=True)
class KindRecord:
    """How many shots of one kind there were, how many were on goal and how many went in."""

    shots: int
    on_goal: int
    goals: int


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


@dataclass(frozen=True)
class ChanceRates:
    """How often each kind of shot went on goal and in, over the matches it was counted from."""

    matches: int
    clear_cut: KindRecord
    other: KindRecord

    def _record(self, kind: str) -> KindRecord:
        return self.clear_cut if kind == "clear_cut" else self.other

    def value(self, kind: str) -> float:
        """What a shot of this kind is worth in goals."""
        if kind == "penalty":
            return PENALTY_VALUE
        record = self._record(kind)
        return _share(record.goals, record.shots)

    def on_goal_rate(self, kind: str) -> float:
        record = self._record(kind)
        return _share(record.on_goal, record.shots)

    def on_goal_value(self, kind: str) -> float:
        """What a shot of this kind is worth once it is on goal."""
        record = self._record(kind)
        return _share(record.goals, record.on_goal)


def chance_rates(matches: Sequence[Sequence[ClassifiedShot]]) -> ChanceRates:
    counts = {kind: [0, 0, 0] for kind in ("clear_cut", "other")}
    for shots in matches:
        for shot in shots:
            if shot.kind in counts:
                tally = counts[shot.kind]
                tally[0] += 1
                tally[1] += shot.on_goal
                tally[2] += shot.goal
    return ChanceRates(len(matches), KindRecord(*counts["clear_cut"]), KindRecord(*counts["other"]))


def _binomial(count: int, p: float) -> list[float]:
    if p <= 0:
        return [1.0] + [0.0] * count
    if p >= 1:
        return [0.0] * count + [1.0]
    log_p, log_q = math.log(p), math.log1p(-p)
    whole = math.lgamma(count + 1)
    return [
        math.exp(whole - math.lgamma(k + 1) - math.lgamma(count - k + 1) + k * log_p + (count - k) * log_q)
        for k in range(count + 1)
    ]


def _convolve(first: Sequence[float], second: Sequence[float]) -> list[float]:
    out = [0.0] * (len(first) + len(second) - 1)
    for i, a in enumerate(first):
        for j, b in enumerate(second):
            out[i + j] += a * b
    return out


def goal_chances(shots: Sequence[ClassifiedShot], rates: ChanceRates) -> list[float]:
    """How likely each number of goals is from these shots (index = goals), each scoring or not on its own."""
    distribution = [1.0]
    for kind, count in sorted(Counter(shot.kind for shot in shots).items()):
        distribution = _convolve(distribution, _binomial(count, rates.value(kind)))
    return distribution


def luck_odds(shots: Sequence[ClassifiedShot], rates: ChanceRates) -> float:
    """How often luck alone leaves goals at least this far from what the shots were worth, in the same direction."""
    distribution = goal_chances(shots, rates)
    goals = sum(shot.goal for shot in shots)
    worth = sum(rates.value(shot.kind) for shot in shots)
    return sum(distribution[:goals + 1]) if goals < worth else sum(distribution[goals:])


def one_in(odds: float) -> str:
    """Odds as "1 time in N", in words a manager reads at a glance."""
    if odds < 0.001:
        return "less than 1 time in 1,000"
    return f"about 1 time in {max(2, round(1 / odds)):,}"
