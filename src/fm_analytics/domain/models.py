from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Mapping


class Visibility(StrEnum):
    KNOWN = "known"
    RANGE = "range"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AttributeObservation:
    visibility: Visibility
    value: int | None = None
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        self._validate()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AttributeObservation:
        raw = _mapping(raw, "attribute observation")
        visibility = Visibility(_required_string(raw, "visibility"))
        if visibility is Visibility.KNOWN:
            if "minimum" in raw or "maximum" in raw:
                raise ValueError("known attributes forbid minimum and maximum")
            value = _required_int(raw, "value")
            return cls(visibility=visibility, value=value)
        if visibility is Visibility.RANGE:
            if "value" in raw:
                raise ValueError("range attributes forbid value")
            return cls(
                visibility=visibility,
                minimum=_required_int(raw, "minimum"),
                maximum=_required_int(raw, "maximum"),
            )
        if any(name in raw for name in ("value", "minimum", "maximum")):
            raise ValueError("unknown attributes forbid numeric fields")
        return cls(
            visibility=visibility,
        )

    def _validate(self) -> None:
        for name, value in (
            ("value", self.value),
            ("minimum", self.minimum),
            ("maximum", self.maximum),
        ):
            if value is not None and not _is_int(value):
                raise TypeError(f"attribute {name} must be an integer")
        if self.visibility is Visibility.KNOWN:
            if self.value is None or self.minimum is not None or self.maximum is not None:
                raise ValueError("known attributes require only an exact value")
        elif self.visibility is Visibility.RANGE:
            if self.value is not None or self.minimum is None or self.maximum is None:
                raise ValueError("range attributes require only minimum and maximum")
            if self.minimum > self.maximum:
                raise ValueError("attribute minimum cannot exceed maximum")
        elif any(item is not None for item in (self.value, self.minimum, self.maximum)):
            raise ValueError("unknown attributes cannot contain values")

    def display(self) -> str:
        if self.visibility is Visibility.KNOWN:
            return str(self.value)
        if self.visibility is Visibility.RANGE:
            return f"{self.minimum}-{self.maximum}"
        return "?"

    def to_dict(self) -> dict[str, Any]:
        if self.visibility is Visibility.KNOWN:
            return {"visibility": self.visibility.value, "value": self.value}
        if self.visibility is Visibility.RANGE:
            return {
                "visibility": self.visibility.value,
                "minimum": self.minimum,
                "maximum": self.maximum,
            }
        return {"visibility": self.visibility.value}


@dataclass(frozen=True)
class Club:
    id: str
    name: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Club:
        raw = _mapping(raw, "club")
        return cls(
            id=_required_string(raw, "id"),
            name=_required_string(raw, "name"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


@dataclass(frozen=True)
class Manager:
    id: str
    name: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Manager:
        raw = _mapping(raw, "manager")
        return cls(
            id=_required_string(raw, "id"),
            name=_required_string(raw, "name"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


@dataclass(frozen=True)
class SourceHealth:
    status: str
    source: str
    detail: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SourceHealth:
        raw = _mapping(raw, "health")
        return cls(
            status=_required_string(raw, "status"),
            source=_required_string(raw, "source"),
            detail=_nullable_string(raw, "detail"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GameState:
    game_date: date
    human_manager: Manager
    controlled_club: Club | None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> GameState:
        raw = _mapping(raw, "game")
        manager = _mapping(_required(raw, "humanManager"), "humanManager")
        controlled_club = _nullable_mapping(raw, "controlledClub")
        return cls(
            game_date=_required_date(raw, "gameDate"),
            human_manager=Manager.from_dict(manager),
            controlled_club=(
                Club.from_dict(controlled_club) if controlled_club is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gameDate": self.game_date.isoformat(),
            "humanManager": self.human_manager.to_dict(),
            "controlledClub": (
                self.controlled_club.to_dict() if self.controlled_club else None
            ),
        }


@dataclass(frozen=True)
class PlayerContract:
    contract_type: str | None
    start_date: date | None
    end_date: date | None
    joined_date: date | None
    squad_status: str | None
    transfer_status: str | None
    contracted_club: Club | None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PlayerContract:
        raw = _mapping(raw, "contract")
        contracted_club = _nullable_mapping(raw, "contractedClub")
        return cls(
            contract_type=_nullable_string(raw, "contractType"),
            start_date=_nullable_date(raw, "startDate"),
            end_date=_nullable_date(raw, "endDate"),
            joined_date=_nullable_date(raw, "joinedDate"),
            squad_status=_nullable_string(raw, "squadStatus"),
            transfer_status=_nullable_string(raw, "transferStatus"),
            contracted_club=(
                Club.from_dict(contracted_club) if contracted_club is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractType": self.contract_type,
            "startDate": _date_text(self.start_date),
            "endDate": _date_text(self.end_date),
            "joinedDate": _date_text(self.joined_date),
            "squadStatus": self.squad_status,
            "transferStatus": self.transfer_status,
            "contractedClub": (
                self.contracted_club.to_dict() if self.contracted_club else None
            ),
        }


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    date_of_birth: date | None
    age: int | None
    positions: tuple[str, ...]
    club_id: str
    condition_percent: int | None
    match_fitness_percent: int | None
    availability: str
    injured: bool | None
    suspended: bool | None
    contract: PlayerContract | None
    attributes: Mapping[str, AttributeObservation]
    # Additive per the v1 contract's field-versioning rule, so it defaults to
    # empty rather than requiring every existing construction site to supply
    # it. Empty means "no reading available", not "unfamiliar with every
    # position" -- callers must not treat a missing entry as a low rating.
    position_familiarity: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for position, rating in self.position_familiarity.items():
            if not isinstance(position, str) or not position:
                raise ValueError("positionFamiliarity keys must be non-empty strings")
            if not _is_int(rating) or not 1 <= rating <= 20:
                raise ValueError("positionFamiliarity ratings must be integers from 1 to 20")
        for name, value in (
            ("conditionPercent", self.condition_percent),
            ("matchFitnessPercent", self.match_fitness_percent),
        ):
            if value is not None:
                if not _is_int(value):
                    raise TypeError(f"{name} must be an integer")
                if not 0 <= value <= 100:
                    raise ValueError(f"{name} must be between 0 and 100")
        if self.age is not None:
            if not _is_int(self.age):
                raise TypeError("age must be an integer")
            if self.age < 0:
                raise ValueError("age cannot be negative")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Player:
        raw = _mapping(raw, "player")
        contract = _nullable_mapping(raw, "contract")
        attributes = _mapping(_required(raw, "attributes"), "attributes")
        return cls(
            id=_required_string(raw, "id"),
            name=_required_string(raw, "name"),
            date_of_birth=_nullable_date(raw, "dateOfBirth"),
            age=_nullable_int(raw, "age"),
            positions=_required_string_array(raw, "positions"),
            club_id=_required_string(raw, "clubId"),
            condition_percent=_nullable_int(raw, "conditionPercent"),
            match_fitness_percent=_nullable_int(raw, "matchFitnessPercent"),
            availability=_required_string(raw, "availability"),
            injured=_nullable_bool(raw, "injured"),
            suspended=_nullable_bool(raw, "suspended"),
            contract=(
                PlayerContract.from_dict(contract) if contract is not None else None
            ),
            attributes={
                _string(name, "attribute name"): AttributeObservation.from_dict(
                    _mapping(value, f"attribute {name!r}")
                )
                for name, value in attributes.items()
            },
            position_familiarity=_nullable_position_familiarity(raw, "positionFamiliarity"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "dateOfBirth": _date_text(self.date_of_birth),
            "age": self.age,
            "positions": list(self.positions),
            "clubId": self.club_id,
            "conditionPercent": self.condition_percent,
            "matchFitnessPercent": self.match_fitness_percent,
            "availability": self.availability,
            "injured": self.injured,
            "suspended": self.suspended,
            "contract": self.contract.to_dict() if self.contract else None,
            "positionFamiliarity": dict(self.position_familiarity),
            "attributes": {
                name: observation.to_dict()
                for name, observation in self.attributes.items()
            },
        }


@dataclass(frozen=True)
class SquadTeam:
    """One non-first-team squad at the managed club: youth, reserves, and so on.

    `marker` is FM's own raw team-type value for this squad (never 0, which
    identifies the first team and lives in `Squad.players` instead, never
    here, so a player is never counted twice). FM's human-readable name for
    each marker has not been decoded yet -- see
    docs/property-discovery-playbook.md -- so only the raw marker is exposed;
    inventing a label such as "Under 18s" here would misrepresent FM's data.
    """

    marker: int
    players: tuple[Player, ...]

    def __post_init__(self) -> None:
        if not _is_int(self.marker) or self.marker == 0:
            raise ValueError("a squad team marker must be a non-zero integer")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SquadTeam:
        raw = _mapping(raw, "squad team")
        players = _required_list(raw, "players")
        return cls(
            marker=_required_int(raw, "marker"),
            players=tuple(
                Player.from_dict(_mapping(player, "players item")) for player in players
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "marker": self.marker,
            "players": [player.to_dict() for player in self.players],
        }


@dataclass(frozen=True)
class Squad:
    club: Club | None
    as_of_date: date
    players: tuple[Player, ...]
    # Additive per the v1 contract's field-versioning rule, so it defaults to
    # empty rather than requiring every existing construction site to supply
    # it. `players` keeps meaning "the first team" exactly as before; this is
    # every other squad at the club. Use `all_players()` for everyone at once.
    other_teams: tuple[SquadTeam, ...] = field(default_factory=tuple)

    def all_players(self) -> tuple[Player, ...]:
        """The whole club: the first team plus every other team's players.

        `players` alone remains "filtered back to the first team"; this adds
        youth, reserve, and any other squad FM reports for the same club.
        """
        return self.players + tuple(
            player for team in self.other_teams for player in team.players
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Squad:
        raw = _mapping(raw, "squad")
        club = _nullable_mapping(raw, "club")
        players = _required_list(raw, "players")
        other_teams = raw.get("otherTeams", [])
        if not isinstance(other_teams, list):
            raise TypeError("otherTeams must be an array")
        return cls(
            club=Club.from_dict(club) if club is not None else None,
            as_of_date=_required_date(raw, "asOfDate"),
            players=tuple(
                Player.from_dict(_mapping(player, "players item")) for player in players
            ),
            other_teams=tuple(
                SquadTeam.from_dict(_mapping(team, "otherTeams item")) for team in other_teams
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "club": self.club.to_dict() if self.club else None,
            "asOfDate": self.as_of_date.isoformat(),
            "players": [player.to_dict() for player in self.players],
            "otherTeams": [team.to_dict() for team in self.other_teams],
        }


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _required(raw: Mapping[str, Any], name: str) -> Any:
    if name not in raw:
        raise KeyError(name)
    return raw[name]


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _required_string(raw: Mapping[str, Any], name: str) -> str:
    return _string(_required(raw, name), name)


def _nullable_string(raw: Mapping[str, Any], name: str) -> str | None:
    value = _required(raw, name)
    return None if value is None else _string(value, name)


def _required_int(raw: Mapping[str, Any], name: str) -> int:
    value = _required(raw, name)
    if not _is_int(value):
        raise TypeError(f"{name} must be an integer")
    return value


def _nullable_int(raw: Mapping[str, Any], name: str) -> int | None:
    value = _required(raw, name)
    if value is None:
        return None
    if not _is_int(value):
        raise TypeError(f"{name} must be an integer or null")
    return value


def _nullable_bool(raw: Mapping[str, Any], name: str) -> bool | None:
    value = _required(raw, name)
    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean or null")
    return value


def _nullable_position_familiarity(
    raw: Mapping[str, Any], name: str
) -> dict[str, int]:
    """Decode the optional raw position-rating map.

    Absent or null means no reading is available for this player, not that
    every position is unfamiliar; it decodes to an empty mapping rather than
    a mapping of zeros so callers cannot mistake "no data" for "known bad".
    """
    if name not in raw or raw[name] is None:
        return {}
    value = _mapping(raw[name], name)
    result: dict[str, int] = {}
    for position, rating in value.items():
        if not isinstance(position, str) or not position:
            raise TypeError(f"{name} keys must be non-empty strings")
        if not _is_int(rating) or not 1 <= rating <= 20:
            raise ValueError(f"{name} values must be integers from 1 to 20")
        result[position] = rating
    return result


def _required_date(raw: Mapping[str, Any], name: str) -> date:
    value = _required_string(raw, name)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 date") from exc


def _nullable_date(raw: Mapping[str, Any], name: str) -> date | None:
    value = _required(raw, name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO 8601 date or null")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 date or null") from exc


def _nullable_mapping(
    raw: Mapping[str, Any], name: str
) -> Mapping[str, Any] | None:
    value = _required(raw, name)
    return None if value is None else _mapping(value, name)


def _required_list(raw: Mapping[str, Any], name: str) -> list[Any]:
    value = _required(raw, name)
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return value


def _required_string_array(raw: Mapping[str, Any], name: str) -> tuple[str, ...]:
    values = _required_list(raw, name)
    if not values:
        raise ValueError(f"{name} must not be empty")
    return tuple(_string(value, f"{name} item") for value in values)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
