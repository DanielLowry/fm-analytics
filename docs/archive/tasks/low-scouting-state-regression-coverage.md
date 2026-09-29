# Low task: scouting-state regression coverage

> **Complete; archived 29 September 2026.** Built 28 September 2026. The *Status*
> section at the end records what was built and the decisions taken. Open
> work is listed in the [task briefs index](../../tasks/README.md).

**Active-plan support:** items 3–5.

**Prerequisite:** none. Restrict this task to domain/web fixtures and tests;
do not edit the currently changing sandbox or scouting-feed tools.

## Why we are doing this

Upcoming recruitment work will combine current and historical observations.
The scouting UI already distinguishes several states that are easy to collapse
accidentally: exact, range, unknown, not captured, and past knowledge. Locking
their visible behaviour down first gives later agents fast feedback without
requiring them to understand FM process-memory research.

## Scope

- Add small reusable test builders or fixtures for each visibility/history
  state used by the scouting list and player report.
- Add focused assertions for the label and score behaviour of each state.
- Cover HTML escaping in player names, clubs, and historical-status text.
- Document any current inconsistency discovered; do not silently redefine the
  state to make a test pass.

Production changes are allowed only for an obvious presentation bug whose
expected behaviour is already stated in `docs/scouting-workspace.md` or the
active plan. Escalate ambiguous behaviour instead of choosing new semantics.

## High-level change outline

1. Consolidate repeated scouting candidate construction in
   `tests/test_web_scouting.py` only where it makes each state clearer.
2. Create cases for current exact, current range, captured unknown, uncaptured,
   carried historical, and dropped-from-reports players.
3. Assert both the list cell and individual player report wording for each
   state.
4. Assert that unknown/uncaptured states do not receive invented numeric role
   or tactic scores.
5. Run the scouting analytics and web test modules, then the full suite.

## Out of scope

- Reading the player-knowledge database.
- Changing candidate-feed JSON or low-level tools.
- Choosing staleness thresholds.
- Adding new scoring or filtering behaviour.

## Success criteria

- Every supported state has a named fixture and an assertion on its rendered
  label.
- Exact values and ranges retain their numeric content.
- Captured unknown is distinguishable from never captured.
- Historical knowledge shows its observation date and cannot appear current.
- A dropped player is not described as never known.
- Unknown, uncaptured, and historical-only cases never expose a hidden raw
  value.
- User-controlled text is escaped.
- Existing production behaviour changes only where a cited requirement makes
  the correction unambiguous.
- Focused tests and the full test suite pass.

## Likely code and tests

- `tests/test_web_scouting.py`
- `tests/test_scouting.py`
- possibly a small shared builder in `tests/web_support.py`
- `src/fm_analytics/web/scouting_render.py` or
  `src/fm_analytics/web/scouting_report.py` only for an unambiguous bug fix

## Status: built (28 September 2026)

`tests/test_web_scouting_states.py` (split out of `test_web_scouting.py` for
the line cap). It has one named builder per state: current exact, current
range, captured unknown, never captured, carried historical (from the
knowledge history, not in the current feed) and dropped from scout reports.
Each is asserted on both the list row and the player report. It also checks
escaping of names, clubs, nationality, facts and the historical club line.
No production code changed.

Two inconsistencies were found and escalated rather than fixed, as the brief
asks:

1. **Min / Median / Max for an unknown or never-captured player** still render
   0.0 / 50.0 / 100.0. That is the documented all-unknown bound in
   `docs/scouting-workspace.md`, but item 3 says such a player is "not given
   an invented score". Item 3's trial priority is now withheld for a player
   with no visible attributes
   ([trial-scenario semantics](senior-trial-scenario-semantics.md)). The
   plain ranking columns are unchanged.
2. **The list's attribute-sheet group headings are always empty.** In
   `scouting_render.attribute_sheet` the per-row tooltip reuses the loop
   variable `title`, so every `<h4>` is blanked. When a group's last
   attribute is historical, the heading prints the tooltip text instead. The
   player report's own sheet renders the headings correctly. **Still open**:
   it is a one-line rename, not yet made.
