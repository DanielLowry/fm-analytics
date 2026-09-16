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

- role attributes use `required = 2` and `desirable = 1` weights;
- attributes contribute linearly;
- positional eligibility is a `>= 10` gate and familiarity is a linear
  multiplier;
- team instructions are assessed from role capability tags, not the selected
  players' detailed attributes;
- the XI component still uses the legacy mean/weakest-player objective;
- opponent suitability and whole-tactic familiarity are not scored.

## Prioritised improvements

### 1. Explicit role attribute weights

Keep required and desirable attributes as useful labels, but stop treating the
labels themselves as numerical weights.  Each role/duty should eventually own
an explicit, versioned attribute model, for example a BPD-D might weight
marking and positioning at `1.0`, tackling at `0.9`, heading at `0.8`, passing
at `0.75`, and so on.

This remains **per role/duty, not per position**.  Position defines whether a
player may occupy a slot; the role describes what quality means inside it.

Implementation considerations:

- store weights in the catalogue rather than code;
- retain the semantic labels for UI and explanation;
- version every model so recommendations can be reproduced;
- add role-specific tests for expected ranking changes.

### 2. Nonlinear attribute contribution

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

### 3. Soft thresholds and weak-link penalties for core attributes

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
- Treat role and duty as independently structured data where the source data
  permits it, rather than relying only on combined keys such as `BPD-D`.
- Replace or benchmark the bounded role/player beam search with an exact or
  better-bounded optimiser when the catalogue grows; retain several
  near-optimal alternatives for explanation.
- Explain selected roles, rejected alternatives, capability shortfalls and the
  marginal effect of likely swaps in the UI.
- Make bench, depth and recruitment analysis evaluate permitted role
  configurations and system deficits, not only the selected starting XI.

## Recommended order

1. Explicit weights, nonlinear curves and soft core-attribute thresholds.
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
