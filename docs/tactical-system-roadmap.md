# Tactical System Roadmap

This is a record of deliberate next steps for the tactical and player-suitability
model.  They are **not implemented** unless explicitly marked otherwise.  The
point is to keep the current POC explainable while providing a clear route from
hand-authored hypotheses to a stronger model.

## Current POC baseline

The current implementation already separates position eligibility from role
quality and jointly selects a permissible role/duty and player for each
formation slot.  It also reports separate XI suitability, tactical-coherence
and team-instruction components.

The following remain intentionally provisional:

- attributes contribute linearly (see "Explicit role attribute weights"
  below for what has changed here and what has not);
- positional eligibility is a `>= 10` gate and familiarity is a linear
  multiplier;
- team instructions are assessed from role capability tags, not the selected
  players' detailed attributes;
- the XI component still uses the legacy mean/weakest-player objective;
- opponent suitability and whole-tactic familiarity are not scored;
- role weighting is per role/duty only, not per tactic: a Deep-Lying
  Playmaker is weighted identically in every tactic that selects one, even
  where one tactic's build-up depends on that passing more than another's.

## Prioritised improvements

### 1. Explicit role attribute weights — **implemented**

Done. Every role/duty owns an explicit per-attribute weight (0-10), authored
inline in its role entry under
`src/fm_analytics/analytics/data/roles/<position>.json` as a plain
`{"passing": 9}` map and loaded into the catalogue at import time. (It was once
generated from a spreadsheet; that CSV and its converter were retired and the
JSON is now the source of truth.) The old `required = 2` / `desirable = 1`
flat-weight fallback has been removed: a role with no weights is a load error.

This is still **per role/duty, not per position, and not per tactic** — see
"Attribute-aware team-instruction suitability" below and the new item
this gap prompted, "Per-tactic role weighting", for what that still leaves
out.

### 2. Nonlinear attribute contribution — **not implemented**

Replace uniform linear scaling with functions that can depend on the role and
tactical context:

```
contribution = f(attribute, role, duty, tactical context)
```

For example, a low passing value may be a practical barrier to a ball-playing
defender, while improvement at the very top of the scale may have diminishing
returns.  Pace can become much more important under a high defensive line.

Start with transparent piecewise curves and thresholds, not a black-box model.
They should be inspectable in the catalogue and visible in explanations.

Scoring applies each role attribute's weight alone, linearly. A per-attribute
`dutyModifier` used to ship in the role files ahead of this work, but nothing
read it, so it was removed (config that is not applied is not kept). Implementing
this item means adding that data back alongside the code that uses it.

### 3. Soft thresholds and weak-link penalties for core attributes — **partly implemented**

Some attributes must be allowed to dominate when they are catastrophically
low.  A weighted average should not make a Finishing-3 striker look adequate
because unrelated secondary attributes are strong.

Use role/duty-specific soft thresholds rather than binary pass/fail rules:

```
if key_attribute < role_threshold:
    apply rapidly increasing mismatch penalty
```

Thresholds should be limited to genuinely core requirements and should explain
the exact cause of the penalty in the UI.

A **per-tactic** version is being implemented: a tactic declares, per attribute
and optionally per position, a level below which a player's fit tapers away (see
`attributeTaper` in `src/fm_analytics/analytics/CLAUDE.md`). The **per-role**
version is not: a per-attribute soft-floor table used to ship in the role files
(`coreSoftFloorApplies`, `softFloorIfAttrLt6/8/10`, `normalMultiplierIfAttrGe10`)
but nothing read it, so it was removed rather than left as reserved config. A
role-level taper would reuse the same mechanism.

### 1b. Per-tactic role weighting (new)

Not part of the original numbered list, but raised directly by item 1's
"per role/duty, not per tactic" limitation: two tactics can both select a
Deep-Lying Playmaker while depending on that passing to very different
degrees (a possession system's build-up hub vs. a counter-attacking
system's occasional out-ball), and today they score that DLP identically.

There is a low-cost workaround already available with no scoring-engine
change: define a second catalogue role (e.g. `dlp_support_possession`) with
its own role entry (under `data/roles/`) and point the relevant slot at it via
the tactic file's per-slot `role`/`roles`. The catch: it must also get a
`system` block in its role entry (or it contributes nothing; the loader now
refuses such a role), or it silently contributes nothing to that tactic's team-balance
score. A proper fix folds tactical context into `f(attribute, role, duty,
tactical context)` in item 2 instead of multiplying role variants by hand.

### 4. Attribute-aware team-instruction suitability

The POC checks whether the selected roles collectively provide the capabilities
requested by instructions.  The next version should also inspect the XI's
attributes and relevant roles:

| Instruction or context | Illustrative requirements |
| --- | --- |
| High press | Stamina, work rate, acceleration, anticipation |
| High line | Defensive pace, anticipation, positioning |
| Play out | Technique, composure and passing in GK, defence and midfield |
| Direct crossing | Aerial ability in relevant attackers |
| High tempo | Technique, decisions and first touch |

This makes instruction suitability a true player-role-instruction interaction,
rather than a label attached to a tactic template.

### 5. Replace the 65% mean / 35% weakest-player XI objective

The current weakest-link component is a useful POC signal but is arbitrary.
Evolve XI suitability into an explicit accounting of quality and deficiencies:

```
XI quality
- severe player-role mismatch penalties
- tactical requirement deficits
- structural weakness penalties
```

This should naturally penalise a disastrous centre-back fit without assigning
one player's score a fixed 35% of the entire XI score.  The resulting terms
must remain separately visible and testable.

### 6. Revisit positional familiarity and eligibility

Keep positional familiarity distinct from intrinsic role quality.  Replace the
current provisional `rating >= 10` eligibility gate and linear `0.5 -> 1.0`
multiplier only after testing the underlying FM data.

Potential extensions:

- allow emergency selection below 10 with severe, explicit penalties;
- model adjacent and natural position transitions differently;
- establish whether the extracted 1–20 values behave linearly in practice;
- account for player attributes that make adaptation less damaging.

The output should distinguish an intrinsically good role fit from the cost of
asking that player to perform it in an unfamiliar place.

### 7. Decision-aware uncertainty and scouting value

Retain exact, range and unknown attribute observations.  Extend every decision
to expose more than a central estimate:

```
pessimistic suitability
expected suitability
optimistic suitability
uncertainty
value of further scouting
```

This lets the system differentiate a tightly known `65 +/- 2` candidate from a
poorly scouted `70 +/- 20` candidate, and makes “scout this player next” a
decision with a quantified benefit.

### 8. Whole-tactic familiarity and match readiness

When reliable tactical-familiarity data can be extracted, add it as a separate
match-day readiness factor, not as a change to intrinsic tactic quality:

```
expected match effectiveness =
    tactic quality * familiarity/readiness adjustment
```

This should capture the cost of changing shape or instructions frequently while
preserving the ability to compare the underlying tactical designs fairly.

### 9. Opponent-specific tactical evaluation

Do this only after role attributes, player-instruction suitability and
coherence have been strengthened.  The eventual target is:

```
expected effectiveness(
    our XI,
    our roles,
    our instructions,
    opponent XI,
    opponent shape,
    opponent tendencies,
)
```

This should be a separately reported component, with clear confidence limits
based on what is actually known about the opponent.  It must not be presented
as a global “best tactic” score or rely on inaccessible information.

### 10. Calibrate from outcomes, without abandoning explainability

Hand-authored football hypotheses are the right bootstrap.  Preserve catalogue
and policy versions, collect enough match data, then test whether role weights,
instruction requirements and interaction penalties predict useful outcomes.

Use learning to refine and calibrate an understandable model, rather than
replacing it immediately with an opaque outcome predictor.  Evaluation should
include historical back-testing where data quality permits, expert scenario
review, sensitivity analysis and comparisons against the current baseline.

## Supporting engineering work

These are not separate football hypotheses, but make the model safer to evolve.

- Move POC role-family alternatives and default tactical-system traits from
  code into explicit catalogue data, including side-specific role options.
  **Partially done**: role alternatives are now per-slot catalogue data
  (`catalogue.json`'s per-slot `roles`), replacing the old blanket
  `_POC_ROLE_FAMILIES` code table that opened every slot to a fixed family
  regardless of what the tactic needed — see `analytics/CLAUDE.md` for the
  trait-distance method used to decide which pairs are safe to declare
  interchangeable. Default tactical-system traits (formerly `_DEFAULT_ROLE_TRAITS`)
  now live in each role's `system` block under `data/roles/` — done.
- Treat role and duty as independently structured data where the source data
  permits it, rather than relying only on combined keys such as `BPD-D`.
- Keep the exact role-version and player-assignment optimiser benchmarked as
  the catalogue grows; retain several near-optimal alternatives for
  explanation.
- Explain selected roles, rejected alternatives, capability shortfalls and the
  marginal effect of likely swaps in the UI.
- Make bench, depth and recruitment analysis evaluate permitted role
  configurations and system deficits, not only the selected starting XI.

## Recommended order

1. Nonlinear curves and soft core-attribute thresholds (explicit weights are
   already in place — see item 1).
2. Attribute-aware instruction suitability and replacement of the legacy XI
   objective.
3. Validate positional familiarity behaviour and add decision-aware
   uncertainty/scouting value.
4. Move tactical catalogue defaults into data; improve optimiser and
   explanations in parallel.
5. Add whole-tactic familiarity.
6. Add opponent-specific modelling.
7. Calibrate the transparent model against accumulated outcomes.

This order deliberately avoids putting opponent models or machine learning on
top of a player-role model whose assumptions are still unvalidated.
