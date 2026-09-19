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

## Where role choice actually happens

A tactic slot's role is pinned by default. `TacticDefinition.slots` name a
`role_key`, and `FootballCatalogue.role_keys_for_slot` (`catalogue.py:154`)
only ever tries that role plus whatever a slot's own `roles` array in
`catalogue.json` explicitly lists as alternatives — there is no automatic
fallback that opens a slot up on its own. This is deliberate: which role a
slot plays is usually what makes a tactic *that* tactic (a deep playmaker
vs. a ball-winner as the DM defines two different systems), so a slot stays
single-role unless a human decided otherwise for it specifically.

The catalogue currently declares alternatives for exactly three role pairs
— `cd_defend`/`cd_cover`, `af_attack`/`p_attack`, `dlf_support`/`cf_support`
— chosen because their `tactical_system.py` trait contributions are nearly
identical (see `_DEFAULT_ROLE_TRAITS`): swapping one for the other changes
which specific player profile fits the slot, not what the team's system
does. Contrast `dm_defend`/`dm_support`, which looks like a similar swap
but trades off primary `defensiveCover`/`ballProgression` contribution by a
large margin — a genuine screen-vs-distributor identity choice, correctly
left pinned. Before adding a new alternate pair anywhere in the catalogue,
check the trait distance the same way rather than by eye; it's an easy
mistake to make a system-identity role "flexible" because two roles sound
similar in name.

## Role versions and player assignment — read before editing

`_best_role_version` first enumerates every role combination that a tactic
explicitly permits. This is deliberately small: slots are pinned by default,
and a slot only has alternatives named in its `roles` array. Each complete
role version receives its own team-coherence and instruction assessment.

For a fixed role version, a player's score for a slot is independent of the
other selected players. The remaining constraint is simply that a player
cannot fill two slots. `_maximum_total_assignment` therefore uses an exact
assignment solver rather than enumerating XIs or keeping a beam of partial
ones. `_best_full_fit_assignment` repeats that solve at each possible weakest
slot score, which preserves the mean/weakest-slot blend exactly.

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
  scoring, off explicit per-role trait weights (`_DEFAULT_ROLE_TRAITS`) and
  per-instruction requirements (`_INSTRUCTION_REQUIREMENTS`). These are
  declared, reviewable football hypotheses, not tuned/learned weights —
  changing one is a football judgment call, worth calling out as such in
  the commit rather than treating as a pure bugfix.
- `role_weights.py` — loads per-role, per-attribute weights from
  `data/role_weights_v2.json` (generated from a CSV via
  `tools/csv_to_role_weights.py`). Loaded once at import time into
  `catalogue.MVP_CATALOGUE`; don't call `load_role_weights` per-request.
  Only `effective_weight` is actually consumed by scoring — the rest of
  `AttributeWeightConfig` (soft floors, duty modifier) is validated but
  inert data, reserved for `docs/tactical-system-roadmap.md` items 2-3.
  Don't assume a nonlinear or soft-threshold effect is live because the
  field exists; check whether `catalogue._attributes_from_weights` reads it.
- `squad_depth.py` / `bench_selection.py` / `weaknesses.py` — all consume
  the XI evaluations `xi_selection.py` already produced. They shouldn't
  re-run tactic evaluation themselves.
