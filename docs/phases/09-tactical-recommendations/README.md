# Phase 09 — Opposition-specific tactical recommendations

## Planning status

Outline only. The available match history, opposition visibility, and evaluation
signal must be learned from earlier phases before detailed design.

## Outcome

Start from the Phase 05 opponent-neutral tactic and XI, then recommend a small
set of explainable changes for a specific fixture. A matchup recommendation may
retain the baseline unchanged when evidence is weak.

Baseline squad-fit tactic selection belongs to Phases 04–05 and is already part
of the MVP; this phase must not rebuild it.

## Prerequisites

- Valid baseline tactic/XI recommendations from Phase 05
- Opposition reports with calibrated confidence
- Historical actual tactics and outcomes
- Versioned representations of the supported FM20 tactical settings

## Subphases

### 09.1 — Adjustment vocabulary

Extend the Phase 04 tactic model with a deliberately small set of valid
formation, mentality, role/duty, team-instruction, and opposition-instruction
changes. Encode incompatibilities and the distance from baseline.

### 09.2 — Explicit matchup rules

Implement transparent expert rules. State the evidence and confidence required
for each change and prefer no change when the threshold is not met.

### 09.3 — Joint matchup feasibility

Re-evaluate player assignments when an adjustment changes roles or shape.
Reject or relax infeasible recommendations explicitly rather than returning an
attractive but unselectable setup.

### 09.4 — Matchup scoring

Score candidate adjustments using our baseline strengths, opponent tendencies,
venue, availability, and uncertainty. Keep descriptive inputs separate from
normative weights and retain counterfactual alternatives.

### 09.5 — Recommendation and explanation

Return the resulting setup, decisive evidence, confidence, trade-offs,
alternatives, and an explicit diff from the baseline tactic/XI. Avoid changing
many instructions when evidence supports only one adjustment.

### 09.6 — Outcome evaluation

Record whether the recommendation was followed, the actual setup, result and
process metrics, and confounders. Compare against the Phase 05 baseline and
simple-rule policies before introducing learned policies.

## Phase exit criteria

- Recommendations always form a valid FM20 setup within the supported subset.
- Every change from the Phase 05 baseline has a reason and confidence level.
- Weak evidence can produce an explicit `no adjustment` recommendation.
- Actual, baseline, and matchup-recommended tactics are not conflated.
- Backtests are time-correct and comparisons include the opponent-neutral
  baseline.

## Deferred

- Automatic interaction with the FM interface
- Real-time touchline advice
- Claims that observed tactical correlations are causal
- Large tactical search spaces without sufficient evaluation data
