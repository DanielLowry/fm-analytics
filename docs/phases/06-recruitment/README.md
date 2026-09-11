# Phase 06 — Recruitment and squad planning

## Planning status

In progress through the first uncertainty-aware shortlist. Rich cost,
contract, development, and exit planning remain provisional extensions.

## Outcome

Turn a tactic-aware squad weakness into a reproducible recruitment brief and
rank legitimately discoverable players who may improve it. Candidate quality,
knowledge uncertainty, current-squad comparison, cost, and risk remain separate
and explainable.

The MVP must identify when further scouting could change the decision. It must
not imply that a partially known estimate is an exact player rating.

## Implemented MVP slice

Actionable tactic weaknesses can now become position/role recruitment briefs
with a starter or depth threshold. A shortlist scorer accepts only players
already present in the manager-visible export, filters by visible position, and
keeps candidates whose observed lower bound meets the threshold or whose upper
bound could still meet it. The latter are labelled
`possible_with_more_scouting` and carry the role attributes to investigate.
Players below even their optimistic bound are excluded.

Candidate exports must now be accompanied by the result count visible in FM.
Recruitment fails unless the merged export contains exactly that many unique
UIDs. This closes silent pagination/row-loss failures, while real FM20 export
verification, persistence, and cost/attainability remain before recruitment is
complete.

## Prerequisites

- Phase 03 defines and enforces the discoverable-player universe and permissible
  candidate fields
- Phase 04 produces tactic-aware weaknesses and role suitability intervals
- Phase 05 can evaluate how a candidate could change a valid tactic/XI result
- Any cost or contract field used has verified visibility, units, currency, and
  observation-time semantics

## MVP subphases

### 06.1 — Recruitment brief

Turn first-choice quality, depth, simultaneous-coverage, and temporary-gap
findings into explicit briefs. A brief records the tactic/template, role,
horizon, current benchmark, minimum useful improvement, applicable constraints,
and risk tolerance. Temporary availability alone should not automatically
become a permanent recruitment need.

### 06.2 — Candidate universe

Read candidates only from the Phase 03 manager-discoverable collection. Track
why and when each candidate was included, use bounded pagination and coherent
captures, and prevent arbitrary lookup of hidden database players.

Candidate generation may apply visible filters for position, age, geography,
contract, or affordability, but it must retain enough provenance to explain why
a player was considered or excluded.

### 06.3 — Quality under uncertainty

Score candidates for the brief with the same versioned role model used for the
squad. Report lower, central, and upper suitability estimates, the named policy
behind any central estimate, comparison with the current player/depth threshold,
and the observations driving the range.

Recommend `scout more` when plausible values for consequential unknowns could
materially change whether the candidate is an improvement or reorder the
shortlist. Name the fields that would be most valuable to resolve. Do not direct
scouting merely because any value is unknown.

The MVP cut line is reached when 06.1–06.3 can produce a useful shortlist from
a live-derived stored capture.

## Post-MVP subphases

### 06.4 — Cost and attainability

Normalize visible fee ranges, wages, bonuses, contract duration, agent costs,
loan terms, and currency. Separate reported or estimated cost from an actual
negotiated offer and model affordability over an agreed horizon.

### 06.5 — Risk and future value

Introduce transparent heuristics for age curve, visible injury record,
adaptation, playing-time fit, resale horizon, and information uncertainty. Do
not infer hidden potential ability.

### 06.6 — Retention, contracts, and exits

Apply the same role need, cost, horizon, and uncertainty framework to existing
players. Identify contract decisions, sale/loan candidates, succession risks,
and the opportunity cost of retaining a player. Treat market interest and sale
price as uncertain observations, not guaranteed proceeds.

### 06.7 — Development versus acquisition

Compare buying with internal development, retraining, promotion, or delaying
the decision. Use observed development history and planned playing time without
claiming access to hidden potential ability.

### 06.8 — Decision record

Show Pareto trade-offs and scenario sensitivity, record decisions/outcomes for
later evaluation, and include a `do nothing/develop internally` baseline.

## MVP exit criteria

- A stored tactic-aware recruitment brief produces a reproducible shortlist.
- Candidate inclusion is traceable to legitimate manager discoverability.
- Direct lookup and collection behavior cannot expose an undiscoverable player.
- Each candidate is compared with the current squad benchmark using role-score
  bounds; any central estimate names its uncertainty policy.
- Reports expose dominant unknowns and targeted next scouting actions when
  resolving them could change the decision.
- A less-scouted player gains neither an automatic advantage nor an unjustified
  exact ranking.

## Full-phase exit criteria

- Quality, cost, uncertainty, attainability, and risk remain separate before
  any combined decision rule.
- Contract, exit, and internal-development alternatives can be compared with a
  purchase without being forced into one opaque score.
- Historical recommendations can be compared with later contribution and cost.

## Deferred beyond this phase

- Automated scouting assignments, bids, or negotiations
- Claims about potential based on hidden PA
- Learned resale/development models before Phase 10
- A universal scalar `value score` unless its trade-offs are demonstrably useful
