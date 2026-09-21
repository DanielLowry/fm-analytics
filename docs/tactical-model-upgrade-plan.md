# Tactical model upgrade plan

Status: **proposed, not implemented.** This is the plan for four related
changes to the tactical model, requested together:

- **A** — audit the tactic list for gaps and for role choices made stale by
  the expanded role catalogue;
- **B** — make each tactic's instructions internally coherent, and give every
  tactic and every slot a written justification;
- **C** — let a tactic change how much each attribute matters, on top of the
  existing per-role/duty weights;
- **D** — introduce the opponent, initially as manager-set sliders on the
  Tactics page.

It extends [tactical-system-roadmap.md](tactical-system-roadmap.md) rather
than replacing it: A/B are that document's "supporting engineering work" plus
item 4, C is item 1b, and D is item 9. The roadmap's ordering advice — do not
put an opponent model on top of an unvalidated player-role model — is the
reason the sequencing below front-loads calibration.

## Decisions taken

Five choices were made before and during planning, and the plan assumes
them:

| Question | Decision |
| --- | --- |
| Catalogue size | **Large expansion to 40+ tactics**, systematic coverage of FM20 shapes and styles |
| Opponent reach | **Re-rank tactics *and* re-pick the XI** — opponent shifts attribute emphasis, not just tactic order |
| Per-tactic weighting | **Full per-tactic, per-role weight tables**, authored as JSON inside each tactic's own file (§2.3) |
| Weight draft | **Soft seeded first draft** — tactic-wide +2 on the 0–10 scale, hand-tuned after |
| Tactic-free pages | **Squad, Roles and Scouting keep base weights** — a player's "best role" must not move when an opponent slider does |

## 1. Diagnosis — what is actually wrong today

Every claim here was measured against the current catalogue, not inferred.

### 1.1 Fourteen tactics carry a structurally unsatisfiable demand

`_INSTRUCTION_REQUIREMENTS` demands system-dimension totals that
`_DEFAULT_ROLE_TRAITS` cannot supply for that tactic's permitted role
versions. This is not "the squad falls short" — it is unreachable for *any*
squad and *any* legal role combination, so it acts as a fixed handicap on
those tactics that tells the manager nothing.

| Tactic | Unreachable demand (best achievable → required) |
| --- | --- |
| `attacking_433` | pressing 1.5 → 3.5; creativity 0.8 → 1.5 |
| `attacking_343` | pressing 1.5 → 3.5; creativity 1.4 → 1.5 |
| `attacking_424` | pressing 0.9 → 3.0 |
| `positive_4231` | pressing 0.8 → 3.0 |
| `positive_433dm` | pressing 1.0 → 3.0 |
| `positive_3421` | pressing 1.7 → 3.0 |
| `positive_4312_narrow` | pressing 2.3 → 3.0 |
| `control_possession_4231` | pressing 1.4 → 2.0 |
| `gegenpress_4231` | creativity 1.4 → 1.5 |
| `highpress_433` | creativity 0.8 → 1.5 |
| `balanced_4141` | creativity 0.0 → 1.5 |
| `defensive_451` | creativity 0.0 → 1.5 |
| `defensive_532` | creativity 0.9 → 1.5; runners 1.6 → 2.0; penetration 0.0 → 1.5 |
| `lowblock_442` | creativity 0.9 → 1.5; runners 0.0 → 2.0; penetration 0.0 → 1.5 |

The `pressing` dimension is the clearest failure. Only 12 of 65 roles carry
any pressing trait at all, the largest is 1.5 (`bwm_*_support`), and **no
forward, centre-back or attacking full-back carries one**. An eleven
therefore cannot reach 3.0, let alone the 3.5 that "Much Higher Line of
Engagement" asks for. The supply table and the demand table were written
against different implicit scales and have never been reconciled.

The practical effect: the model systematically marks down pressing and
low-block systems for reasons that have nothing to do with the manager's
players.

### 1.2 Ten instructions in use are unscored

`_INSTRUCTION_REQUIREMENTS` has no entry for these, so
`assess_instruction_suitability` silently skips them:

`Pass Into Space` (6 tactics), `Lower Line of Engagement` (3),
`Hit Early Crosses` (2), `Overlap Left` (2), `Overlap Right` (2),
`Hold Shape` (2), `More Direct Passing`, `Much More Direct Passing`,
`Slightly Shorter Passing`, `Prevent Short GK Distribution`.

This is worse than a gap, because it is not neutral. `route_one_442` and
`wing_play_442` both score **100.0 / 100.0** — a flawless rating earned by
having three of their defining instructions go unmeasured. Route One's
entire identity (`Much More Direct Passing`, `Hit Early Crosses`) is
invisible to scoring. A tactic is rewarded for being unmodelled.

### 1.3 No tactic declares its own balance requirements

Not one of the 25 tactics supplies a `system` block, so every one falls
through to `_inferred_system_requirements`. A low-block 5-3-2 and a
gegenpress 4-2-3-1 are held to the *same* `defensiveCover 3.0`,
`ballProgression 2.0`, `restDefence 3.0` thresholds. The only tactic-specific
inputs are a width minimum (2.0 if any wide slot exists, else 1.5) and an
attack-duty cap keyed on mentality — and that cap's lookup table has no
`Cautious` entry, so the three Cautious tactics silently get the Balanced
limit of 4.

"Team balance" is therefore close to a constant across the catalogue. This is
the single most naive part of the current model.

### 1.4 Half the role catalogue is unreachable, and would misbehave if used

**32 of 65 roles are named by no tactic**: every Pressing Forward
(`pf_defend/support/attack`), False Nine, Trequartista (all three
positions), Enganche, Raumdeuter, both Inverted Wingers, both Wide Target
Men, all Complete and Inverted Wing-Backs, `fb_defend`, `fb_attack`,
`wb_dl_dr_defend`, `nnfb_defend`, `dlf_attack`, `cf_attack`, `tm_support`,
`am_attack`, `if_support`, and the AML/AMR and MC Advanced Playmakers.

Worse, **30 of 65 roles have no `_DEFAULT_ROLE_TRAITS` entry and no `system`
block in `catalogue.json`**, so `role_traits()` returns `{}` for them. Using
one today would contribute *nothing* to team balance and quietly depress the
coherence score. The trap is already documented in the roadmap's item 1b;
nothing enforces it.

This directly causes a football error in the tactics that do exist: both
gegenpress systems (`highpress_433`, `gegenpress_4231`) demand urgent
pressing while fielding a Target Man or Advanced Forward with a pressing
trait of exactly zero — when three Pressing Forward roles sit unused in the
catalogue.

### 1.5 Exclusion groups cannot express "at most one in the XI"

`RoleExclusionGroup` requires a `position`, so it can only say "at most one
Cover centre-back among DC slots". It cannot say "at most one Trequartista
anywhere in the eleven" — a rule that matters as soon as Trequartista,
Enganche and Raumdeuter (all near-zero defensive contribution) become
selectable at three different positions.

### 1.6 The data layout is already failing

Five separate symptoms, all of the same cause — config that grew by
accretion:

- **Seven superseded weight files are still in the tree** (`role_weights_v2`
  … `v7`), none loaded by anything.
- **Filename and declared version have drifted.** The loaded file is
  `role_weights_v8.json`; it declares `"version": "role_weights_v5.5"`. They
  matched through v4 and have diverged ever since, so neither name is now a
  reliable identifier.
- **A built wheel ships the wrong data.** `pyproject.toml`'s `force-include`
  enumerates `role_weights_v2.json`, but `role_weights.py` loads `v8`. A
  non-editable install would be missing the file the code actually reads;
  this is invisible locally only because the working install is editable.
- **The CSV and its generator are dead.** `fm20_role_attribute_weights_v2.csv`
  is referenced only by `tools/csv_to_role_weights.py`, which its own
  docstring marks stale, which targets `role_weights_v2.json`, and which has
  no test coverage. Nothing in the loading path touches either.
- **Every role is defined in two files that must agree.** Identity,
  positions and required/desirable live in `catalogue.json`; attribute
  weights live in `role_weights_v8.json`. `_attributes_from_weights` raises
  when they disagree — a guard that exists precisely because they have
  disagreed before (the `wb_support` position split). Meanwhile
  `required`/`desirable` are *mandatory* fields in the role schema and dead
  in production: they are read only on the no-weight-catalogue fallback path
  that real data never takes.

Addressed in §2, and sequenced first — the migration is far cheaper at 25
tactics than at 45.

### 1.7 Cost baseline

Measured on synthetic squads, full effective+potential search:

| Catalogue | 30 players |
| --- | --- |
| 25 tactics (today) | 1.6 s |
| 45 tactics | 2.8 s |
| 60 tactics | 3.9 s |

Split roughly 40% role scoring / 60% assignment solving. At 45 tactics a
cold Tactics page is ~3 s, and an opponent slider that recomputes makes that
an interaction cost rather than a once-per-load cost. Addressed in §6.

## 2. Data layout and maintenance

> **Phase 0 is implemented** (this section describes it; deviations from the
> original proposal are listed in §2.10). The lossless check in §2.9 passed:
> the catalogue loaded from the new layout compares equal, as a whole
> `FootballCatalogue` object, to the one loaded before the split.

The diagnosis in §1.6 is the argument for doing this **first**, before the
catalogue grows. Splitting 25 tactics is a mechanical afternoon; splitting 45
tactics that have each just acquired a `system` block, per-slot
justifications and weight overrides is a merge-conflict festival.

### 2.1 Target layout

```
src/fm_analytics/analytics/data/
  catalogue.json          version, exclusiveRoleGroups, tacticResearchNotes
  roles/
    gk.json      dc.json     dl_dr.json   wbl_wbr.json   dm.json
    mc.json      ml_mr.json  amc.json     aml_amr.json   st.json
  tactics/
    balanced_442.json
    gegenpress_4231.json
    ...                   one file per tactic
```

`catalogue.json` shrinks to the things that are genuinely global: the version
string, the exclusion groups (which span roles by definition) and the
research notes.

### 2.2 Roles: split by position, and merge in the weights

Ten position files, following the `positionGroup` field the weights data
*already* carries — so the split is read out of the data, not invented.
Current distribution: ST 13, AML/AMR 12, DL/DR 12, AMC 7, MC 7, DM 4, DC 3,
ML/MR 3, GK 2, WBL/WBR 2.

This matches how the data is actually edited. You tune all the strikers in
one sitting; today that means paging through a 237 KB file holding all 65
roles, and every such session collides with every other in git history.

**A role's weights move into its role file.** Today a role is defined across
two documents that must agree, guarded by a load-time error that exists
because they have disagreed before (§1.6). Merging them deletes that entire
failure class: one role, one place, identity and system traits and attribute
weights together.

```jsonc
// roles/st.json
{ "roles": [
  { "key": "pf_attack",
    "name": "Pressing Forward (Attack)",
    "positions": ["ST"],
    "system": { "pressing": 2.2, "runners": 1.2, "penetration": 1.0,
                "boxPresence": 0.8, "attackDuty": 1.0 },
    "attributes": {
      "workRate":     { "effectiveWeight": 9, "dutyModifier": 0, ... },
      "acceleration": { "effectiveWeight": 8, "dutyModifier": 0, ... }
    } } ] }
```

While doing this, make `required`/`desirable` **optional**. They are
mandatory today and dead in production — read only on the
no-weight-catalogue fallback that real data never takes. Keep the fallback
for hand-built test catalogues; stop demanding the fields from real ones.

### 2.3 Tactics: one file per tactic, holding everything

Yes — and the case gets stronger under this plan. A tactic entry averages 94
lines today. After its `system` block, per-slot `why`, `whenToUse`,
`whenNotToUse` and `instructionRationale` (§4.2) it is realistically 200+.
At 45 tactics that is a ~10,000-line single file. One file per tactic makes
adding a tactic a new file rather than a conflict, and makes the diff for
"I retuned the gegenpress" show exactly that.

**And yes — the weight overrides belong in it too.** With the CSV retired
(§2.6) there is no generated-vs-hand-authored split to keep apart, and the
argument for cohesion wins outright: the decision "this system needs more
stamina from its wide slots" belongs next to the slot it applies to. One
file is the whole tactic; deleting a tactic deletes one file; a weight
override cannot reference a role the tactic does not field.

```jsonc
// tactics/gegenpress_4231.json
{
  "key": "gegenpress_4231",
  "name": "Gegenpress 4-2-3-1",
  "formation": "4-2-3-1 DM AM Wide",
  "mentality": "Positive",
  "instructions": ["Counter-Press", "Much More Urgent Pressing", ...],
  "instructionRationale": {
    "Counter-Press": "The 4-2-3-1's front four already screen the ball side; ..."
  },
  "system": { "minimums": { "pressing": 6.0, "restDefence": 4.0, ... },
              "maximumAttackDuties": 5, "maximumCreators": 3 },

  "weights": { "stamina": 8, "workRate": 8, "aggression": 6 },

  "slots": [
    { "key": "STC", "position": "ST",
      "role": "pf_attack", "roles": ["af_attack"],
      "why": "The press starts here; an Advanced Forward would leave the ...",
      "weights": { "workRate": 9, "aggression": 8 } }
  ],

  "whyThisShape": "...", "whenToUse": "...", "whenNotToUse": "...",
  "style": "...", "description": "...", "whyGood": "...",
  "keyRequirements": [...], "tags": [...]
}
```

### 2.4 Override semantics — three layers, absolute values

1. **Base** — the role's weights in its position file.
2. **Tactic `weights`** — applies to every slot in this tactic. Stops "this
   gegenpress wants stamina everywhere" from being copy-pasted eleven times.
3. **Slot `weights`** — applies to that slot only, and wins.

Slot-level is deliberately more precise than the tactic-plus-role table
originally proposed: it is strictly more expressive, because the same role
can fill two slots with different demands (the left and right wing-backs of
an asymmetric system). Where a slot has alternates that need *different*
emphasis, key the block by role: `"weights": { "pf_attack": {...} }`.

Values are **absolute `effectiveWeight` on the existing 0–10 scale**, not
multipliers or deltas. Reasons, in order:

- You review the final number, not an expression that produces it.
- A multiplier cannot introduce an attribute the base role scores 0 — a
  high-press tactic could never add stamina to a role that ignores it,
  which is exactly the case this feature exists for.
- Deltas need clamping rules at both ends, and a delta whose base moved is
  silently wrong in a way an absolute value is not.

Only `effectiveWeight` is overridable, so an override is a plain number
rather than the eight-field object the base carries. Add a load-time lint:
an override equal to its base is a no-op and should warn, not pass quietly.

### 2.5 What the split costs, and the fix

Losing the single weights table makes cross-cutting review harder: "which
tactics emphasise stamina, and how much?" becomes a grep across 45 files.

Do not solve this by keeping a second copy. **Derive the view**:
`tools/tactic_weight_report.py` renders the cross-tactic matrix on demand
from the per-tactic files. A derived table cannot drift from its source; a
stored one can, and §1.6 is what that looks like.

### 2.6 Retirements

- **Delete `fm20_role_attribute_weights_v2.csv` and
  `tools/csv_to_role_weights.py`.** Dead, stale by their own admission, no
  tests, and targeting a file the loader abandoned six revisions ago. JSON
  becomes the source of truth outright — which also means the tactic-weight
  CSV pipeline proposed earlier in this plan is dropped (§6.2).
- **Delete `role_weights_v2` … `v7`.** Git holds history; the tree should
  hold current state.

### 2.7 Stop versioning in filenames

One `version` in `catalogue.json`, injected into every role and tactic by
the loader exactly as it is today. Paths become stable: `roles/st.json`, not
`roles/st_v9.json`.

The current scheme has already failed — the file named `v8` declares
`v5.5`, and the two have disagreed since v5. A version in a filename means
every revision forks a new file, `_DATA_PATH` must be edited to match, the
old file lingers, and git — which is the real version record — is bypassed.

### 2.8 Loader and packaging

- `load_catalogue(path)` accepts **either** a directory (production) **or** a
  single JSON document. The single-document path is not legacy baggage:
  `tests/test_catalogue.py` builds minimal in-line catalogues to test
  validation, and those tests should keep working unchanged.
- Files are discovered by **sorted glob**, so ordering is deterministic. Add
  a test asserting each file's `key` matches its filename and that the
  loaded counts are as expected, so a stray, duplicated or mis-named file
  fails loudly rather than being silently absorbed.
- **Delete the `force-include` block in `pyproject.toml`.** Enumerating data
  files was already wrong (§1.6) and is untenable at ~55 files; hatchling's
  `packages = ["src/fm_analytics"]` includes them. Add a CI step that builds
  a wheel, installs it into a clean environment and imports
  `fm_analytics.analytics.catalogue` — the check that would have caught the
  current bug.

### 2.9 Do the migration mechanically

Write a one-off `tools/split_catalogue_data.py` that performs the split from
the current files, and assert the result is **lossless**: load the catalogue
before and after and compare the resulting `FootballCatalogue` objects for
equality. A reshuffle of every scoring input should be proven by comparison,
not reviewed by eye. Delete the tool once merged.

### 2.10 As built — where it differs from the proposal above

- **`required`/`desirable` are dropped from the role files, not just made
  optional.** They were dead in production. The loader still tolerates them
  (and the fallback that reads them) so hand-built test catalogues keep working.
- **`csvRole` is dropped; `positionGroup` and `duty` are kept** on each role
  entry as descriptive labels. A test asserts each role file holds exactly the
  position group its filename names.
- **The loader enforces tactic filename = key** at load time rather than only
  in a test; a mismatched file fails the import.
- **Two document formats remain**: the shipped directory, and a single
  self-contained JSON document (used by `tests/test_catalogue.py` for small
  catalogues). `load_role_weights(path)` likewise still reads the old
  standalone weights document, because `tests/test_role_weights.py` builds its
  fixtures in that shape. Both are test conveniences, not shipped data.
- **The weights file's own version is gone.** The catalogue's single version
  is used for everything (`load_role_weights().version` equals it; tested).
- **Role order in `catalogue.roles` changed** (it now follows sorted filename,
  then file order) and tactic order follows sorted filename. Neither affects a
  result: `recommend_tactic` already breaks ties on `tactic.key`. It can change
  the order of role lists that iterate the catalogue directly, e.g. on the
  Scouting page.
- **`pyproject.toml`'s force-include lost both data entries**; the wheel now
  carries all 36 data files from the package tree. CI gains a step that
  installs the built wheel into a clean venv and loads the catalogue.
- Not done here: `tools/tactic_weight_report.py` (§2.5) — it has nothing to
  report until per-tactic weights exist (phase 5).

## 2b. Phase 1–2 as built (traits, demands, per-tactic balance)

Implemented: A1–A4 and the B1 fixes needed to make demands reachable.

**Done**

- All 65 roles carry a `system` block in `data/roles/*.json`; the code-side
  `_DEFAULT_ROLE_TRAITS` table is gone (removed outright rather than kept as a
  fallback — the tests that needed one already set traits explicitly). The
  loader refuses a shipped role that a tactic uses but that has no traits.
- Supply and demand were recalibrated as one scale. `pressing` was the worst
  offender: it is now supplied by roles that actually press (Pressing Forwards
  1.6–2.0, Ball-Winning Midfielders 1.5, Box-to-Box 1.0, down to 0 for roles
  that don't) so a passive shape cannot accumulate a high-press demand from
  small contributions, and the demands were restated to be reachable.
- All ten unscored instructions are modelled (§1.2).
- Every tactic has its own `system` block, by style (§A4). The old inferred
  thresholds sat far below what any XI supplies for the defensive dimensions
  (needing 3.0 against 6–10 supplied), so they never bit.
- `tests/test_tactical_calibration.py` guards it: no instruction demand or
  balance minimum may exceed what some legal role version can supply, every
  instruction used must be modelled, and a passive shape must not clear the
  urgent-pressing demand.

**Football judgement calls to review** (each changes a score; none is a bugfix)

| Change | Reason |
| --- | --- |
| `positive_4231`, `positive_433dm`: DM `dm_defend` → `bwm_dm_support` | Counter-Press + Higher Line of Engagement with no pressing role fielded |
| `attacking_424`: MC `cm_defend` → `bwm_mc_support` | Same |
| `defensive_532`, `lowblock_442`: `tm_attack` → `af_attack` (alt `p_attack`) | `Counter` with no forward who runs in behind; low block still keeps its DLF/CF hold-up |
| `highpress_433`: `tm_attack` → `pf_attack` (alt `af_attack`) | A Target Man leading a Much More Urgent press |
| `gegenpress_4231`: `af_attack`/`p_attack` → `pf_attack` (alt `af_attack`) | Same; the Poacher alternate is dropped, it doesn't press |
| `counter_352_wingback`: `Narrower` → `Fairly Wide` | Narrower cancelled the width its two wing-backs exist to provide |
| `Counter` demand 2.0 → 1.5 runners | One true outlet (an Advanced Forward supplies 1.5) is a counter threat; 2.0 needed two |
| `Shorter Passing` no longer demands creativity | Short passing needs progression, not chance-making; it made tactics with no creator unreachable |
| `Narrower` now asks for cover + progression, not creativity | Narrow is a compactness instruction as often as a creative one |

**Not done**

- A5 (exclusion groups across the whole XI) — nothing yet selects the new
  free-role positions, so it has no effect until the catalogue expands.
- The remaining B1 items: the asymmetric wide roles in `possession_4141` and
  `vertical_tikitaka_433dm` (left as-is; needs your call on intent), and a
  trait-distance review of slot alternates.

**A finding that changes what the later phases must do.** After
recalibration every tactic scores 100/100 on both balance and instruction fit
for its default role version. That is correct and also a limit: both
components depend only on *roles*, never on *players*, so for a consistent
tactic they are a constant. They now work as a consistency check (a slot
alternate that breaks the tactic's balance is penalised) rather than a ranking
signal, and tactic ranking is now driven by XI quality alone. The old spread
(instruction fit ranged 60–100) was an artifact of unreachable demands, not
information. Real discrimination between tactics has to come from the pieces
still to be built: attribute-aware instruction suitability (roadmap item 4),
per-tactic attribute weights (§5) and the opponent (§6).

## 2c. Justifications as built (B2, B3 for the existing 25)

Every one of the 25 tactics now carries, in its own file:

- `whyThisShape`, `whenToUse`, `whenNotToUse` — what the formation does, and when
  to pick or avoid it;
- a `why` on each slot — why *this role* is in *this slot* of *this tactic*;
- `instructionRationale` — one line per instruction tying it to the shape.

They are shown on the tactic detail page (shape, usage and an expandable
"Why these instructions" list in the notes block; each slot's reasoning above its
"Why <player>?" explanation) and as a one-line hint per tactic on the overview.
None of it is scoring input, and the loader treats all of it as optional, so
hand-built test catalogues are unaffected.

Two behaviours worth knowing:

- The slot text is written for the slot's **default** role. If the optimiser
  picks an alternate for your squad, the page says so instead of presenting the
  default's reasoning as if it described the chosen role.
- Prose beside data can contradict it, so tests enforce completeness (every
  tactic, slot and instruction is explained, no two tactics share text) and that
  an "X is the alternate" claim matches the slot's actual alternates. That test
  found no error in the final text, but a hand check had already caught three
  slots where the default was Cover and the text said Cover was the alternate.

The text is my authorship and is football opinion; it is meant to be edited. The
asymmetric wide roles in `possession_4141`, `vertical_tikitaka_433dm` and
`balanced_4411` are explained in the slot text as "one safe flank, one creative
flank" — that is my reading of the data, not something the catalogue states, so
correct it if the asymmetry was accidental.

## 2d. Catalogue expansion, batch 1 (A6)

Six new tactics, taking the catalogue from 25 to 31 and the roles in use from 34
to 51 of 65: `false_nine_433`, `inverted_wingback_433`, `enganche_4231`,
`raumdeuter_counter_4231`, `deep_counter_541`, `complete_wingback_4231`. Each ships
with its full justification text and its own balance requirements, per the rule
that nothing lands without them, and each fills a legal XI on a synthetic squad.

**How the new tactics' balance requirements were set — this is weaker than for
the original 25.** The original 25 were set by hand by style, then checked for
reachability. For these six I took about 85% of what the intended line-up
supplies, rounded down to 0.5, in the dimensions I judged to define the style
(and left the others unconstrained, e.g. a deep block does not need to press). That
makes each requirement a description of the line-up I wrote rather than an
independent statement of what the style needs, so a default line-up passing them is
close to guaranteed. Their value is in catching a slot alternate that breaks the
tactic, not in judging the tactic. Treat the numbers as editable.

**New guard.** `test_no_tactic_is_a_near_copy_of_another_on_the_same_shape`: two
tactics on the same shape must differ by at least six jobs plus instructions. The
closest existing pair scores 7, so this bites only on a genuine near-copy.

**Still unused (14 roles):** `treq_st_attack`, `treq_amc_attack`,
`treq_aml_amr_attack`, `iwb_dl_dr_attack`, `iwb_dl_dr_defend`, `nnfb_defend`,
`pf_defend`, `pf_support`, `wtm_support`, `wtm_attack`, `fb_attack`, `if_support`,
`iw_support`, `ap_aml_amr_attack`. The three Trequartista roles are the reason A5
(an exclusion group across the whole XI rather than one position) is still needed:
it only matters once a tactic can put two free roles in the same XI.

## 2e. Catalogue expansion, batch 2 (A5, A6)

Nine more tactics, taking the catalogue to **40** and putting **all 65 roles** in
use: `trequartista_4312`, `pressing_442`, `crossing_433`, `aerial_343`,
`solid_4231`, `box_midfield_4231`, `wide_playmakers_433`, `trequartista_442`,
`narrow_4222`. Each ships with its justification text and balance requirements
and fills a legal XI on a synthetic squad; one pass over all 40 tactics with 30
players takes about 1.1s (a full recommendation runs the search twice, for
effective and potential).

**A5 done.** An exclusion group may now omit `position` and then limits a role
across the whole XI. The shipped "Free roles" group allows at most one of
`treq_st_attack`, `treq_amc_attack`, `treq_aml_amr_attack`, `eng_support` and
`raum_attack`. No shipped tactic can currently field two, so it is a guard for
future tactics, not something that changes a result today.

**Same caveat as batch 1** about how the new balance requirements were set (about
85% of the intended line-up's supply, in the dimensions chosen as defining the
style; §2d). One change from the plan while writing: `trequartista_442` uses a
standard defensive line, because a higher one suits a team whose creator does
not defend badly.

**A judgement to review — the one alternate pair that is not near-identical.**
`pf_attack`/`af_attack` in the two gegenpress tactics differs by about 1.2 in
pressing (the other three pairs are near-identical, per `analytics/CLAUDE.md`).
It is a deliberate fallback for a squad with no pressing forward, at a cost in
instruction fit, rather than an interchangeable pair. If you would rather the
gegenpress tactics were strictly Pressing Forward, remove the alternate.

The remaining work on the plan is the review you plan to do, then per-tactic
attribute weights (§5) and the opponent sliders (§6).

## 2f. Per-tactic attribute weights as built (workstream C)

Implemented and seeded across all 40 tactics. A tactic now shifts what it asks
of its players, so the same player can fit a gegenpress and a low block
differently.

**Three deviations from 5.1-5.4, each for a reason found while building:**

1. **Deltas, not absolute weights.** 2.4 specified absolute `effectiveWeight`
   values. That cannot work for a tactic-wide block: one block covers all eleven
   slots, so an absolute `stamina: 8` would mean stamina 8 for the goalkeeper
   too. It also cannot express the agreed seed rule, because roles list only the
   attributes they care about (a centre-back has no `stamina` entry at all), so
   "+2 only where the role already values it" is only sayable as a delta. Both
   layers are therefore deltas, clamped to 0-10, applied only where the role
   already weights the attribute. Negative deltas work, which 2.4's absolute
   scheme also allowed but less directly.
2. **Named `attributeEmphasis`, not `weights`.** Once the values are deltas,
   calling them weights invites reading `stamina: 2` as "stamina weight 2".
3. **The seed weights each instruction by how rare it is** across the catalogue.
   Without it every tactic's top four collapsed to the same handful of
   attributes that common instructions ask for, which is the opposite of the
   point. It is also what stopped an aerial crossing tactic emphasising
   positioning and first touch over heading and jumping reach.

**Mechanism.** `FootballCatalogue.for_tactic(key)` returns the catalogue with
every role re-weighted for that tactic; role keys, names, positions, system
traits and the version are untouched, so every lookup and check keeps working.
A tactic with no emphasis returns the same catalogue, so that case is provably
unchanged. `role_for_slot(slot, role_key)` resolves a slot-level override.
Derivation happens inside each per-tactic entry point (`evaluate_tactic`,
`select_bench`, `build_substitution_board`, `explain_tactic_selection`,
`assess_weaknesses`), so callers need no changes and CLI and web stay in step.

**Two bugs this found, both fixed and now tested:**

- `dataclasses.replace` was handing the copy the *original* catalogue's memo
  cache, so a modified catalogue silently returned the original's derived
  views. The cache is now `init=False`.
- The derived catalogue re-validated authored emphasis names against its own
  already-narrowed roles, so any emphasis that took a weight to zero made an
  unrelated tactic fail to load. A `tactic_view` flag skips that one check on
  computed catalogues; it still runs on all authored data.

**Measured effect of the seed** (three synthetic 30-player squads, against the
same catalogue with emphasis stripped): tactic score moves by -0.05 on average
(range -0.44 to +0.31), 1.25 of 11 starters change on average, and 66% of the
nudges land — 7% are already at 10 and clamp, 27% name an attribute the role
does not have and are correctly refused. That matches the band measured when
+2 was agreed. Full effective+potential over 40 tactics and 30 players is 2.41s,
about 10% above the pre-emphasis cost.

**Position-scoped blocks (a later change, from review).** `attributeEmphasis` was
first a single whole-team block, which could not say "the back four need pace
under a high line" without repeating it per slot. It is now a **list of blocks**,
each with an optional `positions`:

```json
"attributeEmphasis": [
  {"attributes": {"stamina": 2, "workRate": 2}},
  {"attributes": {"pace": 2}, "positions": ["DL", "DC", "DR"]}
]
```

No `positions` means the whole team. Every block covering a slot is **summed**,
together with that slot's own block, then clamped to 0-10. Summing replaced "the
slot block overrides the tactic block": with a list, "which one wins" has no good
answer, and addition is order-independent and easy to predict. (No shipped data
used a slot-level block, so nothing changed for it.)

Three guards: a block may not name a position the tactic does not field (it would
silently do nothing, and `"DCL"` for `"DC"` is the obvious typo); an unknown key
such as `"position"` is refused (it would quietly become a whole-team block); and
the old dict form is refused with a message saying what to write. The migration
was proven lossless: all 120 evaluations across three squads (scores and every
slot's player and role) were bit-identical before and after.

The shipped seed is still one whole-team block per tactic, by design. A
position-aware seed (a high line raising pace for the back four only; crossing
for wide players only) would be an improvement but would overwrite tuning, so it
is a decision for you, not something done silently.

**What is not done:** slot-level blocks are never seeded; no slot-level
block is seeded, and a test enforces that, so every slot-level block in the tree
will be one you added. The tactic detail page names what a tactic leans on, but
does not yet show base-versus-emphasised weight per attribute (5.4).

## 2g. The tactic index

`docs/tactic-catalogue.md` is a generated one-page index: a scannable table of
all 40 tactics (shape, mentality, what each leans on, when to use it) and a
compact block per tactic with its roles by line, emphasis, requirements and
instructions. Detail stays in the per-tactic files.

It is generated by `tools/tactic_index.py` and **never hand-edited**;
`tests/test_tactic_index.py` fails when it is stale, which is what stops a
second copy of the catalogue drifting from the real one. Generating it exposed
that the batch 1 and 2 tactics had put a style name in `formation`
("4-2-3-1 Enganche") where the original 25 use FM formation labels; those are
now normalised, with the style kept in the `style` field where it belongs.

## 3. Workstream A — the catalogue

### A1. Give all 65 roles system traits

Move `_DEFAULT_ROLE_TRAITS` out of `tactical_system.py` and into
`catalogue.json` as the per-role `system` block the loader already supports
(`_role_from_json` reads `raw.get("system")`; nothing uses it yet). Author
traits for all 65 roles in the same pass, using the existing 35 as the
calibration reference.

Add a catalogue-load invariant: **a role named by any tactic slot must have
a non-empty trait map.** This converts §1.4's silent failure into a load
error, and is the guard rail that makes the expansion in A3 safe.

Keep `_DEFAULT_ROLE_TRAITS` as a fallback for one release so tests that
construct catalogues by hand keep working, then delete it.

### A2. Recalibrate the trait and requirement scales together

Do this *before* any new tactic is authored, or the new ones inherit the same
mis-scaling. Two halves, and they must move together:

- **Supply.** Every role gets a `pressing` value consistent with how that
  role actually presses — Pressing Forwards high, Advanced Forward low but
  non-zero, attacking full-backs and wing-backs non-zero, centre-backs small
  but real in a high line. Likewise `creativity`, which today only five roles
  supply at ≥ 1.2, making several tactics' creativity demands unreachable.
- **Demand.** Restate `_INSTRUCTION_REQUIREMENTS` on a scale an eleven can
  actually reach.

Acceptance: **no tactic in the catalogue may carry an unsatisfiable demand.**
Encode this as a test that reproduces §1.1's search over permitted role
versions and fails on any dimension where the maximum achievable total is
below the requirement. That test is the regression guard for every later
change.

### A3. Model the ten missing instructions

Add entries for all ten in §1.2. Notes on the interesting ones:

- `Hit Early Crosses` → `width` and `aerialOutlet`, and a **box-presence
  requirement**: crossing into nobody is the failure mode to catch.
- `Overlap Left`/`Overlap Right` → `width`, plus a `restDefence` cost, since
  overlapping full-backs are exactly the trade-off the manager is making.
- `Hold Shape` → `restDefence` and `defensiveCover`; it is the counterpart to
  `Counter-Press` and should not be free.
- `Pass Into Space` → `runners` and `penetration`; it appears in 6 tactics
  and is currently the largest single blind spot.
- `Prevent Short GK Distribution` → `pressing`, on the recalibrated scale.

Add a test asserting **every instruction string used by any tactic has a
requirements entry**, so the failure mode in §1.2 cannot recur silently.

### A4. Per-tactic system requirements

Author an explicit `system` block for every tactic, replacing
`_inferred_system_requirements` as the normal path. A low block should demand
high `defensiveCover`/`restDefence` and little `width`; a gegenpress should
demand `pressing` and `restDefence` and tolerate low `defensiveCover`.

Keep the inferred function as the fallback for catalogues that omit the
block (tests rely on it), but add the missing `Cautious` mentality entry to
its attack-duty table either way.

### A5. Extend exclusion groups to the whole XI

Make `RoleExclusionGroup.position` optional. When absent, the group counts
across all eleven slots. New groups to add:

- **Free roles** — at most one of `treq_st_attack`, `treq_amc_attack`,
  `treq_aml_amr_attack`, `eng_support`, `raum_attack` in the XI.
- **Cover centre-back** — as today, extended to any new Cover/Stopper role.
- **Inverted wing-backs** — at most one `iwb_*` alongside a defensive-minded
  DM, since both occupy the same space.

### A6. Expand to 40+ tactics

Fix the existing 25 first (§3), then add shapes and styles that are genuinely
distinct rather than re-skins. Candidates, chosen to exercise the unused
roles:

| Shape / style | Roles it unlocks |
| --- | --- |
| 4-2-3-1 Narrow (AMC × 3) | `ap_amc_support`, `am_attack`, `eng_support` |
| 4-4-2 Diamond (MC, no DM) | `ap_mc_attack`, `mez_attack` at MC |
| 4-3-3 False Nine | `f9_support`, `iw_attack` |
| Inverted build-up 4-3-3 | `iwb_dl_dr_defend/support/attack` |
| 5-4-1 / 5-2-3 | `nnfb_defend`, `wtm_support/attack` |
| 4-2-2-2 narrow box | `ss_attack`, `pf_support` |
| Gegenpress 4-3-3 with Pressing Forward | `pf_attack`, `pf_defend` |
| 3-1-4-2 | `cwb_dl_dr_support/attack` |
| Trequartista 4-3-1-2 | `treq_amc_attack` |
| Wide-overload 4-2-3-1 | `ap_aml_amr_support/attack`, `raum_attack` |

Two guard rails for an expansion this size:

- A **near-duplicate detector** test: no two tactics may share a formation
  *and* have role sets differing by fewer than N slots *and* have
  instruction sets differing by fewer than M entries. `tests/test_catalogue.py`
  already asserts "materially different complete tactics"; this makes that
  claim enforceable at 40+ rather than aspirational.
- Every new tactic must ship its justification text (§3) and its `system`
  block in the same commit. No tactic lands without them.

## 4. Workstream B — coherence and justifications

### B1. Fix the tactics whose football is wrong

Beyond the scale problems in §1.1, these are judgement calls to make
explicitly, each as its own reviewable commit (per `analytics/CLAUDE.md`, a
trait or weight change is a football hypothesis, not a bugfix):

- **`highpress_433`** fields `tm_attack` (Target Man) as the lone striker
  under `Much More Urgent Pressing` and `Shorter Passing`. Should be
  `pf_attack`, with Target Man at most an alternate.
- **`gegenpress_4231`** fields `af_attack`/`p_attack`, neither of which
  presses. Pressing Forward should be the default or an explicit alternate.
- **`counter_352_wingback`** pairs `Counter` with `Lower Tempo` *and*
  `Narrower` while fielding two wing-backs — three instructions pulling
  against each other and against the shape.
- **`possession_4141`** and **`vertical_tikitaka_433dm`** use asymmetric
  wide roles (`wm_support` one side, `winger_*` the other; `wb_*` one side,
  `fb_support` the other) with nothing in the catalogue explaining why.
  Either justify the asymmetry or make it symmetric.
- **Slot alternates** should be re-reviewed now that 32 more roles exist,
  using the trait-distance method in `analytics/CLAUDE.md` — *not* by name
  similarity. Only three alternate pairs exist today; several more are
  probably justified (e.g. `pf_attack`/`af_attack` in a pressing system),
  and some currently-pinned slots may deserve opening.

### B2. Justification data

Tactics already carry `style`, `description`, `whyGood`, `keyRequirements`
and `tags`, rendered by `rendering._tactic_notes`. Extend the schema with:

- `whyThisShape` — what the formation does structurally (where the numerical
  overloads are, which spaces it concedes).
- `whenToUse` / `whenNotToUse` — the manager-facing selection guidance.
- Per-slot `why` — one line per slot explaining why *that* role is in *that*
  tactic. This is the piece most obviously missing today: the Tactics page
  can tell you a Mezzala was picked, not why this system wants one.
- `instructionRationale` — a line per instruction tying it to the shape.

All of it is manager-facing commentary, not scoring input, so it stays
optional and older entries keep loading unchanged — the existing
`_tactic_notes` contract.

### B3. Surfacing

- Tactic detail page: `whyThisShape` and `whenToUse` near the top; per-slot
  `why` in the XI table next to each role.
- Tactics overview: `whenToUse` as a one-line hint per row.
- Where a shortfall is reported, name the instruction or requirement that
  caused it and the role that would fix it, rather than the raw
  `dimension x.x/y.y` string `_tactical_shortfalls` prints today.

## 5. Workstream C — per-tactic, per-role attribute weights

### C1. Data model

Defined in §2.3 and §2.4: the overrides live inside each tactic's own file,
as a tactic-wide `weights` block plus per-slot `weights` blocks, carrying
absolute `effectiveWeight` values that layer over the role's base weights.

**Sparse throughout.** An absent tactic, slot or attribute inherits. A
tactic with no `weights` anywhere scores exactly as it does today — which is
both the migration path and a test assertion.

### C2. Authoring — a soft seeded draft

**Decided: generate a first draft, deliberately gentle, and hand-tune from
there.** JSON is the source of truth; there is no CSV and no round-trip
generator (§2.6). The seed runs once, its output is committed as ordinary
data, and from that point the files are hand-owned.

#### What "soft" means, measured

"Small" needs a number, so the seed rule was prototyped against the current
catalogue on three synthetic 30-player squads. Bumping the attributes an
instruction implies, by a fixed delta on the 0–10 scale:

| Delta | Tactic score moves | Best-for-this-job changes | Quality of that change |
| --- | --- | --- | --- |
| +1 | 0.11 pts (max 0.37) | 2.4% of slot/role pairs | +0.36 pts |
| **+2** | **0.21 pts (max 0.70)** | **4.7%** | **+0.61 pts** |
| +3 | 0.25 pts (max 0.87) | 6.2% | +0.81 pts |
| +5 | 0.32 pts (max 0.94) | 9.8% | +1.02 pts |

Context for the scale: role weight totals average 113 across ~17 weighted
attributes, so +2 on three attributes redistributes roughly 5% of a role's
weight.

**+2 is the recommendation.** Around one slot decision in twenty changes,
each one a genuine improvement under that tactic's own stated priorities,
while tactic ranking barely moves — which is exactly the "take the tactics
into account but don't let them dominate" balance asked for.

#### Two cautions about reading the effect

- **Tactic score is the wrong instrument for judging this.** It moves 0.2
  points, because the score is a normalised weighted average and re-weighting
  shifts every candidate similarly. You cannot tune the emphasis by watching
  the headline number; judge it on *who gets picked*.
- **Raw XI churn overstates it.** A +2 nudge changes 1.35 of 11 starters on
  average, but measuring those swaps shows the newly-picked player is
  frequently no better even under the nudged weights — the XI is a global
  assignment, so one genuine upgrade cascades into several consequential
  moves. The honest measure is the per-slot one in the table above, which
  holds the assignment problem fixed. Build the review tooling around that,
  not around a diff of the eleven.

These are synthetic squads with uniformly random attributes; a real save has
specialists and will not reproduce these percentages exactly. Re-measure
against your own squad once the seed lands, before deciding whether +2 is
right.

#### Seed rules

Deliberately conservative — the mechanism is more capable than the draft
uses, and the extra capability is reserved for your hand edits:

1. **Tactic-wide only.** The seed writes one `weights` block per tactic and
   never a slot-level override. Slot-level stays a purely human decision, so
   every one in the tree is one you made.
2. **+2, clamped at 10.**
3. **Only attributes the role already weights above 0.** The seed never
   invents a requirement a role does not have — a Central Defender that
   ignores crossing keeps ignoring it. The file format permits introducing
   an attribute from zero (§2.4); the automated draft simply declines to.
4. **At most four attributes per tactic**, taken from the instruction and
   mentality mapping. A tactic that emphasises everything emphasises nothing.

A seeded tactic therefore carries three or four numbers in one block —
small enough to read in the diff and argue with, which is the point.

#### Telling seed from judgement

Extend `tools/tactic_weight_report.py` (§2.5) to mark each override as seed
default or hand-tuned, by magnitude and by whether a slot-level block
exists. Review then focuses on what you actually changed, and the draft
never quietly becomes indistinguishable from deliberate football judgement.

### C3. Plumbing — the derived-catalogue approach

The minimal-diff mechanism, which also serves workstream D:

```python
catalogue.for_context(tactic_key, opponent_profile) -> FootballCatalogue
```

Returns a catalogue whose `roles` carry re-weighted `attributes` but
**identical keys, positions and version**. That invariant is what makes it
cheap: `_system_fit`'s `catalogue.roles[...]` lookup, `role_keys_for_slot`,
the exclusion groups and the `role.catalogue_version == self.version` check
all keep working untouched, and every function already taking
`(catalogue, tactic)` works with no signature change.

Built lazily and memoised. Applies to the tactic-specific consumers —
`xi_selection`, `bench_selection`, `substitution_board`, `squad_depth`,
`weaknesses`, `selection_explanation` — and **not** to `role_matrix`,
`position_comparison` or `scouting`, per the decision to keep tactic-free
pages on base weights.

### C4. What this changes about the numbers

Weights are normalised by the role's total, so a score stays "% of the ideal
player for this job". Emphasising stamina raises the denominator too; scores
do not inflate. But the meaning shifts from *"% of the ideal Mezzala"* to
*"% of the ideal Mezzala in this system"*, and cross-tactic comparison
becomes a comparison of two differently-defined ideals. That is the right
model, and it must be said in the UI rather than left for the manager to
infer.

The tactic detail page's attribute contributions become tactic-specific;
label them so, and show base vs emphasised weight where they differ.

## 6. Workstream D — the opponent

### D1. Profile

`src/fm_analytics/analytics/opponent.py`, holding a frozen `OpponentProfile`
of six axes, each an integer −2…+2 defaulting to 0:

| Axis | −2 | +2 |
| --- | --- | --- |
| `quality` | much weaker | much stronger |
| `defensive_line` | deep block | high line |
| `pressing` | passive | heavy press |
| `attacking_width` | central threat | wide threat |
| `aerial_threat` | negligible | dominant |
| `pace_in_behind` | slow | very fast |

Six is a judgement call: enough to describe the scouting report you actually
get, few enough to set in seconds before a match. `OpponentProfile.neutral()`
is all zeros.

### D2. Declared effects

`OPPONENT_AXES` as reviewable data in the same spirit as
`_INSTRUCTION_REQUIREMENTS` — each axis declares, per step:

- **`system_demands`** — deltas to the tactic's balance minimums. Their pace
  in behind raises the `defensiveCover` a tactic must supply; their deep
  block raises `creativity` and `boxPresence` and lowers the value of
  `runners`.
- **`attribute_emphasis`** — multipliers scoped to a position group. Aerial
  threat raises `heading`/`jumpingReach`/`strength` for DC and GK; pace in
  behind raises `pace`/`acceleration` for the back line; their heavy press
  raises `composure`/`firstTouch`/`passing` for defence and midfield. **This
  is what makes the XI change, not just the ranking** — it is the same
  emphasis mechanism as C3, sourced from the opponent instead of the tactic,
  and composed with it.
- **`tag_affinity`** — small score deltas against tactic tags and mentality.
  A deep block penalises `counter`-tagged tactics and rewards `wing-play`
  and `crossing`; a stronger opponent rewards `Cautious`/`Defensive`.

### D3. Scoring

`assess_opponent_fit(tactic, roles, profile) -> SystemAssessment`, reusing
the existing type and the `active` convention. `SystemFitPolicy` gains
`opponent_weight` (proposed 0.20); `_system_fit` already excludes inactive
components, so **a neutral profile leaves every number byte-identical to
today**. That is a test, not an aspiration.

Reported as its own component alongside coherence and instruction fit, per
roadmap item 9's requirement that it never be folded into a global "best
tactic" number.

### D4. Plumbing and parity

`RecommendationPolicy` gains `opponent: OpponentProfile = neutral()`.
`build_recommendation_bundle`'s signature is unchanged, so the one-path rule
in `CLAUDE.md` holds automatically: the CLI gets `--opponent-<axis>` flags
and the web gets sliders, both feeding the same policy into the same
computation.

`SquadWebServer.bundle()` currently takes no arguments and caches on time
alone. It becomes keyed on the opponent profile, backed by a small LRU rather
than a single slot, so flicking a slider back and forth is free.
`_tactic_report_cache` already keys on `id(bundle)` and needs no change.

### D5. UI

Sliders on `/tactics` as a plain GET form (`?opp_aerial=1&opp_line=-2&…`):
the page stays read-only, bookmarkable, shareable, and works without JS.

The feature that makes it worth having is a **delta view** — for each tactic,
its rank and score against this opponent versus neutral, so the page answers
"what changes about my thinking against a deep block" rather than just
re-sorting silently. Plus a short "because" line naming the axis that moved
it, and a reset-to-neutral control.

Confidence framing matters: this is the manager's own estimate of the
opponent, so the page should say so plainly and not present the opponent-fit
component with the same authority as squad fit.

### D6. Towards automation

The eventual goal is deriving the profile from the opposition squad. The
manager-visible boundary applies unchanged: the profile may be computed from
scouted attributes and visible ranges, **never** from opponent Current or
Potential Ability. Keeping `OpponentProfile` as the single interface means
the automatic version substitutes for the sliders without touching scoring.

## 7. Cross-cutting

### 7.1 Performance

At 45 tactics a bundle is ~2.8 s (§1.7), and the slider turns that into an
interaction cost. Three mitigations, in order of value:

1. **Memoise role scores** on `(derived-role identity, player id)`. Role
   scoring is ~40% of the time and is repeated per tactic today even though
   most tactics share most role definitions. Per-tactic weights reduce but do
   not eliminate the sharing — key the memo on the derived role's identity,
   never on the tactic, or the win disappears.
2. **LRU the bundle by opponent profile**, so revisiting a setting is free.
3. **Consider pinning the *potential* pass to a neutral opponent.** The
   effective/potential double-run doubles cost; training targets are a
   squad-development question, not an opponent question. Worth deciding
   explicitly rather than paying for it by default.

Re-benchmark after each workstream. Per `CLAUDE.md`, measure the full bundle
against the real catalogue on a synthetic squad, not the three-player
fixture.

### 7.2 Tests

New invariants, each guarding a failure this plan found:

- No tactic carries an unsatisfiable system demand (§A2) — the key one.
- Every instruction used by a tactic has a requirements entry (§A3).
- Every role named by a tactic slot has non-empty system traits (§A1).
- A neutral opponent reproduces today's scores exactly (§D3).
- A tactic with no weight override scores identically to base weights (§C1).
- Opponent monotonicity: raising an axis never lowers the emphasis it is
  supposed to raise.
- Seeded tactic weights stay inside the soft band of §C2 — so a later
  hand-tune that leaves it is a visible, deliberate act rather than drift.
- Near-duplicate detection across the expanded catalogue (§A6).
- Existing CLI/web parity coverage extended to carry an opponent profile.

### 7.3 Documentation

Update `analytics/CLAUDE.md` (traits move to catalogue data; the derived-
catalogue mechanism; the exclusion-group extension), mark roadmap items 1b,
4 and 9 as in progress, and link this plan from `docs/README.md`.

## 8. Sequencing

Ordered so that nothing is tuned on top of a known-broken baseline.

| Phase | Work | Why here |
| --- | --- | --- |
| **0 — done** | **§2 data layout migration and retirements** | **Cheapest now: 25 small tactics, not 45 large ones. Also fixes the wheel-packaging bug before anyone installs one.** |
| 1 — done | A1 traits for all 65 roles, A2 scale recalibration, A3 missing instructions | Fixes §1.1–1.2. Everything downstream is measured against this. Do not skip ahead. |
| 2 — partly done | A4 per-tactic system requirements (done), A5 exclusion groups, B1 fix the existing 25 (reachability fixes done; see §2b) | Makes the current 25 correct before multiplying them. |
| 3 — done (40 tactics, 65/65 roles) | A6 expand to 40+, with B2 justifications authored alongside (31 now; see §2d) | Now safe: the load-time invariants from phase 1 catch a mis-authored tactic. |
| 4 — partly done | B3 surface justifications (done for the existing 25; better shortfall messages still to do) | The manager can now read why, which is also how you review phases 1–3. |
| 5 — done | C1–C4 per-tactic attribute emphasis (see §2f) | Needs a correct system model and a settled tactic list. |
| 6 | D1–D5 opponent model and slider | Reuses C3's emphasis mechanism; last per the roadmap's ordering advice. |
| 7 | 7.1 performance pass and re-benchmark | After the catalogue and scoring have stopped moving. |

Phase 0 is a pure refactor and should land on its own, proven lossless by the equality check in §2.9 — no football judgement changes in that commit.

Phases 1 and 2 are worth reviewing together before phase 3 begins: they
change every existing score, and the whole point is that you can see and
disagree with the football judgements.

## 9. Out of scope

- Automatic opponent profiling from the opposition squad (§D6 is the
  interface for it, not the implementation).
- Roadmap items 2 and 3 — nonlinear contributions and soft core-attribute
  floors. The data already exists in the role weights and is inert.
  They interact with workstream C and should follow it, not accompany it.
- Reconciling the two recruitment paths (`analytics/recruitment.py` vs
  `analytics/scouting.py`). Untouched here, and this plan deliberately keeps
  tactic emphasis out of both so it does not deepen that split.
- Whole-tactic familiarity (roadmap item 8).
