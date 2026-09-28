# Medium task: squad capture upgrade path

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)). Old
review item 3.1. The live read is the working source, so this was not urgent.

**Prerequisite:** the active plan schedules this item, and a reviewer settles
the baseline decision below.

## Why we are doing this

`persistence/store.py::SnapshotStore` is at `SCHEMA_VERSION = 4`.
`initialize()` raises a bare `RuntimeError("unsupported snapshot schema
version …")` for any other version, so `--snapshot-db` on an older capture
simply fails. A format change has already left the only real capture
unreadable once. The player-knowledge store shows the pattern that avoids this.

## Scope

- An ordered migration list for the squad capture store, a consistent backup
  before migrating, atomic per-step application, and a refusal to open a newer
  or unrelated file. Copy `persistence/player_knowledge.py` (`MIGRATIONS`,
  `initialize`, `_apply`).
- A typed error carrying the file path and the recovery action, caught by the
  CLI and web entry points and printed plainly instead of a traceback.

## High-level change outline

1. Recover the schema history. `SCHEMA_VERSION` changed in commits `f41d6c5`,
   `41707ad`, `a9f5bbc` and `d67ab4d`. The review records that v2 to v3 added
   a nullable `team_marker` column.
2. Existing v4 files must keep opening. A fresh file must still be created at
   the latest version.
3. Add the backup, the atomic steps and the typed error.
4. Tests: injected extra step, backup created, failed step rolled back, newer
   file refused, non-capture SQLite file refused, and older-than-baseline
   message.

## Decisions reserved for review

- Reconstruct steps from v1 so older files can be upgraded, or start the
  upgrade path at v4 and tell older files to re-capture.

## Success criteria

- A v4 capture opens unchanged, and a fresh database is identical to today's.
- An injected v5 step upgrades a v4 file, after a backup, atomically.
- Every refusal names the file and what to do.
- CI compile step, bridge smoke test and full suite pass.

## Likely code and tests

- `src/fm_analytics/persistence/store.py`
- `src/fm_analytics/cli.py` and `src/fm_analytics/web/providers.py` for the
  error message
- `tests/test_persistence.py`
