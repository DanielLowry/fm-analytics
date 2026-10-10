"""The matches the manager chose to store for experiments, their labels and their groups.

Nothing is stored here unless the manager asks: reading matches from FM never
adds to it, and it is a database of its own (`data/experiments.sqlite3` by
default), apart from the match history. A replay of a fixture is not a match
the season had, and recording one in the history would make it that match's
current version. Follows the same rules as the other stores (see
`persistence.migrations`): a label, a note, a withdrawal or a match joining
or leaving a group is a later row; the latest wins. The exceptions are the
manager's own housekeeping, done only when asked: deleting a stored match or
a group removes its rows, and renaming a group changes its row.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from fm_analytics.domain.experiments import (
    MAX_NOTE_LENGTH,
    MatchGroup,
    MatchLabel,
    Stored,
    StoredMatch,
    validate_label,
    validate_name,
)
from fm_analytics.domain.matches import MatchRecord, TeamRef
from fm_analytics.domain.mentality import MentalityPlan
from fm_analytics.persistence.migrations import bring_up_to_date


class ExperimentStoreError(RuntimeError):
    """The database cannot be used as it is (wrong or newer version, not ours)."""


_V1 = """
-- One match exactly as FM recorded it, stored because the manager asked.
CREATE TABLE stored_matches (
    id INTEGER PRIMARY KEY,
    stored_at TEXT NOT NULL,
    club_id TEXT NOT NULL,
    club_name TEXT NOT NULL,
    match_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    document TEXT NOT NULL,
    UNIQUE (club_id, content_hash)
);

-- How the manager labels a stored match (the variant it tried, the
-- catalogue tactic, notes, tags) and whether it is withdrawn. Append only;
-- the latest per match wins.
CREATE TABLE match_labels (
    id INTEGER PRIMARY KEY,
    stored_match_id INTEGER NOT NULL REFERENCES stored_matches(id),
    recorded_at TEXT NOT NULL,
    variant TEXT NOT NULL,
    tactic_key TEXT,
    note TEXT NOT NULL,
    tags TEXT NOT NULL,
    withdrawn INTEGER NOT NULL CHECK (withdrawn IN (0, 1))
);
CREATE INDEX match_labels_by_match ON match_labels (stored_match_id, id);

-- The manager's own groups of stored matches.
CREATE TABLE match_groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- A match joining (1) or leaving (0) a group. Append only; the latest wins.
CREATE TABLE group_memberships (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES match_groups(id),
    stored_match_id INTEGER NOT NULL REFERENCES stored_matches(id),
    recorded_at TEXT NOT NULL,
    member INTEGER NOT NULL CHECK (member IN (0, 1))
);
CREATE INDEX group_memberships_by_group ON group_memberships (group_id, stored_match_id, id);
"""

_V2 = """
-- The mentality the match was played in, as the manager records it: JSON
-- [{"from": minute, "mentality": name}, ...], the first from kickoff; NULL
-- when not recorded. Part of the label, so a later label row carries it on.
ALTER TABLE match_labels ADD COLUMN mentality TEXT;
"""

# Append only. Version N of the file is the result of applying MIGRATIONS[:N].
MIGRATIONS: tuple[str, ...] = (_V1, _V2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(match: MatchRecord) -> str:
    return hashlib.sha256(json.dumps(match.to_document(), sort_keys=True).encode("utf-8")).hexdigest()


class ExperimentStore:
    def __init__(self, path: str | Path, *, migrations: Sequence[str] = MIGRATIONS):
        self.path = Path(path)
        self._migrations = tuple(migrations)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            bring_up_to_date(connection, self.path, self._migrations, kind="experiments", error=ExperimentStoreError)

    # -- writing -----------------------------------------------------------

    def store(
        self, match: MatchRecord, club: TeamRef, label: MatchLabel, *, groups: Iterable[str] = ()
    ) -> Stored:
        """Keep one match with full stats, labelled, and put it in `groups` (each must exist).

        Storing the same match again adds nothing; it still joins `groups`.
        """
        label = validate_label(label)
        match.side_of(club.id)  # refuses a match the club did not play
        if match.detail is None:
            raise ValueError("FM's stats for this match could not be read, so it cannot be compared")
        content_hash = _hash(match)
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            group_ids = [self._group_id(connection, name) for name in groups]
            existing = connection.execute(
                "SELECT id FROM stored_matches WHERE club_id = ? AND content_hash = ?", (club.id, content_hash)
            ).fetchone()
            if existing:
                match_id, added = existing["id"], False
            else:
                match_id = connection.execute(
                    "INSERT INTO stored_matches (stored_at, club_id, club_name, match_key, content_hash, document) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (_now(), club.id, club.name, match.key, content_hash, json.dumps(match.to_document(), sort_keys=True)),
                ).lastrowid
                self._label(connection, match_id, label, withdrawn=False)
                added = True
            for group_id in group_ids:
                self._membership(connection, group_id, match_id, member=True)
        return Stored(match_id, added)

    def relabel(self, match_id: int, label: MatchLabel, *, withdrawn: bool = False) -> None:
        """A stored match's new label, notes or tags, or its withdrawal from every comparison."""
        label = validate_label(label)
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            self._existing(connection, match_id)
            self._label(connection, match_id, label, withdrawn=withdrawn)

    def set_mentality(self, match_ids: Iterable[int], mentality: MentalityPlan | None) -> None:
        """Record the mentality stored matches were played in (None clears it), each keeping the rest of its label."""
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            for match_id in match_ids:
                self._existing(connection, match_id)
                current = self._latest_label(connection, match_id)
                self._label(
                    connection, match_id, replace(self._label_of(current), mentality=mentality),
                    withdrawn=bool(current["withdrawn"]),
                )

    def create_group(self, name: str, note: str = "") -> None:
        name = validate_name(name, "a group")
        if len(note.strip()) > MAX_NOTE_LENGTH:
            raise ValueError(f"a group's note is limited to {MAX_NOTE_LENGTH} characters")
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            if connection.execute("SELECT 1 FROM match_groups WHERE name = ?", (name,)).fetchone():
                raise ValueError(f"there is already a group called {name!r}")
            connection.execute(
                "INSERT INTO match_groups (name, note, created_at) VALUES (?, ?, ?)", (name, note.strip(), _now())
            )

    def set_membership(self, group: str, match_ids: Iterable[int], *, member: bool) -> None:
        """Put stored matches into a group, or take them out."""
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            group_id = self._group_id(connection, group)
            for match_id in match_ids:
                self._existing(connection, match_id)
                self._membership(connection, group_id, match_id, member=member)

    def delete(self, match_ids: Iterable[int]) -> None:
        """Remove stored matches for good: each record, every label it had and its place in every group.

        Withdrawing keeps a match out of comparisons and can be undone; this
        cannot. The number of the latest match stored can be given to the
        next one.
        """
        match_ids = list(match_ids)
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            for match_id in match_ids:
                self._existing(connection, match_id)
                for table in ("group_memberships", "match_labels"):
                    connection.execute(f"DELETE FROM {table} WHERE stored_match_id = ?", (match_id,))
                connection.execute("DELETE FROM stored_matches WHERE id = ?", (match_id,))

    def edit_group(self, name: str, new_name: str, note: str) -> None:
        """Rename a group and set its note; its matches stay in it."""
        new_name = validate_name(new_name, "a group")
        if len(note.strip()) > MAX_NOTE_LENGTH:
            raise ValueError(f"a group's note is limited to {MAX_NOTE_LENGTH} characters")
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            group_id = self._group_id(connection, name)
            taken = connection.execute("SELECT id FROM match_groups WHERE name = ?", (new_name,)).fetchone()
            if taken and taken["id"] != group_id:
                raise ValueError(f"there is already a group called {new_name!r}")
            connection.execute("UPDATE match_groups SET name = ?, note = ? WHERE id = ?", (new_name, note.strip(), group_id))

    def delete_group(self, name: str) -> None:
        """Remove a group. Its matches stay stored, and in any other group they are in."""
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            group_id = self._group_id(connection, name)
            connection.execute("DELETE FROM group_memberships WHERE group_id = ?", (group_id,))
            connection.execute("DELETE FROM match_groups WHERE id = ?", (group_id,))

    # -- reading -----------------------------------------------------------

    def matches(self) -> tuple[StoredMatch, ...]:
        """Every stored match, oldest first, withdrawn ones included."""
        if not self.path.exists():
            return ()
        self.initialize()
        with closing(self._connect()) as connection:
            memberships = self._memberships(connection)
            return tuple(
                self._stored(connection, row, memberships.get(row["id"], ()))
                for row in connection.execute("SELECT * FROM stored_matches ORDER BY id").fetchall()
            )

    def groups(self) -> tuple[MatchGroup, ...]:
        """Every group with its current matches, newest group first."""
        if not self.path.exists():
            return ()
        everything = {match.id: match for match in self.matches()}
        with closing(self._connect()) as connection:
            members = self._members(connection)
            return tuple(
                MatchGroup(row["name"], row["note"], row["created_at"],
                           tuple(everything[match_id] for match_id in members.get(row["id"], ()) if match_id in everything))
                for row in connection.execute("SELECT * FROM match_groups ORDER BY id DESC").fetchall()
            )

    def group(self, name: str) -> MatchGroup | None:
        return next((group for group in self.groups() if group.name == name), None)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _members(connection: sqlite3.Connection) -> dict[int, list[int]]:
        """Group ID -> its current matches' IDs, in the order they were stored."""
        latest: dict[tuple[int, int], int] = {}
        for row in connection.execute("SELECT group_id, stored_match_id, member FROM group_memberships ORDER BY id"):
            latest[(row["group_id"], row["stored_match_id"])] = row["member"]
        members: dict[int, list[int]] = {}
        for (group_id, match_id), member in sorted(latest.items(), key=lambda item: item[0][1]):
            if member:
                members.setdefault(group_id, []).append(match_id)
        return members

    def _memberships(self, connection: sqlite3.Connection) -> dict[int, tuple[str, ...]]:
        """Stored match ID -> the names of the groups it is in now."""
        names = {row["id"]: row["name"] for row in connection.execute("SELECT id, name FROM match_groups")}
        found: dict[int, list[str]] = {}
        for group_id, match_ids in self._members(connection).items():
            for match_id in match_ids:
                found.setdefault(match_id, []).append(names[group_id])
        return {match_id: tuple(sorted(groups)) for match_id, groups in found.items()}

    @staticmethod
    def _latest_label(connection: sqlite3.Connection, match_id: int) -> sqlite3.Row:
        return connection.execute(
            "SELECT * FROM match_labels WHERE stored_match_id = ? ORDER BY id DESC LIMIT 1", (match_id,)
        ).fetchone()

    @staticmethod
    def _label_of(row: sqlite3.Row) -> MatchLabel:
        return MatchLabel(
            row["variant"], row["tactic_key"], row["note"], json.loads(row["tags"]),
            MentalityPlan.from_document(json.loads(row["mentality"])) if row["mentality"] else None,
        )

    @classmethod
    def _stored(cls, connection: sqlite3.Connection, row: sqlite3.Row, groups: tuple[str, ...]) -> StoredMatch:
        label = cls._latest_label(connection, row["id"])
        return StoredMatch(
            id=row["id"],
            stored_at=row["stored_at"],
            club=TeamRef(row["club_id"], row["club_name"]),
            match=MatchRecord.from_document(json.loads(row["document"])),
            label=cls._label_of(label),
            withdrawn=bool(label["withdrawn"]),
            groups=groups,
        )

    @staticmethod
    def _group_id(connection: sqlite3.Connection, name: str) -> int:
        row = connection.execute("SELECT id FROM match_groups WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise ValueError(f"no group is called {name!r}")
        return row["id"]

    @staticmethod
    def _existing(connection: sqlite3.Connection, match_id: int) -> None:
        if not connection.execute("SELECT 1 FROM stored_matches WHERE id = ?", (match_id,)).fetchone():
            raise ValueError(f"no stored match {match_id}")

    @staticmethod
    def _label(connection: sqlite3.Connection, match_id: int, label: MatchLabel, *, withdrawn: bool) -> None:
        connection.execute(
            "INSERT INTO match_labels (stored_match_id, recorded_at, variant, tactic_key, note, tags, withdrawn, mentality) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (match_id, _now(), label.variant, label.tactic_key, label.note,
             json.dumps(dict(label.tags), sort_keys=True), int(withdrawn),
             json.dumps(label.mentality.to_document()) if label.mentality else None),
        )

    @staticmethod
    def _membership(connection: sqlite3.Connection, group_id: int, match_id: int, *, member: bool) -> None:
        connection.execute(
            "INSERT INTO group_memberships (group_id, stored_match_id, recorded_at, member) VALUES (?, ?, ?, ?)",
            (group_id, match_id, _now(), int(member)),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")
