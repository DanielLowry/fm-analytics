# Low task: weakest-slot navigation

**Active-plan item:** 3, worth-a-trial ranking against the weakest slots.

**Prerequisite:** analytics/reporting supplies a prepared list of weak slots
and the exact scouting filter parameters for each link. The implementer must
not choose which slots count as weak.

## Why we are doing this

The depth and weakness reports can identify where the pinned tactics need help,
but the manager currently has to reproduce that need manually on the scouting
page. A small navigation block should turn “Wing Play is weak at ML” into the
corresponding filtered candidate list in one click.

## Scope

- Render a **Weakest slots** block near the top of `/scouting`.
- Show tactic, slot/position, role, and whether the concern is the starter or
  cover, exactly as supplied by the prepared result.
- Link each entry back to `/scouting` with the supplied position, role, tactic,
  and trial-priority filters.
- Preserve unrelated user-selected filters where doing so does not contradict
  the selected weak slot.
- Show a calm empty state when no weak-slot data is available.

## High-level change outline

1. Add a small URL-building helper beside the existing scouting filter/query
   helpers rather than concatenating query strings in HTML.
2. Render the prepared weak-slot rows without recalculating weakness in the
   handler or template helper.
3. Reuse existing position and role labels.
4. Add round-trip tests: generate a link, parse it through the real scouting
   filter parser, and assert that it selects the intended tactic/position/role.
5. Add HTML tests for starter weakness, cover weakness, special characters,
   and the no-data case.

## Out of scope

- Selecting or ranking weak slots.
- Implementing median-scenario gain or trial-priority scoring.
- Inventing a score for candidates with no visible attributes.
- Changing weakness analytics.

## Success criteria

- Every rendered link parses to the intended existing filter state.
- Clicking a weak slot narrows candidates to its supplied tactic, position,
  and role and activates the supplied trial-priority sort.
- Existing compatible filters are retained and contradictory ones are removed
  deliberately, with tests documenting which.
- Empty or unavailable weak-slot data does not break the scouting page.
- Link text remains understandable without colour or tooltip content.
- Focused web tests and the full test suite pass.

## Likely code and tests

- `src/fm_analytics/web/scouting_pages.py`
- `src/fm_analytics/web/scouting_render.py`
- `src/fm_analytics/web/scouting_script.py` only if client-side controls need
  to recognise an existing server-side filter
- `tests/test_web_scouting.py`
