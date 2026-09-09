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
class GameState:
    game_date: date
    human_manager: Manager
    controlled_club: Club

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> GameState:
        return cls(
            game_date=date.fromisoformat(raw["gameDate"]),
            human_manager=Manager.from_dict(raw["humanManager"]),
            controlled_club=Club.from_dict(raw["controlledClub"]),
        )


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    age: int
    positions: tuple[str, ...]
    club_id: str
    attributes: Mapping[str, AttributeObservation]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Player:
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            age=int(raw["age"]),
            positions=tuple(raw["positions"]),
            club_id=str(raw["clubId"]),
            attributes={
                name: AttributeObservation.from_dict(value)
                for name, value in raw.get("attributes", {}).items()
            },
        )


@dataclass(frozen=True)
class Squad:
    club: Club
    as_of_date: date
    players: tuple[Player, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Squad:
        return cls(
            club=Club.from_dict(raw["club"]),
            as_of_date=date.fromisoformat(raw["asOfDate"]),
            players=tuple(Player.from_dict(player) for player in raw["players"]),
        )
