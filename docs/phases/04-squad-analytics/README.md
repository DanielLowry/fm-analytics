# Phase 04 — Squad model and baseline tactics

## Planning status

MVP-defined. Exact roles, weights, and tactic templates are selected from the
first real Phase 02–03 captures and then versioned.

## Outcome

Explain player-role suitability, how well the squad supports a small catalogue
of baseline tactics, and where first-choice quality or depth is weak. A manager
should see not just a rank, but why it exists and how uncertainty, availability,
or a different supported shape changes the conclusion.

This phase defines and scores baseline tactical options. It does not yet choose
the jointly optimal tactic and eleven-player assignment; Phase 05 does that.

## Prerequisites

- Reliable current and stored squad queries
- Approved visibility policy for every scoring input
- Position, attribute, availability, condition, and sharpness naming normalized
  in the Python domain

## Subphases

### 04.1 — Role catalogue

Define the roles and duties required by the first supported tactics, their
positional eligibility, required versus desirable attributes, and config
versioning. Encode only what the initial templates consume rather than the
entire FM20 role catalogue.

### 04.2 — Baseline tactic catalogue

Define three to five complete, coherent FM20 tactic templates that cover
materially different squad shapes. Each template specifies formation slots,
roles, duties, mentality, a small compatible instruction set, structural rules,
and an explanation of the intended style.

These are opponent-neutral starting points. The catalogue should be data/config,
not hard-coded across the scoring implementation.

### 04.3 — Deterministic suitability scoring

Implement normalized, configurable weighted role scores with tests for exact,
ranged, and unknown observations. Preserve score version, inputs, uncertainty
policy, lower/central/upper results, and component contributions. Do not merge
current condition, sharpness, or selection eligibility into intrinsic role
quality.

### 04.4 — Player comparison

Compare candidates for the same role using score bounds, contribution
breakdowns, position familiarity, current availability context, and material
trade-offs. Prevent less-scouted or missing data from creating an artificial
advantage.

### 04.5 — Tactic-aware depth and weakness model

Map the squad across every supported template, allowing one player to cover
several roles while distinguishing nominal coverage from simultaneous
coverage. Report separately:

- weak likely starters;
- inadequate backups;
- conflicts where one player is the best cover for multiple simultaneous slots;
- temporary gaps caused by injury, suspension, condition, or sharpness; and
- weaknesses created or avoided by choosing another supported tactic.

Turn material structural gaps into draft recruitment briefs with the tactic,
role, required improvement, and reason retained.

### 04.6 — Report and expert review

Deliver CLI/report views, compare output with human football judgment, record
surprising rankings, and adjust weights only through versioned changes with a
rationale. Establish simple baselines for later optimisation and learning.

## Phase exit criteria

- At least three materially different baseline tactics have complete,
  versioned roles, duties, instructions, and slot definitions.
- Rankings are deterministic and reproducible from a stored capture.
- Exact, ranged, and unknown inputs remain visible in score explanations.
- Condition, sharpness, availability, familiarity, and intrinsic role quality
  remain distinguishable.
- A tactic-aware depth report identifies first-choice, backup,
  simultaneous-coverage, and temporary weaknesses.
- Each material weakness can produce a traceable draft recruitment brief.
- Expert review examples and sensitivity tests expose obviously brittle weights.

## Deferred

- Selecting the tactic and jointly valid XI (Phase 05)
- Searching and pricing transfer targets (Phase 06)
- Opposition-specific tactical adjustments (Phases 08–09)
- Learning role weights from match performance (Phase 10)
- A comprehensive catalogue of every FM20 role and instruction

## Decisions to settle from real data

- The first three to five tactical templates and how different they must be to
  provide a meaningful comparison
- How position familiarity constrains eligibility versus reducing suitability
- How owned-player missing observations affect ranking and explanation
- Whether condition and sharpness should be hard selection thresholds or
  versioned soft penalties in Phase 05
