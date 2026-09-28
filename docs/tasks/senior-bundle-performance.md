# Senior task: full-bundle performance

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)):
"fast enough on a 17-player squad". Start only when the plan schedules it, or
when a real page (for example multi-tactic scouting, or a larger squad) makes
cost a problem.

**Prerequisite:** read [analytics-performance.md](../analytics-performance.md)
in full, and §7.1 of
[tactical-model-upgrade-plan.md](../tactical-model-upgrade-plan.md) for the
history.

## Why we are doing this

Four ranking workers brought the 17-player live ranking to about 3.5 s, and
the 30-player seed-7 synthetic from 16.6 s to 5.4 s. Compact numeric scoring
("Phase 2" in analytics-performance.md) is the recorded next lever. The old
review's items 1.1 to 1.4 have partly moved on:

- 1.2 (incremental beam sort key) is obsolete: the beam no longer exists.
- 1.4 (memoise role scores) is done as the bundle-scoped `RoleScoreCache`.
- 1.1 (memoise coherence and instruction checks) needs reassessing against a
  fresh profile.
- 1.3 (skip an identical potential pass) is still valid, but only with a proof
  over every selectable player/slot candidate that the familiarity multiplier
  is already 1.0.

## Scope

1. **Re-profile first.** The square-root-mean objective changed the profile.
   Use `tools/benchmark_tactic_ranking.py` (30 players, seed 7), state the
   generator with every timing, and measure the full bundle, not only the
   ranking. Record the catalogue version and tactic count at measurement
   time: older documents disagree (42 vs 50 tactics).
2. **Equivalence harness before any change.** Dataclass equality plus a
   canonical JSON projection over several inputs, including the four tie cases
   SciPy changed (`narrow_4222`, `no_nonsense_532`, `defensive_532`,
   `trequartista_4312`) as named fixtures.
3. **Compact numeric scoring,** following Phase 2 steps 1 to 6, if the profile
   still supports it. Use an integer-numerator representation so ties stay
   exact.
4. **Familiarity fast path (1.3),** only with the proof above.
5. Update analytics-performance.md in place. Do not copy numbers into other
   documents.

## Constraints

- The exact-output rule in analytics-performance.md: every band, assignment
  and tie, not just the same winner.
- Keep the split in `xi_selection.py` between role-version expansion and exact
  assignment. Read `analytics/CLAUDE.md` first.
- The core path needs no third-party packages today. Adding NumPy as a required
  dependency is a product decision.

## Decisions reserved for review

- Whether NumPy becomes a core dependency, or is optional with a pure-Python
  path that gives identical output.
- The performance target.

## Success criteria

- The equivalence harness passes on every input, before and after.
- Before and after timings are recorded with revision, catalogue version,
  generator, worker count and machine.
- Worker-pool and sequential paths produce identical bundles.
- Full suite, CI compile step and bridge smoke test pass.

## Likely code and tests

- `src/fm_analytics/analytics/xi_selection.py`
- `src/fm_analytics/analytics/role_scoring.py`
- `src/fm_analytics/analytics/assignment_solver.py`
- `tools/benchmark_tactic_ranking.py`
- a new equivalence test module
- `docs/analytics-performance.md`
