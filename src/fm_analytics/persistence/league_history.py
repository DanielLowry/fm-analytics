"""Append-only dated league/roster snapshots, separate from attribute history."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fm_analytics.analytics.league_insights import TeamSummary
from fm_analytics.domain.leagues import LeagueCapture
from fm_analytics.persistence.migrations import bring_up_to_date

APPLICATION_ID = 0x4C454147
MIGRATIONS = (f"""
PRAGMA application_id = {APPLICATION_ID};
CREATE TABLE league_captures (
    id INTEGER PRIMARY KEY,
    save_key TEXT NOT NULL,
    game_date TEXT NOT NULL,
    competition_id TEXT NOT NULL,
    season TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    document TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (save_key, content_hash)
);
CREATE INDEX league_captures_by_date ON league_captures (save_key, competition_id, game_date, id);
""", """
-- What one comparison concluded about each club, to explain the next read.
-- A derived result, keyed by the scope (catalogue, policies, tactic choice)
-- it was computed under, so a model change is never mistaken for new knowledge.
CREATE TABLE league_team_summaries (
    save_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    scope TEXT NOT NULL,
    club_id TEXT NOT NULL,
    document TEXT NOT NULL,
    PRIMARY KEY (save_key, content_hash, scope, club_id),
    FOREIGN KEY (save_key, content_hash) REFERENCES league_captures (save_key, content_hash)
);
""")


class LeagueHistoryError(RuntimeError):
    pass


class LeagueHistoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            occupied = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
            if application != APPLICATION_ID and (application or occupied):
                raise LeagueHistoryError(f"{self.path} is not a league-history database")
            bring_up_to_date(connection, self.path, MIGRATIONS, kind="league-history", error=LeagueHistoryError)
            yield connection

    def record(self, capture: LeagueCapture) -> bool:
        # Revalidate even captures constructed directly rather than decoded.
        capture = LeagueCapture.from_document(capture.to_document())
        with self._connection() as connection, connection:
            existing = connection.execute("SELECT 1 FROM league_captures WHERE save_key=? AND content_hash=?",
                                          (capture.save_key, capture.content_hash())).fetchone()
            if existing:
                return False
            latest = connection.execute("SELECT MAX(game_date) FROM league_captures WHERE save_key=?",
                                        (capture.save_key,)).fetchone()[0]
            if latest and capture.game.game_date.isoformat() < latest:
                raise ValueError("league capture predates this save's recorded history; use a separate save key for a reload branch")
            connection.execute("INSERT INTO league_captures (save_key,game_date,competition_id,season,content_hash,document,recorded_at) VALUES (?,?,?,?,?,?,?)",
                               (capture.save_key, capture.game.game_date.isoformat(), capture.competition.id,
                                capture.season, capture.content_hash(), json.dumps(capture.to_document()),
                                datetime.now(timezone.utc).isoformat()))
            return True

    def record_summaries(self, capture: LeagueCapture, scope: str, summaries: dict[str, TeamSummary]) -> None:
        """Keep one recorded capture's per-club conclusions under `scope`."""
        with self._connection() as connection, connection:
            if not connection.execute("SELECT 1 FROM league_captures WHERE save_key=? AND content_hash=?",
                                      (capture.save_key, capture.content_hash())).fetchone():
                raise LeagueHistoryError("record the league capture before its summaries")
            connection.executemany(
                "INSERT OR REPLACE INTO league_team_summaries (save_key,content_hash,scope,club_id,document) VALUES (?,?,?,?,?)",
                [(capture.save_key, capture.content_hash(), scope, club_id, json.dumps(summary.to_document()))
                 for club_id, summary in summaries.items()])

    def previous_summaries(self, capture: LeagueCapture, scope: str) -> dict[str, TeamSummary]:
        """The latest other read of this league, same save and scope, never a later date."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT c.content_hash FROM league_captures c WHERE c.save_key=? AND c.competition_id=? "
                "AND c.content_hash<>? AND c.game_date<=? AND EXISTS (SELECT 1 FROM league_team_summaries s "
                "WHERE s.save_key=c.save_key AND s.content_hash=c.content_hash AND s.scope=?) "
                "ORDER BY c.game_date DESC, c.id DESC LIMIT 1",
                (capture.save_key, capture.competition.id, capture.content_hash(),
                 capture.game.game_date.isoformat(), scope)).fetchone()
            if row is None:
                return {}
            rows = connection.execute(
                "SELECT club_id, document FROM league_team_summaries WHERE save_key=? AND content_hash=? AND scope=?",
                (capture.save_key, row[0], scope)).fetchall()
        return {club_id: TeamSummary.from_document(json.loads(document)) for club_id, document in rows}

    def latest(self, save_key: str, competition_id: str, *, as_of: date) -> LeagueCapture | None:
        with self._connection() as connection:
            row = connection.execute("SELECT document FROM league_captures WHERE save_key=? AND competition_id=? AND game_date<=? ORDER BY game_date DESC,id DESC LIMIT 1",
                                     (save_key, competition_id, as_of.isoformat())).fetchone()
        return LeagueCapture.from_document(json.loads(row[0])) if row else None
