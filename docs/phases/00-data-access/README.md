# Phase 00 — Prove FM20 data access

## Outcome

From Python, print the current date, human-controlled club, and first-team squad
from a running FM20 save. The path must be repeatable, read-only, and explicit
about what has and has not been verified as manager-visible.

This is the principal feasibility gate. Until it passes, the fixture remains
the development source and later phases remain planning work.

## Prerequisites

- A supported Windows environment with FM20 and a test save
- Exact game/database build recorded
- A pinned candidate memory-reading framework or fork
- .NET SDK/runtime compatible with that framework
- The fixture-backed bridge and Python client in this repository

## Subphases

| ID | Subphase | Status | Result |
| --- | --- | --- | --- |
| 00.1 | [Environment baseline](00.1-environment-baseline.md) | In progress | A reproducible test matrix and pinned dependencies |
| 00.2 | [Process attachment](00.2-process-attachment.md) | In progress | Safe detection and attachment with useful failures |
| 00.3 | [Game context](00.3-game-context.md) | In progress | Live date, manager, and controlled club |
| 00.4 | [Squad extraction](00.4-squad-extraction.md) | Not started | Stable first-team identities and basic fields |
| 00.5 | [End-to-end validation](00.5-end-to-end-validation.md) | Not started | Live FM20 → bridge → Python proof |

## Phase exit criteria

- Starting the system before FM20 or before a save produces a clear recoverable
  status, not a crash.
- `/game` returns live date, manager, and club data.
- `/squad` returns stable IDs, names, positions, and a deliberately limited set
  of safe fields.
- Advancing the save changes subsequent responses without restarting FMBridge.
- The Python CLI prints the live squad through HTTP.
- At least two runs after a clean restart produce the same identities.
- No write operation against FM memory is present or required.
- Environment versions, limitations, and sanitized evidence are documented.

## Non-goals

- A comprehensive entity API
- General scouting-knowledge support
- Persistence, analytics, optimisation, or a UI
- Supporting multiple FM editions or patches

## Key risks

- The extraction framework may target a different FM20 executable or database
  revision.
- Pointers or object wrappers may become stale when the game advances.
- Apparent attributes may be underlying truth rather than manager knowledge.
- Identifiers may not remain stable across reloads.
