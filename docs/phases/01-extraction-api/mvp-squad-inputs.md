# MVP squad-input inventory

## Purpose

Identify the smallest live, manager-visible squad projection required to build
the first opponent-neutral tactic, XI, and weakness recommendations. A field
being useful does not authorize reading it: unresolved visibility remains a
hard extraction block.

The first selection universe is the controlled club's first-team squad. Reserve
and youth expansion can be added when it has an explicit selection use case and
verified collection semantics.

## Current live coverage

| Input | MVP use | Current state | Next evidence/action |
| --- | --- | --- | --- |
| Player ID and name | Identity and explanations | Proven live and reload-stable in Phase 00 | Retain as opaque strings |
| First-team membership | Selection universe | Proven live for the Phase 00 save | Complete the deferred temporary membership-change soak |
| Date of birth and age | Context and later squad planning | Implemented and observed live | Retain nullable date/integer semantics |
| Position labels | Slot eligibility | Natural/accomplished labels implemented and observed live | Use labels only; do not expose raw familiarity precision |
| Condition | Current readiness | Visible whole-number percentage implemented and observed live | Keep separate from role quality |
| Match fitness/sharpness | Current readiness | Visible whole-number percentage implemented and observed live | Confirm display naming used in reports |
| Injury and suspension | Hard/soft availability constraints | Extraction implemented; controlled positive live cases not yet recorded | Verify injured, suspended, and combined scenarios |
| Derived availability | Selection constraint and explanation | Implemented from the visible flags above | Keep the string vocabulary open |
| Contract and owning club | Explain loans; later squad planning | Implemented, including a live loan case | Not required for initial XI scoring |
| Playing attributes | Role suitability and tactic fit | V1 shape proven with fixtures; live adapter intentionally returns an empty map | Blocking visibility research: map only manager-visible exact/range/unknown observations |

## Required attribute capability

The football model needs the manager-visible playing-attribute panels for both
outfield players and goalkeepers. Phase 04 role configuration will select the
actual weighted subset; the extraction contract should not hard-code tactical
weights or manufacture a universal player rating.

For owned players, research must prove whether each displayed attribute comes
from the same manager-knowledge representation used by the UI. For later
external candidates, the same public observation shape must support exact,
ranged, and unknown values without ever carrying hidden truth.

Until that mapping is proven, an empty attribute map means `not supplied by this
source`; it must never be interpreted as zero ability or as a fully unknown
scouting report.

## Explicitly deferred from the first scoring slice

- opposition attributes, tendencies, or matchup adjustments;
- raw numeric position familiarity;
- hidden condition, fitness, injury-risk, CA, PA, or personality values;
- morale, happiness, promises, dynamics, and training load;
- match-performance history and learned weights;
- reserves, youth, and external-player enumeration;
- detailed cost and transfer-attainability modelling.

These can enter only through a later documented use case and visibility owner.

## Gate into squad analytics

Before Phase 04 scoring begins, the stored/live domain must provide:

- stable first-team identities and position labels;
- condition, match fitness/sharpness, and availability with verified semantics;
- manager-visible attribute observations for the supported role catalogue;
- a coherent capture date and source/contract version; and
- fixtures covering normal, nullable, ranged, unknown, and unavailable cases
  without hidden-value leakage.
