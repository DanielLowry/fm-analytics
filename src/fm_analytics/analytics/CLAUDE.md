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
`role_key`, and `FootballCatalogue.role_keys_for_slot` (`catalogue.py:183`)
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

## `_best_joint_role_state` (`xi_selection.py:737`) — read before editing

This is a beam search: it fills tactic slots one at a time (fewest
candidates first), and after each slot keeps only the best
`role_assignment_beam_width` partial teams by individual player/role score,
discarding the rest.

**The last slot is handled differently, on purpose.** A flat "keep the best
scorers" cut at the final slot would always keep whichever role scores best
*individually* — but the whole reason this search is "joint" rather than
per-slot-independent is to let a lower-scoring role choice win because it
makes the *team* better (covers a missing runner, adds width, satisfies an
instruction). So the final step buckets survivors by which role they'd use
in that slot and keeps the best few *per role*, not overall, before scoring
team coherence and instructions. If you flatten that back to a single
top-K cut, tests still pass at first glance and the code gets simpler and
faster — and then the optimiser silently stops making that trade-off. See
`tests/test_joint_role_system.py::test_joint_search_can_trade_individual_role_fit_for_system_coherence`,
which exists specifically to catch this regression.

If you need to make this faster, profile first — the last time this got
slow (a squad taking ~60s to score) it was this exact function, and the fix
that didn't break the test above still left real headroom (repeatedly
re-sorting the full candidate list at every step, not just once at the
end).

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
- `squad_depth.py` / `bench_selection.py` / `weaknesses.py` — all consume
  the XI evaluations `xi_selection.py` already produced. They shouldn't
  re-run tactic evaluation themselves.
