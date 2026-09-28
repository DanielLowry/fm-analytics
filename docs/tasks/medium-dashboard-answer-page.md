# Medium task: dashboard as an answer page

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)). Old
review item 2.5.

**Prerequisites:** the active plan schedules this item, and the
[web cache rework](medium-web-cache-rework.md) has landed so the dashboard can
use the bundle without paying for a duplicate build. The
[weakest-slot service](medium-weakest-slot-service.md) is strongly preferred,
so the dashboard does not become a fourth definition of "squad problems".

## Why we are doing this

`/` (`_dashboard` in `web/handlers.py`) shows club, date, manager, squad size,
pinned tactics and attribute coverage. It reads only `server.read()`, which
avoided the multi-second bundle build. It tells the manager nothing about what
to do next.

## Scope

- Lead with the primary tactic: its name, rank among all tactics, score and gap
  to the top, as the **Your tactics** table on `/tactics` shows them.
- Freshness: snapshot game date, build time, and refresh state or error.
- The few highest-priority squad problems, each linking to `/depth` or the
  affected `/squad/player/<id>`.
- Recruitment needs, each linking to a pre-filtered `/scouting`.
- Keep today's metadata and coverage block as provenance, lower down.
- When the bundle is unavailable (incomplete attributes, source error, still
  building), show today's page plus the reason, not an error page.

## High-level change outline

1. Read every figure from the bundle or a reporting helper. Compute nothing
   in the handler.
2. Reuse the tactics page's and depth page's existing helpers and wording.
3. Build scouting links from the weakest-slot service's filter values.
4. Tests: full bundle, pins and no pins, incomplete squad, provider error,
   and escaping.

## Decisions reserved for review

- Which problems qualify and how many. Prefer the weakest-slot service's
  selection.
- On a cold start, whether the dashboard waits for the build or shows
  "building…".

## Success criteria

- Every number on the dashboard equals the number on the page it links to.
- Degraded states still render useful content.
- No analytics code in the handler.
- Focused web tests and the full suite pass.

## Likely code and tests

- `src/fm_analytics/web/handlers.py` (`_dashboard`)
- `src/fm_analytics/web/rendering.py`
- `tests/test_web_server.py` or a focused dashboard test module
