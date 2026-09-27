# Low task: present multi-tactic scouting results

**Active-plan item:** 2, trialist review across pinned tactics.

**Prerequisite:** the
[multi-tactic scouting service](medium-multi-tactic-scouting-service.md) returns
a stable, already-computed presentation model. Do not start by calling tactic
analytics from a renderer.

## Why we are doing this

Once the service can assess a player across the manager's tactics, the scouting
list and player report must make the comparison readable. This task is kept to
presentation so it can be delegated without asking the implementer to decide
football or uncertainty semantics.

## Scope

- Add a **My tactics** view or section to `/scouting`.
- Add the same summary above the existing single-tactic detail on
  `/scouting/player/<id>`.
- Show each pinned tactic in configured order with best job, gain bands,
  starting/replacement status, and cover status supplied by the service.
- Add sort controls for the options already supported by the service.
- Preserve existing filters and toggles in generated links.

## High-level change outline

1. Add focused render helpers in the scouting web modules; do not expand the
   HTTP server or generic rendering module with feature-specific logic.
2. Render unavailable data as a neutral dash or explicit “not assessed”, not
   as zero.
3. Use the existing wording and formatting helpers for score bands so the
   single- and multi-tactic views cannot imply different meanings.
4. Keep table headings accessible and include tactic names in text rather than
   relying only on colour or icons.
5. Add HTML tests using a prepared service result with at least two tactics:
   the candidate starts in one and is cover in the other.

## Out of scope

- Calling or changing scoring functions.
- Defining cover value.
- Adding caching or background work.
- Changing how pinned tactics are configured.

## Success criteria

- Both the scouting list and player report show every pinned tactic once, in
  configured order.
- The displayed single-tactic figures and the corresponding **My tactics**
  figures are identical for the same prepared input.
- Starting, replacement, cover, and unavailable states have distinct text.
- Sort/filter links retain unrelated current query parameters.
- Names and notes are HTML-escaped.
- With no pinned tactics, existing page content and default behaviour remain
  unchanged.
- Focused web tests and the full test suite pass.

## Likely code and tests

- `src/fm_analytics/web/scouting_pages.py`
- `src/fm_analytics/web/scouting_render.py`
- `src/fm_analytics/web/scouting_report.py`
- `tests/test_web_scouting.py`
