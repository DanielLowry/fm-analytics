"""How you managed the score over a run of matches, and how that is trending: the Matches page's "Season trends".

- **Points dropped from winning positions:** matches you led at some point and
  did not win; a draw drops two points, a defeat three. Beside it, how often a
  side that led went on to win in the same matches, both sides counted, since
  some leads are always lost (as `game_state` reads it for the Diagnosis).
- **Chances allowed while ahead:** their shots, shots on goal and clear-cut
  chances per 90 minutes while you led, beside the same while level.
- **The last 15 minutes,** from FM's 76th minute as `game_state` and the period
  figures count it: goals and chances each way, and the points that changed
  hands then, the result against the score after 75 minutes.
- **Before and after your changes:** each substitution (FM records the minute)
  and each mentality change you recorded, against the 15 minutes before it,
  split by the score at the time. Their substitutions are alongside for
  comparison: later minutes and the score move both sides, whoever changes.

Each figure is given for every match, the last 10 and the last 5. Results
figures need every goal timed and leave out extra-time matches. Chance figures
are the "By the score" panel's own (`match_breakdowns.counted_split` and
`match_clock`): they also need every shot and leave out a match with a
sending-off, as that panel does. Everything here is on FM's own match screens.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Mapping, Sequence

from fm_analytics.analytics.game_state import LATE_MINUTE
from fm_analytics.analytics.match_analysis import MatchSummary
from fm_analytics.analytics.match_breakdowns import (
    PERIODS,
    STATES,
    MatchClock,
    ScoreSplit,
    Tally,
    counted_split,
    match_clock,
)

CHANGE_WINDOW = 15  # minutes either side of a change
LATE_PERIOD = PERIODS[-1][0]  # "76–90+"
WINDOWS = (("season", "Every match", None), ("last10", "Last 10", 10), ("last5", "Last 5", 5))
_POINTS = {"W": 3, "D": 1, "L": 0}


def _points(ours: int, theirs: int) -> int:
    return 3 if ours > theirs else 1 if ours == theirs else 0


def fm_clock(minute: int, added_time: int = 0) -> str:
    """A minute as FM shows it: 45, or 90+2."""
    return f"{minute}+{added_time}" if added_time else str(minute)


@dataclass(frozen=True)
class MatchTrend:
    """One match: how its score went, and whether it counts in the results and chance figures."""

    key: str
    date: date
    opponent: str
    venue: str  # "Home" or "Away"
    result: str
    goals_for: int
    goals_against: int
    timed: bool  # every goal timed and no extra time: it counts in the results figures
    goals: tuple[tuple[str, int, int], ...] = ()  # (FM's clock, you, them) after each goal, in order
    led: bool = False  # you were ahead at some point
    they_led: bool = False
    score_after_75: tuple[int, int] = (0, 0)
    split: ScoreSplit | None = None  # by the score and period, when it counts in the chance figures
    left_out: str | None = None  # why it is left out of the chance figures
    dropped_so_far: int = 0  # running totals to this match, over the matches with goal times
    late_so_far: int = 0

    @property
    def points(self) -> int:
        return _POINTS[self.result]

    @property
    def dropped(self) -> int:
        """Points dropped from a winning position: two for a draw, three for a defeat."""
        return 3 - self.points if self.led else 0

    @property
    def late_points(self) -> int:
        """Points won (above zero) or lost (below) after 75 minutes: the result against the score then."""
        return self.points - _points(*self.score_after_75) if self.timed else 0

    @property
    def late_goals(self) -> tuple[int, int]:
        return (self.goals_for - self.score_after_75[0], self.goals_against - self.score_after_75[1])


@dataclass(frozen=True)
class TrendWindow:
    """Every match, the last 10 or the last 5 of the selection."""

    key: str
    label: str
    matches: int
    timed: int  # matches in the results figures
    led: int
    led_won: int
    led_drawn: int
    dropped: int
    they_led: int
    they_led_won: int  # their leads they went on to win: with yours, what is usual
    late_goals: tuple[int, int]
    late_won: int  # points won after 75 minutes
    late_lost: int  # points lost after 75 minutes, as a positive number
    split_matches: int  # matches in the chance figures
    by_state: Mapping[str, Tally]
    late: Tally  # shots, chances and goals from the 76th minute, in the chance figures' matches

    @property
    def led_lost(self) -> int:
        return self.led - self.led_won - self.led_drawn

    @property
    def usual_hold(self) -> float | None:
        """How often a side that led went on to win in these matches, both sides counted."""
        leads = self.led + self.they_led
        return (self.led_won + self.they_led_won) / leads if leads else None


@dataclass(frozen=True)
class Change:
    """One change in one match (substitutions in the same minute are one), with the minutes either side of it."""

    match_key: str
    date: date
    opponent: str
    minute: int  # on the match clock: a change "at 65" takes effect from 65:00
    ours: bool
    kind: str  # "substitution", "mentality" or, in the same minute, "both"
    what: str
    score: tuple[int, int]  # you, them, when it was made
    state: str  # "ahead", "level" or "behind", from your side
    before: Tally
    after: Tally


@dataclass(frozen=True)
class ChangeGroup:
    key: str
    label: str
    changes: int
    before: Tally
    after: Tally


@dataclass(frozen=True)
class SeasonTrends:
    matches: tuple[MatchTrend, ...]  # every selected match, in the order played
    windows: tuple[TrendWindow, ...]  # every match, then the last 10 and the last 5 when there are more
    changes: tuple[Change, ...]
    change_groups: tuple[ChangeGroup, ...]  # only groups with a change in them
    left_out: Mapping[str, int] = field(default_factory=dict)  # reason -> matches out of the chance figures

    def window(self, key: str) -> TrendWindow | None:
        return next((window for window in self.windows if window.key == key), None)

    def group(self, key: str) -> ChangeGroup | None:
        return next((group for group in self.change_groups if group.key == key), None)

    @property
    def dropped_matches(self) -> tuple[MatchTrend, ...]:
        return tuple(match for match in self.matches if match.dropped)


def _goal_sequence(row: MatchSummary) -> tuple[tuple[int, int, bool], ...] | None:
    """(minute, added time, ours) for every goal in order; None unless every goal is timed."""
    goals = [incident for incident in row.match.incidents if incident.is_goal]
    if len(goals) != row.goals_for + row.goals_against:
        return None
    # FM's order: first-half added time (45+2) comes before the 46th minute.
    return tuple(sorted((goal.minute, goal.added_time, goal.side == row.side) for goal in goals))


def _match_trend(row: MatchSummary, split: ScoreSplit | None, reason: str | None) -> MatchTrend:
    base = dict(
        key=row.match.key, date=row.match.date, opponent=row.opponent.name, venue=row.venue, result=row.result,
        goals_for=row.goals_for, goals_against=row.goals_against, split=split, left_out=reason,
    )
    sequence = None if row.match.after_extra_time else _goal_sequence(row)
    if sequence is None:
        return MatchTrend(timed=False, **base)
    ours = theirs = 0
    goals = []
    led = they_led = False
    after_75 = (0, 0)
    for minute, added_time, scored in sequence:
        ours, theirs = ours + scored, theirs + (not scored)
        if minute < LATE_MINUTE:
            after_75 = (ours, theirs)
        goals.append((fm_clock(minute, added_time), ours, theirs))
        led = led or ours > theirs
        they_led = they_led or theirs > ours
    return MatchTrend(timed=True, goals=tuple(goals), led=led, they_led=they_led, score_after_75=after_75, **base)


def _window(key: str, label: str, matches: Sequence[MatchTrend]) -> TrendWindow:
    timed = [match for match in matches if match.timed]
    splits = [match.split for match in matches if match.split is not None]
    by_state = {name: Tally() for name in STATES}
    late = Tally()
    for split in splits:
        for name in STATES:
            by_state[name].add(split.by_state[name])
        late.add(split.by_period[LATE_PERIOD])
    led = [match for match in timed if match.led]
    return TrendWindow(
        key=key, label=label, matches=len(matches), timed=len(timed),
        led=len(led),
        led_won=sum(match.result == "W" for match in led),
        led_drawn=sum(match.result == "D" for match in led),
        dropped=sum(match.dropped for match in timed),
        they_led=sum(match.they_led for match in timed),
        they_led_won=sum(match.they_led and match.result == "L" for match in timed),
        late_goals=(sum(match.late_goals[0] for match in timed), sum(match.late_goals[1] for match in timed)),
        late_won=sum(max(match.late_points, 0) for match in timed),
        late_lost=sum(max(-match.late_points, 0) for match in timed),
        split_matches=len(splits), by_state=by_state, late=late,
    )


def _changes_in(row: MatchSummary, clock: MatchClock) -> list[Change]:
    """Each side's substitutions, and your recorded mentality changes, with the minutes either side of each."""
    detail = row.match.detail
    found: list[Change] = []
    for ours in (True, False):
        side = row.side if ours else ("away" if row.side == "home" else "home")
        players = detail.players_for(side) if detail else ()
        # minute -> (who came on and off, the mentality change); in the same minute they are one change.
        moments: dict[int, tuple[str | None, str | None]] = {}
        for minute in sorted({player.came_on for player in players if player.played and player.came_on is not None}):
            on = [player.label for player in players if player.came_on == minute]
            off = [player.label for player in players if player.went_off == minute]
            moments[minute] = (f"On: {', '.join(on)}" + (f"; off: {', '.join(off)}" if off else ""), None)
        if ours and row.mentality is not None:
            plan = row.mentality.changes
            for (_from, previous), (minute, name) in zip(plan, plan[1:]):
                moments[minute] = (moments.get(minute, (None, None))[0], f"{previous} to {name}")
        times = sorted(minute for minute in moments if minute < clock.end)
        for index, minute in enumerate(times):
            start = max(0.0, minute - CHANGE_WINDOW, times[index - 1] if index else 0.0)
            stop = min(clock.end, minute + CHANGE_WINDOW, times[index + 1] if index + 1 < len(times) else clock.end)
            score = (sum(1 for at, goal in clock.score_changes if at <= minute and goal > 0),
                     sum(1 for at, goal in clock.score_changes if at <= minute and goal < 0))
            substitution, mentality = moments[minute]
            found.append(Change(
                match_key=row.match.key, date=row.match.date, opponent=row.opponent.name, minute=minute, ours=ours,
                kind="both" if substitution and mentality else "substitution" if substitution else "mentality",
                what="; ".join(part for part in (substitution, mentality) if part),
                score=score, state=clock.state(minute),
                before=clock.tally(start, minute), after=clock.tally(minute, stop),
            ))
    return found


def _group(key: str, label: str, changes: Sequence[Change]) -> ChangeGroup:
    before, after = Tally(), Tally()
    for change in changes:
        before.add(change.before)
        after.add(change.after)
    return ChangeGroup(key, label, len(changes), before, after)


def _change_groups(changes: Sequence[Change]) -> tuple[ChangeGroup, ...]:
    ours = [change for change in changes if change.ours]
    subs = [change for change in ours if change.kind != "mentality"]
    groups = [
        _group("substitutions", "Your substitutions", subs),
        *(_group(f"substitutions_{state}", f"… made while {state}", [c for c in subs if c.state == state])
          for state in ("ahead", "level", "behind")),
        _group("mentality", "Your mentality changes", [change for change in ours if change.kind != "substitution"]),
        _group("theirs", "Their substitutions, for comparison", [change for change in changes if not change.ours]),
    ]
    return tuple(group for group in groups if group.changes)


def season_trends(rows: Sequence[MatchSummary]) -> SeasonTrends:
    """The season trends of `rows`, in the order played (a review's `matches`)."""
    matches: list[MatchTrend] = []
    changes: list[Change] = []
    left_out: dict[str, int] = {}
    dropped = late = 0
    for row in rows:
        split, reason = counted_split(row.match, row.side, row.mentality)
        if reason:
            left_out[reason] = left_out.get(reason, 0) + 1
        trend = _match_trend(row, split, reason)
        if trend.timed:
            dropped += trend.dropped
            late += trend.late_points
            trend = replace(trend, dropped_so_far=dropped, late_so_far=late)
        matches.append(trend)
        clock = match_clock(row.match, row.side) if split is not None else None
        if clock is not None:
            changes += _changes_in(row, clock)
    windows = tuple(
        _window(key, label, matches if size is None else matches[-size:])
        for key, label, size in WINDOWS if size is None or len(matches) > size
    )
    return SeasonTrends(tuple(matches), windows, tuple(changes), _change_groups(changes), left_out)
