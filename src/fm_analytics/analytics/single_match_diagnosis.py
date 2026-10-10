"""One match against the usual range of the others: a match page's Diagnosis.

One match cannot carry a finding: the season diagnosis needs five for any of
them.  What it can show is where it sits against the usual range of the other
competitive matches, by that diagnosis's own opponent-and-venue expectation,
which is a description with its count, not a verdict.  It also says how the
score went and which players were rated well away from their own average in
the role.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Sequence

from fm_analytics.analytics.match_analysis import MatchReview, MatchSummary
from fm_analytics.analytics.match_diagnostics import (
    CORE_TEAM_STATS,
    MIN_BASELINE_MATCHES,
    _band_key,
    _complete_goal_sequence,
    _Expectations,
    _game_state,
    _GameState,
    _valid_team_stats,
    eligible_team_summaries,
)

MIN_STANDOUT_MINUTES = 30
MIN_USUAL_APPEARANCES = 3
STANDOUT_RATING_GAP = 0.5
MAX_STANDOUTS = 3
LATE_MINUTE = 76
_STAT_LABELS = {"shots": "Shots", "shots_on_target": "On target", "clear_cut_chances": "Clear-cut chances"}
_OPPONENT_PHRASES = {
    "top": "top-third teams",
    "middle": "mid-table teams",
    "bottom": "bottom-third teams",
    "early": "teams early in the season",
    "outside": "teams outside your league",
}


@dataclass(frozen=True)
class UsualRangeCheck:
    """One core stat of one side against its usual range for that opponent band and venue.

    The range is the expectation (the season model above, from the other
    matches) plus or minus one standard deviation of how far those matches
    fell from theirs, widened to whole counts.
    """

    metric: str
    label: str
    side: str  # "ours" or "theirs"
    actual: int
    expected: float
    usual_low: int
    usual_high: int

    @property
    def standing(self) -> str:
        if self.actual < self.usual_low:
            return "below"
        return "above" if self.actual > self.usual_high else "usual"

    @property
    def favourable(self) -> bool | None:
        """Whether an unusual figure is good for us (more of ours, fewer of theirs); None when usual."""
        if self.standing == "usual":
            return None
        return (self.standing == "above") == (self.side == "ours")


@dataclass(frozen=True)
class RatingStandout:
    name: str
    role: str
    rating: float
    usual: float
    matches: int  # his other rated appearances in this role, behind `usual`


@dataclass(frozen=True)
class OneMatchDiagnosis:
    match_key: str
    compared_with: str  # "mid-table teams away"
    baseline_matches: int
    not_compared: str | None  # why the stats are not compared, or None when they are
    headline: str | None
    checks: tuple[UsualRangeCheck, ...]
    game_state: tuple[str, ...]
    above_usual: tuple[RatingStandout, ...]
    below_usual: tuple[RatingStandout, ...]


def _usual_ranges(summary: MatchSummary, baseline: Sequence[MatchSummary]) -> tuple[UsualRangeCheck, ...]:
    expected = _Expectations(baseline)
    checks = []
    for side in ("ours", "theirs"):
        for metric in CORE_TEAM_STATS:
            spread = stdev(float(getattr(row, side)[metric]) - expected(row, side, metric) for row in baseline)
            centre = expected(summary, side, metric)
            # Rounded outwards: these are small counts, and rounding inwards
            # would make a third of all ordinary clear-cut-chance figures "unusual".
            low, high = math.floor(max(centre - spread, 0.0)), math.ceil(centre + spread)
            checks.append(UsualRangeCheck(
                metric, _STAT_LABELS[metric], side, int(getattr(summary, side)[metric]), centre, low, high,
            ))
    return tuple(checks)


def _headline(checks: Sequence[UsualRangeCheck]) -> str:
    def overall(side: str) -> str:
        standings = {check.standing for check in checks if check.side == side} - {"usual"}
        return standings.pop() if len(standings) == 1 else "mixed" if standings else "usual"

    attack = {
        "below": "Created less than usual", "above": "Created more than usual",
        "usual": "Created about the usual", "mixed": "Mixed in attack",
    }[overall("ours")]
    defence = {
        "above": "allowed more than usual", "below": "allowed less than usual",
        "usual": "allowed about the usual", "mixed": "mixed in defence",
    }[overall("theirs")]
    return f"{attack}; {defence}."


def _how_it_played_out(summary: MatchSummary, season: _GameState | None) -> tuple[str, ...]:
    lines: list[str] = []
    sequence = _complete_goal_sequence(summary)
    if sequence is None:
        lines.append("Goal times aren't known for this match.")
    else:
        ours = theirs = late_for = late_against = 0
        first_lead: tuple[int, int, int] | None = None
        deepest: tuple[int, int] | None = None
        for minute, side in sequence:
            if side == summary.side:
                ours += 1
                late_for += int(minute >= LATE_MINUTE)
            else:
                theirs += 1
                late_against += int(minute >= LATE_MINUTE)
            if ours > theirs and first_lead is None:
                first_lead = (minute, ours, theirs)
            if theirs > ours and (deepest is None or theirs - ours > deepest[1] - deepest[0]):
                deepest = (ours, theirs)
        if first_lead is not None and summary.result != "W":
            minute, scored, conceded = first_lead
            line = f"Led {scored}–{conceded} from {minute}′ but {'drew' if summary.result == 'D' else 'lost'}"
            if season is not None and season.matches:
                line += f"; that has happened in {season.led_not_won} of {season.matches} matches"
            lines.append(line)
        if deepest is not None and summary.result != "L":
            lines.append(
                f"Came back from {deepest[0]}–{deepest[1]} down to {'win' if summary.result == 'W' else 'draw'}"
            )
        if late_for or late_against:
            lines.append(f"From {LATE_MINUTE}′: {late_for} scored, {late_against} conceded")
    for incident in summary.match.incidents:
        if incident.kind == "sent_off":
            who = "You" if incident.side == summary.side else "They"
            lines.append(f"{who} had a player sent off at {incident.clock}′")
    return tuple(lines)


def _rating_standouts(
    review: MatchReview, summary: MatchSummary
) -> tuple[tuple[RatingStandout, ...], tuple[RatingStandout, ...]]:
    """Our players rated well away from their own average in the same role, in the other matches."""
    key = summary.match.key
    usual: dict[tuple[str, str], list[float]] = {}
    for row in review.matches:
        if row.match.key == key or row.match.detail is None:
            continue
        for player in row.match.detail.players_for(row.side):
            role = review.appearance_roles.get((row.match.key, player.side, player.short_id))
            if player.played and player.rating is not None and role:
                usual.setdefault((player.player_id or player.label, role), []).append(player.rating)
    above: list[RatingStandout] = []
    below: list[RatingStandout] = []
    for player in summary.match.detail.players_for(summary.side):
        role = review.appearance_roles.get((key, player.side, player.short_id))
        ratings = usual.get((player.player_id or player.label, role or ""), [])
        if (
            player.rating is None or not role or player.minutes < MIN_STANDOUT_MINUTES
            or len(ratings) < MIN_USUAL_APPEARANCES
        ):
            continue
        average = mean(ratings)
        gap = round(player.rating - average, 2)
        if abs(gap) >= STANDOUT_RATING_GAP:
            (above if gap > 0 else below).append(
                RatingStandout(player.label, role, player.rating, average, len(ratings))
            )
    above.sort(key=lambda item: item.usual - item.rating)
    below.sort(key=lambda item: item.rating - item.usual)
    return tuple(above[:MAX_STANDOUTS]), tuple(below[:MAX_STANDOUTS])


def diagnose_one_match(review: MatchReview, summary: MatchSummary) -> OneMatchDiagnosis:
    """One match against the usual range of the review's other usable matches.

    `review` is the selection the season diagnosis reads (competitive matches);
    `summary` is the match itself, which may be outside it, as a friendly is.
    """
    key = summary.match.key
    in_review = any(row.match.key == key for row in review.matches)
    baseline = [row for row in eligible_team_summaries(review) if row.match.key != key]
    venue = "at home" if summary.side == "home" else "away"
    if not in_review:
        reason = "Friendlies aren't compared with your competitive matches."
    elif summary.match.detail is None:
        reason = "Only the result was found, so there are no stats to compare."
    elif summary.match.after_extra_time:
        reason = "It went to extra time, so its stats cover 120 minutes and aren't compared."
    elif not _valid_team_stats(summary):
        reason = "FM's shots or clear-cut chances for this match are missing or don't add up."
    elif len(baseline) < MIN_BASELINE_MATCHES:
        reason = (
            f"Your usual range needs {MIN_BASELINE_MATCHES} other usable matches; there are {len(baseline)}."
        )
    else:
        reason = None
    checks = _usual_ranges(summary, baseline) if reason is None else ()
    above, below = (
        _rating_standouts(review, summary)
        if in_review and summary.match.detail is not None else ((), ())
    )
    return OneMatchDiagnosis(
        match_key=key,
        compared_with=f"{_OPPONENT_PHRASES[_band_key(summary)]} {venue}",
        baseline_matches=len(baseline),
        not_compared=reason,
        headline=_headline(checks) if checks else None,
        checks=checks,
        game_state=_how_it_played_out(summary, _game_state(review.matches) if in_review else None),
        above_usual=above,
        below_usual=below,
    )
