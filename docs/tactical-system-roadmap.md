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
- the XI component uses a proportional square-root mean that rewards balance;
- whole-tactic familiarity is not scored, and opponent suitability is scored
  only from a manager-set profile (see item 9), not from opposition data;
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

A **per-tactic** version is implemented: a tactic declares, per attribute and
optionally per position and/or permitted role, a level below which a player's
fit tapers away (see `attributeTaper` in
`src/fm_analytics/analytics/CLAUDE.md`). A global **base-role** version is not:
a per-attribute soft-floor table used to ship in the role files
(`coreSoftFloorApplies`, `softFloorIfAttrLt6/8/10`, `normalMultiplierIfAttrGe10`)
but nothing read it, so it was removed rather than left as reserved config. A
role can now be scoped within a tactic without bringing that dead global table
back.

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

### 4b. Player-dependent in-possession settings (new)

Not part of the original numbered list. `analytics/in_possession.py` now
carries a tactic's actual FM tactics-screen settings (`InPossessionSettings`),
split into fixed (part of the tactic's identity, hand-authored, and wired
into `assess_instruction_suitability` via `in_possession_instruction_strings`
-- see `analytics/CLAUDE.md`) and player-dependent (overlaps/underlaps,
crossing type, shoot on sight, dribble less vs. run at defence, expressive
vs. disciplined, play for set pieces). This item is only about the
player-dependent half: it only ever carries a fallback today — nothing
computes it from a squad, and nothing here should let it feed scoring
directly either (see the circularity note below). A first version should be
a small set of
reviewable rules in the same spirit as `_INSTRUCTION_REQUIREMENTS`, reading
only manager-visible attributes (see `analytics/CLAUDE.md`'s "The manager-
visible boundary"), for example:

| Setting | Illustrative rule |
| --- | --- |
| Overlap a side | The full-back's stamina and crossing clear a level and the wide player ahead of him tends to cut inside rather than hug the touchline |
| Crossing type | Floated/whipped when a striker's jumping reach and heading are strong; low when he is quicker than tall |
| Play for set pieces | A back four or midfield with a standout set-piece taker and aerial presence in the box |
| Run at defence vs. dribble less | The front line's dribbling and pace relative to the rest of the squad |
| Be more expressive vs. disciplined | Squad flair/decisions balance, tempered by how young or unfamiliar the shape is |

This must run **after** the XI is picked and must not feed back into
selection or scoring, or it would be circular (the settings would change who
gets picked, which would change the settings) and would break the exact
one-player-per-slot assignment `xi_selection.py` relies on (see "Role
versions and player assignment" above). It is advisory output alongside the
XI, computed once in `reporting.py` so the CLI and every web view show the
same answer — never recomputed per surface.

**Where the rules live (agreed 7 October 2026): globally, not per tactic.**
Each setting asks a question about the players on the pitch, not about the
tactic. "Overlap on the left?" depends on who plays left-back (stamina,
crossing, work rate) and whether the player ahead of him cuts inside, which is
mostly his role: an Inside Forward cuts in, a Winger stays wide. "Which crossing
type?" depends on who is in the box. The same players should get the same
answer in any tactic, so:

- **One global rule table**, like `_INSTRUCTION_REQUIREMENTS`, with fixed
  attribute levels. There are no per-tactic attribute thresholds: 52 tactics ×
  12 settings would be tuned by hand, and the same left-back could get "overlap"
  in one 4-4-2 and not another for no football reason.
- **Rules can still depend on the tactic without per-tactic config.** They read
  the tactic's own slots, roles and fixed settings: they find the left
  full-back from slot positions, and only consider crossing type when the
  tactic has wide players who cross. This is unlike `attributeTaper` and
  `attributeEmphasis`, which are per tactic because they change who is picked.
  These rules only advise once the XI is picked.
- **Per tactic: an optional lock or veto, for identity only.** A tactic may
  lock a setting that defines it (e.g. `wing_play_442` always overlaps) or rule
  one out (e.g. `solid_4231` is never "Be more expressive"). Nothing else about
  these settings is set per tactic.
- **Today's `dependsOnPlayers` values become the fallback**, used only when a
  rule cannot decide, e.g. when the attributes it needs are hidden or out of
  date.
- **Every setting shows its reason in plain terms** on the tactic page, e.g.
  "Overlap left: Yes. Smith (DL) stamina 15, crossing 13; Jones (ML) is an
  Inside Forward, so the flank is free." Because they are computed from the
  picked XI, excluding a player or using the ignore form/condition switches
  updates them with the XI.

Build this after 4c, so the rules only ever pick choices FM's screen allows.

### 4c. Instructions that mirror FM's tactics screen (new)

Raised 7 October 2026. The three phases encoded "not selected" three
different ways, and none matched FM's screen (in possession and in transition
are now fixed; see below):

- **In possession:** `true`/`false`, with `false` shown as "No", which reads as
  a deliberate choice.
- **Out of possession:** `true`/`false`/`"Neutral"`: three states for what is
  one checkbox in FM.
- **In transition:** an explicit `"Neither"` option.

**The model to move to.** Most instructions are a focus the manager either
selects or does not. Not selected is FM's default, "no particular focus", never
a positive "No". Selecting one can make others **unavailable**. For example,
selecting Hit Early Crosses makes Work Ball Into Box unavailable but leaves
Shoot On Sight available. So:

- **Toggles** are selected or not. A tactic file lists the ones it selects, and
  the page shows the rest as "Not selected".
- **Scales** (attacking width, tempo, line of engagement and so on) keep a
  middle "Standard" default.
- **One of several** (crossing type, the transition choices): none selected is
  FM's default.
- **Locks:** a table of "selecting X makes Y unavailable", taken from FM20's
  screen. The catalogue loader refuses a tactic that selects both, naming the
  instruction that locks the other. The page shows a locked instruction as
  "Unavailable: Hit Early Crosses is selected".

**Review, one instruction at a time.** Each instruction is checked against
FM20's tactics screen before the code changes; nothing here is assumed from
memory. Status:

| Phase | Instruction | Kind and FM20 behaviour | Confirmed |
| --- | --- | --- | --- |
| In possession | Attacking width, passing directness (7 steps), tempo | Scales | 7 October 2026 |
| In possession | Time wasting | Scale: Never / Sometimes / Frequently | 7 October 2026 |
| In possession | Crossing type | Dropdown, independent of everything | 7 October 2026 |
| In possession | Play Out Of Defence, Pass Into Space, Play For Set Pieces | Toggles, independent | 7 October 2026 |
| In possession | Focus Play Down The Left / Down The Right / Through The Middle | Left and right may both be selected; either makes Through The Middle unavailable | 7 October 2026 |
| In possession | Overlap / Underlap, each side | Toggles; overlap and underlap on the same side clash | 7 October 2026 |
| In possession | Work Ball Into Box, Hit Early Crosses, Shoot On Sight | Work Ball Into Box clashes with both others; Hit Early Crosses and Shoot On Sight may both be selected | 7 October 2026 |
| In possession | Dribble Less / Run At Defence; Be More Expressive / Be More Disciplined | Neither by default; selecting one makes the other unavailable | 7 October 2026 |
| In transition | Counter-Press / Regroup; Counter / Hold Shape; Distribute Quickly / Slow Pace Down | Neither by default; selecting one makes the other unavailable | 7 October 2026 |
| In transition | Distribute to area/player | One target makes all others unavailable, except that Centre Backs and Full Backs may be selected together | 7 October 2026 |
| In transition | Distribution type | None, or one; selecting one makes the others unavailable | 7 October 2026 |
| Out of possession | All, including whether any FM20 options are missing from the model | | To review |

**In possession is built** (7 October 2026). Tactic files list only the toggles
they select (`"selected": [...]`), the loader refuses a clashing pair (also
against legacy `instructions` strings), and the tactic page shows each toggle
as Selected, Not selected, or Unavailable with what locks it. The 13 tactics
with an in-possession block were converted without changing any score: the
strings scoring reads are identical.

**In transition is built** (7 October 2026) the same way: each of FM's five
sections lists what it selects, `[]` replacing `"Neither"`. Two tactics broke
the confirmed rules and were corrected by the manager's choice: `balanced_442`
now distributes to the flanks with long kicks (it had Flanks with Full Backs,
and Roll It Out with Take Long Kicks), and `deep_counter_541` to its target man
(it had Target Man with Flanks). Distribution has no scoring weight, so no score
changed. Out of possession reuses `analytics/instruction_toggles.py` once
reviewed.

### 5. Replace the 65% mean / 35% weakest-player XI objective — completed

The fixed weakest-link weight was replaced with a square-root mean:

```
player score = mean(sqrt(XI slots))²
```

It strictly increases with every player improvement, scales proportionally, and
penalises uneven XIs without assigning one player a fixed share of the result.
Because maximising it is equivalent to maximising summed square roots, it also
reduced the optimiser from a sweep of score floors to one assignment solve per
role version. The earlier objective and benchmark history remains in
[tactical-model-upgrade-plan.md](tactical-model-upgrade-plan.md) §7.1.

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

### 9. Opponent-specific tactical evaluation — **manual profile implemented**

A **manager-set** opponent now exists: a likely-formation choice plus nine
sliders (`OpponentProfile` in `analytics/opponent.py`), each -2..+2, which shift
attribute emphasis by position and impose absolute team-balance floors. Opponent fit is reported as
its own component beside coherence and instruction fit, never folded invisibly
into one number, and a neutral profile is provably inert. It reaches tactic
ranking, XI choice, bench, substitutions, depth and weaknesses. See
`analytics/CLAUDE.md` and §2j of
[tactical-model-upgrade-plan.md](tactical-model-upgrade-plan.md) for what was
built and the five deviations from the original design.

A manager can set it from the CLI (`--opponent-<axis>`, one flag per axis) or
from bookmarkable controls on `/tactics`. The web view reports rank and
score changes versus neutral, the separate opponent-fit check, and carries the
profile into each tactic drill-down.
Deriving the profile from opposition data rather than a slider is Phase 08/D6
and is deliberately out of scope — `OpponentProfile` is the interface an
automatic version would substitute into without touching scoring.

Note the ordering advice below still applies to everything *beyond* the manual
sliders. The eventual target is:

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

Agreed next, ahead of this list (7 October 2026): 4c (instructions mirror
FM's screen), then 4b (player-dependent settings picked from the XI).

This order deliberately avoids putting opponent models or machine learning on
top of a player-role model whose assumptions are still unvalidated.
