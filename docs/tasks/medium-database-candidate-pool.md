# Medium task: database-backed scouting candidate pool

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
