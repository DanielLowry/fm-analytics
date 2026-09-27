# Medium task: “now gettable” and “re-scout due” alerts

**Active-plan item:** 6.

**Prerequisites:** database-backed best-known profiles, current manual
verdicts, and an accepted source of weakest-slot role attributes.

## Why we are doing this

The player-knowledge history becomes most useful when it notices a change the
manager would otherwise miss: a known player has become attainable, or a
watched player's information is too old or incomplete for a weak position.
These are prompts to review or scout, not automatic signing decisions.

## Scope

Produce two prepared alert collections after a successful refresh:

- **Known and now gettable:** previously known players who newly satisfy the
  canonical current realistic/gettable rule, become free agents, become
  listed, or enter the agreed near-contract-end window. Exclude current Reject
  verdicts.
- **Re-scout due:** current Watch players whose assembled profile is older than
  the configured threshold, or is missing visible information for attributes
  important to an accepted weakest-slot role.

Render the collections as a small block on `/scouting`, with links to the
existing player report or filtered list.

## High-level change outline

1. Add a pure alert service over prepared current and previous profile states,
   verdicts, and weak-role requirements. Keep SQL and HTML out of the rule
   functions.
2. Define “newly” by comparing the latest two relevant in-game observations,
   not by wall-clock refresh time.
3. Use the application's canonical current realistic/gettable result. Do not
   substitute the historical `matched_active_search` field unless a reviewer
   explicitly confirms they mean the same thing.
4. Make the stale threshold configurable with a six-month default expressed in
   the same in-game date units used by the knowledge store.
5. Return reason codes/data as well as display text so rules can be tested
   without parsing HTML.
6. Add focused transition tests, then render the prepared results on the
   scouting page.

## Decisions reserved for review

- Exact near-contract-end window.
- Calendar interpretation of six months in the FM date model.
- Which weak-slot attributes are important enough to trigger re-scouting.
- Alert ordering when a player has several reasons.

## Success criteria

- A continuously gettable player does not alert on every refresh; a false-to-
  true transition alerts once for the current state.
- A free/listed/contract transition retains a specific human-readable reason.
- Reject verdicts suppress “now gettable”; Target and Watch do not.
- A fresh complete Watch profile is not due, while an old profile crosses the
  configured threshold deterministically.
- Unknown and uncaptured important attributes can trigger a due alert;
  unrelated unknown attributes cannot.
- No previous observation means the service does not falsely claim a newly
  changed state.
- Alert calculations use in-game dates and remain isolated by save.
- Empty alert sets produce a quiet empty state rather than an error.
- Focused service/web tests and the full test suite pass.

## Likely code and tests

- a new focused module under `src/fm_analytics/analytics/` or an application
  service beside the scouting composition code
- `src/fm_analytics/web/scouting_pages.py`
- `src/fm_analytics/web/scouting_render.py`
- a focused new test module plus `tests/test_web_scouting.py`
