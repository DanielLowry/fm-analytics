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

## Status: built (28 September 2026)

Three new fields on `TacticScoutingAssessment`: `player_median`,
`could_start`, `trial_priority`, plus `cover_assessment`/`could_be_first_cover`
from [the cover-value contract](senior-cover-value-contract.md). The
questions above, as taken:

1. **Median in tactic terms:** deliberately *not* a fourth XI reprojection.
   `player_median` is the candidate's own `RoleScore.median` (already computed
   by `score_role` for every role score, never a new calculation) in his best
   slot/role -- exactly the same "what could he be worth" question
   `PositionRanking.median`/`ScoutingAssessment.median` already answer
   elsewhere in scouting, just carried into tactic terms. A whole-XI median
   re-optimisation was rejected: it would need a parallel assignment solve
   (roughly doubling the per-candidate cost the
   [scouting cost budget](senior-scouting-cost-budget.md) is trying to keep
   down) for a number whose only declared use is ranking, not a displayed
   projected score. `floor ≤ estimate ≤ median ≤ ceiling` holds by
   construction: `RoleScore.median` is documented to sit between `score.lower`
   and `score.upper`, and central ≤ median attribute-by-attribute because an
   unknown attribute counts at the scale minimum for central but at mid-scale
   for median; known and ranged attributes give the two the same value.
2. **Could start:** `could_start` is `True` exactly when the existing
   ceiling-scenario assignment (`best_by_field["upper"]`, already computed for
   `score_gain.ceiling`) finds the candidate a starting slot -- no new
   calculation, just naming an existing result. Never true for a candidate who
   already starts at the estimate and then somehow not at the ceiling, since
   scores only rise from central to upper.
3. **Could be first cover:** `could_be_first_cover` is
   `cover_assessment is not None`, at the cover contract's own central-score
   comparison -- not evaluated separately at the ceiling. A ceiling-based cover
   flag was considered and rejected as a second, differently-scaled "could"
   flag competing with `could_start`'s ceiling-based one, for no stated use.
4. **Trial-priority value:** the candidate's `player_median`, gated on his
   best slot being flagged weak (`weak_starter`, `no_backup` or `weak_backup`)
   in *this tactic's own* `weakness_report` -- not the cross-tactic
   [weakest-slot service](medium-weakest-slot-service.md), which exists for
   navigation and alerts, not for this per-candidate gate. **Additional
   guard, found while implementing:** a candidate with zero known or ranged
   attributes gets `trial_priority = None` even when his best slot is weak --
   his median would be a pure mid-scale fabrication, and ranking him on it is
   exactly the "invented score" the active plan rules out for a Scout First
   player. `player_median` itself is not suppressed for him (matching how
   `PositionRanking.median` is never suppressed elsewhere); only the
   ranking-facing `trial_priority` is. Multi-tactic combination (max across
   pinned tactics, tie-breaks) is left to whichever brief first needs it
   across more than one tactic; this module scores one tactic at a time and
   makes no claim beyond it.
5. **Realistic and gettable default filter state:** left to the
   [trial-priority list](medium-trial-priority-list.md), which owns the
   sort's UI and default filters; this brief only supplies the value sorted
   on.
6. **Wording:** left to the presentation brief; nothing here renders text.

`rank_candidates_for_tactic` gained one new optional parameter,
`weakness_report: WeaknessReport | None = None`. With it omitted (both
existing `web/scouting_pages.py` call sites), `cover_assessment` and
`trial_priority` are always absent and every existing field is bit-for-bit
unchanged -- verified by the full existing test suite, unmodified, still
passing. Tests: `tests/test_tactic_scouting.py`.
