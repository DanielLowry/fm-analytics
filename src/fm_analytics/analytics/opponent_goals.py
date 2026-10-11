"""How a side's goals came, scored or conceded, against the league's share: the opponent report's profile.

From FM's description of each goal (`goal_descriptions`) and the positions its
scorer and crosser played. "Possibly from a corner" and "at the far side" are
guesses and always say so (`match_timeline.CORNER_GUESS`, `FAR_SIDE_GUESS`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from fm_analytics.analytics.chance_value import at_least
from fm_analytics.analytics.match_timeline import GoalMoment
from fm_analytics.analytics.opponent_players import LINES, WIDE, line_of, timeline_goals, where
from fm_analytics.domain.matches import MatchRecord, PlayerMatchStats

# A share that luck alone reaches less often than this is called a pattern,
# as the season Diagnosis does for its findings (docs/match-analysis-plan.md).
PATTERN_ODDS = 0.1

PERIODS = ((1, 15), (16, 30), (31, 45), (46, 60), (61, 75), (76, 90))
FAR_SIDE_GUESS = (
    "Where a goal was finished is not in FM's record. This counts a goal from a cross "
    "as met at the far side when the crosser played on one flank and the scorer on the "
    "other (a right winger meeting a cross from the left), so it is a guess from positions."
)


@dataclass(frozen=True)
class ProfileRow:
    """One way of scoring (or conceding): how many goals, their share, and the league's."""

    key: str
    label: str
    words: str  # how a sentence says it: "with headers from crosses"
    goals: int
    share: float  # of the goals the profile counts
    league_share: float | None
    # How often luck alone gives at least this many (or at most, when below the
    # league's share) at the league's rate; None without a league figure.
    luck: float | None = None
    guess: bool = False  # a labelled guess, never a fact

    @property
    def pattern(self) -> str | None:
        """"more" or "fewer" than the league when luck alone rarely leaves a gap this large; else None."""
        if self.luck is None or self.league_share is None or self.luck >= PATTERN_ODDS:
            return None
        return "more" if self.share > self.league_share else "fewer"


@dataclass(frozen=True)
class GoalProfile:
    """How a side's goals came (scored or conceded)."""

    goals: int  # every goal, own goals included
    described: int  # goals whose timeline says how
    how: tuple[ProfileRow, ...]  # penalty, direct free kick, cross..., other open play, own goal
    area: tuple[ProfileRow, ...]  # six-yard box, area, edge, outside
    lines: tuple[ProfileRow, ...]  # which line scored them
    periods: tuple[ProfileRow, ...]
    cross_flanks: tuple[ProfileRow, ...]  # crosses from the left, right and middle (corners left out)
    far_side: int  # crosses met at the far side (FAR_SIDE_GUESS)
    flank_crosses: int  # crosses from one flank, the far-side guess's denominator

    def row(self, key: str) -> ProfileRow | None:
        return next((row for group in (self.how, self.area, self.lines, self.periods, self.cross_flanks)
                     for row in group if row.key == key), None)


@dataclass
class _GoalCounts:
    goals: int = 0
    described: int = 0
    how: Counter = field(default_factory=Counter)
    area: Counter = field(default_factory=Counter)
    lines: Counter = field(default_factory=Counter)
    periods: Counter = field(default_factory=Counter)
    flanks: Counter = field(default_factory=Counter)
    far_side: int = 0
    flank_crosses: int = 0


# (key, label, the words a sentence uses: "scored 5 of 25 goals <words>")
HOW_ROWS = (
    ("header_from_cross", "Headers from crosses", "with headers from crosses"),
    ("foot_from_cross", "Shots and volleys from crosses", "with shots and volleys from crosses"),
    ("possibly_corner", "Possibly from corners (a guess)", "possibly from corners (a guess)"),
    ("penalty", "Penalties", "from penalties"),
    ("direct_free_kick", "Direct free kicks", "from direct free kicks"),
    ("open_play", "Other open play", "in other open play"),
    ("own_goal", "Own goals", "from own goals"),
)
GUESSES = frozenset({"possibly_corner"})  # labelled guesses (match_timeline.CORNER_GUESS), never called a pattern
# Never called a pattern either: an own goal is the other side's mistake, not a way of scoring.
NOT_JUDGED = GUESSES | {"own_goal"}
AREA_ROWS = (
    ("six_yard_box", "In the six-yard box", "from the six-yard box"),
    ("area", "Elsewhere in the area", "from elsewhere in the area"),
    ("edge", "On the edge of the area", "from the edge of the area"),
    ("outside", "From outside the area", "from outside the area"),
)
# goal_descriptions' words for each area
AREA_WORDS = {"six_yard_box": "in the six-yard box", "area": "in the area",
              "edge": "on the edge of the area", "outside": "from outside the area"}
LINE_ROWS = tuple((key, label, f"by {label[0].lower() + label[1:]}") for key, label, _members in LINES)
PERIOD_ROWS = tuple((f"{start}-{end}", f"{start}-{end}′", f"in minutes {start}-{end}")
                    for start, end in PERIODS)
# Crosses by the flank they came down, always from the report's club's point
# of view: a cross it conceded from the crosser's right came down its left.
FLANK_ROWS = (
    ("left", "Down their left", "from crosses down their left"),
    ("right", "Down their right", "from crosses down their right"),
    ("centre", "From the middle", "from crosses from the middle"),
)


def _player_at(match: MatchRecord, side: str, short_id: int | None) -> PlayerMatchStats | None:
    return next((player for player in match.detail.players_for(side) if player.short_id == short_id), None)


def _count_goal(counts: _GoalCounts, match: MatchRecord, moment: GoalMoment, conceded: bool) -> None:
    counts.goals += 1
    event = moment.event
    minute = event.minute
    period = next((f"{start}-{end}" for start, end in PERIODS if start <= minute <= end), None)
    if period is not None and not match.after_extra_time:
        counts.periods[period] += 1
    if event.kind == "own_goal":
        counts.how["own_goal"] += 1
        counts.described += 1
        return
    scorer = _player_at(match, event.side, event.player_short_id)
    position, scorer_side = where(scorer) if scorer else (None, "centre")
    line = line_of(position)
    if line:
        counts.lines[line] += 1
    if event.kind == "penalty":
        counts.how["penalty"] += 1
        counts.described += 1
        counts.area["area"] += 1
        return
    how = moment.how
    if how is None or (how.strike is None and how.area is None and how.how is None):
        return
    counts.described += 1
    area_key = next((key for key, words in AREA_WORDS.items() if how.area == words), None)
    if area_key:
        counts.area[area_key] += 1
    if how.how == "direct free kick":
        counts.how["direct_free_kick"] += 1
    elif how.how == "cross":
        if moment.possibly_from_a_corner:
            counts.how["possibly_corner"] += 1
            return
        counts.how["header_from_cross" if how.strike == "header" else "foot_from_cross"] += 1
        crosser = _player_at(match, moment.assist.side, moment.assist.player_short_id) if moment.assist else None
        if crosser is not None:
            _position, crosser_side = where(crosser)
            flank = crosser_side if crosser_side in ("left", "right") and _position in WIDE else "centre"
            # A cross conceded from the crosser's right came down the defending side's left.
            counts.flanks[{"left": "right", "right": "left"}.get(flank, flank) if conceded else flank] += 1
            if flank in ("left", "right"):
                counts.flank_crosses += 1
                counts.far_side += scorer_side in ("left", "right") and scorer_side != flank
    else:
        counts.how["open_play"] += 1


def count_goals(matches: Iterable[tuple[MatchRecord, str]], *, conceded: bool = False) -> tuple[_GoalCounts, int]:
    """Goals counting for each (match, side), and how many of those goals had no timeline.

    With `conceded`, crosses are counted by the flank they came down from the
    conceding side's point of view; the sides given are still the scorers'.
    """
    counts = _GoalCounts()
    without = 0
    for match, side in matches:
        moments = timeline_goals(match)
        if moments is None:
            without += match.goals(side)
            counts.goals += match.goals(side)
            continue
        for moment in moments:
            if moment.counts_for == side:
                _count_goal(counts, match, moment, conceded)
    return counts, without


def _luck(goals: int, total: int, league_share: float | None) -> float | None:
    """How often luck at the league's rate leaves a count at least this far from it, in the same direction."""
    if league_share is None or not total:
        return None
    if goals >= total * league_share:
        return at_least(goals, total, league_share)
    return 1.0 - at_least(goals + 1, total, league_share)


def _rows(spec, counts: Counter, total: int, league: Counter | None, league_total: int) -> tuple[ProfileRow, ...]:
    rows = []
    for key, label, words in spec:
        guess = key in GUESSES
        goals = counts.get(key, 0)
        league_share = league.get(key, 0) / league_total if league is not None and league_total else None
        rows.append(ProfileRow(
            key, label, words, goals, goals / total if total else 0.0, league_share,
            None if key in NOT_JUDGED else _luck(goals, total, league_share), guess,
        ))
    return tuple(rows)


def goal_profile(counts: _GoalCounts, league: _GoalCounts | None) -> GoalProfile:
    described = counts.described
    league_described = league.described if league else 0
    timed = sum(counts.periods.values())
    lines_total = sum(counts.lines.values())
    flanks_total = sum(counts.flanks.values())
    return GoalProfile(
        goals=counts.goals,
        described=described,
        how=_rows(HOW_ROWS, counts.how, described, league.how if league else None, league_described),
        area=_rows(AREA_ROWS, counts.area, sum(counts.area.values()),
                   league.area if league else None, sum(league.area.values()) if league else 0),
        lines=_rows(LINE_ROWS, counts.lines, lines_total,
                    league.lines if league else None, sum(league.lines.values()) if league else 0),
        periods=_rows(PERIOD_ROWS, counts.periods, timed, league.periods if league else None,
                      sum(league.periods.values()) if league else 0),
        cross_flanks=_rows(FLANK_ROWS, counts.flanks, flanks_total,
                           league.flanks if league else None, sum(league.flanks.values()) if league else 0),
        far_side=counts.far_side,
        flank_crosses=counts.flank_crosses,
    )
