# Analytics

Role and tactic scoring, the football catalogue, squad depth, and weaknesses.
This is where a "recommendation" actually gets computed — `reporting.py`
one level up just calls into here once and hands the result to the CLI and
web view unchanged.

## The manager-visible boundary

Every score must be derivable from data a human manager could see in-game:
known attribute values, scouted min/max ranges, or "unknown" (see
`Visibility` in `fm_analytics.domain`). Never let a hidden value (Current
Ability, Potential Ability, true match-engine weights) leak into a score,
even as a tie-breaker or a "just for now" shortcut. This is a hard product
requirement, not a style preference — the whole point of the tool is that
its numbers are things the manager could in principle have worked out by
hand.

## Where the data lives

`data/catalogue.json` (version, exclusion groups, notes), `data/roles/<pos>.json`
(one file per position group: role identity *and* attribute weights together)
and `data/tactics/<key>.json` (one file per tactic; the file name must equal
the key). Discovery is a sorted glob, so adding a tactic is adding a file. The
catalogue has a single version, in `catalogue.json` — never put a version in a
file name. A tactic file also carries manager-facing justification text
(`whyThisShape`, `whenToUse`, `whenNotToUse`, `instructionRationale`, and a `why`
on each slot); it is not scoring input, and it must be kept in step with the
roles, alternates and instructions it describes. The wheel picks these files up from the package tree; don't
enumerate them in `pyproject.toml`.

## No ignored config

The loader rejects any key it does not read (roles, tactics, slots, system blocks,
exclusion groups, the catalogue file), naming the key and listing what is
allowed. That is deliberate: config that nothing reads only misleads whoever
edits it, and a misspelled key (`whyThisShap`) would otherwise be dropped
silently. Do not add a field "for later"; add it with the code that reads it. (A
per-attribute duty modifier and soft-floor table once shipped in the role files
unread, and were removed.)

## Where role choice actually happens

A tactic slot's role is pinned by default. `TacticDefinition.slots` name a
`role_key`, and `FootballCatalogue.role_keys_for_slot` (`catalogue.py:154`)
only ever tries that role plus whatever a slot's own `roles` array in
the tactic's own file under `data/tactics/` explicitly lists as alternatives — there is no automatic
fallback that opens a slot up on its own. This is deliberate: which role a
slot plays is usually what makes a tactic *that* tactic (a deep playmaker
vs. a ball-winner as the DM defines two different systems), so a slot stays
single-role unless a human decided otherwise for it specifically.

The catalogue declares alternatives for six distinct role sets:
`cd_defend`/`cd_cover`, `af_attack`/`p_attack`, `dlf_support`/`cf_support`,
`cm_support`/`b2b_support`, the one three-role set
`dlf_support`/`pf_support`/`cf_support`, and `pf_attack`/`af_attack`. All but
the last are chosen because their `tactical_system.py` trait contributions are nearly
identical (see each role's `system` traits in `data/roles/`): swapping one for the other changes
which specific player profile fits the slot, not what the team's system
does. `pf_attack`/`af_attack` (only in the two gegenpress tactics) is the
exception: pressing differs by about 1.2, so choosing Advanced Forward costs
that tactic instruction fit. It is a deliberate fallback for a squad with no
pressing forward, not an interchangeable pair. Contrast `dm_defend`/`dm_support`, which looks like a similar swap
but trades off primary `defensiveCover`/`ballProgression` contribution by a
large margin — a genuine screen-vs-distributor identity choice, correctly
left pinned. Before adding a new alternate pair anywhere in the catalogue,
check the trait distance the same way rather than by eye; it's an easy
mistake to make a system-identity role "flexible" because two roles sound
similar in name.

## Illegal role combinations

Slot alternatives are chosen independently, so a tactic can name the same
role in two slots on one line. `data/catalogue.json`'s `exclusiveRoleGroups` rules
those out: each group names roles of which at most one slot may play, at one
position or, with no `position`, anywhere in the eleven. Three groups ship
today: **Cover centre-back** (`cd_cover`, `bpd_cover`, `nncb_cover`) and
**Stopper centre-back** (`cd_stopper`, `bpd_stopper`, `nncb_stopper`), both
scoped to DC, and **Free roles** across the whole XI (the three Trequartistas,
Enganche, Raumdeuter). Roles in a
group are the ones that only make sense alongside a partner who isn't in it.
`_best_role_version` skips any role version that breaks a group, and
`FootballCatalogue` refuses to load a tactic with no legal version. When a new
Cover or Stopper role is added at DC, put it in the matching group.

## Per-tactic attribute emphasis

A tactic's `attributeEmphasis` is a list of blocks that shift what it asks of
its players: `{"attributes": {"stamina": 2}}` means +2 on each role's
stamina weight, not stamina 8 for everybody. If a role has no base weight for
that attribute, it starts from zero: positive emphasis therefore introduces a
tactic-specific requirement. A
block may carry `positions` (`["DL", "DC", "DR"]`) to reach only slots at those
positions; without it the block covers the whole team. **Every block that covers
a slot is added together**, along with the slot's own `attributeEmphasis`, and
the total is clamped to 0-10. Positions are slot positions, not slot keys
(`"DC"`, not `"DCL"`), and naming one the tactic does not field is an error.
Loading the catalogue rejects unknown attribute names, while known attributes
may be introduced on any covered role.

`catalogue.for_tactic(key)` returns the catalogue with roles re-weighted for one
tactic, keeping every key, name, position, system trait and the version, so
lookups and exclusion groups keep working. `catalogue.for_context(key,
extra_emphasis=...)` is the same thing with further blocks layered on top, which
is how an opponent reaches player scoring (see "The opponent" below); with no
extra blocks it *is* `for_tactic`, cache included. Score through
`catalogue.role_for_slot(slot, role_key)`, never `catalogue.roles[...]`, anywhere
a slot is in hand.

**Derive a view once, and never pass a derived catalogue to something that
derives its own.** Each per-tactic entry point (`evaluate_tactic`,
`select_bench`, `build_substitution_board`, `assess_weaknesses`,
`explain_tactic_selection`) calls `for_context` itself, so callers hand it the
plain catalogue. Deriving twice for the same tactic applies its emphasis
*twice*: the deltas are recomputed from the unchanged `TacticDefinition` and
added to already-emphasised weights. This was a real bug —
`explain_tactic_selection` derived a view and then passed it into
`evaluate_tactic_with_forced_assignment`, which derived again, so every
counterfactual score in the "why this player" alternatives was computed at
double emphasis. Fixed, and guarded by
`tests/test_opponent_integration.py::NoDoubleApplicationRegressionTests`.

The blocks were seeded once by `tools/seed_tactic_emphasis.py` and are now
hand-owned; re-running it discards tuning unless you pass `--force`. Keep the
deltas soft (the shipped seed is at most +2, and a test enforces that band) —
the emphasis is meant to separate close candidates, not to overturn what a
role fundamentally asks for. There is deliberately no attribute-count cap on a
block: a tactic may name every genuine requirement. The seed was whole-team only;
three tactics (`balanced_442`, `balanced_433dm`, `vertical_442`) have since been
given hand-authored position-scoped blocks. No slot-level block is seeded and a
test enforces that, so every one in the tree is deliberate.

Tactic-free surfaces (the Squad roster, Roles, Scouting) deliberately stay on
base weights, so a player's best role does not move between pages.

## Attribute taper

A tactic may declare `attributeTaper`: a list of `{"attribute": "passing",
"taperBelow": 12, "positions": ["MC"], "roles": ["dlp_mc_support"]}`.
`positions` and `roles` are both optional filters. If both are present, both
must match; with neither, the taper covers the whole team. Role scope can
distinguish two jobs at the same position and can distinguish alternate roles
inside one flexible slot.
Below the level a player's slot score is multiplied by
`max(0.5, 1 - 0.06 * shortfall)`; at or above it he is untouched. The name is
deliberate: this is a **taper, not a minimum**. There is no cliff and nobody is
ruled out. Several tapers multiply, floored at 0.35 so no one is scored to zero.
`taperBelow` is a whole number 2-20; naming an unfielded position, a misspelled
attribute, an unused role, an empty position/role intersection, or overlapping
tapers for the same attribute and exact slot/role is an error.

Why it exists: a weighted average can never say "this tactic does not work
without passing" (a midfielder on passing 4 costs ~8% of his score however much
the role values passing). Emphasis moves a weight; a taper scales the finished
score.

**Calibration to know about.** The maximum score is 100, so however good a short
player's other attributes are, a big enough shortfall cannot be overcome. Against
a rival on 60: 3 points short needs 73, 5 short needs 86, 6 short needs 94, and 7+
is impossible. So the defaults are "heavy but survivable" up to about 5 points
short and behave as a bar beyond that. The knob is
`attribute_taper.AttributeTaperPolicy` (rate, single floor, combined floor); it is
not yet part of `RecommendationPolicy`, so it is a default argument, not a UI
setting.

The taper is applied per player, slot and candidate role, independent of the
other ten, which keeps the exact assignment in `assignment_solver` exact. It
reaches selection,
bench, substitution cover, explanations, and the depth/weakness report (starter
and cover are both tapered, or a penalised starter would look better than his
cover). A group rule such as "at least one midfielder with passing 12" would
couple players and is deliberately not supported.

## The opponent

`opponent.py` holds an `OpponentProfile`: six sliders, each an integer -2..+2,
all 0 by default. It is the manager's **own estimate** of the opposition, never
derived from anything hidden — `quality` in particular is relative to *us*,
which only the manager can judge, so it is set, not computed. Roadmap item 9 and
the upgrade plan's workstream D are the background.

An opponent acts through exactly two channels, both declared as reviewable data
in `AXIS_DEFINITIONS` in the same spirit as `_INSTRUCTION_REQUIREMENTS`:

- **`EmphasisRule`** — attribute emphasis blocks scoped to positions, composed
  with the tactic's own via `for_context`. This is what changes *who is picked*
  (an aerial threat raises `heading`/`jumpingReach`/`strength` for DC).
- **`FloorRule`** — absolute minimums the eleven's roles must jointly supply,
  scored by `assess_opponent_fit` and reported as a fourth component alongside
  coherence and instruction fit (`SystemFitPolicy.opponent_weight`, 0.20).
  Absolute, **not** a delta on each tactic's own minimums: adding to a
  gegenpress's deliberately low `defensiveCover` and a low block's high one
  would penalise both, where a shared floor correctly only bites the tactic
  with no slack.

**A neutral profile is provably inert.** It produces no blocks and no floors, so
`for_context` returns the plain `for_tactic` view and `assess_opponent_fit` is
`active=False`, dropping out of the blend exactly as coherence does for a tactic
with no requirements. `tests/test_opponent_integration.py` asserts byte-identical
results — evaluation, ranking, bench, substitution board, weakness and depth
reports — with and without an explicit neutral profile.

**Adding a slider** is two edits, both pure data: a field on `OpponentProfile`,
and its `OpponentAxis` entry. `_check_profile_matches_axes()` runs at import and
refuses to load if either half is missing, so a slider cannot silently do
nothing. The shape suits another *scalar* axis; a categorical signal ("they play
a back three") would need its own mechanism rather than being forced into -2..+2.

**Two things to know before tuning the numbers.**

- Floors must stay reachable. The first draft was on the wrong scale and 40 of
  42 tactics could not meet it — the same failure `test_tactical_calibration.py`
  exists to prevent. `tests/test_opponent.py::ReachabilityTests` now guards every
  axis and setting against what the catalogue can actually supply.
- **The blended score is not monotonic in opponent difficulty**, and that is not
  a bug. Opponent fit, like coherence and instruction fit, measures whether the
  *roles* clear a bar — not whether your players are good. For a weak squad it
  can sit well above `xi_score`, so activating it can raise the total even
  against a harder opponent. Explain "this got harder" from the component, never
  from the headline number.

`fm-analytics` exposes one `--opponent-<axis>` flag per axis, generated from
`AXIS_DEFINITIONS`, so a new slider gets a flag with no change in `cli.py`.

Not built yet: the `/tactics` sliders and the delta view (plan D5). **Before
building them, `SquadWebServer.bundle()` must be keyed on the profile** — it
caches on time alone today, so a slider would serve the previous opponent's
answer for the length of the TTL. That is a correctness fix, not an
optimisation.

One presentation trap the CLI already handles: an axis with emphasis but no
floors (`aerial_threat`) changes who is picked while leaving opponent fit
inactive, so **no opponent score appears at all**. Say so explicitly, or a
manager sets the slider, sees no new number and concludes it did nothing.

Scouted ranges follow the observation band (penalised at the low end, not the
high); an unknown attribute is the scale minimum centrally, as everywhere.

## Role versions and player assignment — read before editing

`_best_role_version` first enumerates every role combination that a tactic
explicitly permits. This is deliberately small: slots are pinned by default,
and a slot only has alternatives named in its `roles` array. Each complete
role version receives its own team-coherence and instruction assessment.

For a fixed role version, a player's score for a slot is independent of the
other selected players. The remaining constraint is simply that a player
cannot fill two slots. `assignment_solver._maximum_total_assignment` therefore uses an exact
assignment solver rather than enumerating XIs or keeping a beam of partial
ones. `_best_full_fit_assignment` repeats that solve at each possible weakest
slot score, which preserves the mean/weakest-slot blend exactly.

**That repeat is where the time goes, and it is worth understanding before you
try to optimise anything here.** An assignment algorithm maximises a *total* and
cannot also maximise a *minimum*, so the 35% weakest-slot term in
`TacticFitPolicy` is handled by sweeping the floor: solve "best total with no
slot below X" for every candidate X, keep the best blend. That turns one solve
per role version into ~42, and accounts for roughly half of a full run (22,446
solver runs in the benchmark). The solver itself is fast; it simply runs a great
many times. So **changing the mean/weakest blend also changes the cost profile**
— relevant to roadmap item 5, which proposes replacing that objective. Measured
numbers, method and the ranked mitigations are in
[tactical-model-upgrade-plan.md](../../../docs/tactical-model-upgrade-plan.md)
§7.1; don't restate them here, they drift.

Do not collapse this into greedy "best player per slot" selection: it must
still resolve the case where the same player is best at two jobs. Do not
discard role versions before their system score is assessed either; see
`tests/test_joint_role_system.py::test_joint_search_can_trade_individual_role_fit_for_system_coherence`.

This approach is exact only while team-system scoring depends on selected
roles, not on particular player pairings. If a future feature adds a
player-A-with-player-B interaction, revisit the optimiser rather than
silently treating it as independent.

## Everything else in here

- `tactical_system.py` — team-balance ("coherence") and instruction-fit
  scoring, off explicit per-role `system` traits (in the role files) and
  per-instruction requirements (`_INSTRUCTION_REQUIREMENTS`). Traits supply
  and instruction demands share one scale; `tests/test_tactical_calibration.py`
  fails a tactic whose demands no legal XI can meet. These are
  declared, reviewable football hypotheses, not tuned/learned weights —
  changing one is a football judgment call, worth calling out as such in
  the commit rather than treating as a pure bugfix. `assess_demands` is the
  shared "how fully do these roles meet these minimums" scorer; instruction fit
  and opponent fit are both built on it, so they cannot drift apart.
- `opponent.py` — the manager-set opponent profile and its declared effects;
  see "The opponent" above. Imports from `catalogue`/`tactical_system` and is
  imported by the tactic-specific entry points, so it must not import them back.
- `role_weights.py` — validates per-role attribute weights, which are authored
  inline in each role's entry under `data/roles/<position>.json` as a plain
  `{"passing": 9}` map (one file per position group; the JSON is the source of
  truth, there is no CSV). Loaded once at import time into
  `catalogue.MVP_CATALOGUE`. Scoring is linear in these weights.
- `squad_depth.py` / `bench_selection.py` / `weaknesses.py` — all consume
  the XI evaluations `xi_selection.py` already produced. They shouldn't
  re-run tactic evaluation themselves.
