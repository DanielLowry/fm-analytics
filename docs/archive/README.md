# Documentation archive

These documents preserve superseded research procedures and decisions. They
are evidence, not current runbooks. Current documentation is indexed from
[`docs/README.md`](../README.md).

## Completed plans

- [`plans/initial-plan.md`](plans/initial-plan.md) preserves the original broad
  project vision. The maintained scope now lives in the MVP and phase roadmap.
- [`plans/decision-support-design-2026-09-15.md`](plans/decision-support-design-2026-09-15.md)
  preserves the proposal that introduced position familiarity, the role matrix,
  squad-wide depth, and the first web surface. Those slices were implemented;
  its catalogue size, benchmark, and “blocked” statements are no longer current.
- [`plans/app-improvement-review-2026-09-19.md`](plans/app-improvement-review-2026-09-19.md)
  preserves the performance, caching and workflow review that was the active
  backlog until 26 September 2026. The [active plan](../active-plan.md)
  superseded it and records where each item went.

## Completed task briefs

[`tasks/`](tasks/) holds briefs from the [task briefs index](../tasks/README.md)
that are built or superseded. Each keeps its original scope, then a *Status*
section recording what was built and the decisions taken.

- Built: [best-known player profiles](tasks/medium-best-known-player-profiles.md),
  [manual scouting verdicts](tasks/medium-manual-scouting-verdicts.md),
  [database-backed candidate pool](tasks/medium-database-candidate-pool.md),
  [scouting-state regression coverage](tasks/low-scouting-state-regression-coverage.md),
  [cover-value contract](tasks/senior-cover-value-contract.md),
  [trial scenario semantics](tasks/senior-trial-scenario-semantics.md) and
  [weakest-slot service](tasks/medium-weakest-slot-service.md).
- Superseded: the [results log](tasks/medium-results-log.md), built instead as
  match history read live from FM (see the
  [match analysis plan](../match-analysis-plan.md)).

## Superseded runbooks

- [`research/discoverability-experiment-protocol.md`](research/discoverability-experiment-protocol.md)
  records the former operator-led package/search workflow. The semantic
  registry, corpus, and `tools/fm20_research.py` replace it operationally.
