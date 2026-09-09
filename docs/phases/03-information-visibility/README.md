# Phase 03 — Information visibility

## Outcome

Establish and enforce a tested policy for what the human manager can know. The
Python application and database receive only manager-visible observations,
including uncertainty, provenance, and staleness where those concepts matter.

This is a governance and data-correctness phase, not merely a different JSON
shape. It is the gate for analytics involving players outside our club.

## Prerequisites

- Phase 00 has located candidate knowledge/scouting structures
- Phase 01 can expose allowlisted visibility-aware fields
- Phase 02 preserves observation time and uncertainty
- Test saves can exercise different scouting and knowledge levels

## Subphases

| ID | Subphase | Result |
| --- | --- | --- |
| 03.1 | [Knowledge taxonomy](03.1-knowledge-taxonomy.md) | Defined states and field-level policy |
| 03.2 | [FM representation research](03.2-fm-representation-research.md) | Evidence mapping FM structures to visible UI |
| 03.3 | [Boundary enforcement](03.3-boundary-enforcement.md) | Hidden truth cannot cross FMBridge |
| 03.4 | [Uncertainty model](03.4-uncertainty-model.md) | Analytics-safe ranges, absence, and staleness |
| 03.5 | [Verification corpus](03.5-verification-corpus.md) | Repeatable cases across knowledge levels |
| 03.6 | [Visibility audit](03.6-visibility-audit.md) | Release gate and ongoing regression process |

## Phase exit criteria

- Field-level policy covers our players, known opposition, partially scouted
  players, unscouted players, injuries, fitness, reports, and contextual data
  used by the next phases.
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

