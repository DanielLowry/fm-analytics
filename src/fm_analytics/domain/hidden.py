"""Every league club's players with their hidden attributes: the real values FM keeps.

HIDDEN DATA. Unlike every other capture, this one holds what FM does not show
the manager: the true 1-20 value of each attribute for every player, however
little the manager knows him, and his true rating at every position. It exists
for one purpose, the League page's "Hidden attributes" view
(docs/hidden-attributes.md), and must never reach the recommendation, the
visible League comparison, Scouting or anything else that promises to use only
what FM shows. It has its own format, file and loader so that it cannot be
mistaken for a manager-visible capture.

Written by ``tools/fm20_hidden_capture.py``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from fm_analytics.domain.attributes import VISIBLE_ATTRIBUTES
from fm_analytics.domain.matches import Competition, TeamRef

FORMAT = "fm-analytics/hidden-attributes"
VERSION = 1

# FM's fifteen position ratings, in the order FM stores them.
POSITION_CODES = ("GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "AMC", "AMR", "ST", "WBL", "WBR")
# A position counts as one a player can play from this rating up, the same rule
# our own squad's read uses (tools/fm20_linux_probe.POSITION_ELIGIBILITY_MINIMUM).
ELIGIBLE_RATING = 10


def _object(raw: Any, fields: set[str], where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where} must be an object")
    unknown = set(raw) - fields
    if unknown:
        raise ValueError(f"{where} has unsupported fields: {', '.join(sorted(unknown))}")
    return raw


def _text(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} {key} must be non-empty text")
    return value


def _ratings(raw: Any, keys, low: int, where: str) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where} must be an object")
    if set(raw) != set(keys):
        missing, extra = set(keys) - set(raw), set(raw) - set(keys)
        raise ValueError(f"{where} must hold exactly the expected names"
                         + (f"; missing {', '.join(sorted(missing))}" if missing else "")
                         + (f"; unexpected {', '.join(sorted(extra))}" if extra else ""))
    for name, value in raw.items():
        if type(value) is not int or not low <= value <= 20:
            raise ValueError(f"{where} {name} must be a whole number from {low} to 20")
    return dict(raw)


@dataclass(frozen=True)
class HiddenPlayer:
    id: str  # FM's unique ID, the one the squad and league reads key a player by
    short_id: int  # the ID FM's match records name him by
    name: str
    age: int | None
    attributes: Mapping[str, int]  # every attribute FM shows on a profile, at its true value
    position_ratings: Mapping[str, int]  # FM's own 1-20 rating at each of the fifteen positions

    @property
    def positions(self) -> tuple[str, ...]:
        """The positions he can play, by the rule our own squad's read uses."""
        shown = tuple(code for code in POSITION_CODES if self.position_ratings.get(code, 0) >= ELIGIBLE_RATING)
        if shown:
            return shown
        return (max(POSITION_CODES, key=lambda code: self.position_ratings.get(code, 0)),)

    @classmethod
    def from_document(cls, raw: Any) -> HiddenPlayer:
        where = "a hidden-attribute player"
        row = _object(raw, {"id", "shortId", "name", "age", "attributes", "positionRatings"}, where)
        player_id = _text(row, "id", where)
        if not player_id.isdigit():
            raise ValueError(f"{where} id must be FM's numeric unique ID")
        short_id, age = row.get("shortId"), row.get("age")
        if type(short_id) is not int or short_id <= 0:
            raise ValueError(f"{where} shortId must be a positive whole number")
        if age is not None and (type(age) is not int or not 0 <= age <= 80):
            raise ValueError(f"{where} age must be a whole number of years")
        return cls(player_id, short_id, _text(row, "name", where), age,
                   _ratings(row.get("attributes"), VISIBLE_ATTRIBUTES, 1, f"{where}'s attributes"),
                   _ratings(row.get("positionRatings"), POSITION_CODES, 1, f"{where}'s position ratings"))

    def to_document(self) -> dict[str, Any]:
        return {"id": self.id, "shortId": self.short_id, "name": self.name, "age": self.age,
                "attributes": dict(sorted(self.attributes.items())),
                "positionRatings": {code: self.position_ratings[code] for code in POSITION_CODES}}


@dataclass(frozen=True)
class HiddenTeam:
    club: TeamRef
    player_ids: tuple[str, ...]  # the first-team squad, in the same scope as the League page's read
    evidence: str

    def to_document(self) -> dict[str, Any]:
        return {"club": self.club.to_document(), "playerIds": list(self.player_ids), "evidence": self.evidence}


@dataclass(frozen=True)
class HiddenCapture:
    save_key: str
    game_date: date
    season: str
    club: TeamRef  # ours
    competition: Competition  # our league this season
    teams: tuple[HiddenTeam, ...]
    players: Mapping[str, HiddenPlayer]  # by FM unique ID: every squad player and every stored starter
    notes: tuple[str, ...] = ()
    _by_short_id: dict[int, HiddenPlayer] = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.save_key.strip() or not self.season.strip():
            raise ValueError("a hidden-attribute capture needs a save key and a season")
        clubs = [team.club.id for team in self.teams]
        if len(clubs) != len(set(clubs)):
            raise ValueError("a club appears twice in the hidden-attribute capture")
        if self.club.id not in clubs:
            raise ValueError("the hidden-attribute capture must include our own club")
        listed: set[str] = set()
        for team in self.teams:
            for player_id in team.player_ids:
                if player_id not in self.players:
                    raise ValueError(f"{team.club.name}'s player {player_id} has no attributes in the capture")
                if player_id in listed:
                    raise ValueError(f"player {player_id} is in two squads")
                listed.add(player_id)
        for key, player in self.players.items():
            if key != player.id:
                raise ValueError("hidden-attribute players must be keyed by their own ID")
            # A short ID FM reuses would put the wrong player in a line-up; refuse rather than guess.
            if self._by_short_id.setdefault(player.short_id, player) is not player:
                raise ValueError(f"two players share FM's match ID {player.short_id}")

    def squad(self, club_id: str) -> tuple[HiddenPlayer, ...]:
        team = next((team for team in self.teams if team.club.id == club_id), None)
        return tuple(self.players[player_id] for player_id in team.player_ids) if team else ()

    def by_short_id(self, short_id: int) -> HiddenPlayer | None:
        return self._by_short_id.get(short_id)

    @classmethod
    def from_document(cls, document: Any) -> HiddenCapture:
        raw = _object(document, {"format", "formatVersion", "saveKey", "gameDate", "season", "club",
                                 "competition", "teams", "players", "notes"}, "hidden-attribute capture")
        if raw.get("format") != FORMAT or type(raw.get("formatVersion")) is not int or raw["formatVersion"] != VERSION:
            raise ValueError("not a version 1 hidden-attribute capture")
        teams = raw.get("teams")
        players = raw.get("players")
        notes = raw.get("notes", [])
        if not isinstance(teams, list) or not isinstance(players, list):
            raise ValueError("a hidden-attribute capture's teams and players must be arrays")
        if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
            raise ValueError("a hidden-attribute capture's notes must be text")
        parsed_teams = []
        for entry in teams:
            row = _object(entry, {"club", "playerIds", "evidence"}, "a hidden-attribute team")
            ids = row.get("playerIds")
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                raise ValueError("a hidden-attribute team's playerIds must be text")
            parsed_teams.append(HiddenTeam(TeamRef.from_document(row.get("club"), "a hidden-attribute club"),
                                           tuple(ids), _text(row, "evidence", "a hidden-attribute team")))
        parsed_players = [HiddenPlayer.from_document(item) for item in players]
        by_id = {player.id: player for player in parsed_players}
        if len(by_id) != len(parsed_players):
            raise ValueError("a player appears twice in the hidden-attribute capture")
        try:
            game_date = date.fromisoformat(_text(raw, "gameDate", "the capture"))
        except ValueError as exc:
            raise ValueError(f"the capture's gameDate is not a date: {exc}") from exc
        return cls(_text(raw, "saveKey", "the capture"), game_date, _text(raw, "season", "the capture"),
                   TeamRef.from_document(raw.get("club"), "the capture's club"),
                   Competition.from_document(raw.get("competition"), "the capture's competition"),
                   tuple(parsed_teams), by_id, tuple(notes))

    def to_document(self) -> dict[str, Any]:
        return {"format": FORMAT, "formatVersion": VERSION, "saveKey": self.save_key,
                "gameDate": self.game_date.isoformat(), "season": self.season, "club": self.club.to_document(),
                "competition": self.competition.to_document(), "teams": [team.to_document() for team in self.teams],
                "players": [self.players[key].to_document() for key in sorted(self.players, key=int)],
                "notes": list(self.notes)}

    def content_hash(self) -> str:
        payload = json.dumps(self.to_document(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
