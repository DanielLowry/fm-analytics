# Phase 05 — Joint tactic and XI selection

## Planning status

MVP-defined. Solver choice and exact constraint weights follow the Phase 04
baseline and real squad scenarios.

## Outcome

Recommend an opponent-neutral tactical template, legal starting XI, and
substitutes by evaluating the supported tactics and player assignments jointly.
The result accounts for role suitability and today's availability, condition,
match sharpness, and positional familiarity. It remains an explainable decision
aid, not an automatic team-submission system.

## Prerequisites

- Versioned role scores, tactic templates, and weakness model from Phase 04
- Reliable injury, suspension, condition, sharpness, and position observations
- A stored capture that makes each recommendation reproducible

## Subphases

### 05.1 — Availability and eligibility

Define hard exclusions versus soft concerns for injuries, suspensions,
registration, condition, sharpness, and position familiarity. Record the reason
when a player or tactic/slot assignment is unavailable.

### 05.2 — Fixed-tactic baseline selector

Build a deterministic greedy or exhaustive XI selector for one tactic. This
tests slot, uniqueness, eligibility, bench, and objective semantics before
comparing tactics or adopting an optimisation library.

### 05.3 — Joint tactic/XI evaluation

Run the same valid-assignment process for every supported template and define a
versioned, comparable team objective. Keep tactical fit, intrinsic role quality,
current readiness, and hard constraints as separately explainable components.
Do not claim that a small score difference proves one football philosophy is
universally superior.

### 05.4 — Constrained optimiser

Maximize the versioned team objective subject to eleven unique players, filled
slots, eligibility, and configured readiness rules. Add bench coverage,
rotation, youth, congestion, and tactical-balance preferences one at a time
only when they have explicit semantics and tests.

### 05.5 — Alternatives and explanation

Return the chosen tactic and XI, substitutes, binding constraints, excluded
players, marginal swaps, and several near-optimal tactic/XI alternatives.
Explain why the top eleven individual player scores may not form the best valid
team and why another formation may make better use of the squad.

### 05.6 — Scenario evaluation

Test injuries, fatigue, suspension, rotated cup teams, changed readiness
thresholds, and deliberately infeasible inputs. Compare with simple fixed-tactic
and strongest-player baselines, and record recommendation stability under small
input changes.

## Phase exit criteria

- At least three baseline tactics produce or explicitly fail to produce valid
  eleven-player assignments for the same stored capture.
- The recommendation includes a formation, mentality, roles, duties, supported
  instructions, starting XI, and explainable substitutes.
- Every recommendation is reproducible and has a feasible/infeasible status.
- Hard constraints, intrinsic role fit, and readiness preferences are
  distinguishable in output.
- Alternative tactic/XI combinations and marginal decisions are explainable.
- The selector beats or meaningfully clarifies the documented simple baselines.

## Deferred

- Opposition-specific tactic selection or adjustments
- Automatic application of a lineup or tactic inside FM
- Learned player-performance objectives
- Complex promises/happiness modelling until trustworthy data exists
