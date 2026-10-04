"""Matches as the manager saw them: results, FM's match stats and player stats.

A `MatchCapture` is what `tools/fm20_match_probe.py capture` read from the
game: the managed first team's results with their goals and sendings-off,
full stats for every match FM still held in memory or in its match archive,
and every result of the leagues it plays in (so the table at
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
INCIDENT_KINDS = ("goal", "own_goal", "penalty", "sent_off")
GOAL_INCIDENTS = frozenset({"goal", "own_goal", "penalty"})
# FM's pitch positions, as a match records where a player played: the
# catalogue's position names, plus FM's sweeper.
PITCH_POSITIONS = frozenset(
    {"GK", "SW", "DR", "DL", "DC", "WBR", "WBL", "DM", "MR", "ML", "MC", "AMR", "AML", "AMC", "ST"}
)
CENTRE_SIDES = ("left", "right")
# The duties FM's saved tactic words are known to mean (see
# docs/match-duty-extraction.md). FM has three more duty values, which are
# leads for Stopper, Cover and Automatic; until checked they read as unknown.
DUTY_CODES = {0x200000: "defend", 0x400000: "support", 0x800000: "attack"}

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


def _score(value: Any, where: str) -> tuple[int, int] | None:
    """An optional (home, away) score for one stage of a match."""
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{where} must be [home, away]")
    return _count(value[0], where), _count(value[1], where)


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


def _optional_choice(value: Any, choices, where: str) -> str | None:
    if value is None:
        return None
    if value not in choices:
        raise ValueError(f"{where} must be one of {', '.join(sorted(choices))}")
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
    role_code: int  # FM's code for the role he played; see analytics.match_roles
    played: bool
    rating: float | None  # None when FM shows none (unused, or barely on)
    stats: Mapping[str, int]
    distance_m: int = 0
    came_on: int | None = None  # minute a substitute came on
    went_off: int | None = None  # minute he was taken off
    # Where FM says he played (a PITCH_POSITIONS name), where he started (None
    # for a substitute) and, in a central pair, on which side he started. All
    # None in captures made before they were read, and when FM's value is not
    # a single known position.
    position: str | None = None
    start_position: str | None = None
    start_centre_side: str | None = None

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
            position=_optional_choice(raw.get("position"), PITCH_POSITIONS, f"{where} position"),
            start_position=_optional_choice(raw.get("startPosition"), PITCH_POSITIONS, f"{where} startPosition"),
            start_centre_side=_optional_choice(
                raw.get("startCentreSide"), CENTRE_SIDES, f"{where} startCentreSide"
            ),
        )

    def to_document(self) -> dict[str, Any]:
        document = {
            "side": self.side, "order": self.order, "started": self.started,
            "shortId": self.short_id, "playerId": self.player_id, "name": self.name,
            "shirt": self.shirt, "roleCode": self.role_code, "played": self.played,
            "rating": self.rating, "stats": dict(self.stats),
            "distanceM": self.distance_m, "cameOn": self.came_on, "wentOff": self.went_off,
        }
        # Left out when unknown, so a match recorded before positions were read
        # keeps its content hash and is not stored again for nothing.
        for key, value in (
            ("position", self.position),
            ("startPosition", self.start_position),
            ("startCentreSide", self.start_centre_side),
        ):
            if value is not None:
                document[key] = value
        return document


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
class SavedTacticSlot:
    """One slot of the tactic FM saved with a match: where, which role code, which duty."""

    position: str  # a PITCH_POSITIONS name
    centre_side: str | None  # "left"/"right" in a central pair
    role_code: int  # the same code FM's player records carry
    duty_code: int  # FM's raw duty value; `duty` names it when known

    @property
    def duty(self) -> str | None:
        return DUTY_CODES.get(self.duty_code)

    @classmethod
    def from_document(cls, raw: Any) -> SavedTacticSlot:
        where = "a saved tactic slot"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where} must be an object")
        position = _optional_choice(raw.get("position"), PITCH_POSITIONS, f"{where} position")
        if position is None:
            raise ValueError(f"{where} needs a position")
        return cls(
            position=position,
            centre_side=_optional_choice(raw.get("centreSide"), CENTRE_SIDES, f"{where} centreSide"),
            role_code=_count(raw.get("roleCode"), f"{where} roleCode"),
            duty_code=_count(raw.get("dutyCode"), f"{where} dutyCode"),
        )

    def to_document(self) -> dict[str, Any]:
        return {"position": self.position, "centreSide": self.centre_side,
                "roleCode": self.role_code, "dutyCode": self.duty_code}


@dataclass(frozen=True)
class SavedTactic:
    """The tactic FM saved with a match for one side, chosen because it places
    every one of that side's starters exactly as FM's player records do."""

    name: str
    slots: tuple[SavedTacticSlot, ...]

    def slot_at(self, position: str | None, centre_side: str | None) -> SavedTacticSlot | None:
        return next(
            (slot for slot in self.slots if slot.position == position and slot.centre_side == centre_side), None
        )

    @classmethod
    def from_document(cls, raw: Any) -> SavedTactic:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("slots"), list):
            raise ValueError("a saved tactic needs a list of slots")
        return cls(str(raw.get("name") or ""), tuple(SavedTacticSlot.from_document(slot) for slot in raw["slots"]))

    def to_document(self) -> dict[str, Any]:
        return {"name": self.name, "slots": [slot.to_document() for slot in self.slots]}


@dataclass(frozen=True)
class MatchDetail:
    """FM's match stats panel for both sides, the player stats and the timeline."""

    home: Mapping[str, int]
    away: Mapping[str, int]
    players: tuple[PlayerMatchStats, ...] = ()
    events: tuple[MatchEvent, ...] = ()
    # Each side's tactic as FM saved it with the match, where one fits its line-up.
    saved_tactics: Mapping[str, SavedTactic] = field(default_factory=dict)

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
            saved_tactics={
                _side(side, "a saved tactic side"): SavedTactic.from_document(tactic)
                for side, tactic in (raw.get("savedTactics") or {}).items()
            },
        )

    def to_document(self) -> dict[str, Any]:
        document = {
            "home": dict(self.home), "away": dict(self.away),
            "players": [player.to_document() for player in self.players],
            "events": [event.to_document() for event in self.events],
        }
        # Left out when none was read, so older matches keep their content hash.
        if self.saved_tactics:
            document["savedTactics"] = {side: tactic.to_document() for side, tactic in self.saved_tactics.items()}
        return document


@dataclass(frozen=True)
class MatchIncident:
    """A goal or a sending-off, from the result FM keeps for every match.

    `side` is the side a goal counts for, so an own goal's side is not its
    scorer's; for a sending-off it is the side of the player sent off.
    """

    minute: int
    added_time: int
    side: str
    kind: str
    player_short_id: int
    player: str | None = None

    @property
    def is_goal(self) -> bool:
        return self.kind in GOAL_INCIDENTS

    @property
    def clock(self) -> str:
        """The minute as FM shows it: 45, or 90+4."""
        return f"{self.minute}+{self.added_time}" if self.added_time else str(self.minute)

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> MatchIncident:
        where = "a match incident"
        kind = raw.get("kind")
        if kind not in INCIDENT_KINDS:
            raise ValueError(f"{where} kind must be one of {', '.join(INCIDENT_KINDS)}")
        player = raw.get("player")
        return cls(
            minute=_count(raw.get("minute"), f"{where} minute"),
            added_time=_count(raw.get("addedTime", 0), f"{where} addedTime"),
            side=_side(raw.get("side"), f"{where} side"),
            kind=kind,
            player_short_id=_count(raw.get("playerShortId"), f"{where} playerShortId"),
            player=str(player) if player else None,
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "minute": self.minute, "addedTime": self.added_time, "side": self.side, "kind": self.kind,
            "playerShortId": self.player_short_id, "player": self.player,
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
    # Goals and sendings-off in match order; empty for a capture made before
    # they were read, and for a 0-0 without a red card.
    incidents: tuple[MatchIncident, ...] = ()
    # home_goals/away_goals are the score FM shows, after extra time when it
    # was played; these are (home, away) for the stages beyond 90 minutes.
    score_at_90: tuple[int, int] | None = None
    penalties: tuple[int, int] | None = None

    @property
    def after_extra_time(self) -> bool:
        return self.score_at_90 is not None

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
            incidents=tuple(MatchIncident.from_document(item) for item in raw.get("incidents") or ()),
            score_at_90=_score(raw.get("scoreAt90"), f"{where} scoreAt90"),
            penalties=_score(raw.get("penalties"), f"{where} penalties"),
        )

    def to_document(self) -> dict[str, Any]:
        document = {
            "date": self.date.isoformat(),
            "competition": self.competition.to_document(),
            "home": self.home.to_document(),
            "away": self.away.to_document(),
            "homeGoals": self.home_goals,
            "awayGoals": self.away_goals,
            "attendance": self.attendance,
            "detail": self.detail.to_document() if self.detail else None,
        }
        # Left out when empty, so a match recorded before these were read
        # keeps its content hash and is not stored again for nothing.
        if self.score_at_90:
            document["scoreAt90"] = list(self.score_at_90)
        if self.penalties:
            document["penalties"] = list(self.penalties)
        if self.incidents:
            document["incidents"] = [incident.to_document() for incident in self.incidents]
        return document

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
