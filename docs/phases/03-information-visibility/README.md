# Phase 03 — Information visibility

## Outcome

Establish and enforce a tested policy for which players the human manager can
discover and what the manager knows about each one. The Python application and
database receive only manager-visible observations, including uncertainty,
provenance, and staleness where those concepts matter.

This is a governance and data-correctness phase, not merely a different JSON
shape. It is the gate for analytics involving players outside our club.

## Prerequisites

- Phase 00 has proved safe live reads on the supported environment
- Phase 01 can expose allowlisted visibility-aware fields
- Phase 02 preserves observation time and uncertainty
- Test saves can exercise different scouting and knowledge levels

## Subphases

| ID | Subphase | Result |
| --- | --- | --- |
| 03.1 | [Knowledge taxonomy](03.1-knowledge-taxonomy.md) | Entity-discoverability states and field-level policy |
| 03.2 | [FM representation research](03.2-fm-representation-research.md) | Evidence mapping player-search and knowledge structures to visible UI |
| 03.3 | [Boundary enforcement](03.3-boundary-enforcement.md) | Hidden players and hidden field truth cannot cross FMBridge |
| 03.4 | [Uncertainty model](03.4-uncertainty-model.md) | Analytics-safe ranges, absence, and staleness |
| 03.5 | [Verification corpus](03.5-verification-corpus.md) | Repeatable cases across knowledge levels |
| 03.6 | [Visibility audit](03.6-visibility-audit.md) | Release gate and ongoing regression process |

## Phase exit criteria

- Field-level policy covers our players, known opposition, partially scouted
  players, unscouted players, injuries, fitness, reports, and contextual data
  used by the next phases.
- A paginated candidate collection enumerates all and only players legitimately
  discoverable by the manager for controlled verification saves, with a
  traceable inclusion reason and coherent snapshot semantics.
- Direct player lookup cannot reveal a player outside that approved universe.
- Bridge mapping is derived from manager-knowledge structures, not hidden truth
  relabelled after reading.
- UI comparisons validate exact, ranged, unknown, stale, and not-applicable
  cases.
- Contract, persistence, logging, fixtures, and tests have passed a leakage
  audit.
- Analytics APIs force callers to acknowledge uncertainty instead of silently
  converting it to an exact value.

## Non-goals

- Solving uncertainty with one universal midpoint
- Inferring hidden PA/CA or personality variables from memory
- Guaranteeing identical visibility semantics across other FM editions
- Recruitment rankings; this phase only makes them safe to build
- Deciding that every player object reachable in memory is manager-visible
