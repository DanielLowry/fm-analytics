"""Matches as the manager saw them: results, FM's match stats and player stats.

A `MatchCapture` is what `tools/fm20_match_probe.py capture` read from the
game: the managed first team's results, full stats for any match FM still
held in memory, and every result of the leagues it plays in (so the table at
each kickoff can be rebuilt). Everything in it is on FM's own match screens.

Stats are key/value maps rather than fixed fields, so a newly decoded FM stat
needs no schema change anywhere. The perspective stays neutral (home/away):
`MatchRecord.side_of` turns it into "us" and "them" for a given club.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any, Mapping

CAPTURE_FORMAT = "fm-analytics/match-capture"
CAPTURE_FORMAT_VERSION = 1
SIDES = ("home", "away")
MATCH_MINUTES = 90

# FM's match stats panel, in the order FM lists it.
TEAM_STAT_KEYS = (
    "shots",
    "shots_on_target",
    "clear_cut_chances",
    "possession_time",
    "corners",
    "fouls",
    "passes_attempted",
    "passes_completed",
    "tackles_attempted",
    "tackles_won",
    "headers_attempted",
    "headers_won",
    "goals",
)
PLAYER_STAT_KEYS = (
    "goals",
    "assists",
    "shots",
    "shots_on_target",
    "shots_blocked",
    "clear_cut_chances",
    "chances_created",
    "key_passes",
    "dribbles",
    "passes_attempted",
    "passes_completed",
    "tackles_attempted",
    "tackles_won",
    "headers_attempted",
    "headers_won",
    "fouls",
    "corners_taken",
    "goals_conceded",
)


def _require(document: Mapping[str, Any], key: str, kind: type | tuple[type, ...], where: str) -> Any:
    value = document.get(key)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise ValueError(f"{where} needs {key!r}")
    return value


def _count(value: Any, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{where} must be a whole number of at least 0")
    return value


def _counts(raw: Any, where: str) -> Mapping[str, int]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where} must be an object of counts")
    return MappingProxyType({str(key): _count(value, f"{where} {key}") for key, value in raw.items()})


def _team_counts(raw: Any, where: str) -> Mapping[str, int]:
    """A side's panel stats. Captures before the archive reader was aligned with
    the live one named the team's corners `corners_taken`; they are `corners`."""
    counts = _counts(raw, where)
    if "corners_taken" in counts and "corners" not in counts:
        renamed = dict(counts)
        renamed["corners"] = renamed.pop("corners_taken")
        return MappingProxyType(renamed)
    return counts


def _optional_minute(value: Any, where: str) -> int | None:
    if value is None:
        return None
    minute = _count(value, where)
    if minute > 200:
        raise ValueError(f"{where} is not a match minute")
    return minute


def _side(value: Any, where: str) -> str:
    if value not in SIDES:
        raise ValueError(f"{where} must be 'home' or 'away'")
    return value


def _date(value: Any, where: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} must be an ISO date") from exc


@dataclass(frozen=True)
class TeamRef:
    id: str
    name: str

    @classmethod
    def from_document(cls, raw: Any, where: str) -> TeamRef:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where} must be an object")
        return cls(str(_require(raw, "id", str, where)), str(_require(raw, "name", str, where)))

    def to_document(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


@dataclass(frozen=True)
class Competition:
    id: str
    name: str
    short_name: str = ""

    @property
    def label(self) -> str:
        return self.short_name or self.name

    @property
    def is_friendly(self) -> bool:
        return self.name.casefold() in {"friendly", "friendlies"}

    @classmethod
    def from_document(cls, raw: Any, where: str) -> Competition:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where} must be an object")
        return cls(
            str(_require(raw, "id", str, where)),
            str(_require(raw, "name", str, where)),
            str(raw.get("shortName") or ""),
        )

    def to_document(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "shortName": self.short_name}


@dataclass(frozen=True)
class PlayerMatchStats:
    """One player's line in FM's player match stats."""

    side: str
    order: int  # place in FM's line-up list; the first eleven started
    started: bool
    short_id: int
    player_id: str | None  # FM's unique ID when the player is in the managed squad
    name: str | None
    shirt: int
    role_code: int  # FM's role for the position played, one bit per role
    played: bool
    rating: float | None  # None when FM shows none (unused, or barely on)
    stats: Mapping[str, int]
    distance_m: int = 0
    came_on: int | None = None  # minute a substitute came on
    went_off: int | None = None  # minute he was taken off

    @property
    def minutes(self) -> int:
        """Minutes on the pitch, counting a full match as FM does (90)."""
        if not self.played:
            return 0
        return max((self.went_off or MATCH_MINUTES) - (self.came_on or 0), 0)

    def stat(self, key: str) -> int:
        return self.stats.get(key, 0)

    @property
    def label(self) -> str:
        return self.name or f"Player #{self.shirt}"

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> PlayerMatchStats:
        where = "a match player"
        rating = raw.get("rating")
        if rating is not None and (not isinstance(rating, (int, float)) or not 0 <= rating <= 10):
            raise ValueError(f"{where} rating must be between 0 and 10")
        name = raw.get("name")
        player_id = raw.get("playerId")
        return cls(
            side=_side(raw.get("side"), f"{where} side"),
            order=_count(raw.get("order"), f"{where} order"),
            started=bool(raw.get("started")),
            short_id=_count(raw.get("shortId"), f"{where} shortId"),
            player_id=str(player_id) if player_id is not None else None,
            name=str(name) if name else None,
            shirt=_count(raw.get("shirt"), f"{where} shirt"),
            role_code=_count(raw.get("roleCode"), f"{where} roleCode"),
            played=bool(raw.get("played")),
            rating=float(rating) if rating is not None else None,
            stats=_counts(raw.get("stats", {}), f"{where} stats"),
            distance_m=_count(raw.get("distanceM", 0), f"{where} distanceM"),
            came_on=_optional_minute(raw.get("cameOn"), f"{where} cameOn"),
            went_off=_optional_minute(raw.get("wentOff"), f"{where} wentOff"),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "side": self.side, "order": self.order, "started": self.started,
            "shortId": self.short_id, "playerId": self.player_id, "name": self.name,
            "shirt": self.shirt, "roleCode": self.role_code, "played": self.played,
            "rating": self.rating, "stats": dict(self.stats),
            "distanceM": self.distance_m, "cameOn": self.came_on, "wentOff": self.went_off,
        }


@dataclass(frozen=True)
class MatchEvent:
    """A timeline entry: a goal, its assist, or a clear-cut chance."""

    minute: int
    side: str
    kind: str
    code: int

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> MatchEvent:
        return cls(
            minute=_count(raw.get("minute"), "an event minute"),
            side=_side(raw.get("side"), "an event side"),
            kind=str(raw.get("kind") or "other"),
            code=_count(raw.get("code", 0), "an event code"),
        )

    def to_document(self) -> dict[str, Any]:
        return {"minute": self.minute, "side": self.side, "kind": self.kind, "code": self.code}


@dataclass(frozen=True)
class MatchDetail:
    """FM's match stats panel for both sides, the player stats and the timeline."""

    home: Mapping[str, int]
    away: Mapping[str, int]
    players: tuple[PlayerMatchStats, ...] = ()
    events: tuple[MatchEvent, ...] = ()

    def team(self, side: str) -> Mapping[str, int]:
        return self.home if _side(side, "a side") == "home" else self.away

    def players_for(self, side: str) -> tuple[PlayerMatchStats, ...]:
        return tuple(player for player in self.players if player.side == side)

    def possession_percent(self, side: str) -> int | None:
        """FM's possession figure: each side's share of possession time."""
        ours, total = self.team(side).get("possession_time", 0), (
            self.home.get("possession_time", 0) + self.away.get("possession_time", 0)
        )
        return round(100 * ours / total) if total else None

    @classmethod
    def from_document(cls, raw: Any) -> MatchDetail | None:
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ValueError("match detail must be an object")
        return cls(
            home=_team_counts(raw.get("home"), "home stats"),
            away=_team_counts(raw.get("away"), "away stats"),
            players=tuple(PlayerMatchStats.from_document(item) for item in raw.get("players") or ()),
            events=tuple(MatchEvent.from_document(item) for item in raw.get("events") or ()),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "home": dict(self.home), "away": dict(self.away),
            "players": [player.to_document() for player in self.players],
            "events": [event.to_document() for event in self.events],
        }


@dataclass(frozen=True)
class MatchRecord:
    date: date
    competition: Competition
    home: TeamRef
    away: TeamRef
    home_goals: int
    away_goals: int
    attendance: int | None = None
    detail: MatchDetail | None = None

    @property
    def key(self) -> str:
        """Stable across captures: a club plays at most once a day."""
        return f"{self.date.isoformat()}:{self.home.id}:{self.away.id}"

    def side_of(self, club_id: str) -> str:
        if club_id == self.home.id:
            return "home"
        if club_id == self.away.id:
            return "away"
        raise ValueError(f"club {club_id} did not play in {self.key}")

    def goals(self, side: str) -> int:
        return self.home_goals if _side(side, "a side") == "home" else self.away_goals

    def team(self, side: str) -> TeamRef:
        return self.home if _side(side, "a side") == "home" else self.away

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> MatchRecord:
        where = "a match"
        attendance = raw.get("attendance")
        return cls(
            date=_date(raw.get("date"), f"{where} date"),
            competition=Competition.from_document(raw.get("competition"), f"{where} competition"),
            home=TeamRef.from_document(raw.get("home"), f"{where} home team"),
            away=TeamRef.from_document(raw.get("away"), f"{where} away team"),
            home_goals=_count(raw.get("homeGoals"), f"{where} homeGoals"),
            away_goals=_count(raw.get("awayGoals"), f"{where} awayGoals"),
            attendance=_count(attendance, f"{where} attendance") if attendance is not None else None,
            detail=MatchDetail.from_document(raw.get("detail")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "competition": self.competition.to_document(),
            "home": self.home.to_document(),
            "away": self.away.to_document(),
            "homeGoals": self.home_goals,
            "awayGoals": self.away_goals,
            "attendance": self.attendance,
            "detail": self.detail.to_document() if self.detail else None,
        }

    def content_hash(self) -> str:
        text = json.dumps(self.to_document(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LeagueResult:
    """One result of a league the managed team plays in, for its table."""

    date: date
    home: TeamRef
    away: TeamRef
    home_goals: int
    away_goals: int

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> LeagueResult:
        return cls(
            date=_date(raw.get("date"), "a league result date"),
            home=TeamRef.from_document(raw.get("home"), "a league result home team"),
            away=TeamRef.from_document(raw.get("away"), "a league result away team"),
            home_goals=_count(raw.get("homeGoals"), "a league result homeGoals"),
            away_goals=_count(raw.get("awayGoals"), "a league result awayGoals"),
        )


@dataclass(frozen=True)
class MatchCapture:
    captured_at: str
    game_date: date
    managed_club: TeamRef
    matches: tuple[MatchRecord, ...]
    league_results: tuple[tuple[Competition, tuple[LeagueResult, ...]], ...] = field(default=())

    @classmethod
    def from_document(cls, document: Any) -> MatchCapture:
        if not isinstance(document, Mapping) or document.get("format") != CAPTURE_FORMAT:
            raise ValueError("not a match capture (run tools/fm20_match_probe.py capture)")
        if document.get("formatVersion") != CAPTURE_FORMAT_VERSION:
            raise ValueError(
                f"match capture format {document.get('formatVersion')!r} is not "
                f"version {CAPTURE_FORMAT_VERSION}, which this program reads"
            )
        source = document.get("source") or {}
        return cls(
            captured_at=str(_require(document, "capturedAt", str, "a match capture")),
            game_date=_date(document.get("gameDate"), "the capture gameDate"),
            managed_club=TeamRef.from_document(source.get("managedClub"), "the capture's managed club"),
            matches=tuple(MatchRecord.from_document(item) for item in document.get("matches") or ()),
            league_results=tuple(
                (
                    Competition.from_document(item.get("competition"), "a league"),
                    tuple(LeagueResult.from_document(row) for row in item.get("results") or ()),
                )
                for item in document.get("competitionResults") or ()
            ),
        )
