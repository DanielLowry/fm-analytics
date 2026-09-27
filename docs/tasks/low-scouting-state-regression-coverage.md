# Low task: scouting-state regression coverage

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
