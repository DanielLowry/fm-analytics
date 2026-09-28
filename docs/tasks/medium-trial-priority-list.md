# Medium task: trial-priority list

**Active-plan item:** 3, worth-a-trial ranking against the weakest slots.

**Prerequisites:** the [trial scenario semantics](senior-trial-scenario-semantics.md)
are accepted (median scenario, flags and priority value), and the
[weakest-slot service](medium-weakest-slot-service.md) is merged.

## Why we are doing this

Scouting and trial capacity is the manager's binding constraint. This brief
turns the agreed semantics into the list the manager actually works from:
realistic, gettable candidates ordered by how likely a trial is to pay off.

## Scope

- A **Trial priority** sort on `/scouting` in tactic and **My tactics** modes.
- The median scenario shown beside floor, estimate and ceiling, and the
  **could start** and **could be first cover** flags shown as text.
- The unknown count for each row (already on the assessment as
  `unknown_attributes`).
- Players with no visible attributes stay under **Scout first**, grouped by
  the weakest slot they could fill, with no score.
- A visible statement that the median is for choosing whom to look at, never
  whom to sign, worded as the semantics brief fixes it.

## High-level change outline

1. Add the sort key beside the existing ones in `sort_tactic_assessments`, or
   in the multi-tactic equivalent if that has landed. Read the priority value
   from the semantics work; do not compute it in the renderer.
2. Apply the agreed default realistic/gettable filter state when this sort is
   chosen, without discarding the user's other filters.
3. Add a pure function that groups no-visible-attribute candidates by weakest
   slot, using the existing position-eligibility rules (including
   `include_raw_external_positions`).
4. Render in the scouting modules, reusing the existing band formatting so
   single- and multi-tactic figures cannot read differently.
5. Tests for ordering, ties, missing values, grouping, flags and escaping.

## Out of scope

- The median formula, flag definitions or priority value.
- Choosing weakest slots.
- The weakest-slot header links; the navigation brief owns those.

## Success criteria

- Sorting is deterministic, and rows with no priority value go last, as other
  sorts already do.
- A player with no visible attributes never shows a priority number.
- Flags match the semantics brief's worked examples.
- Existing sorts and their results are unchanged.
- Together with the navigation brief: one click goes from "Wing Play 4-4-2 is
  weakest at ML" to realistic ML targets ordered by trial priority.
- The disclaimer is present wherever the median is shown.
- Focused tests and the full suite pass.

## Likely code and tests

- `src/fm_analytics/analytics/tactic_scouting.py`
- `src/fm_analytics/web/scouting_pages.py`, `scouting_render.py`
- `tests/test_tactic_scouting.py`, `tests/test_web_scouting.py`
