# Phase 09 — Tactical recommendation engine

## Planning status

Outline only. The tactical action space, available observations, and evaluation
signal must be learned from earlier phases before detailed design.

## Outcome

Recommend an explainable tactical setup for a specific fixture, including the
formation, player assignments, and a small set of high-confidence adjustments.

## Prerequisites

- Valid lineup optimisation
- Opposition reports with calibrated confidence
- Historical actual tactics and outcomes
- Versioned representations of the FM20 tactical settings in scope

## Subphases

### 09.1 — Tactical action vocabulary

Represent a deliberately small, valid subset of formations, mentalities, roles,
duties, team instructions, and opposition instructions. Encode incompatibilities
without attempting every possible FM combination.

### 09.2 — Baseline tactical policies

Implement explicit expert rules and fixed-tactic baselines. State the evidence
and confidence required for an opposition-specific adjustment.

### 09.3 — Joint squad/tactic feasibility

Combine tactical choices with available-player constraints. Reject or relax
infeasible recommendations explicitly rather than returning an attractive but
unselectable setup.

### 09.4 — Matchup scoring

Score candidate setups using our strengths, opponent tendencies, venue,
availability, and uncertainty. Keep descriptive inputs separate from normative
weights and retain counterfactual alternatives.

### 09.5 — Recommendation and explanation

Return the selected setup, expected trade-offs, decisive evidence, confidence,
alternatives, and changes from the team's baseline tactic. Avoid changing many
instructions when evidence supports only one adjustment.

### 09.6 — Outcome evaluation

Record whether the recommendation was followed, the actual setup, result and
process metrics, and confounders. Compare against fixed-tactic and simple-rule
baselines before introducing learned policies.

## Phase exit criteria

- Recommendations always form a valid FM20 setup within the supported subset.
- Every change from baseline has a reason and confidence level.
- Actual and recommended tactics are never conflated in evaluation.
- Backtests are time-correct and comparisons include simple baselines.

## Deferred

- Automatic interaction with the FM interface
- Real-time touchline advice
- A claim that observed tactical correlations are causal
- Large tactical search spaces without sufficient evaluation data

