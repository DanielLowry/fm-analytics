from __future__ import annotations

import hashlib
import itertools
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from fm_analytics.contract import CONTRACT_VERSION
from fm_analytics.domain import GameState, Player, Squad
from fm_analytics.persistence.migrations import apply_migration
from fm_analytics.persistence.snapshot_schema import SCHEMA


class SnapshotStoreError(RuntimeError):
    """The capture database cannot be opened as it is: too new, too old, or not ours.

    Every message names the file and what to do about it, so a caller can
    print it plainly instead of a traceback.
    """


# A capture is a read of the live game, not history that fades the way scouted
# attributes do (see `persistence/player_knowledge.py`), so an unreadable file
# is survivable: re-run the capture. That is why the upgrade path below starts
# at this baseline rather than reconstructing v1-v3 -- there is no real v1-v3
# capture left to recover, and inventing that history to migrate a file nobody
# has would just be risk with no payoff. A file older than the baseline is
# refused with a clear instruction to re-capture, never silently upgraded.
BASELINE_VERSION = 4


# Append only, like the schema itself before it: version N (N >= BASELINE_VERSION)
# of the file is BASELINE_VERSION's schema plus MIGRATIONS[:N - BASELINE_VERSION].
# Never edit an entry that has shipped, add a new one.
MIGRATIONS: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaptureRecord:
    id: int
    created: bool
    fingerprint: str
    captured_at: datetime
    source: str
    contract_version: str


def _bring_up_to_date(
    connection: sqlite3.Connection, path: Path, migrations: Sequence[str]
) -> None:
    """Create the schema at the baseline, upgrade past it, or refuse the file.

    Unlike `persistence.migrations.bring_up_to_date`, version 0 does not start
    from nothing: it is built straight to `BASELINE_VERSION` in one step, and
    a file older than that baseline is refused rather than reconstructed --
    see the note above `BASELINE_VERSION`.
    """
    latest = BASELINE_VERSION + len(migrations)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > latest:
        raise SnapshotStoreError(
            f"{path} is squad-capture schema v{version}, newer than this "
            f"program understands (v{latest}). Update the program; do not delete the file."
        )
    if version == 0 and connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
    ).fetchone():
        raise SnapshotStoreError(f"{path} is a SQLite database but not a squad-capture database.")
    if version == latest:
        return
    if 0 < version < BASELINE_VERSION:
        raise SnapshotStoreError(
            f"{path} is squad-capture schema v{version}, older than this program's "
            f"baseline (v{BASELINE_VERSION}). There is no upgrade path from before the "
            "baseline -- re-run the capture against the live game with --snapshot-db "
            "to start a fresh file at this path."
        )
    if version > 0:
        # A whole-database copy through SQLite's own backup API, so it is
        # consistent even if another process has the file open.
        backup = path.with_name(f"{path.name}.bak-v{version}")
        with closing(sqlite3.connect(backup)) as target:
            connection.backup(target)
    if version == 0:
        apply_migration(connection, BASELINE_VERSION - 1, SCHEMA, error=SnapshotStoreError)
        version = BASELINE_VERSION
    for step in range(version, latest):
        apply_migration(
            connection, step, migrations[step - BASELINE_VERSION], error=SnapshotStoreError
        )


class SnapshotStore:
    """Persist and reconstruct the narrow, immutable MVP squad capture."""

    def __init__(self, path: str | Path, *, migrations: Sequence[str] = MIGRATIONS):
        self.path = Path(path)
        self._migrations = tuple(migrations)

    def initialize(self) -> None:
        """Create the file, upgrade an older one from the baseline, or refuse it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            _bring_up_to_date(connection, self.path, self._migrations)

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
            ordinal = 0
            for player in squad.players:
                self._insert_player(connection, capture_id, ordinal, player, team_marker=None)
                ordinal += 1
            for team in squad.other_teams:
                for player in team.players:
                    self._insert_player(
                        connection, capture_id, ordinal, player, team_marker=team.marker
                    )
                    ordinal += 1

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
            first_team = [player for player in players if player["team_marker"] is None]
            other_team_players = [player for player in players if player["team_marker"] is not None]
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
                    for player in first_team
                ],
                "otherTeams": [
                    {
                        "marker": marker,
                        "players": [
                            self._load_player(connection, capture_id, player)
                            for player in group
                        ],
                    }
                    # `other_team_players` is already ordinal-ordered, and
                    # ordinal insertion groups each team's players together
                    # (see `capture` above), so a plain groupby needs no
                    # re-sort to recover each team intact and in marker order.
                    for marker, group in itertools.groupby(
                        other_team_players, key=lambda player: player["team_marker"]
                    )
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
        player_ids = [player.id for player in squad.all_players()]
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
        *,
        team_marker: int | None = None,
    ) -> None:
        contract = player.contract
        contracted_club = contract.contracted_club if contract else None
        connection.execute(
            """
            INSERT INTO squad_players (
                capture_id, player_id, ordinal, team_marker, name, date_of_birth, age,
                club_id, condition_percent, match_fitness_percent, availability,
                injured, suspended, preferred_foot, contract_present, contract_type,
                contract_start_date, contract_end_date, contract_joined_date,
                squad_status, transfer_status, contracted_club_id,
                contracted_club_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture_id,
                player.id,
                ordinal,
                team_marker,
                player.name,
                player.date_of_birth.isoformat() if player.date_of_birth else None,
                player.age,
                player.club_id,
                player.condition_percent,
                player.match_fitness_percent,
                player.availability,
                player.injured,
                player.suspended,
                player.preferred_foot,
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
            INSERT INTO player_position_familiarity (
                capture_id, player_id, position, rating
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (capture_id, player.id, position, rating)
                for position, rating in player.position_familiarity.items()
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
        familiarity = connection.execute(
            """
            SELECT position, rating FROM player_position_familiarity
            WHERE capture_id = ? AND player_id = ? ORDER BY position
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
            "preferredFoot": row["preferred_foot"],
            "contract": contract,
            "positionFamiliarity": {
                item["position"]: item["rating"] for item in familiarity
            },
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
