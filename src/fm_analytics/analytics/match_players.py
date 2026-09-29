"""What each of our players did across the matches reviewed (full-stats matches only).

The per-player counterpart of `match_roles.summarise_roles`: FM's own player
match stats summed per player, with the role he played each time. A player is
known by FM's unique ID when he is in the managed squad, else by his name.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from fm_analytics.analytics.match_roles import RoleCodes
from fm_analytics.domain.matches import PLAYER_STAT_KEYS, PlayerMatchStats


@dataclass(frozen=True)
class PlayerRating:
    date: date
    opponent: str
    rating: float


@dataclass(frozen=True)
class PlayerSeason:
    name: str
    player_id: str | None
    appearances: int
    starts: int
    minutes: int
    distance_m: int
    stats: Mapping[str, int]  # every PLAYER_STAT_KEYS total
    roles: tuple[tuple[str, int], ...]  # role label, appearances; most played first
    ratings: tuple[PlayerRating, ...]  # oldest first

    @property
    def substitute_appearances(self) -> int:
        return self.appearances - self.starts

    @property
    def average_rating(self) -> float | None:
        if not self.ratings:
            return None
        return round(sum(item.rating for item in self.ratings) / len(self.ratings), 2)

    def stat(self, key: str) -> int:
        return self.stats.get(key, 0)

    def per_90(self, value: float) -> float | None:
        """A count per 90 minutes played; None with no minutes to divide by."""
        return 90 * value / self.minutes if self.minutes else None


def summarise_players(
    appearances: Iterable[tuple[PlayerMatchStats, date, str]], codes: RoleCodes
) -> tuple[PlayerSeason, ...]:
    """Group (player line, match date, opponent name) by player, most minutes first."""
    rows: dict[str, dict] = {}
    for player, day, opponent in appearances:
        if not player.played:
            continue
        row = rows.setdefault(player.player_id or player.label, {
            "name": player.label, "player_id": player.player_id, "counts": Counter(),
            "roles": Counter(), "ratings": [],
        })
        counts = row["counts"]
        counts["appearances"] += 1
        counts["starts"] += int(player.started)
        counts["minutes"] += player.minutes
        counts["distance_m"] += player.distance_m
        for key in PLAYER_STAT_KEYS:
            counts[key] += player.stat(key)
        row["roles"][codes.label(player.role_code)] += 1
        if player.rating is not None:
            row["ratings"].append(PlayerRating(day, opponent, player.rating))
    seasons = [
        PlayerSeason(
            name=row["name"],
            player_id=row["player_id"],
            appearances=row["counts"]["appearances"],
            starts=row["counts"]["starts"],
            minutes=row["counts"]["minutes"],
            distance_m=row["counts"]["distance_m"],
            stats={key: row["counts"][key] for key in PLAYER_STAT_KEYS},
            roles=tuple(row["roles"].most_common()),
            ratings=tuple(sorted(row["ratings"], key=lambda item: item.date)),
        )
        for row in rows.values()
    ]
    seasons.sort(key=lambda season: (-season.minutes, season.name))
    return tuple(seasons)
