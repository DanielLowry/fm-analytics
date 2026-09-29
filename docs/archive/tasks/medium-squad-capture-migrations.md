# Medium task: squad capture upgrade path

> **Complete; archived 29 September 2026.** Built 29 September 2026. The
> *Status* section at the end records what was built and the decision taken.
> Open work is listed in the [task briefs index](../../tasks/README.md).

**Active-plan status:** parked (see [Parked](../../active-plan.md#parked)). Old
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

## Status

**Built 29 September 2026.** `persistence/store.py` now has a real upgrade
path instead of the bare `RuntimeError`:

- **Baseline decision:** started the upgrade path at v4 rather than
  reconstructing v1-v3. A squad capture is a read of the live game, not history
  that fades the way scouted attributes do (`player_knowledge.py`'s reason for
  keeping every version reachable), so an unreadable file is survivable by
  re-capturing. There is also no real v1-v3 file left to recover -- the only
  capture that broke on a schema change is already at v4 -- so reconstructing
  that history would be risk with no payoff. `BASELINE_VERSION = 4` in
  `store.py` documents this reasoning inline. A file older than the baseline is
  refused with a message naming the file and telling the manager to re-run the
  capture; it is never silently upgraded.
- **`SnapshotStoreError(RuntimeError)`** is the typed error, always naming the
  file and the recovery action: too new ("update the program"), the wrong kind
  of SQLite file, a failed-and-rolled-back migration, or older than the
  baseline ("re-run the capture").
- **`MIGRATIONS: tuple[str, ...] = ()`** is the append-only list of schema
  changes *after* the v4 baseline, mirroring `player_knowledge.py`'s pattern;
  `SnapshotStore(path, migrations=...)` accepts an override the same way, for
  tests. A fresh file is still built straight to the latest version in one
  step (`apply_migration` from `persistence/migrations.py`, reused rather than
  copied, targeting `BASELINE_VERSION - 1` so the jump from empty to v4 lands
  on the right version number).
- **Backup:** any file already at or past the baseline that needs to move
  further gets a whole-database backup (`<name>.bak-v<N>`, via SQLite's own
  backup API) before any step runs, exactly as `player_knowledge.py` does.
  Each step and its version bump apply atomically (`BEGIN; ...; PRAGMA
  user_version = N; COMMIT;`), rolled back and reported through
  `SnapshotStoreError` on failure.
- The squad-capture upgrade logic is *not* routed through
  `persistence.migrations.bring_up_to_date`: that function assumes version 0
  is real history to be replayed from an empty database, which is true for the
  player-knowledge and match-history stores but not here, where 1-3 are
  deliberately unreachable. A small `_bring_up_to_date` in `store.py` owns the
  baseline-aware version gating and reuses only the shared, version-agnostic
  `apply_migration` step-runner.
- **Web entry point:** `web/server.py::_build_provider` now calls
  `SnapshotStore(args.snapshot_db).initialize()` eagerly when `--snapshot-db`
  is given, converting `SnapshotStoreError` into `SystemExit(str(exc))` so an
  unreadable capture is refused in plain text at server startup, not on the
  first page load mid-request.
- **CLI entry point:** needed no new handling. `cli.py::main`'s existing top
  level `except (..., RuntimeError, ...)` already catches `SnapshotStoreError`
  by inheritance and prints `error: {exc}`, which already names the file and
  the action.
- Tests: `tests/test_persistence.py::SnapshotMigrationTests` (fresh file at
  baseline, idempotent re-initialise, an existing baseline file opens
  unchanged, an injected step backs up and upgrades, a failing migration rolls
  back and leaves the data usable, a newer file is refused untouched, an
  unrelated SQLite file is refused, and a pre-baseline file is refused with the
  re-capture message) and `tests/test_web_server.py::BuildProviderTests::test_an_unreadable_snapshot_db_is_refused_at_startup_not_first_request`.
  Full suite passes.
