# Low task: named depth evidence

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)). Old
review item 2.3. Item 2 covers the recruitment side; this is the `/depth` page
itself.

**Prerequisite:** the active plan schedules this item. A reviewer should
confirm the presentation rule below before work starts.

## Why we are doing this

`/depth` (`_depth_page` in `web/auxiliary_pages.py`) lists each position with a
status, "weak in n / m tactics" and the weakness kinds. It names no players.
The manager has to open other pages to find out who the weak starter or thin
cover actually is, even though the bundle already holds that detail.

## Data already in the bundle

- `bundle.squad_depth.per_tactic[tactic_key].depth`: one `SlotDepth` per slot,
  with `slot` (`TacticSlot`, including `position`), `starter`
  (`SlotAssignment`), `available_backups`, `temporarily_unavailable` and
  `occupied_starter_cover` (each a `DepthCandidate` with `player_name` and
  `role_score`).
- The same report's `weaknesses`, including `shared_cover`.
- `bundle.primary`, and `bundle.planning_depth` for the tactics in scope.

## Presentation rule (fixed by this brief)

For each position row, show the **primary tactic's** slot or slots at that
position: starter and fit, first available backup and fit, and whether that
backup is also the first cover somewhere else (a `shared_cover` weakness). If
the primary tactic does not use the position, say so in text. Below each row,
a collapsible `<details>` block lists the same evidence for every tactic in the
current scope (pinned, or all with `?scope=all`).

If a reviewer prefers a different rule, change this brief first. Do not pick
another one during implementation.

## High-level change outline

1. Add render helpers in or beside `auxiliary_pages.py`. They read the bundle
   only.
2. Reuse the existing name-link and score-band helpers. Link each name to
   `/squad/player/<id>`.
3. Show the two fits side by side. If a drop-off figure is wanted, add it as a
   small reporting helper, not arithmetic inside the renderer.
4. Tests: pinned and unpinned bundles, a position the primary tactic does not
   use, no available backup, shared cover, and HTML escaping.

## Out of scope

- Changing weakness analytics or the policy ratios.
- Choosing the "representative" tactic by any rule other than the one above.

## Success criteria

- Every named starter and first backup matches the per-tactic report for the
  same bundle.
- A position without cover says so in text, not only with colour.
- Existing rows, conclusions and the `?scope=all` toggle are unchanged.
- Names are escaped.
- Focused web tests and the full suite pass.

## Likely code and tests

- `src/fm_analytics/web/auxiliary_pages.py`
- `src/fm_analytics/web/rendering.py` for any shared helper
- `tests/test_web_server.py` or `tests/test_pinned_tactics.py`, where the
  existing depth-page tests live
