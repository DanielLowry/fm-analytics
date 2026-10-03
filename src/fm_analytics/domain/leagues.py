"""Dated league membership and visible first-team observations.

Diagnostic inventories are deliberately a different format. Historical player
knowledge cannot supply today's roster or narrow today's attribute bounds.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from fm_analytics.domain.models import GameState, Squad
from fm_analytics.domain.matches import Competition
from fm_analytics.domain.attributes import VISIBLE_ATTRIBUTES

FORMAT = "fm-analytics/league-capture"
VERSION = 1


def _object(raw: Any, fields: set[str], where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where} must be an object")
    unknown = set(raw) - fields
    if unknown:
        raise ValueError(f"{where} has unsupported fields: {', '.join(sorted(unknown))}")
    return raw


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    return value


def _boolean(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


@dataclass(frozen=True)
class LeagueRoster:
    squad: Squad
    roster_complete: bool
    positions_complete: bool
    evidence: str
    errors: tuple[str, ...] = ()

    def to_document(self) -> dict[str, Any]:
        return {"squad": self.squad.to_dict(), "rosterComplete": self.roster_complete,
                "positionsComplete": self.positions_complete, "evidence": self.evidence,
                "errors": list(self.errors)}


@dataclass(frozen=True)
class LeagueCapture:
    save_key: str
    game: GameState
    season: str
    competition: Competition
    membership_complete: bool
    membership_evidence: str
    source_kind: str
    teams: tuple[LeagueRoster, ...]

    def __post_init__(self) -> None:
        if not self.save_key.strip() or not self.season.strip() or not self.membership_evidence.strip():
            raise ValueError("save key, season, and membership evidence are required")
        if self.source_kind not in {"fixture", "manager-visible"}:
            raise ValueError("league source must be fixture or manager-visible")
        if not isinstance(self.membership_complete, bool):
            raise ValueError("membershipComplete must be a boolean")
        clubs, players = set(), set()
        for roster in self.teams:
            squad = roster.squad
            if squad.club is None or squad.club.id in clubs:
                raise ValueError("league rosters require unique club IDs")
            clubs.add(squad.club.id)
            if squad.as_of_date != self.game.game_date:
                raise ValueError("league rosters must share the capture game date")
            if squad.other_teams:
                raise ValueError("league comparison captures contain first-team rosters only")
            if not isinstance(roster.roster_complete, bool) or not isinstance(roster.positions_complete, bool):
                raise ValueError("roster and position completeness must be booleans")
            if not roster.evidence.strip():
                raise ValueError("roster evidence is required")
            for player in squad.players:
                if set(player.attributes) - VISIBLE_ATTRIBUTES:
                    raise ValueError("league captures only support allowlisted visible attributes")
                if player.id in players or player.club_id != squad.club.id:
                    raise ValueError("a player must belong to one captured roster with a unique ID")
                players.add(player.id)
                if (self.game.controlled_club is None or squad.club.id != self.game.controlled_club.id) and player.position_familiarity:
                    raise ValueError("external numeric position familiarity is not supported by this capture")
                if len(player.positions) != len(set(player.positions)):
                    raise ValueError("player positions must be unique")
                if roster.positions_complete and not player.positions:
                    raise ValueError("complete position evidence requires positions for every player")
                for observation in player.attributes.values():
                    for value in (observation.value, observation.minimum, observation.maximum):
                        if value is not None and not 1 <= value <= 20:
                            raise ValueError("visible attributes must be between 1 and 20")
        if self.membership_complete and (not clubs or self.game.controlled_club is None or self.game.controlled_club.id not in clubs):
            raise ValueError("complete league membership must include the managed club")

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> LeagueCapture:
        raw = _object(document, {"format", "formatVersion", "saveKey", "game", "season", "competition",
                                 "membershipComplete", "membershipEvidence", "sourceKind", "teams"}, "league capture")
        if raw.get("format") != FORMAT or type(raw.get("formatVersion")) is not int or raw["formatVersion"] != VERSION:
            raise ValueError("not a supported version 1 league capture")
        teams = raw.get("teams")
        if not isinstance(teams, list):
            raise ValueError("league teams must be an array")
        rosters = []
        player_fields = {"id", "name", "dateOfBirth", "age", "positions", "clubId", "conditionPercent",
                         "matchFitnessPercent", "availability", "injured", "suspended", "contract",
                         "attributes", "positionFamiliarity", "preferredFoot"}
        for entry in teams:
            row = _object(entry, {"squad", "rosterComplete", "positionsComplete", "evidence", "errors"}, "league roster")
            squad = _object(row.get("squad"), {"club", "asOfDate", "players", "otherTeams"}, "league squad")
            if not isinstance(squad.get("players"), list):
                raise ValueError("roster players must be an array")
            for player in squad["players"]:
                _object(player, player_fields, "league player")
                attributes = player.get("attributes")
                if not isinstance(attributes, Mapping):
                    raise ValueError("player attributes must be an object")
                for observation in attributes.values():
                    _object(observation, {"visibility", "value", "minimum", "maximum"}, "attribute")
            errors = row.get("errors", [])
            if not isinstance(errors, list) or not all(isinstance(error, str) for error in errors):
                raise ValueError("roster errors must be text entries")
            rosters.append(LeagueRoster(Squad.from_dict(squad, allow_unknown_positions=True), _boolean(row, "rosterComplete"),
                                       _boolean(row, "positionsComplete"), _text(row, "evidence"), tuple(errors)))
        return cls(_text(raw, "saveKey"), GameState.from_dict(raw["game"]), _text(raw, "season"),
                   Competition.from_document(raw["competition"], "league competition"),
                   _boolean(raw, "membershipComplete"), _text(raw, "membershipEvidence"),
                   _text(raw, "sourceKind"), tuple(rosters))

    def to_document(self) -> dict[str, Any]:
        return {"format": FORMAT, "formatVersion": VERSION, "saveKey": self.save_key,
                "game": self.game.to_dict(), "season": self.season, "competition": self.competition.to_document(),
                "membershipComplete": self.membership_complete, "membershipEvidence": self.membership_evidence,
                "sourceKind": self.source_kind, "teams": [team.to_document() for team in self.teams]}

    def content_hash(self) -> str:
        payload = json.dumps(self.to_document(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
