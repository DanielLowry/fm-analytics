# Low task: remove dead imports from `web/server.py`

**Active-plan status:** old review item 3.4, "trivial cleanup when next
touching `web/server.py`".

**Prerequisite:** none. Do it as its own commit, not mixed into behaviour
changes.

## Why we are doing this

When the web package was split, `server.py` kept imports from its old
rendering and handler role. On 28 September 2026 a check found **29** unused
imports:

`subprocess`, `HTTPStatus`, `BaseHTTPRequestHandler`, `parse_qs`, `urlparse`,
`ScoutRecommendation`, `ScoutingFilters`, `TacticDefinition`, `WeaknessKind`,
`WeaknessReport`, `assess_scouting_candidates`, `available_fact_values`,
`filter_scouting_candidates`, `Squad`, `required_role_attributes`, and every
name in the `fm_analytics.web.rendering` import block.

They make it harder to see what the server actually depends on.

## Scope

- Remove the unused imports.
- Remove the redundant local `from pathlib import Path` lines inside
  `_default_fixture_path` and `_default_scouting_path`. `Path` is already
  imported at module level.
- No behaviour change.

## High-level change outline

1. Re-check the list against the current file. It may have changed.
2. Confirm nothing imports these names from `fm_analytics.web.server` or
   patches them there: `grep -rn "web.server" src tests`. Tests currently
   import `SquadWebServer`, `_build_provider`, `build_parser` and `main`, and
   patch `fm_analytics.web.server.build_recommendation_bundle`. All of those
   stay.
3. Delete, then run the checks below.

## Out of scope

- Any other refactor of `server.py`.

## Success criteria

- No unused module-level imports remain (a short `ast` check or `pyflakes`,
  if available, confirms it).
- `uv run python -m compileall src` succeeds.
- The full test suite passes unchanged.

## Likely code and tests

- `src/fm_analytics/web/server.py`
