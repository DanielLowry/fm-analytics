# Delegable task briefs

These briefs turn selected parts of the [active plan](../active-plan.md) into
bounded assignments for lower-skilled implementation agents. They do not form
a second backlog: the active plan still decides priority and product scope.

## Skill labels

- **Low** means a contributor can follow an existing code and test pattern.
  The task must not require a new data model, scoring rule, persistence rule,
  or interpretation of Football Manager internals.
- **Medium** means a contributor can make a change across a few application
  layers, design a small internal API, and write edge-case tests. A reviewer
  should still approve visibility, timeline, migration, and performance
  decisions.
- **Senior/specialist** work is deliberately absent. In particular, these
  briefs do not delegate process-memory access, Unicorn/Frida behaviour,
  discoverability research, new scoring semantics, or the definition of cover
  value.

An agent should not start a task whose prerequisite is unmet. A blocked brief
is useful as a later handoff, not permission to invent the missing contract.

## Recommended order

| Brief | Level | Active-plan item | Ready when |
|---|---|---:|---|
| [Multi-tactic scouting service](medium-multi-tactic-scouting-service.md) | Medium | 2 | A reviewer has settled the cover-assessment contract |
| [Multi-tactic scouting presentation](low-multi-tactic-scouting-presentation.md) | Low | 2 | The service returns a stable presentation model |
| [Weakest-slot navigation](low-weakest-slot-navigation.md) | Low | 3 | Weak-slot link data is supplied by analytics/reporting |
| [Scouting-state regression coverage](low-scouting-state-regression-coverage.md) | Low | 3–5 support | Now; keep it away from the in-progress feed tools |
| [Best-known player profiles](medium-best-known-player-profiles.md) | Medium | 5 | Now; the knowledge store write side is built |
| [Database-backed candidate pool](medium-database-candidate-pool.md) | Medium | 5 | Best-known profiles have a stable API |
| [Manual scouting verdicts](medium-manual-scouting-verdicts.md) | Medium | 5 | Now; coordinate its migration with other database work |
| [Scouting alerts](medium-scouting-alerts.md) | Medium | 6 | Database profiles and verdicts are both available |

The multi-tactic and weakest-slot presentation briefs depend on product-facing
analytics that may need senior ownership. Regression coverage is ready now.
The final four stay on the application side of the already-built
player-knowledge database, although migrations and time-based semantics still
need review.

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
  task explicitly requires it. None of the briefs below does.

## Handoff expectation

The assigning agent should name the brief, confirm that its prerequisites are
met, and identify the reviewer for any decision reserved in the brief. The
implementing agent should report changed files, tests run, and any acceptance
criterion it could not verify against real data.
