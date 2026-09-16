# Phase 05 — Joint tactic and XI selection

## Planning status

In progress. A deterministic bounded joint role/player assignment engine now
evaluates each versioned tactic against the available squad. Exact constraint
weights and the role-system profiles still need football review against a
visibility-safe squad capture.

The engine assigns each eligible player to at most one of the eleven tactic
slots and chooses one permitted role/duty for that player/slot pairing. A
legacy template's fixed role is now its default member of a deliberately small
role family; future catalogue entries may declare their exact `roles` list per
slot. The bounded search is necessary because different role choices can have
the same local player score but materially different team effects. Injury,
suspension, explicit availability, and minimum readiness thresholds are hard
constraints. Condition and match fitness apply a separately versioned,
separately reported penalty; they never alter intrinsic role quality.

The current opponent-neutral **XI suitability** policy (`tactic-fit-v1`) scores
each possible XI from its eleven post-readiness player/role selection scores:

```text
tactic fit = 0.65 × mean(XI slots) + 0.35 × minimum(XI slots)
```

An unfilled slot contributes zero, so a partial XI cannot look strong just
because it omits a hard-to-fill position. The 35% weakest-slot weight is a
provisional preference, not a measured win-probability coefficient. It makes
one glaring mismatch more costly than a small increase in average quality:
ten slots scoring about 58 and one scoring 0 have a higher mean than eleven
slots scoring about 47, but a lower tactic fit. The selector uses that component
together with `system-fit-v1`: 60% XI suitability, 25% tactical coherence, and
15% instruction suitability, with a 20% weakest-component penalty. Coherence
scores explicit role contributions (width, cover, progression, creators,
runners, penetration, aerial outlet, box presence, rest defence, and pressing)
against the formation's requirements and caps redundant attack duties and
creators. Instruction suitability tests the same selected system against demands
such as counter-pressing, playing out, or counter-attacking. The role profiles
and weights are transparent POC hypotheses, not calibrated claims about FM's
hidden match engine. Lower and upper overall bounds use the selected XI's score
bounds; they do not express uncertainty over which XI would be selected.

The selected shape now also receives an explainable seven-player bench. Only
selectable non-starters are considered; greedy selection prioritizes new
XI-slot coverage and then role/readiness quality. Each substitute reports every
slot they can cover, their primary assignment, and any collective coverage
gaps. This is a deliberately transparent MVP heuristic rather than a claim
about competition-specific bench rules or match-state substitution planning.

The full pipeline has now run against a real unchanged-save Physical export.
It produced a feasible partial XI and exposed the squad's missing left-sided
role. Because only 8 of 32 role inputs were exported, the CLI now labels those
scores provisional and lists the missing inputs; this is a pipeline validation,
not yet the accepted football recommendation.

The proven exact owned-squad reader is now wired into FMBridge, and the CLI can
recommend without HTML when every player has the complete role-input set. A
synthetic eleven-player no-HTML end-to-end test covers a legal XI and snapshot.
The new `--direct-live --recommend` route uses the same validated owned-squad
source without starting the HTTP bridge. It rejects mismatched game/squad dates
or clubs before scoring. On the live 24 June 2019 Hungerford save, all 32 role
inputs were present for every player. The original three wide templates could
not produce a legal XI because no player was eligible at ML/AML. The versioned
balanced narrow diamond did produce eleven unique, position-eligible starters,
plus a bench, weaknesses, and draft recruitment briefs. This completes a live
technical slice for goals 1–3, but football review of role weights,
instructions, and the low-tier weakness thresholds remains before accepting
its judgments. The separate HTTP bridge transport still needs a fresh live
validation.

## Outcome

Recommend an opponent-neutral formation, coherent role system, legal starting
XI, and substitutes by evaluating permitted roles and player assignments
jointly. The result separately reports role suitability, XI suitability,
tactical coherence, instruction suitability, and today's availability,
condition, match sharpness, and binary position eligibility. It remains an
explainable decision aid, not an automatic team-submission system.

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

Tactic familiarity is a distinct future input, not a hidden part of current
role or readiness scores. Before adding it, obtain a manager-visible and
reproducible observation of the squad's/player's familiarity with each tactic,
including its source, in-game date, and unknown/stale state. Then define a
separately versioned adjustment, rerun XI/tactic comparisons, and test how it
changes choices without allowing an unavailable familiarity value to become
an assumed advantage. Until then, every tactic is compared on squad fit only;
the output must not claim that the squad already knows the selected shape.

*Position* familiarity is a separate and much nearer input; see
[Phase 04](../04-squad-analytics/README.md) and Phase 03's 15 September note.
Once it lands, the [decision-support design](../../decision-support-design.md)
gets "best tactic now versus the one to aim for" from this subphase unchanged,
by running the comparison twice — once with the familiarity penalty applied
(**effective**) and once ignoring it (**potential**) — and reporting the gap as
a retraining cost. That is a reporting distinction over existing machinery, and
it must not be confused with the tactic-familiarity input deferred above: it
says nothing about whether the squad knows the *shape*, only whether players
are playing in positions they are suited to.

### 05.4 — Constrained optimiser

Note a cost characteristic, now measured after the catalogue grew to seven
tactics and twenty-eight roles (15 September 2026). `_assignment_states` is
acceptable on its own, but `_best_fit_state` re-runs that whole search once
per distinct candidate score threshold, and thresholds scale with players
times slots. A synthetic `recommend_tactic_effective_and_potential` run (seven
tactics, two familiarity modes) measured 0.19s at 17 players, 2.1s at 25, and
3.0s at 30, all on ordinary development hardware with no attempt at
optimisation. That is a fine cost for a one-shot CLI command; it is not a cost
a web page should pay synchronously on every request once
[Phase 11](../11-automation-and-ui/README.md) exists -- that page should cache
the recommendation and recompute on demand, not on every view. It also means
the catalogue can keep growing for now without this becoming the blocking
concern, but a much larger squad or catalogue should re-measure rather than
assume the trend stays linear. Known remedies if it does bite: binary search
over thresholds, or sharing the search across thresholds, instead of the
current full re-run per threshold.

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
- Tactic-familiarity adjustment until a trustworthy visible input and
  calibrated, separately versioned policy exist
- Complex promises/happiness modelling until trustworthy data exists
