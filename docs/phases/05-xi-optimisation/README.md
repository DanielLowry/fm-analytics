# Phase 05 — Starting-XI optimisation

## Planning status

Provisional. Solver choice and exact constraints should wait for real squad,
availability, and role data.

## Outcome

Recommend a legal, explainable starting XI for a selected tactical shape while
accounting for role suitability and current availability. The first version is
a decision aid, not an automatic team submission system.

## Prerequisites

- Versioned role scores and squad-depth model from Phase 04
- Reliable injury, suspension, fitness, and position observations
- A stored capture that makes each recommendation reproducible

## Subphases

### 05.1 — Formation and slot model

Represent a small set of formations as eleven typed slots with roles/duties,
positional eligibility, and any structural rules. Separate the abstract shape
from the player assignment.

### 05.2 — Availability and eligibility

Define hard exclusions versus soft concerns for injuries, suspensions,
registration, fitness, sharpness, and position familiarity. Record the reason
when a player cannot occupy a slot.

### 05.3 — Baseline selector

Build a deterministic greedy or exhaustive baseline for one formation. This
tests data and objective semantics before adopting an optimisation library.

### 05.4 — Constrained optimiser

Maximize a versioned team objective subject to eleven unique players, filled
slots, eligibility, and configured fitness rules. Add rotation, youth,
congestion, and tactical-balance constraints one at a time only when measurable.

### 05.5 — Alternatives and explanation

Return the chosen XI, binding constraints, excluded players, marginal swaps,
and several near-optimal alternatives. Show why the top eleven individual
scores may not form the best valid team.

### 05.6 — Scenario evaluation

Test injuries, fatigue, rotated cup teams, changed formations, and deliberately
infeasible inputs. Compare with simple baselines and record recommendation
stability under small input changes.

## Phase exit criteria

- One or more formations produce valid eleven-player assignments.
- Every recommendation is reproducible and has a feasible/infeasible status.
- Hard constraints and soft preferences are distinguishable in output.
- Alternative lineups and marginal decisions are explainable.
- The optimiser beats or meaningfully clarifies the documented baseline.

## Deferred

- Opposition-specific tactics
- Automatic application of a lineup inside FM
- Learned player-performance objectives
- Complex promises/happiness modelling until trustworthy data exists

