# Delegable task briefs

These briefs turn every open and parked item in the
[active plan](../active-plan.md) into bounded assignments. Low and medium
briefs suit lower-skilled implementation agents. Senior briefs settle the
contracts and research those agents must not invent. The briefs do not form a
second backlog: the active plan still decides priority and product scope, and
a parked item's brief is a ready handoff, not permission to start.

## Skill labels

- **Low** means a contributor can follow an existing code and test pattern.
  The task must not require a new data model, scoring rule, persistence rule,
  or interpretation of Football Manager internals.
- **Medium** means a contributor can make a change across a few application
  layers, design a small internal API, and write edge-case tests. A reviewer
  should still approve visibility, timeline, migration, and performance
  decisions.
- **Senior/specialist** briefs (`senior-*.md`) are for the product owner or
  an engineer trusted with process-memory access, Unicorn/Frida and sandbox
  behaviour, discoverability research, new scoring semantics (such as the
  definition of cover value), or exact-output performance work. They frame the
  questions and constraints rather than prescribe an answer. Their usual output
  is a recorded decision or contract that unblocks a low or medium brief. Low
  and medium briefs must never take over a senior brief's decisions.

An agent should not start a task whose prerequisite is unmet. A blocked brief
is useful as a later handoff, not permission to invent the missing contract.

## Recommended order

### Scheduled items (1–6)

Items 1 and 4 are built and need no brief.

| Brief | Level | Active-plan item | Ready when |
|---|---|---:|---|
| [Cover-value contract](senior-cover-value-contract.md) | Senior | 2 | Built 28 September 2026 |
| [Scouting cost budget and default tactic](senior-scouting-cost-budget.md) | Senior | 2 (and item 1's deferred default) | Now; needs the real capture in `data/` |
| [Multi-tactic scouting service](medium-multi-tactic-scouting-service.md) | Medium | 2 | The cover-value contract is built; still needs the cost budget |
| [Multi-tactic scouting presentation](low-multi-tactic-scouting-presentation.md) | Low | 2 | The service returns a stable presentation model |
| [Trial scenario semantics](senior-trial-scenario-semantics.md) | Senior | 3 | Built 28 September 2026 |
| [Weakest-slot service](medium-weakest-slot-service.md) | Medium | 3 | Built 28 September 2026 |
| [Trial-priority list](medium-trial-priority-list.md) | Medium | 3 | Now; semantics and weakest-slot service are both built |
| [Weakest-slot navigation](low-weakest-slot-navigation.md) | Low | 3 | Now; the weakest-slot service is built |
| [Scouting-state regression coverage](low-scouting-state-regression-coverage.md) | Low | 3–5 support | Now; keep it away from the in-progress feed tools |
| [Best-known player profiles](medium-best-known-player-profiles.md) | Medium | 5 | Built 27 September 2026 |
| [Database-backed candidate pool](medium-database-candidate-pool.md) | Medium | 5 | Built 28 September 2026 |
| [Manual scouting verdicts](medium-manual-scouting-verdicts.md) | Medium | 5 | Built 27 September 2026 |
| [Scouting alerts](medium-scouting-alerts.md) | Medium | 6 | The weakest-slot service is merged (profiles and verdicts are built) |

Only the scouting cost budget still blocks the multi-tactic scouting service;
the cover-value contract and the trial-scenario semantics that unblocked most
of the rest of items 2–3 are both built. The weakest-slot service is built
too, so the trial-priority list and weakest-slot navigation are ready.
Regression coverage can start now.

### Parked items

Start these only when the active plan schedules them.

| Brief | Level | Plan entry | Ready when |
|---|---|---|---|
| [Results log](medium-results-log.md) | Medium | Item 7 | Superseded: built as [match history](../match-analysis-plan.md), 29 September 2026 |
| [Web cache rework](medium-web-cache-rework.md) | Medium | Parked: web cache | Now, if scheduled |
| [Dashboard as an answer page](medium-dashboard-answer-page.md) | Medium | Parked: dashboard | The web cache rework has landed |
| [Named depth evidence](low-named-depth-evidence.md) | Low | Parked: named depth | The presentation rule is confirmed |
| [Background scouting refresh](medium-background-scouting-refresh.md) | Medium | Parked: background refresh | Now, if scheduled |
| [Squad capture upgrade path](medium-squad-capture-migrations.md) | Medium | Parked: capture upgrade path | The baseline version is decided |
| [Retire the CLI candidate shortlist](medium-retire-cli-candidate-shortlist.md) | Medium | Parked: two recruitment paths | The product owner confirms retire-not-merge |
| [Full-bundle performance](senior-bundle-performance.md) | Senior | Parked: performance | Now, if scheduled |
| [Wages in the scouting capture](senior-wage-capture.md) | Senior | Parked: wages | Now, if scheduled |
| [Remove dead imports from `web/server.py`](low-web-server-dead-imports.md) | Low | Review item 3.4 | Now |

### Deliberately without a brief

- **Dedicated set-piece ratings** (the plan's quick win) is a manager action in
  FM, not code. Follow [set-piece-optimizer.md](../set-piece-optimizer.md).
  Reading those ratings live would be specialist research outside the active
  plan.
- **Tactical model** changes stay in the
  [tactical-system roadmap](../tactical-system-roadmap.md).
- **Opposition analysis from data, machine learning and automation** stay in
  Phases 08–11 of the [delivery roadmap](../phases/README.md).

## Rules shared by every brief

- Use only manager-visible observations. Never recover an unknown attribute
  from a raw value or lower-level research artifact.
- Do not put scoring or database queries directly in HTML render helpers.
- Reuse the existing web `ScoutingCandidate` path. Do not add the same feature
  independently to the older CLI `VisibleExportPlayer` recruitment path.
- Preserve exact, range, unknown, uncaptured, and historical states. They are
  not interchangeable.
- Keep save identity in every player-knowledge query and write.
- Add focused tests and run the relevant modules. Run the full suite before
  declaring a cross-layer task complete.
- Do not modify the current uncommitted sandbox/scouting-feed work unless the
  task explicitly requires it. Only the senior wage brief edits the feed
  tools; the background-refresh brief is designed to leave them unchanged.

## Handoff expectation

The assigning agent should name the brief, confirm that its prerequisites are
met, and identify the reviewer for any decision reserved in the brief. The
implementing agent should report changed files, tests run, and any acceptance
criterion it could not verify against real data.
