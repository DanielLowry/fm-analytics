# Medium task: best-known player profiles

**Active-plan item:** 5, scout from the database.

**Prerequisite:** none. The player-knowledge write side and v1 schema are
already built.

## Why we are doing this

The database preserves observations after FM stops showing them, but the app
currently reads only the latest JSON feed. Until the store can assemble a
dated best-known profile, the history protects data without improving a
scouting decision.

## Required semantics

For a selected save, player, and as-of game date:

- select the latest profile observation at or before that date;
- for each attribute, select the latest non-unknown observation at or before
  that date;
- retain the observation date and source for every selected attribute;
- separately expose the latest recorded state, even when it is unknown, so a
  caller can say that knowledge has faded;
- report the oldest observation date used by the assembled profile; and
- never read observations from another save or from the future.

The query result should describe age, not decide presentation wording such as
“out of date”. The caller supplies the staleness threshold.

## High-level change outline

1. Add immutable read-model types for a selected attribute and assembled
   player profile in `persistence/player_knowledge.py` or a focused adjacent
   module.
2. Add store methods for one player and, if needed by the candidate-pool task,
   a batched form for all players in a save. Avoid an N+1 query design.
3. Keep the existing history methods unchanged unless a shared private query
   can simplify them without altering their result.
4. Calculate profile age/oldest-used date from in-game observation dates, not
   wall-clock ingest time.
5. Add tests containing exact, range, unknown, known-then-unknown, same-day,
   rewind, future, missing-player, and cross-save cases.

## Decisions reserved for review

- The public name and shape of the batched API.
- Tie-breaking when two different ingests contain observations for the same
  player, attribute, and in-game date. It must be deterministic and consistent
  with existing history order.
- Whether staleness is represented as a derived boolean or only as dates.

## Success criteria

- A later unknown observation does not erase the most recent visible value,
  but the result records that the latest state is unknown.
- Exact and range observations round-trip without losing their visibility
  type or bounds.
- `as_of` excludes all later profile and attribute rows.
- Save identities cannot leak into each other, even when player IDs match.
- The batched path performs a bounded number of SQL queries independent of
  player count.
- Empty histories return an explicit absent result rather than a fabricated
  unknown profile.
- Existing migration and write-side tests remain unchanged and pass.
- New focused tests and the full test suite pass.

## Likely code and tests

- `src/fm_analytics/persistence/player_knowledge.py`
- `src/fm_analytics/persistence/__init__.py`
- `tests/test_player_knowledge.py`

This task does not merge database data with live candidates; that is the next
brief.

## Status: built (27 September 2026)

`PlayerKnowledgeStore.best_known_profile(save_key, player_id, as_of)` and
`best_known_profiles(save_key, as_of)` return `BestKnownProfile` objects. The
batched form is keyed by player ID, omits players with nothing dated that
early, and runs a fixed number of queries. The reserved decisions, as taken:

- **Batched API:** `best_known_profiles(save_key, as_of) -> dict[str, BestKnownProfile]`.
- **Tie-break:** in-game date, then row ID (ingest order), newest first. This is
  the order `attribute_history` reports.
- **Staleness:** dates only, never a boolean. Each selected reading carries
  `observed_on`, when the store first recorded that state, and `last_seen_on`,
  the last day a capture still showed it. The profile has
  `profile_last_seen_on`, and `oldest_seen_on` / `latest_seen_on` across
  everything it used.

**Added in review: sightings (schema v3).** Observation rows are change-only,
so the first version dated every reading from when it first appeared. A value
seen unchanged every week would have looked months old, and the feed's own
"last known on" date was discarded whenever the value matched. Each capture
now also records the day it saw each player and read his sheet, and ages run
from the last sighting. Use `last_seen_on` / `oldest_seen_on` for anything
about age, including the candidate pool's historical labels and the
"re-scout due" threshold.

Dates must be `YYYY-MM-DD`. Python also parses `20190908` and `2019-W36-7`,
but stored dates are compared as text, so those forms are refused.
