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
