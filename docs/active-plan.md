# Active plan: results-led priorities

**Agreed:** 26 September 2026, replacing the
[application improvement review](archive/plans/app-improvement-review-2026-09-19.md)
as the active backlog.
**Save context:** Hungerford Town (National League South), first season, 2019/20.

## Why the priorities changed

The original plan ordered work by architecture: extract, persist, check
visibility, model, recommend. That sequence is largely done. The owned squad is
read live, 42 tactics are compared, and depth, weaknesses, bench, set pieces,
opponent sliders and a scouting workspace all exist. The
[phase roadmap](phases/README.md) still records those capability gates.

This plan orders the next work by a different test: **what is most likely to
improve results in the save, for the least implementation effort.** At
Hungerford, the biggest gains come from recruitment rather than further tactic
tuning. The manager's actual loop is:

1. find players who would realistically join (FM's Player Search "realistic"
   switch, free agents, non-contract and loan-listed players);
2. see whether any of their attributes are visible;
3. offer a one-week trial to anyone with something visible, since a trial makes
   every attribute visible; and
4. review the trialists in the app against the tactics actually played.

Scouting and trial capacity is the binding constraint, not the size of the
pool. The plan therefore concentrates on four questions: which tactics we
play, where those tactics are weakest, who is worth a trial, and whether a
trialist would improve the XI or its depth. It then adds a player-knowledge
record, so that what we have seen is not lost when FM's visibility fades.

The tactic catalogue has had a week of tuning without any outcome data to test
it against. Further catalogue work is parked until there is a reason beyond
opinion to change it (see item 7).

## Settled decisions

- **Tactics in use:** Vertical 4-4-2 (`vertical_442`) and Wing Play 4-4-2
  (`wing_play_442`), with Positive 4-3-3 DM Wide (`positive_433dm`) as a backup.
- **Wages:** needed eventually, but not now. Almost every signing is on a
  non-contract deal, so the wage budget currently bites less than the
  scouting budget. Item 4 leaves room for wage facts without a schema change.
- **Signing verdicts are manual.** Improving the tactic score is one input
  among several. The manager also weighs depth and a player's overall fit. The
  app shows the evidence; it does not reject players automatically.
- **Nothing here writes to FM.** Item 5 adds the first write from the web app,
  but it writes the manager's own notes to a local database, never to the game.

## The plan

| # | Item | Effort | Depends on |
|---|---|---|---|
| 1 | Pinned tactics | Small | — |
| 2 | Trialist review across pinned tactics, including depth | Small–medium | 1 |
| 3 | Worth-a-trial ranking against the weakest slots | Small–medium | 1, 2 |
| 4 | Record scouting knowledge in our own database | Small–medium | — |
| 5 | Scout from the database, with manual verdicts | Medium | 4 |
| 6 | "Now gettable" and "re-scout due" alerts | Small | 5 |
| — | Dedicated set-piece ratings from an HTML export | No code | — |
| 7 | Match history and review | Medium–large | Built 29 September 2026 |

Items 1–3 affect the next few in-game weeks. Items 4–6 pay off over the season.
Item 4 does not depend on 1–3: if a heavy scouting push starts before they
land, do item 4 first so those observations are recorded.

Every open and parked item has a bounded brief in
[Task briefs](tasks/README.md). Low and medium briefs say what an agent can
implement without inheriting the specialist FM process research or making new
football-model decisions. Senior briefs frame those decisions and that
research, and their output unblocks the others. This plan remains the source
of priority and product scope if a brief and the plan ever drift apart.

### 1. Pinned tactics

**Problem.** Pages default to whichever tactic ranks top across all 42. Depth,
set pieces, bench, substitutions and scouting's tactic selector therefore
describe a shape we may not play. Tactic familiarity also matters, so the tool
should not keep nudging towards a switch. The `SquadDepthReport` docstring
already asks for "the tactic shortlist that reflects real intent"; nothing
supplies it yet.

**Scope.**

- A `--my-tactics vertical_442,wing_play_442,positive_433dm` option on both
  `fm-web` and `fm-analytics`. The first key is the primary tactic. Unknown keys
  are a start-up error.
- The pins live in `RecommendationPolicy` and are resolved in `reporting.py`,
  for example as a `bundle.primary` evaluation beside the existing
  `recommendation.selected`. Handlers read the resolved value and never
  re-derive it, per the one-computation rule in `CLAUDE.md`.
- `recommendation.selected` keeps its meaning (the top-ranked tactic). The
  Tactics page still ranks all 42 and shows where each pinned tactic sits.
- With pins set: set pieces, the depth page, bench/substitutions and weaknesses
  default to the primary tactic; squad depth's persistent/occasional split is
  computed over the pinned set; scouting's tactic selector defaults to the
  primary tactic. Each page's existing `?tactic=` override still works.
- Without pins, behaviour is unchanged.

**Done when:** every page defaults to the primary pinned tactic when pins are
set, the existing suite passes unchanged without pins, and CLI and web print the
same primary tactic, XI and depth for the same capture.

**Status: built (26 September 2026).** `--my-tactics` on `fm-analytics` and
`fm-web`; `RecommendationPolicy.pinned_tactics`; `RecommendationBundle.primary`,
`.pinned` and `.planning_depth`; `SquadDepthReport.restricted_to`. Tests are in
`tests/test_pinned_tactics.py`, including checks that pins change no score and
that the bench and weakness report equal a direct computation for the pinned
tactic. Two deliberate differences from the scope above:

- **Depth is restricted, not recomputed.** The full 42-tactic depth report is
  still built, because the tactic drill-down needs every per-tactic report.
  `planning_depth` regroups it for the pinned set, with no extra analytics.
  `/depth?scope=all` shows every tactic.
- **The scouting page does not default to the primary tactic yet.** It works
  without a squad bundle and defaults to the generic ranking, so defaulting
  would make every visit run the tactic ranking over the whole candidate pool
  before that cost has been measured. Pinned tactics are listed first, starred,
  in the tactic selectors instead. Item 2 measures the cost and settles the
  default.

Every pinned tactic also appears in a **Your tactics** table on `/tactics`
(rank, score and gap to the top-ranked tactic), and the CLI marks pinned rows
and says when the primary is not the highest-fit tactic.

### 2. Trialist review across pinned tactics, including depth

**Problem.** The scouting page answers "how much does this player improve this
tactic?" for one tactic at a time. We play two. A player who doesn't start
shows a gain of zero, which hides his value as cover, and depth matters at our
level.

**Scope.**

- A **My tactics** mode on `/scouting` that runs
  `analytics.tactic_scouting.rank_candidates_for_tactic` for each pinned tactic.
  For each tactic it shows the player's best job, gain
  (floor/estimate/ceiling), whether he starts, and whom he replaces. The list
  sorts by primary-tactic gain by default and can sort on any tactic's column.
- **Depth effect** for a player who doesn't start in a tactic: the slot he
  would be first cover for, and his fit against the current first cover there.
  This comes from the same weakness/cover data behind the depth page, computed
  in `analytics/` (e.g. alongside `tactic_scouting`), not in the handler.
- A **My tactics** summary at the top of each `/scouting/player/<id>` report,
  above the existing single-tactic selector.
- Measure the page against the real capture (currently about 730 players with
  visible attributes), not the three-player fixture. Precompute each tactic's
  remainder allocations once per page build. Multiple tactics mean several
  times the work, so check that the page stays usable.

**Done when:** one page shows a trialist's starting gain and cover value in
every pinned tactic, and the numbers match the single-tactic view for the same
tactic.

**Status: cover value built for one tactic at a time (28 September 2026),
nothing on `/scouting` yet.** `rank_candidates_for_tactic` now returns
`cover_assessment` (`could_be_first_cover`, the one slot and margin a
non-starter clears the current first cover by, or nothing rather than a zero)
alongside the existing single-tactic gain -- see
[the cover-value contract](tasks/senior-cover-value-contract.md). The **My
tactics** mode across several pinned tactics at once, the page-load budget for
it, and the summary on the player report are still open -- see
[the scouting cost budget](tasks/senior-scouting-cost-budget.md) and
[the service brief](tasks/medium-multi-tactic-scouting-service.md).

### 3. Worth-a-trial ranking against the weakest slots

**Problem.** Tactic gain is computed from what is visible, counting an unknown
attribute at the minimum. That is the right view for a signing decision. It is
the wrong view for deciding whom to trial, where the question is "could he beat
my starter if the unknowns are reasonable?" The Scouted tab already has a
median scenario (`RoleScore.median`) for that question, but not in tactic
terms.

**Scope.**

- A **Weakest slots** header on `/scouting` for the pinned tactics: the few
  starter slots with the lowest fit, and slots whose cover drops off sharply,
  taken from the existing weakness reports. Each links to the list pre-filtered
  to that position and role. This absorbs the old "your needs" item (review
  2.1).
- A median scenario beside floor/estimate/ceiling in the tactic scouting
  result, plus two plain flags: **could start** (ceiling beats the current
  starter in his best slot in any pinned tactic) and **could be first cover**.
- A **Trial priority** sort: realistic and gettable candidates (the existing
  `search_match` and market filters) ordered by median-scenario gain in the
  weakest slots, with the unknown count shown.
- Players with no visible attributes stay under the existing **Scout first**
  label and are grouped by the weakest slot they could fill. They are not given
  an invented score.
- The page states that the median scenario is for choosing whom to look at,
  never for choosing whom to sign. This follows the principle already set out
  in [scouting-workspace.md](scouting-workspace.md).

**Done when:** from the scouting page, one click goes from "Wing Play 4-4-2 is
weakest at ML" to a list of realistic ML targets ordered by trial priority.

**Status: the scoring and the weak-slot list are built (28 September 2026),
nothing on `/scouting` yet.** `TacticScoutingAssessment` now carries
`player_median` (a candidate's own median role score in his best slot/role,
not a whole-XI reprojection), `could_start` (his ceiling alone would win a
starting slot) and `trial_priority` (his median, only when his best slot is
itself flagged weak, and withheld entirely for a Scout First player with no
visible attributes at all, so nobody is ranked on an invented number). Separately,
`reporting.weakest_slots(bundle)` reads the pinned tactics' own weakness
reports into an ordered, capped list of weak starter/cover slots, ready to
drive both the weakest-slots header and the trial-priority filter -- see
[the trial-scenario semantics](tasks/senior-trial-scenario-semantics.md) and
[the weakest-slot service](tasks/medium-weakest-slot-service.md) for the
decisions taken. The **Weakest slots** header, the **Trial priority** sort
itself, and the Scout First grouping are still open -- see
[the trial-priority list](tasks/medium-trial-priority-list.md) and
[weakest-slot navigation](tasks/low-weakest-slot-navigation.md).

### 4. Record scouting knowledge in our own database

**Problem.** FM's visibility fades. Players drop out of scout reports, and the
capture currently keeps only one "last known" snapshot per player, carried
forward inside a JSON file that each refresh rewrites. In the current capture
617 players are already flagged as dropped from scout reports. Several things
are lost on each refresh: attribute history, the dates when a player matched
the realistic switch, and players scouted for other reasons (such as scouting
an opponent). None of it can be recovered later.

**Why this is within the rules.** It stores only what FM showed the manager,
exact, range or unknown, with the date it was seen. A human manager could keep
the same notebook. An old observation is shown as out of date, never as
current, using the stale state already defined in [mvp.md](mvp.md).

**Scope.**

- A new `persistence/player_knowledge.py` module with its **own** SQLite file,
  `data/player-knowledge.sqlite3`, separate from the squad capture store.
- **An upgrade path from day one:** a schema version, an ordered list of
  migration steps, a backup before migrating, and a test for each step. The
  squad capture has no upgrade path, and a format change left the only real
  capture unreadable. That was survivable because the squad can be read from
  the game again. It would not be survivable here, because this database's
  whole value is history the game will not show again.
- Rows are keyed by save identity (managed club and manager) plus FM player ID,
  so a new save never mixes with an old one.
- Store observations only when something changed, and track first- and
  last-seen dates for each player. The stored fields are visible attributes
  (unknowns included, because "we knew nothing on this date" is itself useful),
  knowledge level, age, positions, club, contract type, contract end,
  has-contract, transfer status, and whether he matched the realistic search.
  Facts are key/value pairs, so a wage can be added later without a schema
  change.
- Ingest from the manager-visible capture JSON only, never from the lower-level
  research tools. Run it after every successful scouting refresh
  (`SquadWebServer.refresh_scouting`) and through a command that seeds the
  database from existing captures, including `lastKnownAttributes` at their
  recorded `attributesObservedAt` dates.
- The web pages do not change yet.

**Done when:** re-ingesting the same capture adds nothing, a player who drops
out of a later capture keeps his earlier observations, and the upgrade path is
tested from the first version.

**Status: built (26 September 2026).** `persistence/player_knowledge.py` is the
store and `knowledge_ingest.py` reads a scouting capture into it. Tests are in
`tests/test_player_knowledge.py` and `tests/test_knowledge_ingest.py`, with
mutation checks that change-only recording and rollback are really enforced.

```bash
uv run fm-knowledge status
uv run fm-knowledge ingest data/scouting-capture-enriched.json   # oldest game date first
```

`fm-web` records the current capture at start-up and after every successful
**Refresh scouting data**, and shows a warning on the Scouting page if recording
fails (a failed recording never fails the refresh). `--knowledge-db PATH` and
`--no-record-knowledge` control it. A refresh made by running
`tools/fm20_scouting_feed.py` directly is picked up the next time `fm-web`
starts or you run `fm-knowledge ingest`, so if you refresh several times that
way between two runs, only the last state of each game day is kept.

How it differs from, or adds to, the scope above:

- **Change-only, per player and per attribute.** A profile row is written when
  any profile field differs from the latest one on or before that date, and an
  attribute row when that attribute's state (known, range or unknown) differs.
  An identical capture is skipped outright by content hash, ignoring the
  capture time. Volume: the first real ingest of 4,678 players wrote about
  9,000 profile and 27,500 attribute rows (a 4.7 MB file). Transfer value
  moves for most players every month, so expect a few thousand profile rows per
  game week.
- **Sightings, so an unchanged value still ages from the last look (27
  September 2026).** Each capture also records the day it saw each player, and
  the day it read his current attribute sheet (which lists every attribute). A
  last-known sheet lists only the attributes for his position, so it is sighted
  attribute by attribute. That is up to about 9,000 small rows per new game
  date, and a same-day refresh adds none.
- **Unknown is stored, so fading is visible.** The feed reports every
  attribute of a scouted player, including unknown ones (about 40% of rows
  in the real capture), and a known value that later becomes unknown is a new
  row beside the old one.
- **Old snapshots are seeded at their real dates.** A dropped player's
  `lastKnownAttributes` are recorded at their own observation date with source
  `last_known`; a carried-forward current reading keeps its older date too.
- **Save identity and a rewind guard.** A save is keyed by the managed club
  (`club:<id>`), or by `--save NAME`, because FM player IDs are identical in
  every save. A capture dated earlier than what the save already holds is
  refused unless you pass `--allow-rewind`, so loading an old save cannot
  silently mix two timelines.
- **Own migrations from v1.** An ordered `MIGRATIONS` list, a consistent
  backup (`.bak-v<N>`) before any upgrade, atomic per-step application, and a
  refusal to open a newer or unrelated file. The upgrade path is tested with an
  injected second step.
- **Reset to a single v1 on 27 September 2026.** Verdicts and sightings were
  briefly v2 and v3. The product owner chose to start the history again rather
  than keep them as upgrades, so they were folded into v1 and the old file was
  archived in `data/` (its history ran from 24 June to 19 October 2019). A
  file from before the reset is refused as "newer than this program", not
  misread. Move it aside and the next recording starts a fresh one.

Not done, deliberately: nothing reads this database yet (item 5), and wages
are not captured because the feed does not carry them. The `facts` column is
the place for them when it does.

### 5. Scout from the database, with manual verdicts

**Scope.**

- **Best-known profile:** for each attribute, the most recent observation that
  is not unknown, labelled with its date. The profile shows its oldest date
  used, and anything past a configurable age is labelled out of date. The
  current feed still wins wherever it has a value. This replaces the one-deep
  `lastKnownAttributes` carry-forward.
- **Wider candidate pool:** the current feed plus every player in the database.
  Players we have seen but who are not currently realistic (for example,
  opponents we scouted) appear, labelled *not currently realistic*, and are
  excluded by the existing filters as usual.
- **Manual verdicts:** Target, Watch or Reject, with a note and a date, stored
  in a separate manager-data table in the same database. Rejected players are
  hidden from lists by default, with a toggle to show them. The verdict and its
  edit form sit on the player report. This is a local POST, like the existing
  scouting refresh, and it never touches FM.
- No automatic verdicts. Item 2's columns show the evidence and the manager
  decides.

**Status of the wider candidate pool: built (28 September 2026).** The Scouting
pages read the feed merged with the save's best-known profiles
(`fm_analytics.candidate_pool`); remembered values fill what FM no longer shows
and are marked historical with their dates, and players known only from history
are labelled *not currently realistic* and shown under **Everyone ever scouted**.
See [the task brief](tasks/medium-database-candidate-pool.md) for the decisions
taken.

**Status of the best-known profile: read API built (27 September 2026).** `PlayerKnowledgeStore.best_known_profile` (one player)
and `best_known_profiles` (a whole save, in a fixed number of queries) assemble
a player as of an in-game date, per
[the task brief](tasks/medium-best-known-player-profiles.md). Each selected
reading carries two dates. `observed_on` is when the store first recorded that
state. `last_seen_on` is the last day a capture still showed it. The profile's
age is `oldest_seen_on`, the stalest reading's last-seen date. Observation rows
are change-only, so without sightings a Pace 14 seen every week
would have aged from the week it first appeared, and "re-scout due" would have
fired on players seen days ago. Staleness stays the caller's threshold.
Reading all 5,350 players of the real save (179,000 attribute rows) takes
1.5 to 2 s, mostly building the objects, so the candidate pool should build it
once per refresh rather than once per page.

### 6. "Now gettable" and "re-scout due" alerts

A block on `/scouting`, computed from the database after each refresh:

- **Known and now gettable:** a player with earlier visible attributes who, at
  the latest refresh, newly matches the realistic switch or has become a free
  agent, listed, or near the end of his contract, and is not marked Reject.
- **Re-scout due:** a player marked Watch whose best-known profile is older
  than a configurable age (six months by default), or who still has unknowns
  in attributes that matter for a weakest-slot role.

### Quick win: dedicated set-piece ratings (no code)

Set pieces matter a great deal at this level. The live reader has no verified
offsets for free-kick taking, penalty taking or long throws, so live runs use
proxy profiles and withhold long throws. Exporting one FM custom squad view
with the `Fre`, `Pen` and `L Th` columns and passing it with `--fm-html`
switches set pieces to the dedicated ratings and adds a long-throw order (see
[set-piece-optimizer.md](set-piece-optimizer.md)). Repeat it when the squad
changes.

### 7. Match history and review

**Un-parked and widened on 29 September 2026** from a manual results log to
match analysis, at the product owner's request: it is the evidence the
catalogue, the opponent rules and calibration have been waiting for, and a
match's stats are lost if they are not recorded while FM still holds them.

**Status: built (29 September 2026).** The Matches page and `fm-matches` read
every result and the league's results live from FM, read-only, with full
stats for every match from the match archive FM keeps on disk; there is
nothing to do in FM. They show
results, shots, clear-cut chances and possession by opposition strength (the
league table at kickoff by default), tactic against opposition, where goals
come from, and which roles create and shoot. See
[the match analysis plan](match-analysis-plan.md) for what was built, its
limits and what is still open. That document replaces the
[results-log brief](tasks/medium-results-log.md).

## Parked

- **Wages and affordability:** later, as a fact in item 4's database.
- **Performance** (review items 1.1–1.4): fast enough on a 17-player squad. The
  measured cost model stays in
  [analytics-performance.md](analytics-performance.md).
- **Web cache** (review 1.5 and additional finding 1): parked. If caching is
  reworked, the cache key must include the pinned tactics and the opponent
  profile, not just time.
- **Squad capture upgrade path** (review 3.1): the live read is the working
  source. Item 4 applies the lesson to the database where it matters.
- **Two recruitment paths** (review 2.2/3.3): proposed resolution is to treat
  the web `ScoutingCandidate` path as canonical and retire the CLI
  HTML/`VisibleExportPlayer` shortlist rather than merge the two. Not scheduled;
  items 2–6 build only on the web path so the split does not grow.
- **Background scouting refresh** (review 3.2), **dashboard as an answer page**
  (2.5) and **named depth evidence** (2.3): useful polish, but none changes a
  decision in the save. Item 2 covers the depth question that matters for
  recruitment.
- **Tactical model:** nonlinear curves, instruction suitability,
  whole-tactic familiarity and calibration all stay in the
  [tactical-system roadmap](tactical-system-roadmap.md). Calibration waits for
  enough of item 7's match history.
- **Opposition analysis from data, ML, automation:** Phases 08–11, unchanged.

## What happened to the previous review's items

| Review item | Now |
|---|---|
| 1.1–1.4 Performance | Parked |
| 1.5 Web cache | Parked; cache-key requirement noted above |
| 2.1 Squad needs in scouting | Item 3 (Weakest slots) |
| 2.2 / 3.3 Recruitment unification | Parked, with proposed resolution |
| 2.3 Named depth | Recruitment side in item 2; the rest parked |
| 2.4 Player view | Done: `/squad/player/<id>` |
| 2.5 Dashboard | Parked |
| 3.1 Capture upgrade path | Parked; lesson applied in item 4 |
| 3.2 Background refresh | Parked |
| 3.4 Dead imports | Not re-checked; trivial cleanup when next touching `web/server.py` |
