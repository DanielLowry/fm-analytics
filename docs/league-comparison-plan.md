# League team comparison plan

**Status:** in progress, 3 October 2026. Scenario scoring, dated capture history,
and comparison screens are built. A live read-only capture of the whole league
(`tools/fm20_league_capture.py`) now supplies them, with FM's own attribute and
position visibility. It awaits a check of a few players and squads against FM's
screens before slice 1 counts as done; see "Live league capture" below.
**Request:** rank the players at every club in our league, select each club's
best XI, score it with our existing team model, and compare clubs while showing
the uncertainty caused by incomplete scouting.

## First implementation slice (3 October 2026)

- `SelectionObjective` now threads lower/central/upper selection through the
  existing assignment solver, legal role versions, and tactic ranking. Default
  central results remain unchanged; original attribute observations are retained.
- `analytics/team_comparison.py::compare_team_xi` reselects the XI for all three
  scenarios. It returns the independently optimised team band separately from
  the central lineup's own band. Explicit roster/position-completeness flags
  prevent partial or unverifiable teams from receiving a comparable score.
- `reporting.build_team_xi_comparison` exposes this through the shared reporting
  layer, using existing selection policies and a neutral opponent. The default
  tactic search includes the whole catalogue; a supplied tactic shortlist
  restricts all three scenarios equally.
- Focused tests cover exact-score parity, a ceiling-only unknown reserve,
  endpoint changes of roles and tactics, exhaustive shared-position assignment,
  zero-score unknown squads, taper bounds, incomplete rosters, and reporting.
- A new passive `league-roster-inventory` controller recipe found stable roster
  ID vectors for all 22 clubs represented in 352 National League South results,
  at game date **21 February 2020**, with no read failures or operator action.
  The managed club is Hungerford Town, ID `5103652`; active manager ID
  `1915435143`. This is diagnostic identity evidence, not production approval.
  The immutable session and adapter reports are indexed in the research corpus.

The remaining data gate is an authoritative current participant list (including
preseason), public first-team roster validation, and manager-visible external
positions. The inventory deliberately reads no external attributes, readiness,
or raw positions and cannot feed the scoring service. (All three are now read
by the live capture below, pending the checks against FM listed there.)

## Capture-driven screens (3 October 2026)

- A strict [versioned capture contract](contracts/league-capture.md) carries dated
  participant/roster evidence, visible observations, and completeness flags.
  Unknown positions can be stored, but prevent a comparable team score.
  Research inventories, hidden attributes, and external numeric familiarity
  are rejected. Uncaptured attributes remain distinct from observed unknowns.
- A separate migrated SQLite store appends whole capture revisions by explicit
  save key, records same-date changes, refuses backward-date ingestion without
  a branch key, and never retrieves future observations for an as-of query.
- `/league` shows every captured club, independently selected best-XI ranges,
  interval ranks, own-club highlighting, common-tactic controls, and uncertainty
  sorting. Incomplete clubs remain visible without a score or rank.
- Team drilldowns show conservative/floor/ceiling pitch XIs, full roster
  rankings with position/role filters, visible player attributes, and the
  largest role-scoring information gaps in central and ceiling selections.
- External unknown availability is provisionally available, with an explicit
  assumption. Owned availability follows the existing scorer unchanged.
  Readiness/familiarity fallbacks are shown; comparisons using them are labelled
  conditional. The league's owned observations must agree with the web squad.
- A single background worker computes one revision at a time, with at most one
  pending request. Repeated polling joins that job. A previous completed report
  in the same save/tactic scope stays usable with an update notice; failures
  expose a retry. Completed reports are cached in a bounded in-memory LRU.
- `--league-json` opts into a supplied capture; an explicit demo generator
  allows screen review without inventing a live league. No default live or
  synthetic capture is silently substituted.
- The seeded 22-club, 22-player, mixed-knowledge benchmark covers all 50 tactics
  and three scenarios. Cold computation took 22.497 seconds, with a 0.0117-second
  cached report. See [the performance record](analytics-performance.md#league-comparison-workload-3-october-2026)
  for the generator and limits. This justified moving HTTP requests off the
  computing path; it does not establish the cost of a live full league.

Still open: reuse of unchanged team computations across capture revisions, and
scouting priorities measured by their effect on comparisons with us. The
initial gap list ranks intrinsic role uncertainty rather than claiming that
league impact.

## Live league capture (3 October 2026)

With `fm-web --direct-live`, the League page has a **Read the league from FM**
button. It runs `tools/fm20_league_capture.py` in its own process, which writes
`data/league-capture.json`, the server's default league file in live mode. The
same tool can be run directly. A capture from an earlier game date shows
**League out of date** with the button, rather than an error. Everything is
read-only, and FM's own code runs only in the sandbox. Nothing runs inside the
game.

- **Clubs.** Each first team carries FM's link to this season's league
  (`team + 0x50`, the same competition object as the league's fixtures). On
  the National League South save, exactly 22 of 127,012 teams carried it,
  identical to the clubs in its 352 played results. The link needs no played
  matches, so it should also hold before the season starts (not yet checked
  on an early-season save). When league results exist, any played club missing
  from the link marks membership incomplete.
- **Squads.** Each club's first-team squad vector, the same one our own squad
  comes from, so every club has the same scope as ours.
- **Attributes.** FM's own visibility builder, exactly as the Scouting
  capture uses it.
- **Positions.** Found today by disassembly: FM decides which of another
  club's positions to show with one function (`FM+0x1fb1910`), called by
  Player Search's position filter, the player object and the scouted-player
  data. It asks the manager's knowledge about the player's positions and
  returns the lowest rating FM shows: 18 (Natural only) when nothing is known,
  16 when partly known, everything when fully known. That is exactly Adam
  Mann's case from September, where two Accomplished positions showed as
  Ineffectual. FM's per-position rating getter returned the raw bytes for all
  72 players checked, so the shown positions are the ratings at or above FM's
  answer. The ratings themselves are never published. See
  `tools/fm20_visible_positions.py`.
- **Our club.** The same read as the Squad page, so the web's check that the
  league's own row matches our squad passes.
- Rival readiness, injuries and contracts are not read. Availability is
  `unknown` and labelled as an assumption, as the contract already allows.

First live run, game date 28 May 2020: 22 clubs, 442 players (33 ours), every
squad and every player's positions read, in 6.6 seconds. Of the 409 rivals,
FM showed 107 Natural-only, 257 partly known and 45 fully known. The full
comparison (all 50 tactics, three scenarios) took 15.5 seconds. 21 clubs were
scored. Maidstone United showed **Cannot verify XI** because its first-team
squad held no goalkeeper on that date. Every rival range overlapped ours
(39.2): rival conservative scores were 14.8–26.5 and ceilings 39.3–56.0, so
nothing is called above or below us.

Recent form is not applied in this comparison, for any club. It exists only
for our own players, so applying it would score us on different inputs from
everyone else. The League page says so, because our score there can differ
from the Tactics page, which does apply it.

**Before slice 1 is accepted**, check in FM, on the same game date:

1. A few rivals' position diagrams against the predicted shown/hidden
   positions in `data/research/visibility/position-knowledge-threshold-*.json`
   (one Natural-only, one partly known, one fully known player).
2. Maidstone United's first-team squad: no goalkeeper, as the capture found?
   Also one other club's first-team list against the capture's count.
3. Once a new season starts, rerun the capture before the first league match,
   to confirm that the league link already names the new season's clubs.

## Product decisions

- Add a **League** page containing every club in the current league, including
  ours, with a drilldown into each squad and its best XI.
- By default, compare each club's best legal XI across the same complete tactic
  catalogue. Offer a selected-tactic view to compare every club in one system,
  including one of our pinned tactics. Our pins must not restrict rival clubs'
  default tactic search.
- Use the existing role weights, tactic emphasis, attribute tapers, position
  familiarity, readiness policy, role constraints, and tactic-balance factor.
  Keep the opponent profile neutral for every club in this comparison.
- Show a **floor–ceiling range** prominently. Show the existing central score
  as a **conservative score**, with the policy explained: ranged attributes use
  their midpoint; unknown attributes use 1 centrally and span 1–20.
  It is not a predicted ability or an expected match result.
- Select players, roles, and tactics independently for floor, central, and
  ceiling scenarios. The visible primary XI is the central selection; show
  where the other scenarios select different players or systems.
- All players remain in the team roster, including those with wholly unknown
  attributes. Missing attributes create uncertainty, not an exclusion. Unknown
  positions or missing roster members are a separate completeness problem.

The first version answers which clubs appear stronger under our model and
which scouting gaps could change that judgement. Forecasting the opponent's
actual lineup, analysing match tendencies, and recommending a tactical response
remain separate Phase 08 work.

## What already exists, and what needs extending

| Existing capability | Reuse or extension |
|---|---|
| `analytics/role_scoring.py` | Already returns exact/ranged/unknown score bands and weighted information gaps; reuse unchanged |
| `analytics/role_matrix.py`, `analytics/position_comparison.py` | Reuse for player and role rankings inside any verified team roster |
| `analytics/xi_selection.py`, `analytics/assignment_solver.py` | Already optimise unique player/slot assignments and permitted role versions; extend the objective to select lower, central, or upper scores |
| `analytics/tactic_ranking.py` | Reuse deterministic ranking and worker infrastructure; support the selected scenario without running unrelated training-target work |
| `analytics/tactic_scouting.py` | Useful precedent for separate floor/central/ceiling projections, but its one-recruit-at-a-time calculation is not whole-team optimisation |
| `persistence/player_knowledge.py`, `persistence/best_known.py` | Reuse dated, save-scoped attribute knowledge and provenance |
| Match captures and `domain/matches.py` | Supply competition/team identity evidence; played results alone do not prove complete current league membership |
| Scouting feed and sandbox visibility queries | Reuse visible attribute acquisition; the Player Search pool and its club-name strings do not prove complete club rosters |
| `reporting.py`, web providers and handlers | Add shared league/team reporting helpers and thin pages; keep scoring out of renderers and browser code |

The current XI optimiser chooses using central scores and then calculates the
band for that selected XI. That is useful for a lineup, but its upper value is
not necessarily the upper value of the team's best possible XI. The full
recommendation reporting path also assumes a coherent owned squad; do not
force an incomplete rival roster through that validation or clone the entire
recommendation bundle for every team.

## 1. Capture league membership and complete rosters

This is the first implementation gate and the main research uncertainty.

1. Resolve the managed club's current league, season, and complete participant
   list using a verified manager-visible source. Include clubs with no played
   matches, so the feature works before the season starts.
2. Resolve each participant's first-team roster, stable club and player IDs,
   and manager-visible eligible positions. Establish the same roster scope as
   our current owned-squad comparison. Reserve/youth players are not silently
   added to rival teams while excluded from ours.
3. Read visible attributes through the existing visibility-aware acquisition
   path. Read publicly visible positions and availability only where their
   semantics have been verified. Do not enable the scouting workspace's raw
   external-position opt-in implicitly for this feature.
4. Bind each read to one save, active manager, and in-game date; reject a
   mixed-date or changed-save capture. Record partial failures per team, while
   preserving successful teams and the previous successful capture.
5. Verify the participant list, representative rosters, positions, and
   exact/ranged/unknown cells against FM. Include an unscouted club and an
   early-season save in that evidence.

Do not derive teams by grouping the recruitment shortlist. Player Search can
exclude players for package, market, or discovery reasons; that would omit
potential starters and misstate a team's strength. League/squad visibility
needs its own verified discovery evidence, even when a player is absent from
Player Search. Do not use the hidden-data diagnostic reader as a fallback.

### Capture and persistence contract

Introduce a versioned `LeagueCapture` with save identity, manager identity,
game date, season, competition ID/name, membership-completeness evidence, and
one team roster observation per participant. Each roster records club ID/name,
scope, completeness, players, field provenance, and capture errors.

Keep dated roster membership separate from player attribute knowledge. A
player's historical club-name field must not put him back into a previous
club's current XI after a transfer. Reuse the player-knowledge history for
attributes; add a migrated league/roster store for membership observations.
Use stable IDs for joins, never club or player names.

Preserve **current exact**, **current range**, **captured unknown**,
**uncaptured**, and **historical** states. For the default current comparison,
uncaptured inputs get broad computational bounds and an explicit capture gap;
old readings are shown as historical evidence rather than exact bounds on
today's ability. A later best-known view can reuse historical readings with a
clear date label, but must not silently narrow the current interval.

## 2. Rank every player in a team

The team drilldown starts with the complete roster and supports:

- overall ordering by the player's best eligible base-role central score;
- position and role filters using existing comparison helpers;
- floor, conservative score, ceiling, best role, visible positions,
  availability, attribute coverage, and knowledge dates;
- sorting by floor, central score, ceiling, or uncertainty;
- a player report showing the observations and largest weighted gaps.

Call the overall column **Best role fit**, not a universal player ability
rating. Base-role rankings remain tactic-free, matching the existing Squad,
Roles, and Scouting design. The XI view separately shows the tactic-adjusted
slot score and its readiness/familiarity effects.

Where the best role changes between scenarios, compute the maxima separately
and label the central role as the displayed choice. A player with unknown
positions stays visible as **Position needed** instead of receiving a made-up
role or disappearing from the roster.

## 3. Optimise and score the best XI with uncertainty

Add a scenario objective (`lower`, `central`, `upper`) to the shared selection
path, with `central` as its backwards-compatible default. Thread it through
the assignment solver, role-version selection, tactic ordering, and worker
jobs. Retain original observations and explanation bands; never relabel an
unknown attribute as an observed exact value to run a scenario.

For a fixed roster, eligibility, readiness context, and tactic set, calculate:

```text
team floor   = max over legal tactics/roles/XIs of the lower-scenario score
team central = max over legal tactics/roles/XIs of the central-scenario score
team ceiling = max over legal tactics/roles/XIs of the upper-scenario score
```

For the selected-tactic comparison, restrict all three searches to that
tactic. Each search uses the current formula:

```text
team score = mean(sqrt(adjusted slot scores))² × tactic-balance multiplier
```

This is a model interval over the recorded attribute bounds, not a statistical
confidence interval. The endpoint argument relies on the scorer and tapers
being monotone in attributes and the eligibility constraints being fixed;
prove those assumptions with focused tests. Do not average player bounds,
sum the eleven highest individual scores, or greedily select each slot's
best player. Preserve unique players and every existing legal-role constraint.

### Readiness, familiarity, and eligibility

Use the existing current-team selection policies in the first version, so
our result matches the existing neutral-opponent Tactics result for the same
capture and tactic set. Known injuries, suspensions, and readiness exclusions
apply equally to every club.

External condition, match fitness, availability, and positional familiarity
may also be unknown. Reuse the existing readiness/familiarity fallback values;
if unknown availability is provisionally treated as available, retain that
assumption separately from the observed field and display it prominently.
These score ranges then cover **attribute uncertainty under stated selection
assumptions**, not every possible matchday availability outcome. Do not call
one club definitely stronger when its comparison depends on those assumptions.

If a roster is incomplete or visible positions cannot establish a legal XI,
show **Roster incomplete** or **Cannot verify XI**, plus the known players and
missing slots. A partial XI is not a scored eleven and does not enter the
league strength ordering. A fully unscouted team with verified positions and
a complete roster can still receive a very wide range and a provisional XI.

Return both the selected central XI's own band and the independently optimised
team band. Show them with distinct labels in the drilldown so a ceiling from
a different lineup is never presented as the displayed XI's score.

## 4. Compare every league team on one screen

Add `/league` and `/league/teams/<club-id>`, with bookmarkable comparison
context. Proposed overview:

| Strength position | Club | Best XI range | Conservative score | Central tactic | Knowledge | Compared with us |
|---|---|---|---|---|---|---|
| 2–7 | Example club | 39–65 | 45 | Vertical 4-4-2 | 4 exact, 3 partial, 4 unknown starters | Overlapping |

The numbers above are illustrative. The page should:

- highlight our club and put all score ranges on one shared 0–100 axis;
- default to central-score ordering with a stable ID tie-breaker, labelled as
  a conservative ordering rather than a certain league ranking;
- offer floor, ceiling, uncertainty, and name sorts, and **Best system** /
  **Same tactic** controls;
- show separately **clearly above us**, **overlapping**, or **clearly below
  us** only when comparable intervals and selection evidence justify it;
- show the capture's in-game date, data age, complete-roster count, scored-club
  count, and which clubs need capture or positional evidence;
- retain every unscored team in a visible section; never hide it or score it
  as zero.

For fully comparable teams, a possible strength-position interval follows
from strict interval separation: best position is one plus the number of
other teams whose floors exceed this team's ceiling; worst position is one
plus the number of other teams whose ceilings strictly exceed its floor.
Exact ties share a competition rank even when another club has an uncertain
score. Touching or overlapping ranges generally leave ordering unresolved.
When any league club cannot
be compared, label positions **among N scored clubs** instead of implying a
complete league ranking. When all comparable scores are exact, the endpoints
collapse to competition ranking (one plus the number of strictly higher scores).
Otherwise the position interval describes unresolved ordering;
alphabetical or ID ordering is presentation only.

The team page shows a pitch XI with roles and slot ranges, alternative
floor/ceiling selections, the full ranked roster, and the evidence behind the
team score. The best model system is a capability assessment, not a prediction
of the formation the opposing manager will play.

## 5. Make the next scouting action useful

Show the club's largest unresolved score contributions, including players
who appear only in its ceiling XI and could replace a known starter. Link
those players to the existing player/scouting report where possible.

Prioritise gaps which could change whether the club is above or below us,
then their weighted effect on the slot score. Explain the specific player,
role, and attributes worth learning. Display capture failures as **Capture
needed**, and genuine unknown attributes as **Scout more**. Do not treat a
wide range as evidence that a team is strong, and do not submit scouting
assignments to FM.

## Delivery sequence and acceptance gates

| Slice | Deliverable | Gate |
|---|---|---|
| 1. Data proof and contract | Verified league/roster source; versioned capture; fixtures for complete, partial, and unknown squads | All participants accounted for; representative rosters and visibility validated against FM |
| 2. Scenario selection | Shared floor/central/ceiling optimisation; team and player reporting models | Existing central output unchanged; endpoint searches exact on small exhaustive cases |
| 3. Team drilldown | Ranked roster, best XI, score evidence, and uncertainty explanations | Works for owned, partly scouted, wholly unscouted, and unscorable teams |
| 4. League overview | All clubs, range chart, comparison modes, uncertainty-aware ordering | Our score agrees with existing scoring; incomplete teams remain visible |
| 5. Refresh and scouting guidance | Incremental capture/recompute, retained results, targeted information gaps | New knowledge updates affected clubs and explains changed XI/range |

This is a **medium–large feature**, with a specialist source-validation gate.
Do the data proof first; its outcome sets the remaining implementation estimate.
Fixture-based selection and UI work can proceed after the contract is settled,
without claiming that live league acquisition is complete.

### Performance and refresh

Evaluate only the necessary team/tactic/scenario work. Do not run bench,
set-piece, recruitment, depth, or trained-position analyses for every league
row. Reuse a bounded worker pool rather than creating nested pools per team.

Persist captures and cache results by save, game date, roster/attribute input
revision, catalogue/scoring versions, scenario, tactic scope, and selection
policies. Refresh in the background, keep the last completed view usable, and
publish a coherent comparison revision so refreshed and old team rows are not
silently mixed. A per-team failure stays visible and retryable. Recompute only
affected teams; a transfer affects both clubs.

Benchmark a realistic full league with mixed visibility, shared eligibility,
and all supported tactics. Record cold and warm timings and settle the page
load/refresh budget before polishing the UI. The sample three-player fixture
cannot validate this workload; see [the performance investigation](analytics-performance.md).

### Required checks

- An exact owned roster produces the same central XI, roles, tactic, and score
  as the current neutral-opponent path. Exact inputs collapse all scenario
  scores to one value when the selection assumptions are also fixed.
- A small exhaustive oracle agrees with each objective; a case where a
  poorly scouted reserve becomes the ceiling starter catches fixed-XI bounds.
- Endpoint tactic/role changes, shared-position players, duplicate-player
  prevention, illegal role combinations, zero-score ties, and partial XIs
  behave correctly.
- True attribute values consistent with the observations give an optimised
  score inside the reported team band. Tightening a bound around such values
  cannot widen that band under unchanged selection constraints.
- Unknown, uncaptured, stale, unknown-position, and unknown-readiness inputs
  retain their labels. No raw external position or hidden attribute leaks.
- Transfers, loans, duplicate names, reserve-team scope, season rollover,
  no-match leagues, save switching, mixed-date refreshes, and per-team capture
  failures cannot corrupt membership or another save's knowledge.
- Interval comparisons handle touching ranges, tied exact scores, all-unknown
  clubs, and unscored clubs without inventing certain rankings.
- Run relevant selection, knowledge, persistence, and web tests during each
  slice; run the full suite before declaring the cross-layer feature complete.

Implementation is complete when the live league page includes every current
participant, every verified roster can be ranked and scored through the shared
model, our own score agrees with the existing app, and missing knowledge is
visible in the ranges and next scouting actions.
