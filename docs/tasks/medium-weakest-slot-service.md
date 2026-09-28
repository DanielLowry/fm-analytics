# Medium task: weakest-slot service

**Active-plan item:** 3, worth-a-trial ranking against the weakest slots.

**Prerequisite:** none to start. The selection decisions below must be
approved before merge.

**Unblocks:** [weakest-slot navigation](low-weakest-slot-navigation.md), the
[trial-priority list](medium-trial-priority-list.md), and the "accepted source
of weakest-slot role attributes" that [scouting alerts](medium-scouting-alerts.md)
needs.

## Why we are doing this

Three features need the same answer to "where are my tactics weakest?": the
navigation header, the trial-priority list and the re-scout alerts. Computing
it once in reporting stops three slightly different definitions from appearing,
in line with the one-computation rule in `CLAUDE.md`.

## What already exists

- `bundle.squad_depth.per_tactic[tactic_key]` is a `WeaknessReport` for every
  tactic. Its `depth` holds one `SlotDepth` per slot; its `weaknesses` hold
  `Weakness(kind, slot_keys, player_id, message, target_score)`.
- `WeaknessKind`: `structural_gap`, `simultaneous_gap`, `temporary_gap`,
  `weak_starter`, `no_backup`, `weak_backup`, `shared_cover`.
  `WeaknessPolicy` sets weak starters at 0.85 of the XI median and weak cover
  at 0.80 of the starter.
- `bundle.pinned` gives pinned evaluations in order; `bundle.primary` gives the
  primary one.
- `analytics/recruitment.py::build_recruitment_briefs` already turns one
  tactic's weaknesses into `RecruitmentBrief(tactic_key, slot_keys, position,
  role_key, need, minimum_role_score, reason)`, and the bundle carries them
  for the primary tactic as `bundle.briefs`. Reuse or extend it before writing
  a parallel mapping.
- `/scouting` reads `tactic`, `position` and `role` query parameters
  (`_scouting_filters` in `web/rendering.py`).

## Scope

A reporting-level function or bundle property, for example
`weakest_slots(bundle)`, returning an ordered tuple of items for the pinned
tactics (the selected tactic when there are no pins). Each item carries:

- tactic key and name, slot key, position, role key and name;
- the concern (**starter** or **cover**) and the weakness kinds behind it;
- current starter and first-cover names and fits, taken from the report;
- the role's weighted attributes for that tactic, for the alerts brief; and
- the scouting filter values (tactic, position, role) for navigation links.

## High-level change outline

1. Read only over existing weakness reports. No new scoring.
2. Map kinds to a concern: `weak_starter` to starter; `no_backup` and
   `weak_backup` to cover. The rest are a reserved decision.
3. Order deterministically, and cap the list with a parameter and default.
4. Build filter values from the names `_scouting_filters` already parses, so
   the navigation brief can round-trip them.
5. Expose it where both the CLI and web can use it. Printing it from
   `fm-analytics --recommend` is optional but keeps the two in step.
6. Tests: pinned and unpinned bundles, an incomplete squad with a structural
   gap, ties, and no weaknesses.

## Decisions reserved for review

- Which weakness kinds count, and as which concern.
- How many items ("the few") and how they are ordered across tactics.
- Behaviour with no pins.
- Whether this extends `build_recruitment_briefs` or replaces it.

## Success criteria

- The function reads only the bundle: calling it twice gives equal results,
  and it performs no role scoring.
- Every item's starter and first cover match the same tactic on `/depth`.
- Ordering is deterministic, including ties.
- It returns an empty tuple, not an error, when nothing is weak.
- Focused tests and the full suite pass.

## Likely code and tests

- `src/fm_analytics/reporting.py`
- `src/fm_analytics/analytics/recruitment.py`
- `tests/test_reporting.py`
