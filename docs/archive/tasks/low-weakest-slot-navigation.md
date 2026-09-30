# Low task: weakest-slot navigation

> **Complete; archived 30 September 2026.** Built 30 September 2026. The *Status*
> section at the end records what was built and the decisions taken. Open
> work is listed in the [task briefs index](../../tasks/README.md).

**Active-plan item:** 3, worth-a-trial ranking against the weakest slots.

**Prerequisite:** analytics/reporting supplies a prepared list of weak slots
and the exact scouting filter parameters for each link. The implementer must
not choose which slots count as weak. **Met on 28 September 2026:**
`reporting.weakest_slots(bundle)` returns ordered `WeakSlot` rows with
`tactic_key`, `position`, `role_key` and `concern`. Those map onto the
`tactic`, `position` and `role` query parameters `_scouting_filters` already
reads (see the
[weakest-slot service](medium-weakest-slot-service.md)).
The link can only switch on a **Trial priority** sort once the
[trial-priority list](../../tasks/medium-trial-priority-list.md) adds it to the
web's tactic-mode sorts. Until then, link to the list without that sort.

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

## Status: built (30 September 2026)

`/scouting` renders a **Weakest slots** panel between the recruitment
introduction and the filters.
`web/scouting_pages.py::_weak_slots_block` asks
`reporting.weakest_slots(self.server.bundle())` for the rows -- it selects and
scores nothing itself -- and `web/scouting_render.py::weakest_slots_panel`
lays them out. Tests are `tests/test_web_weakest_slots.py`, a new module
because `test_web_scouting.py` is already near the line cap.

Decisions taken:

- **One URL builder.** `web/rendering.py::_scouting_href(query, **updates)` is
  now the only place a `/scouting` link is assembled; `_scouting_tab_nav` uses
  it too (byte-identical output to what it did before). Naming a parameter
  replaces it, naming it `None` drops it, and everything unnamed is carried
  over -- so a navigation link cannot silently reset the manager's other
  filters.
- **What the link sets and clears.** It supplies `tactic`, `position` and
  `role` from the `WeakSlot`, and deliberately clears `name`, `sort` and
  `dir`: a name search is looking for somebody else, and the sort belongs to
  the table the manager is about to see, not the one he is leaving. `view`,
  market, age, value, knowledge/visibility, `everScouted`,
  `includeRawPositions`, `showRejected`, `limit` and `fact.*` are all kept.
  `WeakestSlotLinkTests` documents both halves.
- **No trial-priority sort yet**, as the prerequisite requires. The link
  carries no `sort` at all today, which also leaves room for the
  [trial-priority list](../../tasks/medium-trial-priority-list.md) to add its
  `sort=trial_priority` to these links when the sort exists; the link already
  owns `sort`, so that is a one-line addition there.
- **Slot and position both shown when they differ** (`DCL (DC)`), and the role
  is the starter's own role from the prepared row rather than the slot's
  configured role. The concern is words -- "Starter concern:", "Cover
  concern:" -- beside the weakness report's own message, never colour alone.
- **Two empty states, one panel.** No weak slots at all says "No weak slots
  in the tactics in play right now."; a squad that cannot be analysed yet
  says why (`Weakest slots need a complete current squad: ...`) and keeps the
  panel, so the page's shape does not depend on squad completeness.
- **Page furniture only.** The panel lives in `_scouting_body`, not in
  `_scouting_results_block`, so `/scouting/results` is unchanged and typing
  does not re-render it.

Checked against the shipped fixtures rather than a capture in `data/`:
following a link is verified by rendering the destination page and asserting
its form has that tactic, position and role selected, and by parsing the href
back through the real `_scouting_filters`. `tests/test_web_weakest_slots.py`
and the full suite pass (the two `test_line_caps` failures come from
`frontend/node_modules` and predate this work).
