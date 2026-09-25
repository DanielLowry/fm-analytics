# Application improvement review

> **Evidence re-checked 22 September 2026. The recommendations still stand; the
> "Evidence checked" figures below do not.** What changed:
>
> - The catalogue is now `fm20-expanded-tactics-v2-position-weights` with **42
>   tactics and 84 roles**, not the 25 and 28 recorded below. Any timing or
>   profile count measured against the old catalogue is void.
> - The suite is **703 tests**, not 443.
> - `SCHEMA_VERSION` is now **4**. Item 3.1 is still open and still P0: there is
>   no migration path at all, so an older capture remains simply unreadable.
> - Still open and unchanged in substance: **1.5 / additional finding 1**
>   (`SquadWebServer.bundle()` still keys on time alone and still computes
>   outside the lock), **2.4** (there is no `/player` route), and **2.2 / 3.3**
>   (recruitment still has two models and two entry paths).
> - Its own **finding 5** — catalogue growth silently invalidating docs — has
>   recurred twice since, and was corrected again in the 22 September pass. The
>   suggestion there to *derive* displayed counts rather than write them down is
>   the durable fix and has not been done.
> - **The performance items (1.1–1.4) now have a measured basis they did not have
>   before, and it partly redirects them.** The joint role/player beam and the
>   later weakest-slot threshold sweep no longer exist; `tactic-fit-v2` needs one
>   assignment solve per role version. Item 1.4 (memoise role scores) remains
>   worthwhile — the earlier profile found 64% of role scoring
>   is measurably redundant — and item 1.5's cache becomes a *correctness*
>   requirement, not just a speed one, as soon as the page can set an opponent.
>   See [analytics-performance.md](analytics-performance.md) for the current
>   50-tactic numbers, package experiments, and method. The older assignment
>   objective and MILP history remains in
>   [tactical-model-upgrade-plan.md](tactical-model-upgrade-plan.md) §7.1.
>
> This document stays in the active index because its recommendations are mostly
> unstarted. Archive it once Releases A–C below are delivered or formally
> dropped, rather than letting it decay further.

**Reviewed:** 19 September 2026  
**Scope:** the supplied performance/product feedback, current implementation,
tests, the local 17-player capture, and maintained documentation.

## Conclusion

The feedback is directionally strong and almost all of it is confirmed. The
application has a capable shared analytics core, but the browser experience is
paying a multi-second calculation too often and the pages do not yet form one
decision workflow. The best next release should therefore focus on operational
reliability and navigation, not new football-model sophistication.

The recommended order is:

1. protect and migrate the only real capture, add an output-equivalence test,
   and record a repeatable benchmark;
2. make recommendation computation single-flight and input-keyed, then remove
   the two dominant search hot spots;
3. add the player page and use it to connect depth, tactics, squad, and the
   dashboard;
4. connect recruitment briefs to scouting through one canonical candidate
   model and one shortlist service; and
5. move long-running scouting refresh into an observable background job.

## Evidence checked

- The current catalogue is `fm20-expanded-tactics-v1`: **25 tactics and 28
  roles**, not the 7- or 12-tactic versions still mentioned in older docs.
- A temporary, non-destructive v2-to-v3 copy of the local 17-player capture
  took **5.02s and 5.44s** for two unprofiled
  `build_recommendation_bundle` runs on this machine.
- A profiled run made about **63.5 million calls**. It invoked both tactical
  system assessments 76,850 times; state sorting/signature generation and
  rounding also dominate the profile. Profiling overhead raised that run to
  12.2s, so it is useful for attribution rather than wall-clock comparison.
- The web server uses an 8-second default TTL and independent `_read_at` and
  `_bundle_at` timestamps. It releases the cache lock while building.
- `data/fm-analytics.sqlite3` is schema v2; `SnapshotStore` requires v3 and has
  no migration path.
- `/scouting/refresh` runs the refresh command synchronously in the request.
- There is no `/player` route. The dashboard reads only source metadata and the
  depth page discards the named player/cover detail already present in the
  bundle.
- Recruitment has two input models and two entry paths:
  `VisibleExportPlayer`/CLI HTML and `ScoutingCandidate`/web JSON.
- `web/server.py` has 25 imports left from its pre-split rendering/handler role.
- The full baseline suite passes: 443 tests on 19 September 2026.

## Review of the proposed work

| Item | Verdict | Review note |
| --- | --- | --- |
| 1.1 Memoise role checks | Reassess if checks become slow | Cache `assess_coherence` and `assess_instruction_suitability` by tactic plus canonical role tuple. They now supply the tactic-balance multiplier, but remain player-independent. |
| 1.2 Incremental beam sort key | Agree, with a correctness caveat | Carry assignment count, total, and weakest score. Preserve exactly the current canonical signature: assignments are appended in candidate-count `slot_order`, not necessarily slot-index order, so simple tuple append is not automatically equivalent. Keep `test_joint_search_can_trade_individual_role_fit_for_system_coherence` and add before/after bundle equality. |
| 1.3 Skip an identical potential pass | Agree | Use a proof over every selectable player/slot candidate that the effective familiarity multiplier is already `1.0`. “All listed positions are 20” is insufficient when a reading is missing and the policy substitutes `unknown_rating=10`. Return the same recommendation only after that proof. |
| 1.4 Memoise role scores | Agree | Scope the cache to one bundle (or a bundle-owned role-score index), where catalogue and scoring policy are fixed. Avoid a process-global `(role_key, player_id)` cache because observations change across captures. Feed the shared index to XI, depth, bench, substitution, role-matrix, and recruitment calculations where practical. |
| 1.5 Fix web caching | Strongly agree; refine the design | Use one cache record containing input fingerprint, bundle, build time, status, and last error. Add explicit refresh/invalidate. Preserve the last good result with a visible stale/error state. Make builds single-flight so concurrent requests do not duplicate work. Fixture and pinned snapshot sources can be immutable; live sources still need explicit or bounded source refresh. Background warming is useful after those semantics exist, not before. Do not call private `SnapshotStore._fingerprint` from web code; extract a public canonical observation fingerprint helper. |
| 2.1 Show squad needs in scouting | Agree | Keep scouting usable without a valid owned-squad bundle, but render optional recruitment briefs when one is available. Each need should link to the existing filters with position, role, and the relevant threshold. Failure to build the squad bundle must degrade to today’s standalone scouting page. |
| 2.2 Unify recruitment models and paths | Agree on the outcome; use adapters | Create one canonical manager-visible candidate/profile model containing the common identity, positions, and observations plus optional scouting metadata and provenance. Adapt HTML and JSON feeds into it. The richer JSON fields should not be discarded merely to make the dataclasses identical. Both CLI and web should call one shortlist service and produce the same ordering and bounds. |
| 2.3 Name players in depth | Agree | Show the selected tactic’s starter, best free cover, drop-off, and cover conflict, with expandable per-tactic evidence for persistent/occasional summaries. The aggregate `PositionDepth` does not itself choose a representative player, so make that presentation rule explicit rather than silently taking the first tactic. |
| 2.4 Add a player view | Strongly agree; highest-value cohesion work | Add `/player?id=…` backed only by bundle data: role ranking, tactic starts, slot/role assignments, depth and bench duties, readiness/familiarity effects, and material information gaps. Link names from squad, roles, tactics, depth, and dashboard. Unknown IDs should be a normal 404 and player names must remain escaped. |
| 2.5 Make the dashboard an answer page | Agree after cache work | Lead with the selected tactic, readiness/staleness, the few highest-priority squad problems, and recruitment needs. Keep the current metadata/coverage block as provenance. When data is incomplete or a build failed, retain the useful degraded dashboard rather than replacing it with an error page. |
| 3.1 Snapshot schema mismatch | Strongly agree; treat as P0 | Add a tested, transactional v2→v3 migration (the known change is the nullable `team_marker` column), make a backup before migrating, and report the path and recovery action on failure. A “re-capture” message alone is inadequate when the sole real capture may not be reproducible. |
| 3.2 Background scouting refresh | Agree | Use one job state (`idle/running/succeeded/failed`), reject duplicate starts, write capture output atomically, show start/end/error and capture age, and keep serving the last good feed. A thread is adequate for this local single-process app if shutdown and exception handling are tested. |
| 3.3 CLI/web drift | Agree | Resolve through the canonical candidate model and shortlist service, then allow either supported feed at either surface. Keep source/provenance labels visible; parity should not erase the distinction between a manual export and live manager-visible capture. |
| 3.4 Dead imports | Agree | The split left 25 unused imports in `web/server.py`. Remove them as a small, separately verifiable cleanup rather than mixing them into behavioural optimisation. |

## Additional findings

### 1. Prevent cache stampedes

`SquadWebServer.bundle()` checks under a lock but computes outside it. With
`ThreadingHTTPServer`, two cold page requests can both miss and each launch the
same five-second build; a startup warmer can race the first request too. A
condition/future representing the in-progress build should let other requests
join it. This belongs in the cache change and should have a concurrency test.

### 2. Make freshness a product concept

Today the dashboard may show a newer `read()` while another page serves a
bundle built from the older read, because their clocks expire independently.
The replacement cache record should expose observation identity, in-game date,
build time, and whether the last refresh failed. “Last good” is safe only when
the UI clearly labels it stale.

### 3. Freeze behaviour before optimising

The proposed “byte-identical bundle” gate is sound in spirit. The bundle is a
dataclass graph rather than an existing byte contract, so use both direct
dataclass equality and a canonical JSON/golden projection over a fixed squad.
Cover tactic ordering, selected XI/roles, all score bounds, bench, substitution
board, weaknesses, depth, role matrix, briefs, and training targets. Run the
existing joint-role regression independently so a serializer cannot hide lost
alternatives.

### 4. Add a performance budget and representative fixture

The bundled fixture has only three players and cannot catch this regression.
Add a deterministic generated 17- or 25-player benchmark fixture outside the
normal unit-test time budget, record catalogue version and machine-independent
call counters, and track wall time as an advisory local/CI benchmark. Counters
for system assessments and signature builds will be less noisy than a strict
seconds threshold.

### 5. Stop catalogue growth from silently invalidating docs and tests

The audit found the README saying 12 tactics, Phase 05 benchmarking 7, and a web
test still commenting that there are 12 while asserting only “at least 12.” The
active README and phase note were corrected in this documentation pass; the
test comment/assertion remains implementation cleanup. Prefer deriving displayed
counts from the catalogue, and make tests assert the behaviour or catalogue
version they actually protect. Update the performance note whenever catalogue
version or beam width changes.

## Delivery plan and gates

### Release A — reliable and fast

1. Back up the local capture and implement/test v2→v3 migration.
2. Add canonical bundle equivalence and representative benchmark coverage.
3. Add the unified, source-aware, single-flight web cache and explicit refresh.
4. Memoise tactical assessments, then carry the beam sort fields incrementally.
5. Add the familiarity fast path and bundle-scoped role-score reuse.
6. Remove dead imports and update measured documentation.

Gate: the migrated capture loads; recommendation output is identical; one cold
build occurs under concurrent requests; cached navigation is immediate; and a
failed refresh leaves a visibly stale last-good result.

### Release B — one connected decision workflow

1. Add `/player` and link every owned-player name.
2. Enrich depth with named starter/cover/drop-off evidence.
3. Turn the dashboard into the decision summary.
4. Add optional “Your needs” links to scouting.

Gate: a manager can move from a dashboard warning to the affected player, see
the depth evidence, and open a pre-filtered scouting search without losing
context or triggering another build.

### Release C — one recruitment workflow

1. Introduce the canonical candidate model and feed adapters.
2. Route CLI and web through one shortlist service.
3. Run scouting refresh as an observable background job.
4. Add source-parity and failed-refresh tests.

Gate: the same captured candidates and brief yield the same ordered shortlist
and score bounds in CLI and web, with provenance preserved.

## Deliberately separate work

Do not combine this programme with nonlinear role scoring, new tactical traits,
opposition analysis, or machine learning. Those change football judgments and
belong in the tactical/phase roadmaps. The work above should preserve current
numbers while making them faster, safer, and easier to use.
