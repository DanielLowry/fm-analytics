# Medium task: database-backed scouting candidate pool

> **Complete; archived 29 September 2026.** Built 28 September 2026. The *Status*
> section at the end records what was built and the decisions taken. Open
> work is listed in the [task briefs index](../../tasks/README.md).

**Active-plan item:** 5, scout from the database.

**Prerequisite:** the
[best-known player profile](medium-best-known-player-profiles.md) API is stable.
## Why we are doing this

Players disappear from current scout reports and may no longer match today's
realistic search even though the manager learned useful information about them
earlier. The scouting workspace should retain those players without pretending
that historical information is current or that they are still gettable.

## Scope

Build one read/composition service that merges:

- candidates in the current manager-visible scouting feed; and
- players known only from the selected save's player-knowledge database.

Current visible values win. A best-known database value may fill a currently
unknown or absent attribute only when it remains labelled with its observation
date and historical state. Database-only players must be labelled **not
currently realistic** and excluded by the existing realistic/gettable filters
unless the user explicitly asks to include them.

## High-level change outline

1. Add a pure composition layer outside HTML rendering and outside the SQLite
   store. It should accept current candidates plus best-known profiles and
   return the canonical web `ScoutingCandidate` representation or a documented
   wrapper around it.
2. Join on save identity plus FM player ID. Never use name as identity.
3. Define field-by-field precedence explicitly. Do not let an old profile
   overwrite current club, contract, transfer, or interest facts.
4. Preserve the date of every historical attribute selected from the database
   and expose the oldest date used for the player.
5. Include database-only players in the unfiltered list but keep current
   realistic/gettable filters conservative.
6. Wire the composed pool into both the scouting list and individual player
   route through their shared data path.
7. Add tests for current-only, database-only, overlapping, stale, unknown,
   same-name/different-ID, and same-ID/different-save cases.

## Decisions reserved for review

- The exact wrapper/read-model shape if `ScoutingCandidate` cannot express
  historical provenance cleanly.
- Which non-attribute profile fields may be shown historically.
- The default age at which the UI calls a fact out of date.

## Success criteria

- Every current-feed candidate appears exactly once.
- A database-only player appears exactly once and is visibly not current/not
  currently realistic.
- Current exact or ranged observations are never replaced by older database
  observations.
- A historical value used in place of a current unknown retains its real date
  and is visibly historical to downstream renderers.
- Current market and interest filters never admit a player solely because of
  an old database fact.
- No query or merge crosses save identity.
- List and player-report routes use the same composed result.
- Focused tests and the full test suite pass.

## Likely code and tests

- `src/fm_analytics/analytics/scouting.py` or a new focused composition module
- `src/fm_analytics/web/providers.py`
- `src/fm_analytics/web/scouting_pages.py`
- `tests/test_scouting.py`
- `tests/test_web_scouting.py`

## Status: built (28 September 2026)

`fm_analytics.candidate_pool.compose_candidate_pool` merges the current feed
with `best_known_profiles(save, as_of)` for the feed's own game date and
returns plain `ScoutingCandidate`s. `SquadWebServer.scouting()` builds it once
per feed file and per recording (reading a whole save costs seconds), and the
list, the live results fragment and `/scouting/player/<id>` all read that one
result. Tests: `tests/test_candidate_pool.py` and
`tests/test_web_scouting_history.py`. The reserved
decisions, as taken (review them):

- **Read model:** no wrapper. `ScoutingCandidate.history` (a
  `CandidateHistory`) is None for a candidate exactly as the feed describes
  him. When set, it names every attribute value that came from history
  (`HistoricalReading`: first recorded, last seen, source), has
  `in_current_feed`, `oldest_seen_on` and `out_of_date`, and for a
  history-only player keeps his last recorded profile for display.
- **Remembered values are scored.** A best-known value fills an attribute the
  feed shows as unknown or omits, and counts in every score and information
  filter like a visible one. It is marked historical, with its date, in the
  list's attribute sheet, the Past knowledge column and the report. Before
  this, a dropped player's last-known sheet was display-only.
- **Historical profile fields:** a history-only player takes age,
  nationality, footedness, positions, position ratings and scouting knowledge
  from his last profile row. Club, contract, transfer status, value and search
  facts are shown dated on his report ("Last seen at Old FC, 2019-03-01") but
  never populate the candidate's own fields, so no market, value or interest
  filter can admit him.
- **Out of date:** six calendar months of game time, clamped to month end
  (`--out-of-date-months` on `fm-web`).
- **Deviation from the brief:** history-only players are *not* in the default
  list. They appear only with **Everyone ever scouted** ticked, the existing
  toggle for players FM no longer lists. This follows the product owner's
  27 September decision that the default lists mirror what FM shows today.
  Showing them by default is a one-line change in
  `analytics/scouting.py:_matches_visible_filters`.
