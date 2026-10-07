"""How strong an opponent was at kickoff, three ways.

* **Table** (the default): the opponent's league position on the morning of
  the match, rebuilt from that season's league results, in thirds. It needs
  no input, works for matches already played, and cannot be coloured by how
  the match went.
* **Relative**: whether they were above or below us in that table.
* **Your rating**: the manager's own pre-match read on the opponent-quality
  scale the tactic sliders use (-2..+2). Optional, and only as honest as the
  moment it was recorded.

A team that has played fewer than `EARLY_SEASON_GAMES` league games is "early
season": a position after one or two games says little. A team outside the
leagues we play in is "not in our league".

FM keeps every season of a league under one competition, so the table is
built from one season's results only: the season FM files a competitive
match under. A friendly has none, so it is rated by the latest season under
way at kickoff (in pre-season, the one just finished). Results recorded
before seasons were read count as one season, as they always did.
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
class LeagueSeason:
    """One season of one league: its results and every team that played in it."""

    competition: Competition
    season: int | None  # the year FM's season starts; None for results recorded before it was read
    results: tuple[LeagueResult, ...]
    teams: frozenset[str]
    starts: date  # its first result
    ends: date  # its last result so far


def league_seasons(leagues: Iterable[tuple[Competition, Sequence[LeagueResult]]]) -> tuple[LeagueSeason, ...]:
    """Each league split into the seasons FM files its results under."""
    seasons = []
    for competition, results in leagues:
        by_season: dict[int | None, list[LeagueResult]] = {}
        for result in results:
            by_season.setdefault(result.season, []).append(result)
        for season, rows in by_season.items():
            dates = [row.date for row in rows]
            seasons.append(LeagueSeason(
                competition, season, tuple(rows),
                frozenset(team.id for row in rows for team in (row.home, row.away)),
                min(dates), max(dates),
            ))
    return tuple(seasons)


@dataclass(frozen=True)
class Strength:
    """One match's opponent strength under every grouping."""

    league: Competition | None
    opponent: TablePosition | None
    ours: TablePosition | None
    rating: int | None
    season: int | None = None  # the season of `league` whose table placed them

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
    """Rebuilds each league season's table once per kickoff date and reuses it."""

    def __init__(self, leagues: Iterable[tuple[Competition, Sequence[LeagueResult]]], club_id: str):
        self.club_id = club_id
        self._ours = tuple(season for season in league_seasons(leagues) if club_id in season.teams)
        self._cache: dict[tuple[str, int | None, date], dict[str, TablePosition]] = {}

    def strength(self, match: MatchRecord, opponent_id: str, rating: int | None) -> Strength:
        league = self.season_of(match, opponent_id)
        if league is None:
            return Strength(None, None, None, rating)
        key = (league.competition.id, league.season, match.date)
        if key not in self._cache:
            self._cache[key] = positions(league.results, match.date)
        table = self._cache[key]
        return Strength(league.competition, table.get(opponent_id), table.get(self.club_id), rating, league.season)

    def season_of(self, match: MatchRecord, opponent_id: str) -> LeagueSeason | None:
        """The league season, ours and the opponent's, whose table rates this match; None if there is none.

        A competitive match uses the season FM files it under. Otherwise it is
        the latest season under way at kickoff; or, once that has finished, the
        next one, so a newly promoted side in pre-season is early season.
        """
        if match.season is not None:
            filed = [league for league in self._ours if league.season == match.season]
            if filed:
                return next((league for league in filed if opponent_id in league.teams), None)
        current = max((league for league in self._ours if league.starts < match.date),
                      key=lambda league: league.starts, default=None)
        if current is not None and opponent_id in current.teams:
            return current
        if current is None or current.ends < match.date:
            following = min((league for league in self._ours if league.starts >= match.date),
                            key=lambda league: league.starts, default=None)
            if following is not None and opponent_id in following.teams:
                return following
        return None
