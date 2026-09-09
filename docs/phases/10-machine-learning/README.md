# Phase 10 — Machine learning

## Planning status

Outline only. No model family or target metric is selected in advance. This
phase begins only when sufficient trustworthy labels exist and deterministic
baselines have known limitations.

## Outcome

Introduce calibrated, reproducible models where they demonstrably improve a
decision or forecast over transparent baselines without violating visibility or
temporal boundaries.

## Prerequisites

- Versioned historical observations and features
- Baselines and evaluation metrics for the chosen decision
- Enough independent data to estimate generalisation honestly
- Audited feature availability at prediction time

## Subphases

### 10.1 — Problem and value definition

Choose one bounded target—such as player match performance, outcome probability,
or development range—and state how better predictions change a decision. Define
the baseline, metric, calibration requirement, and minimum useful improvement.

### 10.2 — Dataset and leakage audit

Create point-in-time datasets from immutable observations. Check post-outcome
features, hidden-value leakage, repeated-player/save dependence, survivorship,
selection bias, and missingness semantics.

### 10.3 — Validation design

Use chronological and grouped splits appropriate to saves, seasons, clubs, and
players. Retain a genuine final holdout and report uncertainty, calibration,
and subgroup performance—not only aggregate accuracy.

### 10.4 — Baseline and candidate models

Start with naive and interpretable statistical models. Increase complexity only
when out-of-sample evidence justifies it. Preserve feature and hyperparameter
definitions with each run.

### 10.5 — Decision integration

Convert predictions into a versioned decision policy, including uncertainty and
abstention. Shadow-test learned output beside existing rules before it influences
recommendations.

### 10.6 — Monitoring and retraining

Track calibration, feature drift, missingness, adoption, and realized outcomes.
Define when to retrain, roll back, or stop using a model. A newer model is not
automatically the active model.

### 10.7 — Later candidate problems

Only after the first model passes its gate, consider tactical effectiveness,
role-weight learning, development forecasts, future contribution, transfer
value, and other targets separately. Each needs its own leakage and utility
review.

## Phase exit criteria

- A registered model beats its agreed baseline on untouched data and is
  acceptably calibrated.
- Training data can be rebuilt from versioned source observations.
- Predictions record model, feature, and input-capture versions.
- The system can abstain or fall back when inputs are out of distribution.
- Decision-level evaluation confirms usefulness, not just predictive lift.

## Deferred

- Deep learning by default
- Training on hidden attributes or outcomes unavailable at decision time
- Online reinforcement learning against the active save without a separate
  ethical/gameplay decision
- A single model intended to solve all football decisions

