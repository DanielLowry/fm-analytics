# Phase 02 — Snapshot persistence

## Outcome

Persist reproducible observations from FMBridge in a local SQLite database so
the system can compare game state over time without confusing observations with
current truth.

## Prerequisites

- Phase 01 contract and error semantics are stable enough to ingest
- Entity identifiers have known stability limits
- Every ingested field has at least a provisional visibility classification

## Subphases

| ID | Subphase | Result |
| --- | --- | --- |
| 02.1 | [Observation model](02.1-observation-model.md) | Clear temporal and identity semantics |
| 02.2 | [SQLite schema](02.2-sqlite-schema.md) | Migrated normalized storage for initial resources |
| 02.3 | [Importer](02.3-importer.md) | Idempotent capture of coherent snapshots |
| 02.4 | [Queries and provenance](02.4-queries-and-provenance.md) | Reproducible current and historical reads |
| 02.5 | [Operations and validation](02.5-operations-and-validation.md) | Backup, migration, and data-quality checks |

## Phase exit criteria

- Importing the same bridge observation twice does not create a false change.
- Current and historical squad state can be queried as of an in-game date and
  capture event.
- Attribute visibility and ranges survive a round trip unchanged.
- Every snapshot records source/contract version and capture provenance.
- Schema creation, upgrade, backup, and restore have automated tests or a
  documented repeatable check.
- The database contains no field that the public bridge contract forbids.

## Non-goals

- A warehouse optimized for ML
- Cloud or multi-user database operation
- Deriving conclusions during ingestion
- Treating repeated polling as match-event capture

