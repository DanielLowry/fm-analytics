# Tactic and role-specific form adjustment

Proposed implementation plan, 3 October 2026. Scoring and refresh behaviour
have not been changed. The defaults below are deliberately small and tunable.

The aim is to let recent performances make a small difference to today's
tactic and XI ranking, provided those performances belong to the exact job
being considered. A player's poor BBM(S) performances in one tactic must not
reduce his CM(S) score in that tactic, or his BBM(S) score in another tactic.

## What the app already supplies

- `domain/matches.py::PlayerMatchStats` records the player's unique ID when
  available, short ID, raw role code, rating, substitution minutes and stats.
  Unused substitutes and appearances FM does not rate have no usable rating.
- `analytics/match_roles.py::RoleCodes` maps confirmed raw codes to catalogue
  role keys. Those keys include duty. However, the underlying code's ability
  to distinguish duties is explicitly **unverified**. Some keys cover two
  positions: Full Back Support covers DL/DR, and Winger Support covers ML/MR.
- `analytics/match_analysis.py::summarise_matches` takes a tactic from a match
  note, or infers one if exactly one catalogue tactic fits the starting roles.
  That inference does not inspect the actual instructions used.
- `persistence/match_history.py` keeps append-only match versions and prefers
  the latest detailed version over a later result-only observation.
- `reporting.build_recommendation_bundle` is the shared CLI/web computation.
  `analytics/xi_selection.py::score_player_for_slot` scores each permitted
  player/position/role choice before the joint XI and role optimiser runs.
- Match capture is currently a separate, synchronous Matches-page action.
  Refreshing the squad does not refresh matches. Cached recommendation
  bundles are not currently invalidated by match capture or note changes.

### Local evidence and timings

The current database has 52 matches from 25 June 2019 to 21 March 2020,
50 with full stats, 712 played appearances and 681 ratings. There are 619
appearances linked to a player ID and 683 labelled by an existing role-code
mapping; these are separate coverage counts, not a count of usable form rows.
There are no explicit tactic notes. The current catalogue infers Vertical
4-4-2 for 28 detailed matches and cannot identify a tactic for the other 22.

In the 90 game days ending 25 March 2020 there are 17 competitive detailed
matches, but only one has an inferred tactic. None of the potentially
eligible player/tactic/role groups has three appearances in that window.
Reliable attribution and improving those recent match labels therefore come
before tuning a form coefficient.

Reading and parsing the 52 latest stored match documents took a median
12.18 ms over seven runs (11.72–15.76 ms), using SQLite read-only access.
This excludes league results, notes and a complete recommendation calculation.

Against the running FM process, three consecutive calls to the existing
capture command took 6.974, 6.995 and 7.011 seconds: median **6.995 seconds**.
Each saw 52 matches, 49 with full stats, through game date 25 March 2020.
These measurements include memory reads, archive parsing and atomic JSON
output to `/tmp`, but exclude initial Python imports, initial PID discovery,
database ingestion and tactic ranking. They used one interpreter, so they
are not a measurement of cold subprocess startup.

A separate cProfile run took 8.226 seconds. Its main costs were three memory
scans (3.536 seconds cumulative) and archive matching (3.069 seconds), including
decompressing 6,949 archive chunks (2.477 seconds). These timings have profiling
overhead and some call categories overlap. The capture files and profile were
written only under `/tmp`; the app's database was not changed.

This supports background capture triggered by changes. It does not support
running a full capture on every page load or health check. Re-profile cold
capture, ingestion and complete recommendation refresh during implementation.

## 1. Establish trustworthy appearance context

Use this identity for a form bucket:

`(save namespace, club ID, player ID, tactic key, position, role key)`

The role key includes duty, for example `b2b_support` versus `cm_support`.
Position means the catalogue position, such as MC or ML, rather than a
formation slot name such as MCL. Two MC slots using the same role in the same
tactic share evidence; ML and MR do not. Alternative role choices remain
under the same tactic key, but occupy different form buckets.

Before using the raw match role field for scoring, verify it against FM's
visible lineup/tactics screens for:

1. BBM(S) and CM(S) in otherwise unchanged tactics;
2. the same role on Support versus Attack/Defend where allowed;
3. roles shared between left/right or multiple positional lines;
4. substitutions and an appearance in which position, role or tactic changes.

Determine whether the recorded field describes the starting, final or another
role. Investigate the archived tactical/lineup objects for actual position,
duty and tactic settings. Reuse the field-acquisition workbench and existing
live/archive readers; do not introduce guessed offsets or hidden engine inputs.

**Progress, 3 October 2026.** FM's player match record holds each player's
starting position (with which of a central pair) and position played,
substitutes included; the capture now reads both (see
[match-analysis-plan.md](match-analysis-plan.md), "Found on 3 October").
Against the checklist above:

- **Position (3):** answered from FM's own record, so no manager confirmation
  is needed for it: DL and DR, ML and MR are distinct positions there.
  Captures made before 3 October have none until the next capture re-reads
  the archive.
- **Substitutions and changes (4):** a substitute carries the role code and
  position of the job he did, which can differ from the player he replaced
  when the shape changes. A starter whose position played differs from his
  starting position moved. A role change within one appearance is not
  visible: there is one role code per appearance.
- **Codes are labels, not identities:** the left-sided Advanced Forward
  (Attack) has two codes (`0x800` to 26 December 2019, `0x80000` after), for
  a reason not yet known. With `0x80000` confirmed, 44 of the 50 detailed
  matches infer Vertical 4-4-2 (it was 28).
- **Duty (1, 2):** answered: the code does not record duty. On 28 March
  2020 Bellamy played CM(S) beside Hargreaves at CM(D), and both carry `0x20`
  (confirmed by the manager). A code therefore names a role *family*; tactic
  inference matches by family (46 of the 51 detailed matches now infer
  Vertical 4-4-2), and the duty comes from the tactic: the slot a player
  filled must allow exactly one duty of his role. Starters are matched to
  slots position by position, using which of a central pair they started
  in; a substitute takes the slot of the player he replaced in the same
  position, and one who came on in a changed shape is not used.

`uv run fm-matches coverage` (`reporting.build_appearance_coverage`, over
`analytics/appearance_context.py`) is this section's completion check. On 3
October 2026, for the last 90 game days (16 matches, 221 appearances): none
usable yet, 166 usable once each match's inferred tactic is confirmed, and 55
not usable. The largest group, 40, is the centre-backs: Vertical 4-4-2 lets
either play Defend or Cover, so their duty stays unsettled until the manager
says which he plays. The rest are substitutes in a changed shape, players no
longer in the squad, and cameos FM did not rate.

Add optional observed context and provenance to the match appearance contract
only when its semantics are verified. Preserve raw role codes. Existing
captures remain readable with unknown context, and any new persisted tables
use the shared migration runner.

Provide a fallback in the existing match detail screen: the manager can
confirm the tactic and, where needed, an appearance's position and role/duty.
Store corrections as append-only local evidence. A global code-to-role label
is not proof of an appearance's duty if duties share a code. A position can
be resolved without a new source field only when confirmed role and tactic
compatibility leave exactly one catalogue position.

For score-changing evidence, accept an actual validated tactic linkage or the
manager's explicit confirmation. Keep role-multiset inference as a suggestion
for confirmation: uniqueness in our catalogue cannot establish which real
tactic instructions were used. Neither pinned tactics nor the current
recommendation establishes what was played historically.

An overall match rating cannot be separated into ratings for multiple roles.
Exclude appearances known to span multiple relevant contexts, or whose context
cannot be established. Do not copy the rating into each role bucket or allocate
it by guessed minutes. If the reader cannot establish a single context,
manager confirmation is the conservative first-release fallback.

Join players by stable IDs, never by display name. A short-ID join is usable
only if uniqueness and its relationship to the current player ID are verified
within the save. Unresolved appearances remain neutral.

The current default save key is `club:<id>`, not a true save identity, and the
web normally selects the latest recorded save. Resolve form from an explicit
matching history namespace, validate club identity and expose a shared
`--match-save-key` setting for the CLI and web. Separate playthroughs/branches
of the same club need distinct namespaces or databases until a reliable save
identifier exists. Never silently select unrelated latest history or accept
an automatic rewind.

**Completion check:** report how many recent appearances have trustworthy
player, tactic, position and duty context, and why other appearances were
excluded. If automatic extraction remains insufficient, state which
confirmations are needed rather than applying approximate form penalties.

## 2. Build a small, pure form calculation

Add `analytics/player_form.py` with a versioned `FormPolicy`, immutable
appearance evidence, bucket summaries and a precomputed lookup. The reporting
layer resolves history and builds the lookup once per input generation.
Reuse the existing match models and confirmed-context resolution; do not
reuse season-wide average ratings as role-specific evidence.

Proposed first-release defaults:

- Competitive first-team matches only; friendlies excluded.
- At most the five latest qualifying appearances in the exact bucket,
  within the preceding 90 game days and no later than the squad snapshot.
- At least 30 minutes played and a rating FM visibly supplies.
- Weight each rating by `min(minutes / 90, 1)` and a 30-game-day half-life:
  `weight = min(minutes / 90, 1) * 2 ** (-age_days / 30)`.
- Use a fixed neutral rating of 6.7 initially. This is a tunable modelling
  choice, not a claimed FM average. Do not derive it from the player's other
  roles or tactics.
- Let `E` be the sum of weights and `R` the weighted mean rating. Use
  `confidence = E / (E + 3)` to shrink small or old samples toward neutral.
- Apply `multiplier = 1 + confidence * clamp(0.02 * (R - 6.7), -0.02, 0.02)`.
- No qualifying evidence gives exactly `1.0`. A disabled policy is also
  exactly neutral. Missing ratings are never treated as zero.

The multiplier can never move a player's score by more than 2% in either
direction, and confidence usually makes it considerably smaller. One recent
90-minute rating of 6.0 gives approximately -0.35%. Five equally recent full
appearances averaging 6.0 give -0.875%: a score of 60 becomes 59.475. Actual
spaced-out matches have lower confidence through age decay. Good form gives
a similarly small bonus, with final score bands bounded to 0–100.

These defaults reward repeated evidence, reduce the influence of short
substitute appearances, and let old poor performances fade away even when the
player does not retry that role. They do not infer causation or adjust for
opposition strength in this first release.

**Completion check:** every adjustment is reproducible from listed match IDs,
ratings, minutes, dates, exact context and policy version.

## 3. Apply form before choosing players and alternate roles

Extend `score_player_for_slot` with explicit tactic/form context and multiply
its existing selection score by the exact candidate role's form multiplier.
Apply the same multiplier to lower/central/upper attribute score bands without
inventing extra attribute knowledge. Carry evidence and the score change on
the resulting assignment so explanations use the computed result.

The lookup must happen separately for every allowed role, before the
assignment solver and legal role-version search. Applying an adjustment to
the selected XI afterward would miss the intended player/role switches.
Eligibility, role exclusions and team balance stay governed by their existing
rules. Since form is independent for each candidate assignment, the current
exact optimiser remains applicable.

Thread one immutable form snapshot through the shared recommendation bundle,
sequential/process-worker ranking, forced assignments, alternative-player
explanations, matchday bench, substitution board and tactic scouting's owned
player baseline/projections. External recruits without evidence in our exact
tactic receive a neutral multiplier; comparisons must use the same form
context for the remaining owned players.

Keep intrinsic attribute scores, tactic-free Squad/Role views, and the
attribute-based weakness/depth/recruitment thresholds on their existing basis.
Where those views show a today's selection score, use or label the adjusted
value explicitly. Temporary poor form should not become an attribute deficit
or a recommendation to recruit a replacement.

Use the same form snapshot in the effective and potential rankings: their
existing difference is position familiarity. This prevents training targets
from treating temporary form as a benefit of position training.

Keep form out of the intrinsic `RoleScoreCache`. Derived form/selection caches
must include tactic, position, role, policy, game date and evidence generation.
Worker jobs receive a serializable precomputed lookup, not a database handle
or one history scan per score call. The bundle retains its form snapshot so a
later drill-down cannot mix old rankings with newer form.

Update score explanations to separate fitness costs from form changes.
Currently `selection_explanation.py` treats the difference between tapered
score and final selection score as readiness cost; that subtraction would
mislabel form as fitness after this feature is added.

**Completion check:** BBM(S) evidence can change the selected BBM(S) player or
make CM(S) win a close role choice, while CM(S)'s own score remains neutral
without CM(S) evidence. Ranking, alternatives and bench use identical inputs.

## 4. Refresh matches automatically without blocking pages

Replace the synchronous capture action with a single background refresh job,
shared by automatic refresh, the existing Matches button and squad refresh.
Reuse `match_ingest` capture/ingestion and the existing capture lock. Keep
serving the last completed coherent recommendation while a job runs.

Initial scheduling proposal, to validate against cold and growing-save
profiles:

1. In a live mode with an available matching capture capability, capture once
   on startup and request capture as part of an explicit squad refresh.
   Fixture, historical-snapshot and incompatible remote-bridge modes do not
   silently capture the local running game.
2. Poll a cheap source fingerprint every 30 seconds: process/session identity,
   available validated date/club context, and archive file identity/size/mtime.
   A new game date alone is not proof of a new match. Prefer archive/new
   completed-fixture changes, debounce writes for about five seconds and
   coalesce triggers. Archive changes must work for a match played on the
   same game date. If a fingerprint cannot be obtained cheaply, begin with
   a bounded background interval, provisionally five minutes, and measure it.
3. Capture only when relevant inputs change, with a provisional 60-second
   minimum between automatic captures. Manual refresh can bypass the interval
   but shares the one-job lock. Retry missing/pending detail after the archive
   settles rather than claiming the result is complete.
4. Validate source identity/date before and after capture. Discard mixed
   captures and retry if the save or game context changed while reading.
   Preserve the existing refusal of unexplained rewinds. Process restarts
   invalidate cached addresses and source fingerprints.
5. Ingest idempotently, preserve previously captured detail, and advance the
   form evidence generation only when relevant evidence changes. An unchanged
   capture updates refresh status without causing a new full tactic ranking.
   If capture costs remain high as archives grow, profile incremental archive
   indexing and re-reading only missing/changed match details before adding it.

Match capture, tactic/context corrections and role confirmations invalidate
all affected opponent-profile bundles, tactic reports and tactic-scouting
projections. Include the evidence generation in cache identities and check it
again before publishing a computed result, so an older job cannot overwrite a
newer result. Publish a completed result atomically.

Automatic refresh must also coordinate with squad refresh. New history beyond
the displayed squad's game date triggers a fresh squad snapshot before new
rankings are published. Do not attach future appearances to an old snapshot.
Date changes rebuild the form lookup even with no new matches, because form
decays and the eligibility window moves.

On failure, retain the previous completed snapshot, show the last successful
capture date/time and error, and retry with bounded backoff. Do not call a
snapshot current simply because its latest match date equals the squad date:
track successful capture coverage separately from when a match was played.
For a club/namespace mismatch or an unexplained rewind, disable use of that
history until the source is resolved. Shut down background jobs cleanly.

**Completion check:** a newly completed match updates stored history and the
recommendation automatically after detection/capture/ranking, without a slow
HTTP request. Repeated unchanged checks cause no full capture or ranking, and
capture failures preserve the previous complete result with visible freshness.

## 5. Explanations, validation and delivery order

Show a small Form contribution on the tactic lineup and alternative-player
views. For example: "-0.5 points · recent form as MC / BBM(S) in Vertical 4-4-2",
with qualifying appearance count, minutes, date range and rating behind an
expandable explanation. Distinguish "no recorded appearances in this job"
from "appearances excluded because role/duty/tactic is unconfirmed"; both are
neutral. Show whether matching evidence is refreshing or stale.

Use meaningful regression cases for:

- Poor BBM(S) evidence, no CM(S) evidence: only BBM(S) changes.
- Same player/role in a different tactic, position, duty or save: neutral.
- Unconfirmed tactic inference, ambiguous side/duty, changed-role appearances,
  missing ID/rating, unused substitutes and short appearances: excluded.
- Positive/negative form bounds, confidence shrinkage, time decay, friendlies,
  rolling-window expiry and exclusion of future matches.
- Actual role/player selection changes, legal-role constraints, exact neutral
  compatibility, sequential/worker equality and CLI/web parity.
- Identical form context in forced-assignment explanations, bench,
  substitutions and scouting projections; separate form/readiness arithmetic.
- Idempotent capture, retained detail, note/correction invalidation,
  same-day match detection, namespace changes, rewind, failed capture,
  overlapping triggers and stale-job publication races.

Benchmark the full shipped catalogue with the existing deterministic
30-player generator (seed 7, two to four eligible positions per player), plus
the captured real squad. State the generator, catalogue and history size with
each timing. Measure history parsing/form aggregation, lookup/worker overhead,
cold/warm capture, ingestion, full bundle and change-to-published-result time
separately. Also measure unchanged polling and histories with multiple seasons.
Use output equality and call counts as regression checks, not brittle CI
wall-clock limits.

Deliver in this order:

1. Attribution verification and a usable confirmation fallback.
2. Pure form policy/lookup and exact-context regression tests.
3. Shared scoring integration and explanations.
4. Background capture, scheduling and cache/snapshot coordination.
5. Full validation, performance measurements and operating documentation.

The main implementation uncertainty is obtaining trustworthy historic
position/duty/tactic context. Capture performance is already sufficient for
occasional background work on this save; the automatic cadence and any
incremental optimisation should follow the implementation measurements.
