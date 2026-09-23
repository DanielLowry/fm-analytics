# Analytics performance investigation

**Measured:** 23 September 2026  
**Revision:** `fd4e9f7`  
**Catalogue:** `fm20-expanded-tactics-v2-position-weights` — 50 tactics,
84 roles  
**Runtime:** Python 3.12.3, Linux x86-64  
**Packages tested:** NumPy 2.5.3, SciPy 1.18.1, Numba 0.67.0  
**Machine:** Intel Core i7-8650U, four physical cores/eight logical CPUs

This is the current source of truth for tactic-ranking performance. The older
measurements in
[tactical-model-upgrade-plan.md](tactical-model-upgrade-plan.md#71-performance)
remain useful history for the assignment objective and joint-MILP experiment,
but their 42-tactic counts are no longer the current baseline.

## Conclusion

Once a squad snapshot exists, the ranking is CPU-bound inside our analytics.
The best demonstrated improvement is to evaluate independent tactics in four
worker processes. It changes neither the scoring model nor the result and
reduced the full effective-plus-potential ranking from 3.57 seconds to 1.48
seconds for the current 17-player live squad.

For the deliberately harder deterministic 30-player input, four processes
reduced 13.02 seconds to 4.75 seconds. Every returned `TacticEvaluation` was
exactly equal to the sequential result in both measurements.

NumPy is the most promising package for a second optimisation: calculate the
numeric player/role table in one batch, search on compact scores, and build the
detailed per-attribute explanation objects only for results that survive. Its
numeric results matched the current scoring function in every live and
generated comparison made in this investigation. This has not yet been
integrated or measured end to end, so its application-level improvement is an
estimate, not a result.

SciPy's assignment solver, SciPy MILP, Numba, threads, and another layer of
assignment memoisation did not meet the combination of speed and exact-output
requirements. They should not be the next implementation.

## Scope and exact-output rule

These timings begin with an immutable, already-captured squad snapshot. They do
not include locating Football Manager, reading process memory, or validating a
new snapshot. Those are a separate refresh phase.

"Same result" means all of the following, not merely the same winning tactic or
headline score:

- effective and potential tactic order;
- every lower, central, and upper score;
- the player and role assigned to every slot;
- deterministic choices between equal-score assignments;
- weakest-slot identity and system assessments;
- training targets and every downstream bundle report.

Several alternative solvers returned the same objective while choosing a
different equal-score XI. That is a result change under this rule.

## Current calculation

`recommend_tactic_effective_and_potential` ranks the complete catalogue twice:

1. **Effective** applies the current position-familiarity penalty.
2. **Potential** repeats the ranking with that penalty removed.

With 50 tactics, that is 100 complete tactic evaluations. For each tactic the
code:

1. derives its tactic-specific role weights;
2. builds every legal player/slot/role candidate;
3. enumerates the tactic's permitted role versions;
4. finds the exact player assignment for each version; and
5. combines XI quality, weakest slot, system coherence, instruction fit, and
   opponent fit.

The exact assignment is repeated at different minimum player-score thresholds
because the objective is 65% mean XI score and 35% weakest-slot score. A normal
assignment solver maximises a total; the threshold sweep is how the application
also optimises the minimum without changing that objective.

Relevant code:

- `analytics/xi_selection.py::recommend_tactic_effective_and_potential`
- `analytics/xi_selection.py::_build_choices`
- `analytics/xi_selection.py::_best_role_version`
- `analytics/assignment_solver.py::_best_full_fit_assignment`
- `analytics/assignment_solver.py::_minimum_cost_full_assignment`
- `analytics/role_scoring.py::score_role`

## Method

### Live input

The live measurement used the current 17-player first-team snapshot. The
catalogue's derived tactic views were warmed before steady-state component
timings. Every experimental implementation ran in the same Python process as
its sequential baseline and against the same immutable player objects.

Wall time varies with CPU frequency and other machine activity, so paired
comparisons are more meaningful than comparing numbers from separate runs.

### Thirty-player input

The scaling input came from
`tools/benchmark_joint_optimizer.py::synthetic_players(30, 7)`:

- 30 players;
- two to four randomly selected eligible positions per player;
- full position familiarity;
- known attributes from 6 to 18;
- deterministic random seed 7; and
- the complete 50-tactic catalogue.

This is deliberately more demanding than the current live squad. Positional
eligibility strongly affects candidate and assignment counts, so player count
alone is not a sufficient description of a benchmark.

### Equality checks

For parallel experiments, every effective and potential `TacticEvaluation`
was compared by dataclass equality with the sequential result. The SciPy and
Numba experiments additionally compared score changes, assignment changes, and
ranking order independently so equal objectives could not hide tie changes.

No production source was changed during these experiments.

## Baseline and profile

The steady-state 17-player ranking took 3.57 seconds in the instrumented
component run. Other unprofiled runs ranged roughly from 3.0 to 5.1 seconds.
The variation is why this document records paired speed-ups and work counts as
well as clocks.

| Area | Calls | Inclusive time | Share of total |
| --- | ---: | ---: | ---: |
| Build player/slot/role choices | 100 | 1.745 s | 48.8% |
| Request role scores, including cache hits | 6,466 | 1.315 s | 36.8% |
| Compare role versions and choose XIs | 100 | 1.784 s | 49.9% |
| Run the innermost assignment algorithm | 4,446 | 0.811 s | 22.7% |

The times overlap: choice building contains role scoring, and role-version
selection contains assignment solving. They must not be added together.

The bundle-scoped `RoleScoreCache` is already valuable. In the profiled live
run it served 4,459 of 6,466 requests from cache and calculated 2,007 new role
scores. The remaining cost is therefore not simply a missing dictionary cache:
candidate and explanation objects are still constructed in large numbers, and
the effective and potential passes still rebuild their candidate structures.

The first effective pass took 2.29 seconds. The potential pass, sharing the
same role-score cache, still took 1.19 seconds. That second figure is the
opportunity for sharing more preparation between the two passes without
sharing their final assignments.

## Experiments

### 1. Independent worker processes — recommended

Each task evaluated one tactic's effective and potential versions together.
Doing the pair in one worker retains useful local role-score reuse. The parent
process collected the results and can apply the existing deterministic sort.

| Input | Sequential | Two processes | Four processes | Four-process speed-up |
| --- | ---: | ---: | ---: | ---: |
| Live, 17 players | 3.571 s | 2.326 s | **1.481 s** | **2.41x** |
| Synthetic, 30 players | 13.017 s | 7.180 s | **4.745 s** | **2.74x** |

All returned evaluations were exactly equal. The timings include creating and
closing the pool, so a safely retained pool should avoid some repeated setup
cost. That must still be measured in the real server.

The benchmark used four workers because the test machine has four physical
cores. The production default should be bounded and configurable rather than
blindly using all eight logical CPUs.

Python's standard-library
[`ProcessPoolExecutor`](https://docs.python.org/3.12/library/concurrent.futures.html#processpoolexecutor)
is sufficient for a first implementation. Because the web server has
background threads, do not create a fresh `fork` pool from an arbitrary request
or refresh thread. Prefer a persistent pool with an explicit safe process start
method and module-level, picklable worker entry point.

[`loky`](https://loky.readthedocs.io/en/stable/API.html) is the one optional
external package worth evaluating for this stage. Its reusable executor is
designed to retain workers and their imported modules. Use it only if an
implementation benchmark shows a practical lifecycle or startup advantage over
the standard library.

### 2. Threads — rejected

Four `ThreadPoolExecutor` workers preserved the result but increased the live
ranking from 3.52 seconds to 10.37 seconds—nearly three times as long. This is
CPU-bound Python work, so threads contend for the interpreter rather than
running the analytics simultaneously.

### 3. NumPy batch scoring — recommended prototype

The current `score_role` creates complete evidence for every computed
player/role score: observations, three score bands, per-attribute weighted
points, and validation-heavy immutable objects. Most candidates never appear
in a final XI or manager-facing explanation.

A two-stage design using
[`numpy.matmul`](https://numpy.org/doc/stable/reference/generated/numpy.matmul.html)
or equivalent deterministic batched arithmetic would:

1. map player observations to compact lower/central/upper numeric arrays;
2. map every distinct tactic-derived role weighting to a weight array;
3. calculate the complete numeric score matrix in a batch;
4. use compact numeric candidates during selection; and
5. call the existing detailed construction path only for selected or displayed
   evidence.

Measured numeric compatibility:

| Input | Comparisons | NumPy arithmetic | Current full object construction | Six-decimal mismatches |
| --- | ---: | ---: | ---: | ---: |
| Live cache contents | 2,026 | 4.19 ms | Not isolated in this run | **0** |
| Generated known/range/unknown/missing observations | 17,160 | 2.33 ms | 10.07 s | **0** |

The second row is not an end-to-end speed-up comparison. The NumPy side only
does the search arithmetic, while the current side deliberately constructs all
detailed evidence. It demonstrates that arithmetic is cheap enough to separate
from explanation construction.

On the live ranking, all role-score requests consumed 1.315 seconds. That is
the maximum directly available saving before accounting for the explanations
that still have to be materialised. A plausible sequential improvement is
roughly 0.7 to 1.1 seconds, but this is explicitly unmeasured until an
end-to-end implementation exists.

Exactness needs more than the zero-mismatch sample. Attributes and role weights
are whole numbers and range midpoints are half-points, so a deterministic
integer-numerator representation is available. Prefer that representation, or
an explicit compatibility calculation at rounding/tie boundaries, over
allowing a platform BLAS implementation to define a new tie accidentally.

NumPy is currently present only as SciPy's development dependency. If imported
by production analytics, declare NumPy directly in `[project].dependencies`;
do not rely on a transitive development dependency.

### 4. SciPy `linear_sum_assignment` — rejected as a drop-in

Replacing the existing Python Hungarian implementation with SciPy's compiled
[`linear_sum_assignment`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linear_sum_assignment.html)
changed a warm live run from 4.147 seconds to 3.680 seconds, about 1.13x overall.

Scores and tactic order were unchanged, but four potential tactic evaluations
selected different players in equal-score XIs:

- `narrow_4222`
- `no_nonsense_532`
- `defensive_532`
- `trequartista_4312`

SciPy returned optimal totals, but not the existing deterministic tie choice.
It therefore fails the exact-output rule. Encoding or recovering the old tie
behaviour would add complexity for a measured saving of less than half a
second, while process-level parallelism is both faster and behaviour-preserving.

### 5. SciPy joint MILP — retain as a scaling escape hatch

The existing joint optimizer is about 2.15 times slower for the current
catalogue, despite matching all central objectives. It also does not yet
reproduce deterministic player/role ties, partial-XI behaviour, or full score
bands.

It becomes faster only in the synthetic 3,456-role-version stress case. Keep it
as evidence for a future catalogue with dramatically broader role flexibility,
not as the current production path. The full historical measurements remain in
[the model upgrade plan](tactical-model-upgrade-plan.md#joint-roleplayer-milp-prototype-23-september-2026).

### 6. Numba assignment loop — rejected

A Numba-compiled implementation of the current assignment loop preserved every
result exactly. After compilation warm-up, however, it took 4.74 seconds versus
3.03 seconds for the Python baseline in the paired run.

The solver receives thousands of very small Python list/dictionary-derived
tables. Converting each one to a NumPy array cost more than compiling the small
numeric loop saved. Numba could help only after moving a much larger part of the
pipeline to persistent numeric arrays, at which point the proposed NumPy score
table should be evaluated first.

### 7. Memoising complete assignment matrices — rejected

Of 4,446 assignment calls in the latest live count:

- 4,074 cost matrices were distinct;
- 372 were exact second occurrences; and
- only 8.4% of calls were reusable.

The solver itself consumed about 0.8 to 1.0 seconds. Even free cache lookup
would therefore save only about 0.08 seconds; hashing every matrix would consume
part or all of that. The existing role-score cache is much higher value.

### 8. Data-frame and serialization packages — not relevant

Pandas, Polars, and faster JSON libraries do not target the measured hot path.
The cost is many small candidate objects and exact combinatorial assignments,
not loading tactic JSON or aggregating large tables.

## Recommended implementation order

### Phase 1 — exact parallel ranking

1. Add a canonical equality projection for a complete recommendation bundle.
2. Add the 30-player deterministic benchmark outside the normal unit-test
   runtime.
3. Introduce a persistent, bounded four-process ranking executor.
4. Make one worker task evaluate both effective and potential versions of one
   tactic with one local `RoleScoreCache`.
5. Assemble and sort all evaluations in the parent using the existing keys.
6. Keep the existing sequential path available for small catalogues, one-CPU
   systems, tests, and safe fallback after worker failure.
7. Measure cold startup, warm refresh, shutdown, exception propagation, and
   concurrent web refresh behaviour.

Expected result from the prototype evidence: approximately 1.5 seconds for the
current live ranking and under five seconds for the deterministic 30-player
case. Do not turn those indicative local numbers into hard CI limits.

### Phase 2 — compact numeric scoring

1. Precompute the immutable observation arrays once per snapshot.
2. Precompute all distinct tactic-derived role weightings once per catalogue
   and opponent context.
3. Produce compact lower/central/upper scores in one deterministic batch.
4. Build effective and potential candidate tables from the shared intrinsic
   table rather than repeating eligibility, readiness, taper, and role work.
5. Materialise the existing `RoleScore`, `AttributeContribution`, and
   `SlotAssignment` evidence only where a returned report requires it.
6. Compare the complete sequential old and new bundles exactly before enabling
   process parallelism around the new core.

### Phase 3 — re-profile

Only after phases 1 and 2 should the weakest-slot threshold sweep be revisited.
Changing or pruning that sweep is the highest correctness risk because it can
alter both the optimum and deterministic ties. Cython, mypyc, Rust extensions,
or a different optimizer are not justified by the current evidence.

## Verification gate

Any optimisation must pass both direct dataclass equality and a canonical JSON
projection over several complete inputs. At minimum compare:

- all 100 effective and potential tactic evaluations;
- tactic ordering and selected tactic;
- every XI player, slot, and chosen role;
- lower, central, and upper bands at every level;
- mean, weakest, XI, coherence, instruction, opponent, and final scores;
- weakest-slot keys and unfilled slots;
- training targets;
- bench and substitution board;
- weakness and squad-depth reports;
- role matrix and recruitment briefs; and
- forced selections, incomplete squads, unknown/ranged attributes, and
  deliberate equal-score cases.

The four tie changes found with SciPy should become named regression fixtures.
An optimiser that merely preserves the winner or central score is insufficient.

## Refreshing this document

Re-run the baselines whenever any of these changes:

- catalogue version or tactic count;
- role alternatives or exclusion groups;
- `TacticFitPolicy` or `SystemFitPolicy`;
- effective/potential familiarity semantics;
- role-score rounding or attribute representation;
- process start method or worker grouping; or
- supported Python/NumPy versions.

Record the revision, catalogue version, Python version, player generator,
eligibility distribution, worker count, machine topology, exact-output result,
and paired sequential time with every update. Counts and equality are the
regression signal; wall time is supporting evidence.
