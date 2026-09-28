# Senior task: cover-value contract

**Active-plan item:** 2, trialist review across pinned tactics.

**Prerequisite:** none.

**Unblocks:** the [multi-tactic scouting service](medium-multi-tactic-scouting-service.md),
and through it the [multi-tactic presentation](low-multi-tactic-scouting-presentation.md).

## Why we are doing this

Today a candidate who does not make a tactic's XI shows a gain of zero (see
"Tactic impact" in [scouting-workspace.md](../scouting-workspace.md)). At
National League South level, depth matters, and a zero hides a player who
would be clearly better cover than what the squad has. The active plan asks
for a **depth effect**: the slot he would be first cover for, and how his fit
compares with the current first cover there.

How that is measured is a scoring decision. The medium service brief may
orchestrate the calculation but must not invent it, so this brief settles the
contract first.

## What already exists

- `analytics/weaknesses.py`: `assess_weaknesses` builds one `SlotDepth` per
  slot, with `starter`, `available_backups`, `temporarily_unavailable` and
  `occupied_starter_cover`. Backups are scored with the same tactic-derived
  role weights as the XI. `WeaknessPolicy.backup_ratio` (0.80) defines weak
  cover relative to the starter.
- `bundle.squad_depth.per_tactic[tactic_key]` holds a `WeaknessReport` for
  every tactic, so each pinned tactic's current cover is already computed once
  per bundle.
- `analytics/tactic_scouting.py`: `rank_candidates_for_tactic` returns a
  `TacticScoutingAssessment` per candidate, with `starts_at_estimate`,
  `replaced_player_names`, `score_gain` (floor, estimate, ceiling) and the
  candidate's best slot and role.

## Questions to settle

1. **Unit.** Is cover value the candidate's tactic-weighted role fit in the
   slot, shown beside the current first cover's fit? The difference between the
   two? Or an effect on a tactic score, such as the XI score with the starter
   removed? The plan's wording implies the first. Confirm it or choose another,
   and give the reason.
2. **Which slot.** A candidate can beat the current first cover in several
   slots. Is one slot reported, and if so chosen by what rule, or are all of
   them reported, in what order?
3. **Uncertainty.** Floor, estimate and ceiling bands, as the gain has, or a
   single figure? The signing view counts an unknown attribute at the minimum
   (`score.central`), and that should not change here.
4. **Knock-on effects.** If the candidate becomes first cover at LB, the
   current LB cover may become first cover somewhere else. Should that be
   ignored (recommended for a first version) or modelled?
5. **Readiness.** The candidate is assumed fully fit, as in tactic scouting.
   Is he compared only with available cover, or also with players in
   `temporarily_unavailable`?
6. **Relationship to starting.** For a candidate who starts in the tactic, is
   cover value left out, or reported for another slot? The recommendation is to
   leave it out, because starting supersedes cover.
7. **When is it worth showing.** When he beats the current first cover by any
   margin, or only when that slot is already flagged `WEAK_BACKUP` or
   `NO_BACKUP`?

## Constraints

- Only manager-visible observations, under the same visibility rules as the
  rest of scouting.
- Reuse the depth and weakness scoring (the same role weights and readiness)
  rather than a second formula, so `/depth` and `/scouting` cannot disagree
  about who the first cover is.
- Computed in `analytics/`, never in a handler or render helper.
- No existing number may change: starting gain, XI, bench, depth.
- The work is multiplied by candidates × pinned tactics. A definition that
  re-solves the XI per candidate per slot needs checking against the
  [scouting cost budget](senior-scouting-cost-budget.md).

## Deliverables

- A short written contract, recorded as a "Decision" section in this brief and
  summarised under "Tactic impact" in `docs/scouting-workspace.md`. It names
  the result fields, units, bands, tie-breaks and slot rule.
- A small frozen result type (for example `CoverAssessment`) with a
  docstring, in or beside `analytics/tactic_scouting.py`, plus one worked
  example test on a hand-built squad. The medium implementer then inherits a
  checked shape rather than a paragraph.
- An update to the service brief's "Decisions reserved for review", marking
  which decisions are now taken.

## Success criteria

- Every question above has a recorded answer.
- In the worked example, a candidate who is not in the XI but beats the current
  first cover in one slot gets a non-zero, explicitly labelled cover result.
  A candidate worse than every current cover gets "no cover role", not a zero.
- The contract identifies the same current first cover as `/depth` does for
  the same bundle.
- Nothing already displayed changes; the existing suite passes unchanged.

## Likely code and tests

- `src/fm_analytics/analytics/tactic_scouting.py`
- `src/fm_analytics/analytics/weaknesses.py`, read and reuse only
- `tests/test_tactic_scouting.py`
- `docs/scouting-workspace.md`

## Status: built (28 September 2026)

`CoverAssessment` lives in its own module, `analytics/cover_value.py` (split
out of `tactic_scouting.py` for size, not for meaning: see the line-cap
comment at the top of the file). `best_cover_assessment` is wired into
`rank_candidates_for_tactic` behind a new optional `weakness_report` parameter
that defaults to `None`; passing nothing leaves `cover_assessment` and
`trial_priority` absent everywhere, so neither existing caller in
`web/scouting_pages.py` changed behaviour. The questions above, as taken:

1. **Unit:** the candidate's own tapered role score in the slot
   (`CoverAssessment.candidate_score`, a `ScoreBand`), shown beside the
   current first cover's central score
   (`current_cover_score: float | None`) -- not a difference and not a
   whole-XI reprojection.
2. **Which slot:** exactly one -- `margin` (candidate central minus current
   cover central, or the candidate's own central when there is no current
   cover at all) is computed for every position-eligible slot, and the
   largest wins.
3. **Uncertainty:** the candidate's own band (floor/central/ceiling); the
   current cover is a single central figure, matching how `/depth` itself
   reports first cover.
4. **Knock-on effects:** ignored, as recommended.
5. **Readiness:** only `available_backups`; `temporarily_unavailable` cover
   is not who the candidate is actually compared against today.
6. **Relationship to starting:** left out. `rank_candidates_for_tactic` never
   calls `best_cover_assessment` for a candidate whose `starts_at_estimate`
   is true.
7. **When it's worth showing:** whenever the margin clears the current cover,
   with no additional weak-slot gate -- that gate is `trial_priority`'s job
   (see [the trial-scenario semantics brief](senior-trial-scenario-semantics.md)),
   not this contract's. `could_be_first_cover` is a plain property
   (`cover_assessment is not None`) for callers that just want the flag.

A candidate worse than every eligible slot's current cover has
`cover_assessment is None` -- never a zero or negative `CoverAssessment`.
Tests: `tests/test_tactic_scouting.py`, covering an outright "no cover exists"
case, a case that must clear a real backup, a starter getting no assessment
at all, and a rejected mismatched-tactic weakness report.
