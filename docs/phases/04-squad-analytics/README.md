# Phase 04 — Squad model and baseline tactics

## Planning status

In progress. Deterministic role scoring, a data-backed catalogue, role matrix,
tactic-aware weaknesses, and squad-wide depth are implemented. Football
calibration and expert review remain open.

## Implemented MVP slice

The Python analytics boundary now provides versioned role definitions and
weighted scoring with lower, central, and upper results. It preserves every
input observation and contribution, treats omitted inputs as unknown, orders
information gaps by their possible effect, and uses a deliberately conservative
central value for unknown attributes so missing knowledge cannot improve a
player's ranking.

Candidate comparison uses conservative central ranking and only calls a winner
interval-certain when its lower bound beats every alternative's upper bound.
Where plausible candidates overlap, uncertain inputs are returned in order of
their maximum effect on the role score. This is the first reusable `scout more`
primitive; it does not yet claim that the external candidates themselves are
safe to enumerate.

Position eligibility is exposed separately and condition, sharpness, injury,
and suspension are not accepted by the intrinsic role scorer. This preserves
the distinction needed by the eventual XI selector between player quality,
positional fit, current readiness, and availability.

The current catalogue (`fm20-expanded-tactics-v1`) contains 28 roles and 25
materially different opponent-neutral templates. It is loaded from versioned
JSON, with eleven slots, mentality, instructions, structural requirements, and
explicit per-slot role alternatives. These remain provisional football
hypotheses; changes create a new catalogue version rather than silently
changing old recommendations.

The first direct live owned-squad recommendation showed why breadth matters:
the managed 17-player Hungerford squad had no left-sided wide player, so the
original wide templates produced partial XIs. A balanced 4-1-2-1-2 DM narrow
diamond then produced a legal live XI on 24 June 2019. The catalogue has grown
substantially since that run, so its 25-tactic output still needs fresh live
and expert review.

The first tactic-aware weakness pass now keeps starter quality, available
backup quality, structural gaps, temporary availability gaps, and shared
simultaneous cover as distinct findings. Thresholds are versioned independently
from the role catalogue. This is sufficient to form the first traceable weak
points; richer severity calibration remains. `weakness-v2` uses ratios against
the selected XI median and starter rather than fixed league-level cutoffs, so
it remains relative to this squad and is not a comparison with rival clubs.

## Outcome

Explain player-role suitability, how well the squad supports a small catalogue
of baseline tactics, and where first-choice quality or depth is weak. A manager
should see not just a rank, but why it exists and how uncertainty, availability,
or a different supported shape changes the conclusion.

This phase defines and scores baseline tactical options. Phase 05 owns the
joint tactic, role, and eleven-player search over those definitions.

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

These are opponent-neutral starting points. The catalogue is versioned JSON
loaded and validated by `analytics/catalogue.py`, rather than definitions
hard-coded across scoring code.

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

- Searching and pricing transfer targets (Phase 06)
- Opposition-specific tactical adjustments (Phases 08–09)
- Learning role weights from match performance (Phase 10)
- A comprehensive catalogue of every FM20 role and instruction

## Decisions to settle from real data

- Whether all 25 templates are materially distinct enough to justify their
  compute and comparison cost
- Whether the implemented continuous position-familiarity multiplier matches
  useful football judgment across the raw 1–20 range
- How owned-player missing observations affect ranking and explanation
- Whether condition and sharpness should be hard selection thresholds or
  versioned soft penalties in Phase 05
