"""Results against chances over a run of matches: the season view of a match page's "Result vs chances".

Each match's chances are valued as on its page (`chance_value`), with the rates
counted from the same run of matches, both sides' shots alike. Over a window
that gives the points those chances usually bring against the points taken,
and the goals scored and conceded against what the chances each way were
worth, with how often luck alone leaves a gap that large. Match by match it is
the trend the Matches page draws: each side's chances as an average of the last
`ROLLING` matches, and a running total of points above or below what the
chances usually bring. Goals here are goals from shots: an own goal is no
chance's doing, so it is left out of both sides of the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from fm_analytics.analytics.chance_value import (
    ChanceRates,
    ClassifiedShot,
    chance_rates,
    classify_shots,
    goal_chances,
    luck_odds,
    outcomes,
)
from fm_analytics.analytics.match_analysis import MatchSummary

_POINTS = {"W": 3, "D": 1, "L": 0}
ROLLING = 5
# A gap between goals and chances is more than luck when luck alone leaves one that large less often than this.
PATTERN_ODDS = 0.05


def standing(odds: float, goals: int, worth: float) -> str:
    """"above" or "below" what the chances were worth by more than luck usually leaves, else "usual"."""
    if odds >= PATTERN_ODDS:
        return "usual"
    return "below" if goals < worth else "above"


def _round(value: float, places: int = 2) -> float:
    return round(value, places)


@dataclass(frozen=True)
class MatchChances:
    key: str
    date: date
    opponent: str
    venue: str  # "Home" or "Away"
    result: str
    goals_for: int  # from shots: own goals aside
    goals_against: int
    worth_for: float
    worth_against: float
    points: int
    expected_points: float  # what chances like these usually bring
    # Each side's chances over this and the previous ROLLING - 1 matches; None before there are that many.
    rolling_for: float | None = None
    rolling_against: float | None = None
    points_above_usual: float = 0.0  # running total of points less expected points, to this match

    def to_document(self) -> dict[str, Any]:
        return {
            "key": self.key, "date": self.date.isoformat(), "opponent": self.opponent, "venue": self.venue,
            "result": self.result, "goals_for": self.goals_for, "goals_against": self.goals_against,
            "chances_worth_for": _round(self.worth_for), "chances_worth_against": _round(self.worth_against),
            "points": self.points, "expected_points": _round(self.expected_points),
            "rolling_chances_worth_for": None if self.rolling_for is None else _round(self.rolling_for),
            "rolling_chances_worth_against": None if self.rolling_against is None else _round(self.rolling_against),
            "points_above_usual": _round(self.points_above_usual),
        }


@dataclass(frozen=True)
class ChanceWindow:
    key: str
    label: str
    matches: int
    points: int
    expected_points: float
    goals_for: int
    worth_for: float
    goals_against: int
    worth_against: float
    scoring_odds: float  # how often luck alone leaves goals scored this far from worth_for, this way
    conceding_odds: float  # the same for goals conceded

    @property
    def scoring(self) -> str:
        return standing(self.scoring_odds, self.goals_for, self.worth_for)

    @property
    def conceding(self) -> str:
        return standing(self.conceding_odds, self.goals_against, self.worth_against)

    def to_document(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "matches": self.matches,
            "points": self.points, "expected_points": _round(self.expected_points, 1),
            "goals_for": self.goals_for, "chances_worth_for": _round(self.worth_for, 1),
            "goals_against": self.goals_against, "chances_worth_against": _round(self.worth_against, 1),
            "scoring_luck_odds": _round(self.scoring_odds, 3), "conceding_luck_odds": _round(self.conceding_odds, 3),
            "scoring": self.scoring, "conceding": self.conceding,
        }


@dataclass(frozen=True)
class SeasonChances:
    rates: ChanceRates
    matches: tuple[MatchChances, ...]  # in the order played
    windows: tuple[ChanceWindow, ...]  # every match, then the last 10 and the last 5
    left_out: int  # usable matches without every shot recorded

    def window(self, key: str) -> ChanceWindow | None:
        return next((window for window in self.windows if window.key == key), None)

    def to_document(self) -> dict[str, Any]:
        return {
            "rates": {
                "matches": self.rates.matches,
                "clear_cut_chance": _round(self.rates.value("clear_cut"), 3),
                "other_shot": _round(self.rates.value("other"), 3),
                "penalty": self.rates.value("penalty"),
            },
            "windows": [window.to_document() for window in self.windows],
            "matches": [match.to_document() for match in self.matches],
            "left_out": self.left_out,
        }


def _window(
    key: str, label: str, rows: Sequence[tuple[MatchSummary, tuple[ClassifiedShot, ...]]],
    matches: Sequence[MatchChances], rates: ChanceRates,
) -> ChanceWindow:
    ours = [shot for row, shots in rows for shot in shots if shot.side == row.side]
    theirs = [shot for row, shots in rows for shot in shots if shot.side != row.side]
    return ChanceWindow(
        key=key,
        label=label,
        matches=len(matches),
        points=sum(match.points for match in matches),
        expected_points=sum(match.expected_points for match in matches),
        goals_for=sum(match.goals_for for match in matches),
        worth_for=sum(match.worth_for for match in matches),
        goals_against=sum(match.goals_against for match in matches),
        worth_against=sum(match.worth_against for match in matches),
        scoring_odds=luck_odds(ours, rates) if ours else 1.0,
        conceding_odds=luck_odds(theirs, rates) if theirs else 1.0,
    )


def season_chances(rows: Sequence[MatchSummary], *, minimum: int) -> SeasonChances | None:
    """Results against chances over `rows` (in the order played); None with fewer than `minimum` to count from."""
    usable = []
    for row in rows:
        shots = classify_shots(row.match)
        if shots is not None:
            usable.append((row, shots))
    if len(usable) < minimum:
        return None
    rates = chance_rates([shots for _row, shots in usable])
    matches: list[MatchChances] = []
    running = 0.0
    for row, shots in usable:
        ours = [shot for shot in shots if shot.side == row.side]
        theirs = [shot for shot in shots if shot.side != row.side]
        win, draw, _loss = outcomes(goal_chances(ours, rates), goal_chances(theirs, rates))
        worth_for = sum(rates.value(shot.kind) for shot in ours)
        worth_against = sum(rates.value(shot.kind) for shot in theirs)
        recent = matches[-(ROLLING - 1):] if len(matches) >= ROLLING - 1 else None
        running += _POINTS[row.result] - (3 * win + draw)
        matches.append(MatchChances(
            key=row.match.key,
            date=row.match.date,
            opponent=row.opponent.name,
            venue=row.venue,
            result=row.result,
            goals_for=sum(shot.goal for shot in ours),
            goals_against=sum(shot.goal for shot in theirs),
            worth_for=worth_for,
            worth_against=worth_against,
            points=_POINTS[row.result],
            expected_points=3 * win + draw,
            rolling_for=None if recent is None else (worth_for + sum(m.worth_for for m in recent)) / ROLLING,
            rolling_against=None if recent is None else (worth_against + sum(m.worth_against for m in recent)) / ROLLING,
            points_above_usual=running,
        ))
    windows = tuple(
        _window(key, label, usable[-count:], matches[-count:], rates)
        for key, label, count in (("season", "Every match", len(usable)), ("last10", "Last 10", 10), ("last5", "Last 5", 5))
    )
    return SeasonChances(rates, tuple(matches), windows, len(rows) - len(usable))
