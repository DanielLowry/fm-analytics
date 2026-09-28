# Senior task: trial scenario semantics

**Active-plan item:** 3, worth-a-trial ranking against the weakest slots.

**Prerequisite:** none to start. Settle the
[cover-value contract](senior-cover-value-contract.md) first or alongside,
because "could be first cover" depends on it.

**Unblocks:** the [trial-priority list](medium-trial-priority-list.md), and the
trial-priority sort that [weakest-slot navigation](low-weakest-slot-navigation.md)
links to.

## Why we are doing this

Tactic gain counts an unknown attribute at the minimum. That is the right view
for deciding whom to sign. It is the wrong view for deciding whom to trial,
where the question is "could he beat my starter if the unknowns are
reasonable?" The Scouted tab already answers a version of that with
`RoleScore.median`, but not in tactic terms. Adding a median scenario to tactic
scouting, and defining **could start**, **could be first cover** and **trial
priority**, are new scoring semantics, so they are settled here rather than by
the medium implementer.

## What already exists

- `ScenarioScores(floor, estimate, ceiling)` in `analytics/tactic_scouting.py`,
  used for `TacticScoutingAssessment.projected_score` and `score_gain`.
- `RoleScore.median` (`_median_score` in `analytics/role_scoring.py`) puts
  every range at its midpoint and every unknown mid-scale. It is deliberately
  separate from `score.central`, so a barely scouted player cannot outrank a
  known one in the optimiser (see "Ranking: who to scout next" in
  [scouting-workspace.md](../scouting-workspace.md)).
- The plan's intent: **could start** means the ceiling beats the current
  starter in his best slot in any pinned tactic. **Trial priority** orders
  realistic, gettable candidates by median-scenario gain in the weakest slots,
  with the unknown count shown. Players with no visible attributes stay under
  **Scout first**, grouped by the weakest slot they could fill, with no score.
- The realism and market inputs in `analytics/scouting.py`: the candidate's
  `in_player_search` flag, and the `ScoutingFilters` fields `transfer_interest`
  and `loan_interest` ("interested" includes "maybe"), `market`,
  `transfer_status` and `availability`. The plan's older name `search_match` no
  longer exists.

## Questions to settle

1. **Median in tactic terms.** Is it a fourth projection of the XI using the
   candidate's median role scores, with owned players unchanged? Or is it
   derived from the existing bands? Confirm that floor ≤ estimate ≤ median ≤
   ceiling holds after the assignment, not only per role score.
2. **Could start.** Compare the candidate's ceiling with which starter score
   (central?), and "his best slot" chosen by which scenario?
3. **Could be first cover.** Use the cover-value contract at the ceiling, or
   at the median?
4. **Trial-priority value.** Is it gain restricted to jobs in the weakest
   slots from the [weakest-slot service](medium-weakest-slot-service.md), or
   overall gain with weakest slots used only as a filter? Across several
   pinned tactics, is it the primary tactic only, the maximum, or a weighted
   sum? How are ties broken?
5. **Realistic and gettable.** Name the exact default filter state the sort
   applies.
6. **Wording.** Fix the sentence the page shows: the median is for choosing
   whom to look at, never whom to sign.

## Constraints

- Never change `score.central`, the signing-view gain, or any existing band.
  The median is additive.
- No score, flag or priority for a player with no visible role attributes.
- Unknowns are the mid-scale assumption, never an estimate from a lower-level
  research source.
- The opponent profile flows through as it does for the other scenarios.

## Deliverables

- A written contract (fields, formulas, tie-breaks, default filters),
  recorded under "Tactic impact" in `docs/scouting-workspace.md`.
- Recommended: the senior owner implements the median scenario itself in
  `tactic_scouting.py`, because it is core scoring, and defines the two flags
  and the priority value as pure functions. Sorting, grouping and rendering
  stay with the medium brief.

## Success criteria

- floor ≤ estimate ≤ median ≤ ceiling for every assessment, tested with exact,
  range and unknown mixes.
- A fully known candidate has median equal to estimate.
- Existing floor, estimate and ceiling values are unchanged over a fixed
  candidate pool (regression test).
- A player with no visible role attributes gets no median, flag or priority.
- Each flag and the priority value has a worked-example test.

## Likely code and tests

- `src/fm_analytics/analytics/tactic_scouting.py`
- `src/fm_analytics/analytics/role_scoring.py`, read only
- `tests/test_tactic_scouting.py`
- `docs/scouting-workspace.md`
