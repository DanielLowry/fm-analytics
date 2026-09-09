# Phase 04 — Squad analytics

## Planning status

Provisional. The outcome and evaluation principles are stable, but specific
roles, weights, and report layouts should be decided from real Phase 02–03 data.

## Outcome

Produce transparent player-role suitability and squad-depth reports using only
permitted observations. A manager should be able to see not just a rank, but
why it exists and how uncertainty could change it.

## Prerequisites

- Reliable current/historical squad queries
- Approved visibility policy for every scoring input
- Position and attribute naming normalized in the Python domain

## Subphases

### 04.1 — Role catalogue

Define a small initial set of positions/roles and duties, their eligibility
rules, required versus desirable attributes, and config versioning. Start with
one formation's roles rather than encoding the entire FM role catalogue.

### 04.2 — Deterministic scoring engine

Implement normalized, configurable weighted scores with tests for missing and
ranged observations. Preserve score version, inputs, uncertainty policy, and
component contributions. Avoid false precision in displayed results.

### 04.3 — Player comparison

Compare candidates for the same role using total score, contribution breakdown,
best/worst bounds, availability context, and material trade-offs. Do not merge
fitness or selection constraints into intrinsic role quality.

### 04.4 — Squad-depth model

Map the squad across roles, allow one player to cover several roles, expose
thin or low-quality areas, and distinguish nominal coverage from simultaneous
coverage. Show the impact of injuries or exclusions as scenarios.

### 04.5 — Report and expert review

Deliver CLI/report views, compare output with human football judgment, record
surprising rankings, and adjust weights only through versioned changes with a
rationale. Establish naive baselines for later learned models.

## Phase exit criteria

- At least one useful tactical shape has complete, versioned role definitions.
- Rankings are deterministic and reproducible from a stored capture.
- Known/ranged/unknown inputs are visible in explanations.
- A depth report identifies coverage and simultaneous-coverage weaknesses.
- Expert review examples and sensitivity tests expose obviously brittle weights.

## Deferred

- Selecting a jointly valid XI (Phase 05)
- Pricing transfer targets (Phase 06)
- Learning role weights from match performance (Phase 10)
- A comprehensive catalogue of every FM role

## Decisions to revisit before implementation

- Whether FM20 role definitions can be represented generically enough to share
  attribute normalization across positions
- How much position familiarity should constrain versus score suitability
- Which uncertainty policy is appropriate for owned players with unexpected
  missing observations

