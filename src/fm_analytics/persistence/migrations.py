"""The one upgrade path for local databases whose history FM will not show again.

The player-knowledge and match-history stores both hold observations the game
cannot give back, so both follow the same rules, kept here rather than copied:

* version N of a file is the result of applying ``migrations[:N]``, and the
  list is append only;
* a file already in use is backed up (``<name>.bak-v<N>``) before any upgrade;
* each step and its version bump are applied atomically; and
* a file from a newer program, or a SQLite file that is not this kind of
  database, is refused and left untouched.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Sequence


def bring_up_to_date(
    connection: sqlite3.Connection,
    path: Path,
    migrations: Sequence[str],
    *,
    kind: str,
    error: type[Exception],
) -> None:
    """Create the schema, upgrade an older file, or refuse one it cannot use."""
    latest = len(migrations)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > latest:
        raise error(
            f"{path} is {kind} schema v{version}, newer than this "
            f"program understands (v{latest}). Update the program; do not delete the file."
        )
    if version == 0 and connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
    ).fetchone():
        raise error(f"{path} is a SQLite database but not a {kind} database.")
    if version == latest:
        return
    if version > 0:
        # A whole-database copy through SQLite's own backup API, so it is
        # consistent even if another process has the file open.
        backup = path.with_name(f"{path.name}.bak-v{version}")
        with closing(sqlite3.connect(backup)) as target:
            connection.backup(target)
    for step in range(version, latest):
        apply_migration(connection, step, migrations[step], error=error)


def apply_migration(
    connection: sqlite3.Connection, step: int, migration: str, *, error: type[Exception]
) -> None:
    """One migration and its version bump, atomically.

    A migration script must not contain its own BEGIN or COMMIT.
    """
    script = f"BEGIN;\n{migration}\nPRAGMA user_version = {step + 1};\nCOMMIT;"
    try:
        connection.executescript(script)
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise error(f"migration to v{step + 1} failed and was rolled back: {exc}") from exc
