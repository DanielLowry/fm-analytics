# Medium task: manual scouting verdicts

**Active-plan item:** 5, scout from the database.

**Prerequisite:** coordinate with any other branch adding a player-knowledge
schema migration. Migrations are append-only and must have a single order.

## Why we are doing this

The analytics provide evidence, but signing is deliberately a manager decision.
Target, Watch, and Reject let the manager retain that decision and a short
reason. Rejects can then stay out of routine lists without teaching the app to
make automatic signing decisions.

## Scope

- Persist `Target`, `Watch`, or `Reject`, a bounded note, and the in-game date
  for one player in one save.
- Allow the verdict to be cleared.
- Read the current verdict for list and player-report use.
- Add a local form to the player report.
- Hide rejected players from lists by default and add a query toggle that
  reveals them.

This writes only manager-authored data to the local SQLite database. It must
never invoke a scouting refresh or write to FM.

## High-level change outline

1. Append a v2 migration to `MIGRATIONS`; never edit the shipped v1 SQL.
2. Store changes in an append-only event table with a deterministic latest-row
   query. A clear action is another event, not deletion, so an earlier decision
   is never destroyed.
3. Add validated store methods for set, clear, get-one, and batched-current
   verdicts. Save key and player ID are mandatory.
4. Add a bounded local POST route following the existing web server's form and
   redirect patterns. Reject unknown verdict strings, missing identities,
   malformed dates, and oversized notes.
5. Render the current verdict and note on the player report. Add the default
   Reject exclusion and an explicit **Show rejected** list toggle.
6. Test the migration backup/upgrade path as well as store and web behaviour.

## Decisions reserved for review

- Maximum note length.
- Whether the form uses the capture's current in-game date or requires an
  explicit date field.

## Success criteria

- Verdicts are isolated by save and player ID.
- Setting a later verdict makes it current while retaining the earlier dated
  decision; clearing it also retains that history.
- Invalid verdict values and oversized notes are rejected without a partial
  write.
- Replaying the same submitted state is idempotent or produces a documented,
  harmless duplicate-free result.
- Reject is hidden by default; **Show rejected** includes it without changing
  other filters.
- Notes and player data are escaped in HTML.
- A database at v1 is backed up and migrates to v2; a failed migration rolls
  back.
- The POST changes only the local knowledge database and redirects to a safe
  local route.
- Focused persistence/web tests and the full test suite pass.

## Likely code and tests

- `src/fm_analytics/persistence/player_knowledge.py`
- `src/fm_analytics/web/scouting_pages.py`
- `src/fm_analytics/web/scouting_report.py`
- `src/fm_analytics/web/server.py` only for route wiring if required
- `tests/test_player_knowledge.py`
- `tests/test_web_scouting.py`

## Status: built (27 September 2026)

Do not follow step 1 above. The schema was reset to a single v1 on 27 September
2026, and `verdict_events` is part of that v1. There is no v2 migration.

- **Store:** `PlayerKnowledgeStore.set_verdict`, `clear_verdict`,
  `get_verdict` and `current_verdicts` (one query per save), with the
  `Verdict` enum and `VerdictRecord`. The table is append-only; a clear is a
  row with no verdict, and re-submitting the current state adds no row.
- **Web:** `POST /scouting/verdict` (`_post_scouting_verdict`), the verdict
  panel on the player report, rejected players hidden from lists by default,
  and a **Show rejected players** toggle. Verdicts are off, rather than half
  available, when the server has no save key.

The reserved decisions, as taken:

- **Note length:** 500 characters (`MAX_VERDICT_NOTE_LENGTH`), enforced in
  Python and by a `CHECK` constraint.
- **Date:** the form submits the capture's in-game date in a hidden
  `decidedOn` field; there is no date input.
