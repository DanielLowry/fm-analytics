"""How strong an opponent was at kickoff, three ways.

* **Table** (the default): the opponent's league position on the morning of
  the match, rebuilt from the league's own results, in thirds. It needs no
  input, works for matches already played, and cannot be coloured by how the
  match went.
* **Relative**: whether they were above or below us in that table.
* **Your rating**: the manager's own pre-match read on the opponent-quality
  scale the tactic sliders use (-2..+2). Optional, and only as honest as the
  moment it was recorded.

A team that has played fewer than `EARLY_SEASON_GAMES` league games is "early
season": a position after one or two games says little. A team outside the
leagues we play in is "not in our league".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

from fm_analytics.domain.matches import Competition, LeagueResult, MatchRecord

EARLY_SEASON_GAMES = 3
GROUPINGS = ("table", "relative", "rating")
GROUPING_LABELS = {
    "table": "Opponent's league position at kickoff",
    "relative": "Opponent above or below us at kickoff",
    "rating": "Your pre-match rating of the opponent",
}


@dataclass(frozen=True)
class Band:
    key: str
    label: str
    order: int


BANDS: Mapping[str, tuple[Band, ...]] = {
    "table": (
        Band("top", "Top third", 0),
        Band("middle", "Middle third", 1),
        Band("bottom", "Bottom third", 2),
        Band("early", "Early season", 3),
        Band("outside", "Not in our league", 4),
    ),
    "relative": (
        Band("above", "Above us", 0),
        Band("below", "Below us", 1),
        Band("early", "Early season", 2),
        Band("outside", "Not in our league", 3),
    ),
    "rating": (
        Band("stronger", "Stronger than us", 0),
        Band("similar", "Similar", 1),
        Band("weaker", "Weaker than us", 2),
        Band("unrated", "Not rated", 3),
    ),
}
_BY_KEY = {grouping: {band.key: band for band in bands} for grouping, bands in BANDS.items()}


@dataclass(frozen=True)
class TablePosition:
    position: int
    teams: int
    played: int
    points: int


@dataclass(frozen=True)
class TableRow:
    team_id: str
    name: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def points(self) -> int:
        return 3 * self.won + self.drawn

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


def league_table(results: Sequence[LeagueResult], before: date) -> tuple[TableRow, ...]:
    """The table on the morning of `before`: every team, results strictly earlier.

    Teams with no result yet are still listed (from later results), so the
    table always has the whole league. Ties go on goal difference, then goals
    scored, then name, which keeps the order deterministic.
    """
    rows: dict[str, dict] = {}
    for result in results:
        for team in (result.home, result.away):
            rows.setdefault(team.id, {"name": team.name, "p": 0, "w": 0, "d": 0, "l": 0, "f": 0, "a": 0})
    for result in results:
        if result.date >= before:
            continue
        for team, scored, conceded in (
            (result.home, result.home_goals, result.away_goals),
            (result.away, result.away_goals, result.home_goals),
        ):
            row = rows[team.id]
            row["p"] += 1
            row["f"] += scored
            row["a"] += conceded
            row["w" if scored > conceded else "d" if scored == conceded else "l"] += 1
    table = [
        TableRow(team_id, row["name"], row["p"], row["w"], row["d"], row["l"], row["f"], row["a"])
        for team_id, row in rows.items()
    ]
    table.sort(key=lambda row: (-row.points, -row.goal_difference, -row.goals_for, row.name))
    return tuple(table)


def positions(results: Sequence[LeagueResult], before: date) -> dict[str, TablePosition]:
    table = league_table(results, before)
    return {
        row.team_id: TablePosition(index, len(table), row.played, row.points)
        for index, row in enumerate(table, start=1)
    }


@dataclass(frozen=True)
class Strength:
    """One match's opponent strength under every grouping."""

    league: Competition | None
    opponent: TablePosition | None
    ours: TablePosition | None
    rating: int | None

    def band(self, grouping: str) -> Band:
        if grouping not in _BY_KEY:
            raise ValueError(f"unknown grouping {grouping!r}; choose one of {', '.join(GROUPINGS)}")
        return _BY_KEY[grouping][self._band_key(grouping)]

    def _band_key(self, grouping: str) -> str:
        if grouping == "rating":
            if self.rating is None:
                return "unrated"
            return "stronger" if self.rating > 0 else "weaker" if self.rating < 0 else "similar"
        if self.opponent is None:
            return "outside"
        if self.opponent.played < EARLY_SEASON_GAMES:
            return "early"
        if grouping == "relative":
            if self.ours is None:
                return "outside"
            return "above" if self.opponent.position < self.ours.position else "below"
        third = round(self.opponent.teams / 3)
        if self.opponent.position <= third:
            return "top"
        if self.opponent.position > self.opponent.teams - third:
            return "bottom"
        return "middle"


class StrengthCalculator:
    """Rebuilds each league's table once per kickoff date and reuses it."""

    def __init__(self, leagues: Iterable[tuple[Competition, Sequence[LeagueResult]]], club_id: str):
        self.club_id = club_id
        self._leagues = [
            (competition, tuple(results), {team.id for result in results for team in (result.home, result.away)})
            for competition, results in leagues
        ]
        self._cache: dict[tuple[str, date], dict[str, TablePosition]] = {}

    def strength(self, match: MatchRecord, opponent_id: str, rating: int | None) -> Strength:
        for competition, results, teams in self._leagues:
            if opponent_id in teams and self.club_id in teams:
                key = (competition.id, match.date)
                if key not in self._cache:
                    self._cache[key] = positions(results, match.date)
                table = self._cache[key]
                return Strength(competition, table.get(opponent_id), table.get(self.club_id), rating)
        return Strength(None, None, None, rating)
