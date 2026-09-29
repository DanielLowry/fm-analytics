"""The manager's match history: what FM showed about each match, kept for good.

FM keeps full match stats in memory only for the latest match and for any
match report opened since, so a match's detail must be recorded while it is
there. The manager's own notes on a match (the tactic used, how strong they
judged the opponent before kickoff) cannot come from FM at all. Both follow
the player-knowledge rules (see `persistence.migrations`):

* **Nothing is overwritten.** Each distinct state of a match is a new row. A
  match's current state is its latest version *with full stats* if one exists,
  otherwise its latest version, so a later capture that no longer sees the
  stats never hides them.
* **It stays readable.** Ordered migrations from v1, a backup before any
  upgrade, and a refusal to open a newer or unrelated file.

Rows are keyed by save (the managed club, like player knowledge), because FM's
club IDs are the same in every save.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from fm_analytics.domain.matches import (
    Competition,
    LeagueResult,
    MatchCapture,
    MatchRecord,
    TeamRef,
)
from fm_analytics.persistence.migrations import bring_up_to_date


class MatchHistoryError(RuntimeError):
    """The database cannot be used as it is (wrong or newer version, not ours)."""


class MatchTimelineError(ValueError):
    """A capture is dated before what the save already holds."""


MAX_NOTE_LENGTH = 1000
RATING_MINIMUM, RATING_MAXIMUM = -2, 2

_V1 = """
CREATE TABLE saves (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    club_id TEXT,
    club_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE captures (
    id INTEGER PRIMARY KEY,
    save_id INTEGER NOT NULL REFERENCES saves(id),
    captured_at TEXT NOT NULL,
    game_date TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    matches_seen INTEGER NOT NULL,
    match_versions_added INTEGER NOT NULL,
    league_results_added INTEGER NOT NULL,
    UNIQUE (save_id, content_hash)
);

-- One row per distinct state of a match, as the capture's JSON document.
CREATE TABLE match_versions (
    id INTEGER PRIMARY KEY,
    save_id INTEGER NOT NULL REFERENCES saves(id),
    match_key TEXT NOT NULL,
    match_date TEXT NOT NULL,
    has_detail INTEGER NOT NULL CHECK (has_detail IN (0, 1)),
    content_hash TEXT NOT NULL,
    document TEXT NOT NULL,
    capture_id INTEGER NOT NULL REFERENCES captures(id),
    UNIQUE (save_id, match_key, content_hash)
);
CREATE INDEX match_versions_by_match ON match_versions (save_id, match_key, id);

-- Every result of a league the managed team plays in, for the table at each
-- kickoff. A played result does not change, so the first sighting is kept.
CREATE TABLE league_results (
    save_id INTEGER NOT NULL REFERENCES saves(id),
    competition_id TEXT NOT NULL,
    competition_name TEXT NOT NULL,
    competition_short_name TEXT NOT NULL,
    result_date TEXT NOT NULL,
    home_id TEXT NOT NULL,
    home_name TEXT NOT NULL,
    away_id TEXT NOT NULL,
    away_name TEXT NOT NULL,
    home_goals INTEGER NOT NULL,
    away_goals INTEGER NOT NULL,
    capture_id INTEGER NOT NULL REFERENCES captures(id),
    PRIMARY KEY (save_id, competition_id, result_date, home_id, away_id)
);

-- The manager's own notes on a match. Append only; the latest wins.
CREATE TABLE match_notes (
    id INTEGER PRIMARY KEY,
    save_id INTEGER NOT NULL REFERENCES saves(id),
    match_key TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    tactic_key TEXT,
    opponent_rating INTEGER CHECK (opponent_rating IS NULL OR opponent_rating BETWEEN -2 AND 2),
    note TEXT NOT NULL CHECK (length(note) <= 1000)
);
CREATE INDEX match_notes_by_match ON match_notes (save_id, match_key, id);

-- The manager's confirmation of which catalogue role an FM role code means.
-- A fact about FM, not about one save. Append only; the latest wins.
CREATE TABLE role_codes (
    id INTEGER PRIMARY KEY,
    code INTEGER NOT NULL,
    role_key TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
"""

# Append only. Version N of the file is the result of applying MIGRATIONS[:N].
MIGRATIONS: tuple[str, ...] = (_V1,)


@dataclass(frozen=True)
class MatchRecordResult:
    matches_seen: int
    versions_added: int
    league_results_added: int
    skipped: bool = False

    def summary(self) -> str:
        if self.skipped:
            return "already recorded; nothing new"
        return (
            f"{self.matches_seen} matches seen, {self.versions_added} new or changed, "
            f"{self.league_results_added} league results added"
        )


@dataclass(frozen=True)
class MatchNote:
    match_key: str
    recorded_at: str
    tactic_key: str | None
    opponent_rating: int | None
    note: str


@dataclass(frozen=True)
class MatchSaveSummary:
    key: str
    club_name: str | None
    matches: int
    detailed_matches: int
    captures: int
    last_game_date: str | None


@dataclass(frozen=True)
class MatchHistory:
    """Everything one save's analysis needs, read in one go."""

    save_key: str
    club: TeamRef
    matches: tuple[MatchRecord, ...]
    league_results: tuple[tuple[Competition, tuple[LeagueResult, ...]], ...]
    notes: Mapping[str, MatchNote]
    role_codes: Mapping[int, str]
    last_game_date: date | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_note(tactic_key: str | None, opponent_rating: int | None, note: str) -> str:
    if opponent_rating is not None and (
        not isinstance(opponent_rating, int) or isinstance(opponent_rating, bool)
        or not RATING_MINIMUM <= opponent_rating <= RATING_MAXIMUM
    ):
        raise ValueError(f"the opponent rating must be a whole number from {RATING_MINIMUM} to +{RATING_MAXIMUM}")
    if tactic_key is not None and not tactic_key.strip():
        raise ValueError("a tactic key cannot be blank")
    if not isinstance(note, str):
        raise ValueError("a match note must be text")
    note = note.strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"a match note is limited to {MAX_NOTE_LENGTH} characters")
    return note


class MatchHistoryStore:
    def __init__(self, path: str | Path, *, migrations: Sequence[str] = MIGRATIONS):
        self.path = Path(path)
        self._migrations = tuple(migrations)

    def initialize(self) -> None:
        """Create the file, or bring an older one up to date, or refuse it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            bring_up_to_date(
                connection, self.path, self._migrations, kind="match-history", error=MatchHistoryError
            )

    # -- writing -----------------------------------------------------------

    def record(
        self, capture: MatchCapture, *, save_key: str, allow_rewind: bool = False
    ) -> MatchRecordResult:
        """Append what `capture` shows, all of it or none of it."""
        self.initialize()
        content_hash = _capture_hash(capture)
        with closing(self._connect()) as connection, _transaction(connection):
            save_id = self._save_id(connection, save_key, capture.managed_club)
            if connection.execute(
                "SELECT 1 FROM captures WHERE save_id = ? AND content_hash = ?", (save_id, content_hash)
            ).fetchone():
                return MatchRecordResult(len(capture.matches), 0, 0, skipped=True)
            latest = connection.execute(
                "SELECT max(game_date) FROM captures WHERE save_id = ?", (save_id,)
            ).fetchone()[0]
            if latest and capture.game_date.isoformat() < latest and not allow_rewind:
                raise MatchTimelineError(
                    f"this capture is dated {capture.game_date}, before {latest}, the latest "
                    f"already recorded for {save_key}. If you reloaded an earlier save, record "
                    "it with --allow-rewind."
                )
            capture_id = connection.execute(
                "INSERT INTO captures (save_id, captured_at, game_date, recorded_at, content_hash, "
                "matches_seen, match_versions_added, league_results_added) VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                (save_id, capture.captured_at, capture.game_date.isoformat(), _now(), content_hash,
                 len(capture.matches)),
            ).lastrowid
            versions = 0
            for match in capture.matches:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO match_versions (save_id, match_key, match_date, has_detail, "
                    "content_hash, document, capture_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (save_id, match.key, match.date.isoformat(), int(match.detail is not None),
                     match.content_hash(), json.dumps(match.to_document(), sort_keys=True), capture_id),
                )
                versions += cursor.rowcount
            results = 0
            for competition, rows in capture.league_results:
                for row in rows:
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO league_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (save_id, competition.id, competition.name, competition.short_name,
                         row.date.isoformat(), row.home.id, row.home.name, row.away.id, row.away.name,
                         row.home_goals, row.away_goals, capture_id),
                    )
                    results += cursor.rowcount
            connection.execute(
                "UPDATE captures SET match_versions_added = ?, league_results_added = ? WHERE id = ?",
                (versions, results, capture_id),
            )
        return MatchRecordResult(len(capture.matches), versions, results)

    def add_note(
        self,
        save_key: str,
        match_key: str,
        *,
        tactic_key: str | None,
        opponent_rating: int | None,
        note: str = "",
    ) -> None:
        """Record the manager's own notes on a match. Local database only; never FM."""
        note = validate_note(tactic_key, opponent_rating, note)
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            save_id = self._existing_save_id(connection, save_key)
            if not connection.execute(
                "SELECT 1 FROM match_versions WHERE save_id = ? AND match_key = ?", (save_id, match_key)
            ).fetchone():
                raise ValueError(f"no match {match_key} is recorded for {save_key}")
            connection.execute(
                "INSERT INTO match_notes (save_id, match_key, recorded_at, tactic_key, opponent_rating, note) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (save_id, match_key, _now(), tactic_key, opponent_rating, note),
            )

    def confirm_role_code(self, code: int, role_key: str) -> None:
        """Record which catalogue role an FM role code is, as the manager confirmed it."""
        if not isinstance(code, int) or isinstance(code, bool) or code <= 0:
            raise ValueError("an FM role code is a positive whole number")
        if not role_key.strip():
            raise ValueError("a role key cannot be blank")
        self.initialize()
        with closing(self._connect()) as connection, _transaction(connection):
            connection.execute(
                "INSERT INTO role_codes (code, role_key, recorded_at) VALUES (?, ?, ?)",
                (code, role_key.strip(), _now()),
            )

    # -- reading -----------------------------------------------------------

    def saves(self) -> tuple[MatchSaveSummary, ...]:
        if not self.path.exists():
            return ()
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT s.key, s.club_name,
                    (SELECT count(DISTINCT match_key) FROM match_versions WHERE save_id = s.id) AS matches,
                    (SELECT count(DISTINCT match_key) FROM match_versions
                        WHERE save_id = s.id AND has_detail = 1) AS detailed,
                    (SELECT count(*) FROM captures WHERE save_id = s.id) AS captures,
                    (SELECT max(game_date) FROM captures WHERE save_id = s.id) AS last_game_date
                FROM saves s ORDER BY s.id
                """
            ).fetchall()
        return tuple(
            MatchSaveSummary(row["key"], row["club_name"], row["matches"], row["detailed"],
                             row["captures"], row["last_game_date"])
            for row in rows
        )

    def latest_save_key(self) -> str | None:
        """The save most recently recorded into, for pages that are not told one."""
        if not self.path.exists():
            return None
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT s.key FROM captures c JOIN saves s ON s.id = c.save_id ORDER BY c.id DESC LIMIT 1"
            ).fetchone()
        return row["key"] if row else None

    def load_history(self, save_key: str) -> MatchHistory | None:
        """The save's current matches, league results, notes and role codes; None if unknown."""
        if not self.path.exists():
            return None
        self.initialize()
        with closing(self._connect()) as connection:
            save = connection.execute("SELECT * FROM saves WHERE key = ?", (save_key,)).fetchone()
            if save is None:
                return None
            # Latest version with full stats if any, else the latest version.
            documents = connection.execute(
                """
                SELECT v.document FROM match_versions v
                WHERE v.id = (
                    SELECT w.id FROM match_versions w
                    WHERE w.save_id = v.save_id AND w.match_key = v.match_key
                    ORDER BY w.has_detail DESC, w.id DESC LIMIT 1
                ) AND v.save_id = ?
                ORDER BY v.match_date, v.match_key
                """,
                (save["id"],),
            ).fetchall()
            leagues: dict[str, tuple[Competition, list[LeagueResult]]] = {}
            for row in connection.execute(
                "SELECT * FROM league_results WHERE save_id = ? ORDER BY result_date, home_name",
                (save["id"],),
            ):
                competition = Competition(row["competition_id"], row["competition_name"], row["competition_short_name"])
                leagues.setdefault(competition.id, (competition, []))[1].append(
                    LeagueResult(
                        date.fromisoformat(row["result_date"]),
                        TeamRef(row["home_id"], row["home_name"]),
                        TeamRef(row["away_id"], row["away_name"]),
                        row["home_goals"], row["away_goals"],
                    )
                )
            notes = {
                row["match_key"]: MatchNote(
                    row["match_key"], row["recorded_at"], row["tactic_key"], row["opponent_rating"], row["note"]
                )
                for row in connection.execute(
                    "SELECT * FROM match_notes WHERE save_id = ? ORDER BY id", (save["id"],)
                )
            }
            role_codes = {
                row["code"]: row["role_key"]
                for row in connection.execute("SELECT code, role_key FROM role_codes ORDER BY id")
            }
            last = connection.execute(
                "SELECT max(game_date) FROM captures WHERE save_id = ?", (save["id"],)
            ).fetchone()[0]
        return MatchHistory(
            save_key=save_key,
            club=TeamRef(save["club_id"] or "", save["club_name"] or ""),
            matches=tuple(MatchRecord.from_document(json.loads(row["document"])) for row in documents),
            league_results=tuple((competition, tuple(rows)) for competition, rows in leagues.values()),
            notes=notes,
            role_codes=role_codes,
            last_game_date=date.fromisoformat(last) if last else None,
        )

    def match_versions(self, save_key: str, match_key: str) -> tuple[MatchRecord, ...]:
        """Every recorded state of one match, oldest first."""
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT v.document FROM match_versions v JOIN saves s ON s.id = v.save_id "
                "WHERE s.key = ? AND v.match_key = ? ORDER BY v.id",
                (save_key, match_key),
            ).fetchall()
        return tuple(MatchRecord.from_document(json.loads(row["document"])) for row in rows)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _save_id(connection: sqlite3.Connection, save_key: str, club: TeamRef) -> int:
        row = connection.execute("SELECT id FROM saves WHERE key = ?", (save_key,)).fetchone()
        if row is not None:
            return row["id"]
        return connection.execute(
            "INSERT INTO saves (key, club_id, club_name, created_at) VALUES (?, ?, ?, ?)",
            (save_key, club.id, club.name, _now()),
        ).lastrowid

    @staticmethod
    def _existing_save_id(connection: sqlite3.Connection, save_key: str) -> int:
        row = connection.execute("SELECT id FROM saves WHERE key = ?", (save_key,)).fetchone()
        if row is None:
            raise ValueError(f"no matches are recorded for {save_key}")
        return row["id"]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _capture_hash(capture: MatchCapture) -> str:
    """What a capture shows, ignoring when it was taken."""
    payload = {
        "gameDate": capture.game_date.isoformat(),
        "matches": sorted(match.content_hash() for match in capture.matches),
        "leagues": [
            [competition.id, len(rows), rows[-1].date.isoformat() if rows else None]
            for competition, rows in capture.league_results
        ],
    }
    text = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")
