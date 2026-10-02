# Medium task: “now gettable” and “re-scout due” alerts

**Active-plan item:** 6.

**Prerequisites:** database-backed best-known profiles, current manual
verdicts, and an accepted source of weakest-slot role attributes. **All met by
29 September 2026:**

- [best-known profiles](medium-best-known-player-profiles.md)
  and the [database-backed candidate pool](medium-database-candidate-pool.md),
  whose `CandidateHistory.out_of_date` already applies a six-month threshold;
- [manual verdicts](medium-manual-scouting-verdicts.md)
  (`PlayerKnowledgeStore.current_verdicts`); and
- `WeakSlot.role_attributes` from the
  [weakest-slot service](medium-weakest-slot-service.md).

One gap remains. Free-agent, listed and contract-end transitions can be read
from `profile_observations` (`has_contract`, `transfer_status`,
`contract_end`). A **newly realistic** transition (Player Search or
transfer/loan interest) has no stored previous state: the knowledge history
does not record interest yet (see "Known gaps" in
[scouting-workspace.md](../../scouting-workspace.md)).

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
3. Use the application's canonical current realistic/gettable result. The
   knowledge store keeps no gettable history of its own: the old
   `matched_active_search` column was dropped on 27 September 2026.
4. Make the stale threshold configurable with a six-month default expressed in
   the same in-game date units used by the knowledge store.
5. Return reason codes/data as well as display text so rules can be tested
   without parsing HTML.
6. Add focused transition tests, then render the prepared results on the
   scouting page.

## Decisions reserved for review

- Exact near-contract-end window.
- ~~Calendar interpretation of six months in the FM date model.~~ Taken by the
  candidate pool: calendar months of game time, clamped to month end
  (`candidate_pool.months_before`, `--out-of-date-months` on `fm-web`). Reuse
  it rather than defining a second "out of date".
- Which weak-slot attributes are important enough to trigger re-scouting.
- Alert ordering when a player has several reasons.
- Whether "newly realistic" waits until interest is recorded in the knowledge
  history, compares with the previous capture file instead, or is dropped
  from the first version.

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

## Status

Built 1 October 2026. A pure alert service supplies reason codes, report links,
role context, and missing attribute names to the Scouting page's two alert
collections. Empty results show a quiet empty state. Market transitions and
stale reminders remain available even when the owned squad is incomplete;
missing-role reminders use the accepted weakest-slot service when available.

Decisions:

- Compare the two latest in-game sightings, resolving the profile effective
  on the previous day. Change-only profile rows are insufficient: they would
  repeat alerts forever and miss an unchanged contract approaching expiry.
  Later unchanged sightings clear a transition; reloads of the same in-game
  state retain it. All history queries are isolated by save and date.
- The near-contract window is six game months, using the existing canonical
  contract-month calculation. Staleness reuses `CandidateHistory.out_of_date`
  and the configurable `--out-of-date-months` cutoff; messages show that cutoff.
- Important attributes are those tied for the highest accepted role weight.
  Exact and ranged values are information; unknown or omitted important
  values trigger a Watch reminder. Unrelated unknowns do not.
- Order market reasons as free, listed, contract, then name and id. Order stale
  reminders before missing-role reminders; the first matching weak slot uses
  the weakest-slot service's order. A player can have several specific reasons.
- Newly realistic via interest or Player Search is deferred from this first
  version, as permitted by the brief: previous interest is not recorded, so a
  transition cannot be substantiated. Free/listed predicates and contract
  calculations reuse the application's canonical market rules. History-only
  market facts never generate current gettable alerts.

Tests cover transitions, unchanged recaptures, no previous observation, save
isolation, Reject suppression, Target/Watch retention, configurable stale
cutoffs, important unknowns, escaping, and the refresh-to-page integration.

Verification: all 1,243 unittest tests passed. Python compilation, package
build, isolated wheel imports/catalogue check, and bridge fixture HTTP smoke
test also passed.
