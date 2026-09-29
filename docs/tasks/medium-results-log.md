# Medium task: results log (manual entry)

> **Superseded 29 September 2026.** Item 7 was built as match history read
> live from FM, not as manual entry. See
> [the match analysis plan](../match-analysis-plan.md); it answers the
> decisions this brief reserved. Kept as the record of the original scope.

**Active-plan item:** 7, results log, currently **parked**.

**Prerequisite:** the active plan un-parks item 7, which it will do after
items 1–3 land and there is a question the log must answer. The storage and
identity decisions below need review before implementation starts.

## Why we are doing this

Recording each match is the only way to judge Vertical 4-4-2 against Wing Play
4-4-2, or any catalogue change, on evidence rather than opinion. It is also the
seed of [Phase 07](../phases/07-match-database/README.md). Manual entry is
acceptable for a first version.

## Scope

For each match, record:

- in-game date, opponent name, home or away, and optionally the competition;
- the tactic actually used (a catalogue key) and the XI actually played;
- the opponent slider settings used (`OpponentProfile`);
- the score, and xG only if FM20 shows it (check that it does before adding a
  field); and
- a short note.

Also snapshot what the app recommended at the time (catalogue and policy
versions, recommended tactic and XI), without assuming it was followed. This
follows Phase 07.4.

Deliver a local entry form, a list page, and simple per-tactic counts
(played, won, drawn, lost, goals). No statistical claims: Phase 07 defers
causal conclusions from simple correlations.

## High-level change outline

1. An append-only store with its own ordered migrations from v1, a backup
   before migrating, and a refusal to open a newer file. Copy the pattern in
   `persistence/player_knowledge.py`. The tactic, XI and sliders cannot be
   recovered from FM later, so this history needs the same protection.
2. Key every row by save, using the `save_key` convention verdicts use.
3. A correction is a new row; the latest wins and history is kept.
4. Prefill the form from the current bundle (primary tactic, its XI, game
   date, the current opponent profile). The manager edits it to what actually
   happened. The handler reads bundle values; it does not recompute them.
5. Validate: non-negative whole-number scores, ISO dates, known tactic keys,
   bounded notes. XI player IDs may later leave the squad and must still load.
6. A local POST following the verdict route's pattern, and a `/results` page,
   newest first.
7. Tests for migrations, the store, POST validation, prefill and escaping.

## Decisions reserved for review

- Its own file (for example `data/results-log.sqlite3`) or a new table in the
  player-knowledge database. The latter is a v2 migration there and must be
  coordinated with any other migration.
- Match identity: date plus opponent, or a generated ID allowing corrections
  and same-day duplicates.
- Whether the XI is stored with slots and roles or as player IDs only.
- Which recommendation fields to snapshot.

## Success criteria

- Rows are isolated by save; corrections keep the earlier entry.
- The migration path is tested from v1 with an injected second step.
- Prefilled values equal what `/tactics` shows for the same bundle.
- Per-tactic counts can be reproduced from the stored rows.
- Nothing is written to FM.
- Focused tests and the full suite pass.

## Likely code and tests

- a new `src/fm_analytics/persistence/results_log.py`
- `src/fm_analytics/web/handlers.py`, plus a focused pages module
- `src/fm_analytics/web/server.py` for store wiring
- a new `tests/test_results_log.py`
