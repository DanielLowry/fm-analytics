# Senior task: scouting cost budget and default tactic

**Active-plan item:** 2, plus the scouting default that item 1 deferred.

**Prerequisite:** the real scouting capture in `data/`, which is gitignored and
absent on a fresh clone. A synthetic pool is fine for the repeatable benchmark,
but the decision must be checked against the real capture.

**Unblocks:** the performance budget reserved in the
[multi-tactic scouting service](medium-multi-tactic-scouting-service.md), and
the question item 1 left open: should `/scouting` default to the primary
tactic?

## Why we are doing this

Item 1 left the Scouting page on the generic ranking. Defaulting to the
primary tactic would run the tactic ranking over the whole candidate pool on
every visit, and that cost had not been measured. Item 2 multiplies the work
by the number of pinned tactics (three today). Someone has to measure it and
set a budget before the service brief chooses between computing per request,
precomputing, caching or using worker processes.

## What already exists

- Pool size on the test save: about 4,551 players in the feed, about 794 known
  or scouted (see "How long a refresh takes" in
  [scouting-workspace.md](../scouting-workspace.md)). The active plan quotes
  about 730 players with visible attributes.
- `rank_candidates_for_tactic` prepares the best allocation of the other ten
  slots once per legal role version and candidate slot, then reuses it across
  the pool.
- `SquadWebServer.scouting_rank_cache` and `warm_scouting_rankings` pre-score
  the generic ranking after start-up and after each refresh. Tactic mode has
  no equivalent.
- `TacticRankingExecutor` is a process pool for the bundle's tactic ranking.
  Scouting does not use it.

## Scope

1. Add a repeatable benchmark under `tools/`, in the style of
   `tools/benchmark_tactic_ranking.py`: a synthetic owned squad and a synthetic
   candidate pool, run for the primary tactic alone and for all three pinned
   tactics. Print the generator (counts, positions per player, known/range/
   unknown mix, seed) with every timing. Timings from different generators are
   not comparable.
2. Measure against the real capture. Record the revision, candidate count,
   how many candidates have at least one visible attribute, owned squad size,
   tactic keys, cold and warm wall time, and machine.
3. Profile to attribute the cost: remainder preparation, per-candidate
   evaluation, and rendering.
4. Decide and record:
   - a page-load budget for `/scouting` in tactic mode and **My tactics** mode;
   - whether the page defaults to the primary tactic when pins are set;
   - whether tactic results are precomputed after a refresh, cached, or
     computed per request; and
   - whether the process pool is justified for scouting.

## Constraints

- Exact output: a cache or optimisation must not change any displayed number.
  This is the same rule as in
  [analytics-performance.md](../analytics-performance.md).
- Any cache key must include the scouting capture, the owned-squad snapshot,
  the opponent profile and the pinned tactics (active plan, "Web cache").
- Stop at measuring and deciding. Building the cache belongs to the service
  brief or the [web cache rework](medium-web-cache-rework.md).

## Deliverables

- The benchmark script, committed and runnable.
- Real-capture numbers and the four decisions, recorded in
  `docs/scouting-workspace.md` (numbers may go in
  `docs/analytics-performance.md` instead).
- Updated status lines for items 1 and 2 in the active plan, and an update to
  the service brief's reserved performance decision.

## Success criteria

- The benchmark runs from a fresh clone without `data/` and prints its
  generator with each timing.
- Real-capture numbers are recorded with their context.
- All four decisions are written down with the measurement that supports each.

## Likely code and tests

- `tools/benchmark_scouting_tactics.py` (new)
- `src/fm_analytics/analytics/tactic_scouting.py`, read only
- `docs/scouting-workspace.md`, `docs/active-plan.md`
