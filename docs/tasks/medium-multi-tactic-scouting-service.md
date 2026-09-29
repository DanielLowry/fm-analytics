# Medium task: multi-tactic scouting service

**Active-plan item:** 2, trialist review across pinned tactics.

**Prerequisite:** a senior reviewer has accepted the representation and
meaning of a candidate's cover assessment. This task may orchestrate that
calculation but must not invent how cover value is scored. **Met on 28
September 2026:** see the
[cover-value contract](../archive/tasks/senior-cover-value-contract.md).
`rank_candidates_for_tactic(..., weakness_report=...)` already returns
`cover_assessment` for one tactic; pass each pinned tactic's report from
`bundle.squad_depth.per_tactic`. The page-load budget is still open in the
[scouting cost budget](senior-scouting-cost-budget.md).

## Why we are doing this

The manager uses more than one tactic. The current scouting view evaluates a
candidate for one tactic at a time, which makes comparisons slow and hides a
player who would be valuable cover without entering the starting XI. The app
needs one consistent result for all pinned tactics before the web presentation
can be a low-skill rendering task.

## Scope

Add an application/analytics service that evaluates each candidate against the
pinned tactics in their configured order. It should return a stable model that
contains, for each tactic:

- tactic key and display name;
- the candidate's best job;
- projected tactic score and gain bands;
- whether the candidate starts and, if so, whom they replace; and
- the accepted cover assessment when they do not start.

The service should be usable by both the scouting list and individual player
report. The web handler must receive the completed result rather than rerun
analytics while rendering.

## High-level change outline

1. Introduce small immutable result types near
   `analytics/tactic_scouting.py`, or in a narrowly named adjacent module.
2. Build the owned-squad baseline and reusable tactic preparation once per
   tactic, then evaluate all requested candidates against it. Do not rebuild
   remainder allocations for every table cell.
3. Add a reporting or web-service entry point that accepts the configured
   pinned keys. Preserve their order; the first remains the primary tactic.
4. Reuse `rank_candidates_for_tactic` results or factor its preparation from
   its per-candidate work. Do not copy its scoring formula.
5. Add query-level sorting by primary-tactic gain and by a named pinned tactic.
   Invalid tactic sort keys should fail clearly or fall back consistently.
6. Add focused analytics/service tests and a repeatable benchmark using a
   realistic synthetic candidate count. A local gitignored capture may be an
   additional check, never the only test fixture.

## Decisions reserved for review

- ~~The definition and units of cover value.~~ Taken: the candidate's tapered
  role score band beside the current first cover's central score (cover-value
  contract, question 1).
- ~~Whether a candidate can be first cover for more than one slot.~~ Taken:
  one slot, the largest margin (question 2).
- The page-load performance budget and whether caching or process workers are
  justified.
- Any change to floor, cautious estimate, median, or ceiling semantics.

## Success criteria

- For every pinned tactic, the starting-XI result exactly matches the existing
  single-tactic calculation for the same candidate and tactic.
- A non-starter can carry an explicit cover assessment rather than an
  artificial zero-value conclusion.
- Pinned tactics are returned in configured order and the primary tactic is
  unambiguous.
- No-pins behaviour remains unchanged.
- Sorting is deterministic, including ties.
- Instrumented tests demonstrate that tactic preparation is not repeated per
  candidate.
- The benchmark records input size, candidate eligibility characteristics,
  tactic count, machine/context, and wall time.
- Relevant tests and the full test suite pass.

## Likely code and tests

- `src/fm_analytics/analytics/tactic_scouting.py`
- possibly a new focused analytics or reporting module
- `src/fm_analytics/web/scouting_pages.py`
- `tests/test_tactic_scouting.py`
- `tests/test_web_scouting.py`

Keep rendering changes out of this task except for the minimum integration
needed to prove the service can be consumed. The dedicated presentation brief
owns the finished HTML.
