from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fm_analytics.contract import CONTRACT_VERSION
from fm_analytics.domain import GameState, Player, Squad


SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE captures (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    contract_version TEXT NOT NULL,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    game_date TEXT NOT NULL,
    manager_id TEXT NOT NULL,
    manager_name TEXT NOT NULL,
    controlled_club_id TEXT,
    controlled_club_name TEXT,
    squad_club_id TEXT,
    squad_club_name TEXT,
    CHECK ((controlled_club_id IS NULL) = (controlled_club_name IS NULL)),
    CHECK ((squad_club_id IS NULL) = (squad_club_name IS NULL))
);

CREATE TABLE squad_players (
    capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    player_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    name TEXT NOT NULL,
    date_of_birth TEXT,
    age INTEGER CHECK (age IS NULL OR age >= 0),
    club_id TEXT NOT NULL,
    condition_percent INTEGER CHECK (
        condition_percent IS NULL OR condition_percent BETWEEN 0 AND 100
    ),
    match_fitness_percent INTEGER CHECK (
        match_fitness_percent IS NULL OR match_fitness_percent BETWEEN 0 AND 100
    ),
    availability TEXT NOT NULL,
    injured INTEGER CHECK (injured IS NULL OR injured IN (0, 1)),
    suspended INTEGER CHECK (suspended IS NULL OR suspended IN (0, 1)),
    contract_present INTEGER NOT NULL CHECK (contract_present IN (0, 1)),
    contract_type TEXT,
    contract_start_date TEXT,
    contract_end_date TEXT,
    contract_joined_date TEXT,
    squad_status TEXT,
    transfer_status TEXT,
    contracted_club_id TEXT,
    contracted_club_name TEXT,
    PRIMARY KEY (capture_id, player_id),
    UNIQUE (capture_id, ordinal),
    CHECK ((contracted_club_id IS NULL) = (contracted_club_name IS NULL))
);

CREATE TABLE player_positions (
    capture_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    position TEXT NOT NULL,
    PRIMARY KEY (capture_id, player_id, ordinal),
    FOREIGN KEY (capture_id, player_id)
        REFERENCES squad_players(capture_id, player_id) ON DELETE CASCADE
);

CREATE TABLE player_attributes (
    capture_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    name TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('known', 'range', 'unknown')),
    value INTEGER,
    minimum INTEGER,
    maximum INTEGER,
    PRIMARY KEY (capture_id, player_id, name),
    FOREIGN KEY (capture_id, player_id)
        REFERENCES squad_players(capture_id, player_id) ON DELETE CASCADE,
    CHECK (
        (visibility = 'known' AND value IS NOT NULL
            AND minimum IS NULL AND maximum IS NULL)
        OR
        (visibility = 'range' AND value IS NULL
            AND minimum IS NOT NULL AND maximum IS NOT NULL
            AND minimum <= maximum)
        OR
        (visibility = 'unknown' AND value IS NULL
            AND minimum IS NULL AND maximum IS NULL)
    )
);
"""


@dataclass(frozen=True)
class CaptureRecord:
    id: int
    created: bool
    fingerprint: str
    captured_at: datetime
    source: str
    contract_version: str


class SnapshotStore:
    """Persist and reconstruct the narrow, immutable MVP squad capture."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                connection.executescript(SCHEMA)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported snapshot schema version {version}; "
                    f"expected {SCHEMA_VERSION}"
                )

    def capture(
        self,
        game: GameState,
        squad: Squad,
        *,
        source: str,
        captured_at: datetime | None = None,
    ) -> CaptureRecord:
        self._validate_capture(game, squad, source)
        observed_at = captured_at or datetime.now(timezone.utc)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        observed_at = observed_at.astimezone(timezone.utc)
        fingerprint = self._fingerprint(game, squad, source)

        self.initialize()
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT id, captured_at FROM captures WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing is not None:
                return CaptureRecord(
                    id=existing[0],
                    created=False,
                    fingerprint=fingerprint,
                    captured_at=datetime.fromisoformat(existing[1]),
                    source=source,
                    contract_version=CONTRACT_VERSION,
                )

            cursor = connection.execute(
                """
                INSERT INTO captures (
                    fingerprint, contract_version, source, captured_at, game_date,
                    manager_id, manager_name, controlled_club_id,
                    controlled_club_name, squad_club_id, squad_club_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint,
                    CONTRACT_VERSION,
                    source,
                    observed_at.isoformat(),
                    game.game_date.isoformat(),
                    game.human_manager.id,
                    game.human_manager.name,
                    game.controlled_club.id if game.controlled_club else None,
                    game.controlled_club.name if game.controlled_club else None,
                    squad.club.id if squad.club else None,
                    squad.club.name if squad.club else None,
                ),
            )
            capture_id = int(cursor.lastrowid)
            for ordinal, player in enumerate(squad.players):
                self._insert_player(connection, capture_id, ordinal, player)

        return CaptureRecord(
            id=capture_id,
            created=True,
            fingerprint=fingerprint,
            captured_at=observed_at,
            source=source,
            contract_version=CONTRACT_VERSION,
        )

    def load(self, capture_id: int) -> tuple[GameState, Squad]:
        self.initialize()
        with closing(self._connect()) as connection:
            capture = connection.execute(
                "SELECT * FROM captures WHERE id = ?", (capture_id,)
            ).fetchone()
            if capture is None:
                raise KeyError(f"capture {capture_id} does not exist")
            players = connection.execute(
                """
                SELECT * FROM squad_players
                WHERE capture_id = ? ORDER BY ordinal
                """,
                (capture_id,),
            ).fetchall()
            game_raw = {
                "gameDate": capture["game_date"],
                "humanManager": {
                    "id": capture["manager_id"],
                    "name": capture["manager_name"],
                },
                "controlledClub": self._club(
                    capture["controlled_club_id"],
                    capture["controlled_club_name"],
                ),
            }
            squad_raw = {
                "club": self._club(
                    capture["squad_club_id"], capture["squad_club_name"]
                ),
                "asOfDate": capture["game_date"],
                "players": [
                    self._load_player(connection, capture_id, player)
                    for player in players
                ],
            }
        return GameState.from_dict(game_raw), Squad.from_dict(squad_raw)

    def latest_capture_id(self) -> int | None:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id FROM captures ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return int(row[0]) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _validate_capture(game: GameState, squad: Squad, source: str) -> None:
        if not source:
            raise ValueError("source must not be empty")
        if game.game_date != squad.as_of_date:
            raise ValueError("game and squad observations must have the same date")
        if game.controlled_club and squad.club:
            if game.controlled_club.id != squad.club.id:
                raise ValueError("game and squad observations must have the same club")
        player_ids = [player.id for player in squad.players]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("squad observations must contain unique player IDs")

    @staticmethod
    def _fingerprint(game: GameState, squad: Squad, source: str) -> str:
        document = {
            "contractVersion": CONTRACT_VERSION,
            "source": source,
            "game": game.to_dict(),
            "squad": squad.to_dict(),
        }
        encoded = json.dumps(
            document, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _insert_player(
        connection: sqlite3.Connection,
        capture_id: int,
        ordinal: int,
        player: Player,
    ) -> None:
        contract = player.contract
        contracted_club = contract.contracted_club if contract else None
        connection.execute(
            """
            INSERT INTO squad_players (
                capture_id, player_id, ordinal, name, date_of_birth, age,
                club_id, condition_percent, match_fitness_percent, availability,
                injured, suspended, contract_present, contract_type,
                contract_start_date, contract_end_date, contract_joined_date,
                squad_status, transfer_status, contracted_club_id,
                contracted_club_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture_id,
                player.id,
                ordinal,
                player.name,
                player.date_of_birth.isoformat() if player.date_of_birth else None,
                player.age,
                player.club_id,
                player.condition_percent,
                player.match_fitness_percent,
                player.availability,
                player.injured,
                player.suspended,
                int(contract is not None),
                contract.contract_type if contract else None,
                _date_text(contract.start_date) if contract else None,
                _date_text(contract.end_date) if contract else None,
                _date_text(contract.joined_date) if contract else None,
                contract.squad_status if contract else None,
                contract.transfer_status if contract else None,
                contracted_club.id if contracted_club else None,
                contracted_club.name if contracted_club else None,
            ),
        )
        connection.executemany(
            """
            INSERT INTO player_positions (capture_id, player_id, ordinal, position)
            VALUES (?, ?, ?, ?)
            """,
            (
                (capture_id, player.id, position_ordinal, position)
                for position_ordinal, position in enumerate(player.positions)
            ),
        )
        connection.executemany(
            """
            INSERT INTO player_attributes (
                capture_id, player_id, name, visibility, value, minimum, maximum
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    capture_id,
                    player.id,
                    name,
                    observation.visibility.value,
                    observation.value,
                    observation.minimum,
                    observation.maximum,
                )
                for name, observation in player.attributes.items()
            ),
        )

    @staticmethod
    def _load_player(
        connection: sqlite3.Connection,
        capture_id: int,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        positions = connection.execute(
            """
            SELECT position FROM player_positions
            WHERE capture_id = ? AND player_id = ? ORDER BY ordinal
            """,
            (capture_id, row["player_id"]),
        ).fetchall()
        attributes = connection.execute(
            """
            SELECT * FROM player_attributes
            WHERE capture_id = ? AND player_id = ? ORDER BY name
            """,
            (capture_id, row["player_id"]),
        ).fetchall()
        contract = None
        if row["contract_present"]:
            contract = {
                "contractType": row["contract_type"],
                "startDate": row["contract_start_date"],
                "endDate": row["contract_end_date"],
                "joinedDate": row["contract_joined_date"],
                "squadStatus": row["squad_status"],
                "transferStatus": row["transfer_status"],
                "contractedClub": SnapshotStore._club(
                    row["contracted_club_id"], row["contracted_club_name"]
                ),
            }
        return {
            "id": row["player_id"],
            "name": row["name"],
            "dateOfBirth": row["date_of_birth"],
            "age": row["age"],
            "positions": [position[0] for position in positions],
            "clubId": row["club_id"],
            "conditionPercent": row["condition_percent"],
            "matchFitnessPercent": row["match_fitness_percent"],
            "availability": row["availability"],
            "injured": _optional_bool(row["injured"]),
            "suspended": _optional_bool(row["suspended"]),
            "contract": contract,
            "attributes": {
                attribute["name"]: _attribute(attribute) for attribute in attributes
            },
        }

    @staticmethod
    def _club(identifier: str | None, name: str | None) -> dict[str, str] | None:
        if identifier is None:
            return None
        return {"id": identifier, "name": name or ""}


def _date_text(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_bool(value: int | None) -> bool | None:
    return bool(value) if value is not None else None


def _attribute(row: sqlite3.Row) -> dict[str, Any]:
    visibility = row["visibility"]
    if visibility == "known":
        return {"visibility": visibility, "value": row["value"]}
    if visibility == "range":
        return {
            "visibility": visibility,
            "minimum": row["minimum"],
            "maximum": row["maximum"],
        }
    return {"visibility": visibility}
