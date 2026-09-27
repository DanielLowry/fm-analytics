"""The manager's own notebook of what they have seen about other players.

FM only shows attributes for players who are currently scouted, and the
knowledge fades: a player drops out of the scout reports and the numbers go
with him. This store keeps every manager-visible observation, with the in-game
date it was seen, so a player rejected today can be reconsidered in six months
and one scouted as an opponent is not forgotten.

It records only what the capture feed already exposes to the manager (exact,
ranged or unknown attributes and the visible profile facts). An old observation
is history, never a current fact: consumers must label it with its date.

Reading it back is equally dated: `best_known_profile` and
`best_known_profiles` assemble a player as of one in-game date, with the last
day each reading was still seen (see `persistence.best_known`).

Two rules this module exists to keep:

* **Nothing is ever deleted or overwritten.** Observations are appended, and only
  when they differ from the latest one at or before that date, so recording the
  same capture twice adds nothing.
* **It must stay readable.** The game will not show these values again, so the
  file has an ordered migration list from its first version, a backup before any
  migration, and refuses to open a file it does not understand. (The squad
  capture store has no upgrade path; that is survivable because the squad can be
  re-read from the game, and this is not.)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Mapping, Sequence

from fm_analytics.domain import AttributeObservation, Visibility

if TYPE_CHECKING:
    from fm_analytics.persistence.best_known import BestKnownProfile


class KnowledgeStoreError(RuntimeError):
    """The database cannot be used as it is (wrong or newer version, not ours)."""


class TimelineError(ValueError):
    """A capture is dated before what the save already holds."""


# A verdict is the manager's own decision, so it is bounded at the door as well
# as in Python: a form cannot smuggle an essay into every row.
MAX_VERDICT_NOTE_LENGTH = 500

_V1 = f"""
CREATE TABLE saves (
    id INTEGER PRIMARY KEY,
    -- Caller-chosen identity of one playthrough. FM player IDs are the same in
    -- every save, so without this two saves would share one history.
    key TEXT NOT NULL UNIQUE,
    club_id TEXT,
    club_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE ingests (
    id INTEGER PRIMARY KEY,
    save_id INTEGER NOT NULL REFERENCES saves(id),
    captured_at TEXT NOT NULL,
    game_date TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    players_seen INTEGER NOT NULL,
    profile_rows_added INTEGER NOT NULL,
    attribute_rows_added INTEGER NOT NULL,
    UNIQUE (save_id, content_hash)
);

CREATE TABLE players (
    save_id INTEGER NOT NULL REFERENCES saves(id),
    player_id TEXT NOT NULL,
    name TEXT NOT NULL,
    first_seen_on TEXT NOT NULL,
    last_seen_on TEXT NOT NULL,
    PRIMARY KEY (save_id, player_id)
);

-- One row each time any visible profile field changed. Positions and raw
-- position ratings keep the "raw" names they have in the feed: they are the
-- accepted visibility gap, not something FM's own screens show.
CREATE TABLE profile_observations (
    id INTEGER PRIMARY KEY,
    save_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    ingest_id INTEGER NOT NULL REFERENCES ingests(id),
    age INTEGER,
    club TEXT,
    contract_type TEXT,
    contract_end TEXT,
    has_contract INTEGER CHECK (has_contract IS NULL OR has_contract IN (0, 1)),
    transfer_status TEXT,
    value INTEGER,
    scouting_knowledge INTEGER,
    matched_active_search INTEGER CHECK (
        matched_active_search IS NULL OR matched_active_search IN (0, 1)
    ),
    dropped_from_scout_reports INTEGER NOT NULL CHECK (dropped_from_scout_reports IN (0, 1)),
    footedness TEXT,
    nationality TEXT,
    positions TEXT NOT NULL,
    raw_positions TEXT NOT NULL,
    raw_position_familiarity TEXT,
    -- Free-form key/value facts (Player Search columns, and later wages),
    -- so a new fact needs no schema change.
    facts TEXT NOT NULL,
    FOREIGN KEY (save_id, player_id) REFERENCES players(save_id, player_id)
);
CREATE INDEX profile_by_player
    ON profile_observations (save_id, player_id, observed_on, id);

-- One row each time an attribute's visible state changed, including a change to
-- "unknown". `observed_on` is the in-game date it was seen, which for a
-- carried-forward or last-known reading is earlier than the ingest.
CREATE TABLE attribute_observations (
    id INTEGER PRIMARY KEY,
    save_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    attribute TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    ingest_id INTEGER NOT NULL REFERENCES ingests(id),
    source TEXT NOT NULL CHECK (source IN ('current', 'last_known')),
    visibility TEXT NOT NULL CHECK (visibility IN ('known', 'range', 'unknown')),
    value INTEGER,
    minimum INTEGER,
    maximum INTEGER,
    CHECK (
        (visibility = 'known' AND value IS NOT NULL AND minimum IS NULL AND maximum IS NULL)
        OR (visibility = 'range' AND value IS NULL AND minimum IS NOT NULL AND maximum IS NOT NULL)
        OR (visibility = 'unknown' AND value IS NULL AND minimum IS NULL AND maximum IS NULL)
    ),
    FOREIGN KEY (save_id, player_id) REFERENCES players(save_id, player_id)
);
CREATE INDEX attributes_by_player
    ON attribute_observations (save_id, player_id, attribute, observed_on, id);

-- Every in-game day a capture showed a player, whether or not anything about
-- him changed. Observation rows are change-only, so they say when a state
-- began; a sighting says it still held on a later day, and a best-known
-- reading ages from its last sighting, not its first.
CREATE TABLE sightings (
    save_id INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    -- 'profile': he was in the capture. 'current': his current attribute sheet
    -- was read, and it lists every attribute. 'last_known': one attribute of a
    -- last-known sheet, which lists only those FM showed for his position, so
    -- each attribute is sighted on its own.
    kind TEXT NOT NULL CHECK (kind IN ('profile', 'current', 'last_known')),
    attribute TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    -- The first ingest to see him that day.
    ingest_id INTEGER NOT NULL REFERENCES ingests(id),
    CHECK ((kind = 'last_known') = (attribute != '')),
    PRIMARY KEY (save_id, player_id, kind, attribute, observed_on),
    FOREIGN KEY (save_id, player_id) REFERENCES players(save_id, player_id)
) WITHOUT ROWID;

CREATE TABLE verdict_events (
    id INTEGER PRIMARY KEY,
    -- Keyed by the caller's save name rather than saves(id): a verdict is the
    -- manager's own note, which may be written before any capture of that save
    -- has been recorded, and two playthroughs still never share a verdict.
    save_key TEXT NOT NULL,
    player_id TEXT NOT NULL,
    -- NULL records a clear. The row stays so the decision it removed survives.
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('target', 'watch', 'reject')),
    note TEXT NOT NULL,
    decided_on TEXT NOT NULL,
    CHECK (length(note) <= {MAX_VERDICT_NOTE_LENGTH})
);
CREATE INDEX verdict_by_player ON verdict_events (save_key, player_id, id);
"""

# Append only. Version N of the file is the result of applying MIGRATIONS[:N];
# never edit an entry that has shipped, add a new one.
MIGRATIONS: tuple[str, ...] = (_V1,)

PROFILE_FIELDS = (
    "age", "club", "contract_type", "contract_end", "has_contract", "transfer_status",
    "value", "scouting_knowledge", "matched_active_search", "dropped_from_scout_reports",
    "footedness", "nationality", "positions", "raw_positions", "raw_position_familiarity",
    "facts",
)
_JSON_FIELDS = frozenset({"positions", "raw_positions", "raw_position_familiarity", "facts"})
_BOOL_FIELDS = frozenset({"has_contract", "matched_active_search", "dropped_from_scout_reports"})


@dataclass(frozen=True)
class PlayerKnowledge:
    """One player as the manager saw him in one capture."""

    player_id: str
    name: str
    profile: Mapping[str, Any]
    attributes: Mapping[str, AttributeObservation] = field(default_factory=dict)
    # In-game date of the attribute read; the capture date when not given.
    attributes_observed_on: str | None = None
    last_known_attributes: Mapping[str, AttributeObservation] = field(default_factory=dict)
    last_known_observed_on: str | None = None

    def __post_init__(self) -> None:
        if not self.player_id or not self.name:
            raise ValueError("a player needs an id and a name")
        unknown = set(self.profile) - set(PROFILE_FIELDS)
        if unknown:
            raise ValueError(f"unknown profile field(s): {', '.join(sorted(unknown))}")
        for label, when in (
            ("attributes_observed_on", self.attributes_observed_on),
            ("last_known_observed_on", self.last_known_observed_on),
        ):
            if when is not None:
                _iso(when, label)
        if self.last_known_attributes and self.last_known_observed_on is None:
            raise ValueError("last-known attributes need the date they were observed")


@dataclass(frozen=True)
class KnowledgeCapture:
    """Everything one scouting capture told the manager, ready to record."""

    save_key: str
    game_date: str
    captured_at: str
    players: tuple[PlayerKnowledge, ...]
    club_id: str | None = None
    club_name: str | None = None

    def __post_init__(self) -> None:
        if not self.save_key:
            raise ValueError("a capture needs a save key")
        _iso(self.game_date, "game_date")
        ids = [player.player_id for player in self.players]
        if len(ids) != len(set(ids)):
            raise ValueError("a capture cannot list the same player twice")

    def content_hash(self) -> str:
        """Identity of what was seen, ignoring when the capture was taken.

        Two refreshes with nothing new in between therefore hash the same and
        the second is skipped outright.
        """
        payload = [
            self.game_date,
            [
                [
                    player.player_id, player.name,
                    _profile_row(player.profile),
                    _attributes_payload(player.attributes),
                    player.attributes_observed_on,
                    _attributes_payload(player.last_known_attributes),
                    player.last_known_observed_on,
                ]
                for player in sorted(self.players, key=lambda item: item.player_id)
            ],
        ]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class RecordResult:
    save_key: str
    game_date: str
    skipped: bool
    players_seen: int = 0
    new_players: int = 0
    profile_rows: int = 0
    attribute_rows: int = 0

    def summary(self) -> str:
        if self.skipped:
            return (
                f"Player knowledge: nothing new since the last recording "
                f"(save {self.save_key}, {self.game_date})."
            )
        return (
            f"Player knowledge: recorded {self.players_seen} players for save "
            f"{self.save_key} at {self.game_date} "
            f"({self.new_players} new, {self.profile_rows} profile changes, "
            f"{self.attribute_rows} attribute observations)."
        )


@dataclass(frozen=True)
class SaveSummary:
    key: str
    club_name: str | None
    players: int
    ingests: int
    first_game_date: str | None
    last_game_date: str | None
    profile_rows: int
    attribute_rows: int


@dataclass(frozen=True)
class AttributeRecord:
    attribute: str
    observed_on: str
    source: str
    observation: AttributeObservation


class Verdict(StrEnum):
    """The three decisions the manager keeps himself: signing is his call."""

    TARGET = "target"
    WATCH = "watch"
    REJECT = "reject"


@dataclass(frozen=True)
class VerdictRecord:
    """One current decision for one player in one save, with its reason."""

    save_key: str
    player_id: str
    verdict: Verdict
    note: str
    decided_on: str

    def __post_init__(self) -> None:
        _verdict_identity(self.save_key, self.player_id, self.decided_on)
        if len(self.note) > MAX_VERDICT_NOTE_LENGTH:
            raise ValueError(
                f"note is limited to {MAX_VERDICT_NOTE_LENGTH} characters, got {len(self.note)}"
            )


def _verdict_identity(save_key: str, player_id: str, decided_on: str) -> str:
    """Check the three things every verdict write must name, and return the date."""
    if not save_key:
        raise ValueError("a verdict needs a save key")
    if not player_id:
        raise ValueError("a verdict needs a player id")
    return _iso(decided_on, "decided_on")


def _bounded_note(note: str | None) -> str:
    if note is None:
        return ""
    if not isinstance(note, str):
        raise ValueError("a verdict note must be text")
    return note.strip()


class PlayerKnowledgeStore:
    def __init__(self, path: str | Path, *, migrations: Sequence[str] = MIGRATIONS):
        self.path = Path(path)
        self._migrations = tuple(migrations)

    # -- lifecycle ---------------------------------------------------------

    def initialize(self) -> None:
        """Create the file, or bring an older one up to date, or refuse it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        latest = len(self._migrations)
        with closing(self._connect()) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > latest:
                raise KnowledgeStoreError(
                    f"{self.path} is player-knowledge schema v{version}, newer than this "
                    f"program understands (v{latest}). Update the program; do not delete the file."
                )
            if version == 0 and connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
            ).fetchone():
                raise KnowledgeStoreError(
                    f"{self.path} is a SQLite database but not a player-knowledge database."
                )
            if version == latest:
                return
            if version > 0:
                # A whole-database copy through SQLite's own backup API, so it
                # is consistent even if another process has the file open.
                backup = self.path.with_name(f"{self.path.name}.bak-v{version}")
                with closing(sqlite3.connect(backup)) as target:
                    connection.backup(target)
            for step in range(version, latest):
                self._apply(connection, step, self._migrations[step])

    @staticmethod
    def _apply(connection: sqlite3.Connection, step: int, migration: str) -> None:
        """One migration and its version bump, atomically.

        A migration script must not contain its own BEGIN or COMMIT.
        """
        script = f"BEGIN;\n{migration}\nPRAGMA user_version = {step + 1};\nCOMMIT;"
        try:
            connection.executescript(script)
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise KnowledgeStoreError(
                f"migration to v{step + 1} failed and was rolled back: {exc}"
            ) from exc

    # -- writing -----------------------------------------------------------

    def record(self, capture: KnowledgeCapture, *, allow_rewind: bool = False) -> RecordResult:
        """Append what `capture` shows, all of it or none of it."""
        self.initialize()
        digest = capture.content_hash()
        with closing(self._connect()) as connection, _transaction(connection):
            save_id = self._save_id(connection, capture)
            if connection.execute(
                "SELECT 1 FROM ingests WHERE save_id = ? AND content_hash = ?", (save_id, digest)
            ).fetchone():
                return RecordResult(capture.save_key, capture.game_date, skipped=True)
            newest = connection.execute(
                "SELECT MAX(game_date) FROM ingests WHERE save_id = ?", (save_id,)
            ).fetchone()[0]
            if newest is not None and capture.game_date < newest and not allow_rewind:
                raise TimelineError(
                    f"This capture is dated {capture.game_date} but save "
                    f"'{capture.save_key}' already holds {newest}. If it is a different "
                    "save, give it its own key so the two histories stay apart; if you "
                    "reloaded an earlier point of the same save, allow the rewind."
                )
            ingest_id = connection.execute(
                "INSERT INTO ingests (save_id, captured_at, game_date, ingested_at, "
                "content_hash, players_seen, profile_rows_added, attribute_rows_added) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                (
                    save_id, capture.captured_at, capture.game_date,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), digest,
                    len(capture.players),
                ),
            ).lastrowid
            new_players = self._upsert_players(connection, save_id, capture)
            profile_rows = self._record_profiles(connection, save_id, ingest_id, capture)
            attribute_rows = self._record_attributes(connection, save_id, ingest_id, capture)
            self._record_sightings(connection, save_id, ingest_id, capture)
            connection.execute(
                "UPDATE ingests SET profile_rows_added = ?, attribute_rows_added = ? WHERE id = ?",
                (profile_rows, attribute_rows, ingest_id),
            )
        return RecordResult(
            capture.save_key, capture.game_date, skipped=False,
            players_seen=len(capture.players), new_players=new_players,
            profile_rows=profile_rows, attribute_rows=attribute_rows,
        )

    @staticmethod
    def _save_id(connection: sqlite3.Connection, capture: KnowledgeCapture) -> int:
        row = connection.execute(
            "SELECT id FROM saves WHERE key = ?", (capture.save_key,)
        ).fetchone()
        if row is not None:
            if capture.club_name:
                connection.execute(
                    "UPDATE saves SET club_id = ?, club_name = ? WHERE id = ?",
                    (capture.club_id, capture.club_name, row[0]),
                )
            return int(row[0])
        return int(connection.execute(
            "INSERT INTO saves (key, club_id, club_name, created_at) VALUES (?, ?, ?, ?)",
            (
                capture.save_key, capture.club_id, capture.club_name,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        ).lastrowid)

    @staticmethod
    def _upsert_players(
        connection: sqlite3.Connection, save_id: int, capture: KnowledgeCapture
    ) -> int:
        existing = {
            row[0] for row in connection.execute(
                "SELECT player_id FROM players WHERE save_id = ?", (save_id,)
            )
        }
        rows = []
        for player in capture.players:
            # A last-known reading proves he was seen on its date, which can be
            # earlier than this capture.
            dates = (
                capture.game_date, player.last_known_observed_on, player.attributes_observed_on
            )
            first = min(when for when in dates if when)
            rows.append((save_id, player.player_id, player.name, first, capture.game_date))
        connection.executemany(
            "INSERT INTO players (save_id, player_id, name, first_seen_on, last_seen_on) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (save_id, player_id) DO UPDATE SET name = excluded.name, "
            "first_seen_on = MIN(first_seen_on, excluded.first_seen_on), "
            "last_seen_on = MAX(last_seen_on, excluded.last_seen_on)",
            rows,
        )
        return sum(1 for player in capture.players if player.player_id not in existing)

    @staticmethod
    def _record_profiles(
        connection: sqlite3.Connection, save_id: int, ingest_id: int, capture: KnowledgeCapture
    ) -> int:
        latest = {
            row[0]: tuple(row)[1:] for row in connection.execute(
                f"SELECT player_id, {', '.join(PROFILE_FIELDS)} FROM ("
                "  SELECT *, ROW_NUMBER() OVER (PARTITION BY player_id "
                "    ORDER BY observed_on DESC, id DESC) AS rn "
                "  FROM profile_observations WHERE save_id = ? AND observed_on <= ?"
                ") WHERE rn = 1",
                (save_id, capture.game_date),
            )
        }
        changed = []
        for player in capture.players:
            row = _profile_row(player.profile)
            if latest.get(player.player_id) != row:
                changed.append((save_id, player.player_id, capture.game_date, ingest_id, *row))
        connection.executemany(
            f"INSERT INTO profile_observations (save_id, player_id, observed_on, ingest_id, "
            f"{', '.join(PROFILE_FIELDS)}) VALUES (?, ?, ?, ?, {', '.join('?' * len(PROFILE_FIELDS))})",
            changed,
        )
        return len(changed)

    @staticmethod
    def _record_attributes(
        connection: sqlite3.Connection, save_id: int, ingest_id: int, capture: KnowledgeCapture
    ) -> int:
        # Group by the date each reading was actually taken, then compare each
        # group with what was known on or before that date.
        groups: dict[str, list[tuple[str, str, str, AttributeObservation]]] = {}
        for player in capture.players:
            if player.attributes:
                observed_on = player.attributes_observed_on or capture.game_date
                groups.setdefault(observed_on, []).extend(
                    (player.player_id, "current", name, observation)
                    for name, observation in player.attributes.items()
                )
            if player.last_known_attributes:
                groups.setdefault(player.last_known_observed_on, []).extend(
                    (player.player_id, "last_known", name, observation)
                    for name, observation in player.last_known_attributes.items()
                )
        added = 0
        for observed_on in sorted(groups):
            latest = {
                (row[0], row[1]): tuple(row)[2:] for row in connection.execute(
                    "SELECT player_id, attribute, visibility, value, minimum, maximum FROM ("
                    "  SELECT *, ROW_NUMBER() OVER (PARTITION BY player_id, attribute "
                    "    ORDER BY observed_on DESC, id DESC) AS rn "
                    "  FROM attribute_observations WHERE save_id = ? AND observed_on <= ?"
                    ") WHERE rn = 1",
                    (save_id, observed_on),
                )
            }
            changed = []
            for player_id, source, name, observation in groups[observed_on]:
                state = _attribute_state(observation)
                if latest.get((player_id, name)) != state:
                    latest[(player_id, name)] = state
                    changed.append(
                        (save_id, player_id, name, observed_on, ingest_id, source, *state)
                    )
            connection.executemany(
                "INSERT INTO attribute_observations (save_id, player_id, attribute, observed_on, "
                "ingest_id, source, visibility, value, minimum, maximum) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                changed,
            )
            added += len(changed)
        return added

    @staticmethod
    def _record_sightings(
        connection: sqlite3.Connection, save_id: int, ingest_id: int, capture: KnowledgeCapture
    ) -> None:
        # The rows above are change-only; these let a value seen unchanged every
        # week age from the last of those weeks rather than the first.
        rows = []
        for player in capture.players:
            rows.append((save_id, player.player_id, "profile", "", capture.game_date, ingest_id))
            if player.attributes:
                rows.append((
                    save_id, player.player_id, "current", "",
                    player.attributes_observed_on or capture.game_date, ingest_id,
                ))
            rows.extend(
                (save_id, player.player_id, "last_known", name, player.last_known_observed_on,
                 ingest_id)
                for name in player.last_known_attributes
            )
        connection.executemany(
            "INSERT OR IGNORE INTO sightings (save_id, player_id, kind, attribute, observed_on, "
            "ingest_id) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    # -- reading -----------------------------------------------------------

    def saves(self) -> tuple[SaveSummary, ...]:
        self.initialize()
        with closing(self._connect()) as connection:
            return tuple(
                SaveSummary(
                    key=row["key"], club_name=row["club_name"],
                    players=row["players"], ingests=row["ingests"],
                    first_game_date=row["first_date"], last_game_date=row["last_date"],
                    profile_rows=row["profile_rows"], attribute_rows=row["attribute_rows"],
                )
                for row in connection.execute(
                    "SELECT s.key, s.club_name, "
                    " (SELECT COUNT(*) FROM players p WHERE p.save_id = s.id) AS players, "
                    " (SELECT COUNT(*) FROM ingests i WHERE i.save_id = s.id) AS ingests, "
                    " (SELECT MIN(game_date) FROM ingests i WHERE i.save_id = s.id) AS first_date, "
                    " (SELECT MAX(game_date) FROM ingests i WHERE i.save_id = s.id) AS last_date, "
                    " (SELECT COUNT(*) FROM profile_observations o WHERE o.save_id = s.id) AS profile_rows, "
                    " (SELECT COUNT(*) FROM attribute_observations a WHERE a.save_id = s.id) AS attribute_rows "
                    "FROM saves s ORDER BY s.key"
                )
            )

    def attribute_history(
        self, save_key: str, player_id: str, attribute: str | None = None
    ) -> tuple[AttributeRecord, ...]:
        """Every recorded state of a player's attributes, oldest first."""
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT a.attribute, a.observed_on, a.source, a.visibility, a.value, "
                "a.minimum, a.maximum FROM attribute_observations a "
                "JOIN saves s ON s.id = a.save_id "
                "WHERE s.key = ? AND a.player_id = ? AND (? IS NULL OR a.attribute = ?) "
                "ORDER BY a.attribute, a.observed_on, a.id",
                (save_key, player_id, attribute, attribute),
            ).fetchall()
        return tuple(
            AttributeRecord(
                attribute=row["attribute"], observed_on=row["observed_on"], source=row["source"],
                observation=AttributeObservation(
                    Visibility(row["visibility"]), value=row["value"],
                    minimum=row["minimum"], maximum=row["maximum"],
                ),
            )
            for row in rows
        )

    def profile_history(self, save_key: str, player_id: str) -> tuple[dict[str, Any], ...]:
        """Every recorded profile of a player, oldest first, with `observed_on`."""
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT o.observed_on, {', '.join('o.' + name for name in PROFILE_FIELDS)} "
                "FROM profile_observations o JOIN saves s ON s.id = o.save_id "
                "WHERE s.key = ? AND o.player_id = ? ORDER BY o.observed_on, o.id",
                (save_key, player_id),
            ).fetchall()
        return tuple(_decoded_profile(row) for row in rows)

    def best_known_profile(
        self, save_key: str, player_id: str, as_of: str
    ) -> BestKnownProfile | None:
        """What `save_key` had recorded about `player_id` at or before `as_of`.

        None when that save holds nothing dated on or before `as_of` for him --
        an unknown id, a player first seen later, another save -- rather than a
        profile assembled out of nothing. The date is required, so a caller
        cannot read the future by forgetting to ask for a cutoff.
        """
        return self._best_known(save_key, as_of, player_id).get(player_id)

    def best_known_profiles(self, save_key: str, as_of: str) -> dict[str, BestKnownProfile]:
        """Every player `save_key` had recorded something about at or before `as_of`.

        Keyed by player id; players with nothing that early are absent rather
        than present as empty profiles. A fixed number of queries, whatever the
        size of the save.
        """
        return self._best_known(save_key, as_of, None)

    def _best_known(
        self, save_key: str, as_of: str, player_id: str | None
    ) -> dict[str, BestKnownProfile]:
        # Imported here: the read model builds on this module's schema, so
        # importing it at the top would be circular.
        from fm_analytics.persistence.best_known import read_best_known

        _iso(as_of, "as_of")
        self.initialize()
        with closing(self._connect()) as connection:
            return read_best_known(connection, save_key, as_of, player_id)

    # -- verdicts -----------------------------------------------------------
    #
    # Append-only like everything else: a later decision is a new row, a clear
    # is a row with no verdict, and nothing already recorded is ever rewritten.

    def set_verdict(
        self,
        save_key: str,
        player_id: str,
        verdict: Verdict | str,
        *,
        note: str = "",
        decided_on: str,
    ) -> VerdictRecord:
        """Record the manager's decision for one player in one save.

        Re-submitting what is already current adds no row, so a double-clicked
        form leaves the history exactly as it was.
        """
        record = VerdictRecord(
            save_key=save_key,
            player_id=player_id,
            verdict=Verdict(verdict),
            note=_bounded_note(note),
            decided_on=decided_on,
        )
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            if self._current_verdict(connection, save_key, player_id) == record:
                return record
            connection.execute(
                "INSERT INTO verdict_events (save_key, player_id, verdict, note, decided_on) "
                "VALUES (?, ?, ?, ?, ?)",
                (save_key, player_id, record.verdict.value, record.note, record.decided_on),
            )
        return record

    def clear_verdict(self, save_key: str, player_id: str, *, decided_on: str) -> bool:
        """Forget the current verdict, keeping every decision already recorded.

        Returns whether anything needed clearing: an untouched player gains no
        row at all, so clearing twice is as harmless as clearing once.
        """
        _verdict_identity(save_key, player_id, decided_on)
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            if self._current_verdict(connection, save_key, player_id) is None:
                return False
            connection.execute(
                "INSERT INTO verdict_events (save_key, player_id, verdict, note, decided_on) "
                "VALUES (?, ?, NULL, '', ?)",
                (save_key, player_id, decided_on),
            )
            return True

    def get_verdict(self, save_key: str, player_id: str) -> VerdictRecord | None:
        """The current decision for this player, or None when there is none."""
        self.initialize()
        with closing(self._connect()) as connection:
            return self._current_verdict(connection, save_key, player_id)

    def current_verdicts(self, save_key: str) -> dict[str, VerdictRecord]:
        """Every current decision in one save, keyed by player id.

        Cleared and untouched players are simply absent. One query whatever the
        number of verdicts, so a list can drop its rejects without an N+1.
        """
        if not save_key:
            raise ValueError("a verdict needs a save key")
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT player_id, verdict, note, decided_on FROM ("
                "  SELECT *, ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY id DESC) AS rn "
                "  FROM verdict_events WHERE save_key = ?"
                ") WHERE rn = 1 AND verdict IS NOT NULL",
                (save_key,),
            ).fetchall()
        return {
            row["player_id"]: VerdictRecord(
                save_key=save_key, player_id=row["player_id"],
                verdict=Verdict(row["verdict"]), note=row["note"], decided_on=row["decided_on"],
            )
            for row in rows
        }

    @staticmethod
    def _current_verdict(
        connection: sqlite3.Connection, save_key: str, player_id: str
    ) -> VerdictRecord | None:
        row = connection.execute(
            "SELECT verdict, note, decided_on FROM verdict_events "
            "WHERE save_key = ? AND player_id = ? ORDER BY id DESC LIMIT 1",
            (save_key, player_id),
        ).fetchone()
        if row is None or row["verdict"] is None:
            return None
        return VerdictRecord(
            save_key=save_key, player_id=player_id, verdict=Verdict(row["verdict"]),
            note=row["note"], decided_on=row["decided_on"],
        )

    def _connect(self) -> sqlite3.Connection:
        # Autocommit; `_transaction` and `_apply` manage their own BEGIN/COMMIT.
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    # IMMEDIATE takes the write lock up front, so two recorders (the web refresh
    # and the command line) queue instead of both deciding "nothing new".
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def _iso(text: str, label: str) -> str:
    # Every date is stored and compared as text, which orders correctly only in
    # YYYY-MM-DD form. `date.fromisoformat` also accepts 20190908 and
    # 2019-W36-7 since Python 3.11, and those sort among stored dates as if
    # they were other days: an `as_of` of "20190701" would admit September.
    try:
        canonical = date.fromisoformat(text).isoformat() == text
    except (TypeError, ValueError):
        canonical = False
    if not canonical:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD), got {text!r}")
    return text


def _decoded_profile(row: Mapping[str, Any]) -> dict[str, Any]:
    """One stored profile row as both readers return it: JSON and flags decoded."""
    item: dict[str, Any] = {"observed_on": row["observed_on"]}
    for name in PROFILE_FIELDS:
        value = row[name]
        if name in _JSON_FIELDS and value is not None:
            value = json.loads(value)
        elif name in _BOOL_FIELDS and value is not None:
            value = bool(value)
        item[name] = value
    return item


def _profile_row(profile: Mapping[str, Any]) -> tuple[Any, ...]:
    """Normalise a profile to exactly what the database stores and returns.

    The same form is used to write, to compare with the latest stored row and to
    hash, so "did anything change" is a plain tuple comparison.
    """
    row = []
    for name in PROFILE_FIELDS:
        value = profile.get(name)
        if name in ("positions", "raw_positions"):
            value = list(value or ())
        elif name == "facts":
            value = dict(value or {})
        if name in _JSON_FIELDS:
            value = None if value is None else json.dumps(
                value, sort_keys=True, separators=(",", ":")
            )
        elif name in _BOOL_FIELDS:
            value = None if value is None else int(bool(value))
        row.append(value)
    if row[PROFILE_FIELDS.index("dropped_from_scout_reports")] is None:
        row[PROFILE_FIELDS.index("dropped_from_scout_reports")] = 0
    return tuple(row)


def _attribute_state(observation: AttributeObservation) -> tuple[Any, ...]:
    return (observation.visibility.value, observation.value, observation.minimum, observation.maximum)


def _attributes_payload(attributes: Mapping[str, AttributeObservation]) -> dict[str, Any]:
    return {name: observation.to_dict() for name, observation in attributes.items()}
