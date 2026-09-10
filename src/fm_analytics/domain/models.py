from __future__ import annotations

from dataclasses import dataclass
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
        return cls(
            visibility=Visibility(raw["visibility"]),
            value=raw.get("value"),
            minimum=raw.get("minimum"),
            maximum=raw.get("maximum"),
        )

    def _validate(self) -> None:
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


@dataclass(frozen=True)
class Club:
    id: str
    name: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Club:
        return cls(id=str(raw["id"]), name=str(raw["name"]))


@dataclass(frozen=True)
class Manager:
    id: str
    name: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Manager:
        return cls(id=str(raw["id"]), name=str(raw["name"]))


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
        return cls(
            status=str(raw["status"]),
            source=str(raw["source"]),
            detail=str(raw["detail"]) if raw.get("detail") is not None else None,
        )


@dataclass(frozen=True)
class GameState:
    game_date: date
    human_manager: Manager
    controlled_club: Club | None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> GameState:
        return cls(
            game_date=date.fromisoformat(raw["gameDate"]),
            human_manager=Manager.from_dict(raw["humanManager"]),
            controlled_club=(
                Club.from_dict(raw["controlledClub"])
                if raw.get("controlledClub") is not None
                else None
            ),
        )


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
        return cls(
            contract_type=raw.get("contractType"),
            start_date=_optional_date(raw.get("startDate")),
            end_date=_optional_date(raw.get("endDate")),
            joined_date=_optional_date(raw.get("joinedDate")),
            squad_status=raw.get("squadStatus"),
            transfer_status=raw.get("transferStatus"),
            contracted_club=(
                Club.from_dict(raw["contractedClub"])
                if raw.get("contractedClub") is not None
                else None
            ),
        )


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

    def __post_init__(self) -> None:
        for name, value in (
            ("conditionPercent", self.condition_percent),
            ("matchFitnessPercent", self.match_fitness_percent),
        ):
            if value is not None and not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.age is not None and self.age < 0:
            raise ValueError("age cannot be negative")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Player:
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            date_of_birth=_optional_date(raw.get("dateOfBirth")),
            age=int(raw["age"]) if raw.get("age") is not None else None,
            positions=tuple(raw["positions"]),
            club_id=str(raw["clubId"]),
            condition_percent=_optional_int(raw.get("conditionPercent")),
            match_fitness_percent=_optional_int(raw.get("matchFitnessPercent")),
            availability=str(raw.get("availability", "unknown")),
            injured=raw.get("injured"),
            suspended=raw.get("suspended"),
            contract=(
                PlayerContract.from_dict(raw["contract"])
                if raw.get("contract") is not None
                else None
            ),
            attributes={
                name: AttributeObservation.from_dict(value)
                for name, value in raw.get("attributes", {}).items()
            },
        )


@dataclass(frozen=True)
class Squad:
    club: Club | None
    as_of_date: date
    players: tuple[Player, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Squad:
        return cls(
            club=Club.from_dict(raw["club"]) if raw.get("club") is not None else None,
            as_of_date=date.fromisoformat(raw["asOfDate"]),
            players=tuple(Player.from_dict(player) for player in raw["players"]),
        )


def _optional_date(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value is not None else None


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None
