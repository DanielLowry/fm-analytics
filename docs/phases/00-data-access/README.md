# Phase 00 — Prove FM20 data access

## Outcome

From Python, print the current date, human-controlled club, and first-team squad
from a running FM20 save. The path must be repeatable, read-only, and explicit
about what has and has not been verified as manager-visible.

This was the principal feasibility gate. It closed on 10 September 2026 after
the complete path ran against the live save and reattached following a real FM
process restart.

## Prerequisites

- The recorded x86-64 Linux/Proton environment with FM20 and a test save
- Exact game/database build recorded
- A pinned candidate memory-reading framework or fork
- .NET SDK/runtime compatible with that framework
- The fixture-backed bridge and Python client in this repository

## Subphases

| ID | Subphase | Status | Result |
| --- | --- | --- | --- |
| 00.1 | [Environment baseline](00.1-environment-baseline.md) | Complete | Reproducible matrix and pinned toolchain |
| 00.2 | [Process attachment](00.2-process-attachment.md) | Complete | Safe detection, bounded reads, recovery, useful failures |
| 00.3 | [Game context](00.3-game-context.md) | Complete | Live date, manager, club, and reload-stable identity |
| 00.4 | [Squad extraction](00.4-squad-extraction.md) | Complete | 17 reload-stable identities and safe basic fields |
| 00.5 | [End-to-end validation](00.5-end-to-end-validation.md) | Complete | Live FM20 → bridge → Python, failure, and restart proof |
| 00.6 | [Basic live monitor](00.6-basic-monitor.md) | Complete | Bridge-backed inspection, refresh, and safe downloads |

## Phase exit criteria

- Starting the system before FM20 or before a save produces a clear recoverable
  status, not a crash.
- `/game` returns live date, manager, and club data.
- `/squad` returns stable IDs, names, positions, and a deliberately limited set
  of safe fields.
- Each uncached observation starts a fresh probe rather than retaining FM
  pointers; dynamic source transitions work without restarting FMBridge.
- The Python CLI prints the live squad through HTTP.
- At least two runs after a clean restart produce the same identities.
- No write operation against FM memory is present or required.
- Environment versions, limitations, and sanitized evidence are documented.

## Current acceptance record

On 10 September 2026, the live path returned the active human manager,
Hungerford Town, game date `2019-06-24`, and 17 unique first-team player IDs.
The Python CLI printed the same 17 players through FMBridge, including a loan
whose contracted club differs from the squad club. Restarting FMBridge and
repeating the queries produced the same date, manager, club, count, and IDs.

FM was then closed while FMBridge remained available. Health changed to
`game_absent`; after FM and the same save were loaded again, that bridge process
returned to `ready`. A strict comparison confirmed the same manager, club,
date, and exact set of 17 player IDs.

At the user's preference, the test did not advance the save or alter the team.
A controlled source transition proves that the bridge does not retain stale
results, and the live probe starts afresh after its one-second cache. An actual
in-game date and membership mutation is retained as a later Phase 01 hardening
test rather than blocking either this feasibility gate or the manually
triggered early-game MVP.

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
