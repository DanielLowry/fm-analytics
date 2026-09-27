# Scouting workspace

`/scouting` is the external-player workspace. It intentionally consumes a
separate manager-visible candidate feed, rather than treating the owned squad
or FM's raw player structures as a recruitment universe.

## What it does

- lets the manager select a tactic and ranks targets by the change they make to
  that tactic's best XI;
- filters candidates by position and role, then scores the selected role;
- shows a score **floor / estimate / ceiling** whenever the manager sees a
  range rather than an exact attribute;
- marks an eligible player with no known role attributes as **Scout first**;
- lists the highest-impact role attributes to scout next for partial profiles;
- keeps an exactly-known profile distinct from a range and an unknown value;
- filters safely supplied age, club, nationality, footedness, transfer status,
  availability, and any additional captured Player Search facts.

“Scout first” is an information recommendation, not a prediction that an
unknown player is good. Unknown attributes receive a conservative central score
while retaining their possible ceiling, so they neither leapfrog known players
on an invented rating nor disappear from the shortlist.

## Tactic impact

Choosing a tactic changes the ranking from a generic position/role comparison
to a squad-relative question: **how much would this player improve this
tactic's score?** For each candidate the optimiser adds him to the current
squad, reselects the complete XI and its permitted role combination, and shows:

- the candidate's best job in the tactic;
- his tactic-specific player-fit floor, estimate, and ceiling;
- the projected tactic score and the gain over the current XI;
- whether he starts at the central estimate, and whom he replaces.

The same analysis is available on every individual scouting report. Its tactic
selector answers the question for that player directly; the main Scouting page
keeps the corresponding ranked comparison across the whole candidate pool.

The candidate is assumed available, at 100% condition and 100% match fitness.
Owned players keep their current readiness. A player who does not beat the
current XI is retained as depth and shows a gain of zero; adding a target can
therefore never make the projection worse. Attribute ranges remain ranges, so a
target can have no estimated gain while still showing meaningful ceiling
upside. Position and role filters narrow the tactic jobs the candidate is
allowed to fill, while all the existing market and identity filters continue
to narrow the candidate pool.

The implementation precomputes the best owned-player allocation for the other
ten slots in each legal role version, then reuses those allocations across the
candidate pool. This gives the same central result as adding each player to the
squad and running the full optimiser again, without repeating all owned-squad
work for every target.

## Two tabs: Scouted players, and All players

Added 18 September 2026. `/scouting?view=scouted` (the nav's first link)
shows every player the manager holds a scout report on -- the same set as
FM's own Scouted list -- with real, read-only visible attributes; see
"Scouted-player attributes" below. Until 27 September 2026 it showed every
player with any knowledge level at all, which is a different and larger set
(see "Checked against FM's own lists" below). A player known without a report
-- a trialist, a past opponent -- is listed under All players with his
knowledge level marked "(no report)". `/scouting?view=all` (the default, for URL and test
compatibility with the position/role browsing this page already did) is the
existing Player Search pool, unchanged. Both tabs read the same
`ScoutingCandidate` list, so a player who is both scouted and in the pool
never has two different answers depending which tab you're looking at --
that is `ScoutingCandidate.is_scouted()` and `.scouting_knowledge`, not a
second computation.

A player whose knowledge record has since disappeared (retired, sold
abroad, a database-only entry now -- FM's own reason for this is not
observable from outside) is kept in the feed with his last-known
knowledge level, flagged rather than silently dropped:
*"This player used to be in the scouted pool but can't be found in the
scout reports anymore."* See `dropped_from_scout_reports_ids` in
`fm20_scouting_feed.capture_pool`. Attributes FM no longer shows are not used
as current facts or scoring inputs. They move to the separately dated
`lastKnownAttributes` snapshot, shown as **Past knowledge** in the list and as
an explicitly historical section on the player report.

**Hidden by default since 27 September 2026.** The kept players pile up: the
product owner's file held 604 of them, and the next refresh would have made
it 697 against the 530 FM's own Scouted list showed. The product owner's
principle is that the app shows what FM shows, then adds filtering, sorting
and analytics on top, so both tabs now match the game by default and an
**Everyone ever scouted** tick box (`everScouted=1`,
`ScoutingFilters.include_former_scouted`) brings the rest back. A player who
has dropped off the scouting list but is still in FM's Player Search stays
under All players by default, as he would in game; that needs the schema-4
`inPlayerSearch` field, so it only works after a refresh that read the pool.
A feed older than schema 4 cannot tell which dropped players had a report
rather than just a knowledge level, so the first refresh from one puts all of
them in "everyone ever scouted".

## Ranking: who to scout next (19 September 2026)

With no role chosen, both tabs rank every player, and choosing a position
ranks everyone for that position. (Until 26 September 2026 the All players tab
showed a plain, unsortable list until a position was picked; see "One table,
one sort" below.) Each player is scored in whichever
role suits him best (`analytics.rank_for_position`), and the table shows three
scores on a 0-100 scale, all built only from what the manager can see:

- **Min** -- every unknown attribute counts as 1 and every range at its low end;
- **Max** -- every unknown counts as 20 and every range at its top;
- **Median** -- every range at its midpoint and every unknown mid-scale.

Min and Max are the existing floor and ceiling of `score_role`. Median is new
(`RoleScore.median`) and is deliberately separate from `score.central`, which
still counts an unknown as the scale minimum so that a barely-scouted player can
never outrank a well-known one; the squad optimiser relies on that. Median asks
a different question -- "what could this player be worth?" -- so an unscouted
player scores 50 and sits above a known poor one. That is intended for choosing
whom to scout, and it is why the table also shows how many of the role's
attributes are known, ranged or unknown, and a bar for the spread.

Every column sorts, in either direction, on the server (`sort` and `dir`
query parameters), so with a long list the top of the list is the true top by
that column rather than the top of whatever was on screen: Min, Median, Max,
Range (ceiling above median), Age, Scouted %, attributes known, name and best
role. A player missing the sorted value (no age, never scouted) always goes
last.

Before a position is chosen a player's role comes from which attributes he
carries: the goalkeeping attributes exist only for goalkeepers and the outfield
ones only for everyone else, so that picks the family without needing a
position. A position label is applied after, only to narrow further.

Each row has an **Attributes** dropdown listing every attribute in FM's own
order, with `-` for anything the manager cannot see.

## One table, one sort (26 September 2026)

Every Scouting view is now the same sortable table, whichever filters produced
it. Which columns exist depends on what is chosen, and the **Sort by** list and
the column headings offer exactly those (`analytics.SORTS_BY_MODE`):

| Chosen | Table | Extra sorts |
|---|---|---|
| a tactic | XI-gain table | XI gain (est/floor/ceiling), projected score, player fit |
| else a role | that role's targets | **Scouting priority** (the old Proven fit → Scout first → Scout to decide order), median, min, ceiling, upside |
| else | best-role ranking | best role, min/median/max, upside, familiarity and in-position score (raw positions only) |

Age, value, scouted %, attributes known and name sort in all three. A `sort`
that belongs to another table falls back to this table's default
(`sort_for_mode`) rather than doing nothing. The role table used to have no
sorting at all, and the All tab with nothing chosen was a bare list.

The visibility, minimum-floor and minimum-ceiling filters now also apply to the
best-role ranking (`filter_position_rankings`); they used to be ignored until a
role was chosen. All three tables share one definition of them
(`matches_information_filters`). A role may be chosen without a position.

**Cost.** Scoring a player against every role is the slow part (about 8 ms per
player measured on 500 players before the shortcut below) and it does
not depend on sort or on who else is listed. `rank_for_position` takes an
optional `cache` (one per server, `SquadWebServer.scouting_rank_cache`) keyed on
the player, position and options, and reused only for the very same candidate
object; `scouting_json_provider` therefore hands back the same candidates until
the capture file changes. Players with no visible attributes are scored once per
role, not once each. The pool is scored on a background thread at startup and
after every refresh, and re-sorting or filtering it is then instant instead of
re-scoring on each keystroke. Measured on that save with one request at a time:
first cold ranking of the whole pool ~7 s (was ~11 s for just the 1,364 scouted
players, on every request); any re-sort or filter afterwards ~0 s.

The row limit is 100 with a **Show more** button (`limit`, capped at 1,000
because each row carries an attribute sheet). Rows show positions, value and
contract for every table, and an "Interested (transfer)"/"Interested (loan)"
tag on the player where FM's own interest rules say so (see "Interest has no
stored answer" below; this replaced an earlier "FM search match" tag).

## Position familiarity (19 September 2026)

The 15 raw position ratings are already read for every scouted player (they
pick his visibility family), so the scouting feed now also stores them, apart
from the verified positions, as `rawPositionFamiliarity`. Shown only when the
existing **Use raw external positions (accepted visibility gap)** box is ticked:
the product owner confirmed that this one opt-in covers the ratings as well, so
there is no second checkbox. This goes beyond the original acceptance, which
covered the eligibility *list* only, and the ratings can show more than FM's own
screens do for a player the manager does not own -- which is why it stays off by
default and is named in the notice above the results.

With it on, the ranking gains two columns. **Familiarity** is his rating for the
position (or, with none chosen, the best rating among the positions the role is
played at) and the multiplier it implies. **In position today** is Min / Median /
Max multiplied by that multiplier, using the *same* `FamiliarityPolicy` the
Tactics page uses, so it is comparable with a squad player's selection score,
while Min / Median / Max stay comparable with his plain role score. The role is
then chosen on that adjusted median. A raw rating of 0 is treated as the worst
rating (the 0.5 floor), and a player with no ratings is left unadjusted rather
than assumed unfamiliar.

## Scouted-player attributes: read-only, no Frida, no Player Search

Added 18 September 2026, in `tools/fm20_scouted_attributes.py`. For every
player on the manager's own scouting-knowledge list -- read as a plain
`{RowID, level}` vector, itself entirely independent of Player Search --
this reads that player's true attribute bytes, position, and age (the same
proven offsets `tools/fm20_owned_visible_source.py` already uses for the
owned squad) purely as *inputs* to FM's own visibility formula
(`fm_analytics.bridge.fm20_visibility_algorithm`, independently recovered
from the executable). The true value is never itself returned; only the
formula's output -- exact, ranged, or unknown -- is. Verified against three
real attributes for a live, heavily-scouted player (Pace, Determination,
Passing all matched exactly, once a scout report was accounted for).

Because this needs neither Frida nor an open Player Search, a plain,
"safe" `Refresh scouting data` now works the instant a save loads, before
Player Search has ever been opened this session -- `capture_pool` reads
scouted attributes first, independently, and only then looks for the wider
pool. If the wider pool isn't available yet, the capture still succeeds
with scouted players alone; `source.poolAvailable: false` marks that the
"All players" tab has nothing to show this time, not that the refresh
failed.

**Scout reports (fixed 19 September 2026).** The first version calculated
every attribute as if no scout report existed, and its ranges came out wider
than FM's -- and, for some attributes, "unknown" where FM showed a range.
Comparing against FM's own exported player profiles found three separate
causes, all now fixed:

1. **The bracket test was inverted.** The width of a range depends on a
   quality figure and on the knowledge level. The code used `or` where FM's
   executable (RVA `0x15a4c86`-`0x15a4cd8`, read from the file on disk, no
   attach) uses `and`, so it picked the widest bracket far too often.
2. **The knowledge level lags.** The percentage in the knowledge list is one
   step behind the level in the player's report record, and FM uses the
   report's. The record sits in a vector 0x2a0 below the manager's Person
   (`read_report_records`) and is reachable without any scan. The lag is the
   "older report, lower percentage" suspicion, and it was right.
3. **Quality comes from the scout.** The figure is the sum of two rating
   bytes on the staff member named in the report record
   (`read_scout_quality_sum`), not anything about the report itself. Players
   share it when they share a scout.

With all three, every attribute FM exported for four scouted players is
reproduced exactly (47 of 47 ranges) and every attribute FM hides stays
hidden. If a record or scout cannot be read the code falls back to the
explicit level and no report, which can only widen a range.

**Still to confirm.** The scout-rating offset was located by fitting three
scouts to the brackets four real players imply. Check it against the staff
profiles in FM (the three scouts in the test save read 11+11, 7+9 and 8+9).

**Positions and club for scouted players (19 September 2026).** A scouted
player who is not in the Player Search pool still has a Person in FM's memory,
so his positions (behind the same accepted-gap checkbox as any raw position)
and his club and transfer status are read from it directly. Without this the
Scouted tab worked but its position filter and Club column were empty until
Player Search had been opened. A player with no current contract simply has no
club, which is real, not a read failure.

**Players known through reputation or other baseline knowledge (superseded
27 September 2026).** A manager can know something about a player who has
never had an explicit scout report -- FM's own baseline-knowledge path. Until
27 September the only way to see it was a red, explicitly-risky button that
ran FM's own visibility builder inside the live game. The sandbox (below)
answers the same question for every candidate, every refresh, without that
risk, so the button is gone outright rather than kept as a fallback.

## Every player's attributes and interest, through the sandbox

**Shipped 27 September 2026**, in `tools/fm20_sandbox_queries.py` on top of
`tools/fm20_sandbox.py`. This replaced the last two things this project ever
ran inside the live game (`--hydrate-player-id` and `--hydrate-active-search`,
both Frida calls into FM's own process) the evening after those exact calls
were implicated in a second round of save corruption. See "Saves broke again
on 26 September 2026" below for what happened, and
`docs/frida-discoverability.md` for the interest-filter research this also
replaced.

**What it reads, for every external and scouted candidate, every refresh, no
Player Search screen required:**

- **Visible attributes** -- FM's own visibility builder (RVA `0x15a4a90`),
  called the way FM's own screens call it (see 03.2, "Both caller inputs
  resolved" -- a zeroed lookup cache plus the player's actual scout as the
  explicit `report` argument). Matched the read-only calculation for all 741
  of a real save's scouted players exactly (23,739 of 23,739 attributes) once
  called this way; a live CLI run against a real, freshly-restarted FM process
  captured all 714 currently-scouted players' attributes via the sandbox in
  8.1 seconds total, with zero read failures that run.
- **Transfer and loan interest** -- FM's own `PERSON_INTERESTED_FILTER_RULE`
  and `PERSON_INTERESTED_LOAN_FILTER_RULE` evaluators, called directly
  (bypassing the composite's own-club/national-pool rules; the caller already
  excludes everyone contracted to the manager's own club) at
  FM's standard "any interest" level, regardless of what is currently ticked
  in FM's UI. See "Interest has no stored answer" below.

Nothing here can write to FM: the sandbox is a Unicorn x86-64 CPU whose memory
is copied in, one page at a time and read-only, from `/proc/<pid>/mem`; any
write FM's own code makes (the builder updates lookup caches, the interest
evaluators do their own bookkeeping) lands only in that copy and is discarded
with the sandbox. A scouted player's own read-only calculation
(`tools.fm20_scouted_attributes`) is still computed first and used as the
floor; the sandbox's answer overrides it for whichever players it could read
this run, the same "later layer wins" merge the old hydration path used.
Footedness is **not** part of this: nothing currently re-captures it live (see
"Known gaps" below).

**Own-club players off the first team: fixed later the same day.** This
section first shipped excluding only `first_team_squad`, flagged as a risk
for scouted reserve or youth players at the manager's own club. It was
worse than that: the Player Search pool itself holds them, and 10 were
published as candidates, every one "interested in transfer". See "Checked
against FM's own lists" below.

### Saves broke again on 26 September 2026

On the evening of 26 September the All players tab's main refresh button
started sending `--hydrate-active-search`, so every refresh ran FM's
visibility builder for the whole open search (about 2,400 builder calls for a
51-player search). The shared thread selector introduced the same evening also
let a call run inside `QueryPerformanceCounter` again when no message pump was
seen. Saves broke again that evening: they saved without an error and then
would not load.

What the native-call log shows, and does not:

- No Frida call ran into FM between the 17 September gating and 26 September
  19:47. The pump hook had never actually been exercised, so the healthy saves
  in between were because refreshes stopped calling FM, not because of it.
- The pool rebuild never ran on 26 September. The visible-attribute batches
  ran at 20:35 and 20:41 (51 players each time), and a footedness batch at
  20:35 timed out after 20 seconds, after which FM had a new PID.
- The log did not record which thread or hook those batches used, so thread
  choice versus the builder's own writes (03.2: it updates recent-lookup
  fields in the manager's knowledge context and may store a report pointer)
  cannot be told apart.

First fixed 27 September morning by making the main refresh button read-only
again and putting the risky attribute call behind a separate, explicit red
button; fixed properly later the same day by removing that native call
entirely in favour of the sandbox above, once it proved both correct and safe.

### The sandbox trial and what it found (27 September 2026)

`tools/fm20_sandbox.py` runs FM's own code in a Unicorn x86-64 emulator whose
memory starts empty and is copied in, one page at a time, from
`/proc/<pid>/mem`, opened read-only. Its trial surfaced several things worth
recording so they are not silently lost or re-broken later:

- **Correct.** All 741 scouted players, 41 attributes each, matched the
  read-only calculation (23,739 of 23,739), once the builder was called the way
  FM's screens call it (see 03.2, "Both caller inputs resolved"). The 43
  unscouted players from 26 September matched, apart from changes explained by
  new scout reports (14 players) and ageing (5 players aged 34-37).
- **Fast.** About 0.1 ms per attribute; one player 4 ms; the whole 3,648-player
  Player Search pool (attributes and interest together) in 13-35 s
  single-threaded depending on live conditions, sharded across up to 8
  parallel sandboxes (`capture_players`) for real wall-clock benefit on a
  multi-core machine.
- **A thread-cloning crash, found and avoided.** The sandbox can either clone
  FM's real main-thread block or build a synthetic one from fm.exe's own TLS
  template. The clone seemed the more faithful choice for anything FM's
  screens compute, but calling the C runtime's `_set_FMA3_enable` (needed
  before the interest evaluators' floating-point maths, since Unicorn has no
  AVX/FMA) under a cloned real thread's snapshot crashed the whole Python
  process outright -- SIGSEGV, not a catchable Unicorn or FM error -- for
  reasons not fully understood. The synthetic thread has been checked
  correct for both attributes and interest and is now the default
  (`FmSandbox(..., as_main_thread=False)`); treat `True` as unverified for any
  new use until it is checked the same way.
- **A vtable slot correction.** The interest rules' real evaluator sits at
  vtable slot `0xd8`, not `0x88` -- confirmed by reading both slots' actual
  targets off the live filter's rule objects: slot `0x88` resolved to the same
  address for both interest rules (a shared, non-scoring method), while slot
  `0xd8` gave each its own address matching the already-disassembled
  evaluators. This is a different rule subclass from the always-on rules
  (`PERSON_INCLUDE_OWN_FILTER_RULE` etc.), whose own evaluator genuinely does
  sit behind a slot-`0x20` thunk to slot `0x88` (`docs/frida-discoverability.md`).
- **A read reliability finding, not fully root-caused.** Reading many
  players' interest in one sandbox occasionally produced a burst of failures
  -- always the identical faulting address across many different players in
  one burst, consistent with a shared CRT/lock structure FM's own background
  threads (about 9% CPU even on a menu screen) were concurrently mutating,
  not anything this module writes -- and the burst size varied wildly run to
  run (0 to over 1,000 of 3,648) with no correlation to worker count.
  Retrying the *same* sandbox's read never recovered it; a fresh sandbox, at a
  later real moment, did. `capture_players` therefore retries only the
  players still missing, in fresh sandboxes, up to
  `fm20_sandbox_queries.MAX_CAPTURE_PASSES` (3) times, and leaves whatever is
  still missing to the caller's existing fallback (a scouted player's
  read-only calculation, or nothing new this refresh) rather than guessing.

### Interest has no stored answer

FM does not store "interested in transfer/loan" anywhere -- its Player Search
filter computes it fresh from the manager's own reputation every time it
runs a search (`docs/frida-discoverability.md`, "Running the filter in the
sandbox"). Checked against FM's own displayed lists on the test save, the
sandbox's exact reproduction of FM's rule matched 24 of 24 individually
labelled players, but the two full-pool checks (1,518 interested-in-transfer,
91 interested-in-loan) each came up short by 5-6% against FM's own count, for
reasons never fully explained (ruled out: rounding, which OS thread ran the
call, which manager/team object was used, and the currently-ticked search
criteria). On 27 September the product owner decided that missing an
interested player is worse than wrongly flagging one, so every interest read
takes FM's own live-computed cut-off (which moves with the manager's
reputation; nothing here is a fixed number) and relaxes it by
`DEFAULT_INTEREST_MARGIN` (0.85). A margin sweep on the test save found any
value from about 0.94 to 0.95 reproduced both of FM's lists exactly, and 0.85
was chosen with headroom rather than tuned to the edge, at the cost of 12-18
extra players per list who scored just under FM's own line. Each player's
result distinguishes FM's own exact verdict (`"yes"`) from one that only
clears the margin (`"maybe"`), shown in the Scouting page as separate tags
rather than losing that distinction. This also retired the "FM search match"
column and filter (`matchedActiveSearch`), which existed only as a proxy for
this same question and needed a search left open in FM to answer it; the
Scouting page's `transferInterest`/`loanInterest` filters replace it, and the
7-14 second scan for FM's on-screen result list is no longer part of a
refresh at all.

### Checked against FM's own lists (27 September 2026, late)

The first full-pool refresh through the finished pipeline was checked
against the product owner's own FM screens on the same save and date. Every
number was off, for three separate reasons, none of them the sandbox:

| List | FM shows | Feed before | Feed after |
| --- | --- | --- | --- |
| Player Search, no filters | 3,371 | 3,383 | 3,373 |
| ...interested in transfer | 1,354 | 1,360 | 1,350 `yes` + 15 `maybe` |
| Scouted, no filters | 532 | 714 | 530 |

- **Own club.** FM's search leaves out everyone contracted to the managed
  club; the feed removed only the first team, so 10 reserve, youth and
  non-contract players at the manager's own club were candidates.
  `fm20_scouting_identity.read_own_club_members` now checks every pool
  record's and scouted player's contract against the managed club. The
  Player Search gap is now 2 players in the unsafe direction, against the
  1 recorded as accepted in `docs/frida-discoverability.md` ("Known
  tolerance"); not investigated further.
- **"Scouted" meant any knowledge, not a report.** The knowledge list
  (726 players) and the report list (530) are different vectors in FM's
  memory. 462 players are on both; 264 are known without a report (trials,
  past opponents), and 68 have a report with no knowledge entry -- 52 of
  those were missing from the app entirely. FM's Scouted list is the
  reports. The feed now reads both lists, marks each known player
  `scoutReport: true/false` (schema 4), and the Scouted tab means a report.
  **Decision:** players known without a report stay in the feed under All
  players, because the attributes FM shows for them are just as real
  (product owner, 27 September: it "shouldn't matter why" a player's
  attributes are known) and the standing preference is to include rather
  than miss players. They are labelled rather than hidden.
- **Unreadable players vanished.** 14 players (10 with reports) have
  position ratings the read-only calculation rejects ("position rating must
  be between 1 and 20"), and the scouted reader dropped them. FM's own code
  in the sandbox reads them fine, so they are now kept, with attributes from
  the sandbox only.

Everything interest-related was already right: within Player Search the
exact verdict is 4 short of FM's count and the 15 `maybe`s cover the gap, as
the margin intends. The much larger all-players interest count (about 1,880)
is correct too: it includes some 680 known or reported players who are
outside FM's Player Search pool, most of them non-league or unattached.

Still unexplained: FM's Scouted list shows 532 and the report vector holds
530, all of which pass the type checks. No own-club players are among them.

### Player Search without opening Player Search (27 September 2026)

FM keeps its Player Search list in memory only, empty after every launch
until the manager opens Player Search. Until now that left two choices: ask
the product owner to open it before refreshing, or run FM's own list builder
inside the live game (`--allow-rebuild`, the in-game kind of call behind the
broken saves). A refresh now runs that same builder (`fm.exe+0x52778C0`) in
the sandbox instead -- `tools/fm20_sandbox_pool.py` -- and reads the list out
of the sandbox's copy. Each player it lists is checked against the live game
before use.

On the test save, with FM freshly restarted and its own list empty, the
builder ran in 8.3 seconds (about 250 MB of FM's memory copied) and produced
3,411 players, the same set on a second run. A whole refresh then took 38
seconds and matched the earlier refresh from FM's own list on every count:
3,411 listed, 38 own-club players removed, 1,350 `yes` plus 15 `maybe`
interested in transfer, 530 with a scout report. The product owner then
opened Player Search (FM showed 3,371, i.e. those 3,411 minus the 38 own-club
players and the 2-player tolerance in `docs/frida-discoverability.md`), and
eight sandbox builds in a row each matched FM's own freshly built list player
for player.

One build, started seconds after Player Search was opened, stopped inside
Wine's Linux-side `ntdll.so` (a write to address 0x70) instead; a slower,
traced rerun a minute later succeeded, as did all eight after it. That is the
same intermittent pattern as the attribute capture's read failures above, so
the build retries in a fresh sandbox up to `MAX_BUILD_ATTEMPTS` (3) times
before the refresh falls back to FM's own list.

**Cause found later that evening, and fixed.** An hour on, the build failed
four times out of four at the same point. The emulated stack showed why: FM's
heap had no room left and asked Windows for more (`RtlAllocateHeap` ->
`NtAllocateVirtualMemory`), a request that crossed into Wine's Linux side,
where the sandbox's synthetic thread has no state. Whether it happens depends
only on how full FM's heap is at the moment it is copied. The sandbox now
answers `NtAllocateVirtualMemory`, `NtFreeVirtualMemory` and
`NtProtectVirtualMemory` itself (`FmSandbox._install_memory_services`), handing
out zero-filled memory that exists only in the sandbox; every other
operating-system request still stops the call. Checked live by forcing a 32 MB
allocation through FM's own heap in the sandbox, which needed three such
requests and succeeded; unit-tested in `tests/test_fm20_sandbox_memory.py`.
The retries stay, for anything else intermittent.

### How long a refresh takes (27 September 2026)

Measured on the test save (3,411 in Player Search, 794 known or scouted,
4,551 players in the feed including everyone ever scouted), from the app's
refresh button:

| Step | Time |
| --- | --- |
| Start-up, read the previous feed, check FM | ~1 s |
| Build the Player Search list in the sandbox | ~8.5 s |
| Names, clubs, contracts, positions (read-only) | ~5 s |
| Attributes and interest for every player (sandbox, 8 in parallel) | ~12 s |
| Checks and writing the feed | ~2 s |
| **Refresh, as the button runs it** | **~31 s** |
| Save the player-knowledge history (web app, after the refresh) | ~3.5 s |
| Score every player for the first page | <1 s |

Before the evening's fixes the same refresh took about 52 seconds: Python
spent 11.5 seconds freeing the nine sandboxes after the feed was already
written (the command-line entry point now ends the process directly instead),
and the first history save after the schema-4 change took 11 seconds.

**Decision:** the sandbox list is used on every refresh, even when FM has
built its own, because FM's is only as recent as the last time Player Search
was opened. FM's own list is the fallback if the sandbox build fails
(`scouting_sandbox_pool_failed` in the log), and the feed says which was used
(`source.poolBuiltInSandbox`). `--allow-rebuild` is now only reachable if both
fail and nothing is scouted either; with the sandbox builder working it is a
candidate for deletion rather than a route anyone should need.

### Known gaps after this change

- **Footedness has no live source any more.** Its only capture path was the
  same Frida hydration this change removed, and porting it to the sandbox was
  not done in this pass (it would follow the same generic property-getter
  chain the attribute builder uses, just for a different key). Existing
  captures keep whatever footedness they already had (`--base-feed` carries it
  forward, dated to when it was actually observed), but nothing refreshes it.
- **Player-knowledge history does not track interest yet.** `matched_active_search`
  stays in the `player_knowledge` SQLite schema (a real migration, not
  attempted here) but is always written `None` now; recording
  `transfer_interest`/`loan_interest` there properly is a follow-up.
- FM's Scouted list is 2 players longer than the report vector (see
  "Checked against FM's own lists").
- Player-knowledge history does not record `scoutReport`, so it cannot tell
  a reported player from a merely known one; same migration as interest.

## Candidate-feed contract

Capture a manager-rooted Player Search pool through Frida, then start the web
app with that JSON feed:

```bash
uv run --extra research python tools/fm20_scouting_feed.py \
  --output data/scouting-capture.json
```

```bash
fm-web --direct-live --scouting-json data/scouting-capture.json
```

When either `data/scouting-capture.json` or the richer
`data/scouting-capture-hydrated.json` exists in this project, `fm-web` loads it
automatically. `--scouting-json` still overrides that choice.

The feed does not reproduce the filters currently open in FM. It takes the
manager's Player Search pool, adds every player the manager knows or holds a
report on, removes everyone contracted to the managed club (not just the
first team), and leaves all remaining filtering to this page. Schema 4 adds
`scoutReport` to every player with a `scoutingKnowledge` level; a feed without
it is older and the page falls back to treating any knowledge as scouted.

### How the pool is obtained, and why it is gated

FM keeps this pool in process memory and builds it as you play, so the normal
path reads it with no native call at all -- the same read-only footing as every
other page. A capture taken this way records
`source.transport: read-only-process-memory`.

The pool is empty until FM builds it, which means it is empty after every FM
launch. Running FM's own builder to fill it executes FM code inside the live
game, and that is the step suspected of producing saves that write successfully
and then fail to load. So the capture tool will not do it unless asked:

- Without `--allow-rebuild`, an empty pool exits **3**, changes nothing, and
  reports that Player Search has not been opened yet.
- With `--allow-rebuild`, FM's builder runs and the capture records
  `source.poolRebuiltByCapture: true`.

On `/scouting`, the Refresh button never carries that consent. If the pool is
empty the page returns 409 and offers two routes: open Player Search in FM once
(recommended, no native call), or approve the rebuild with its warning. The
resulting page states which route produced the data, so the risky one is never
silent. Opening Player Search is needed once per FM session, not once per
refresh.

### The game date always advances; older facts do not get thrown away

A refresh reuses whatever `--base-feed` already has for a player (attributes,
footedness) rather than re-hydrating them every time. Earlier this required
the base feed's `gameDate` to match today's live read exactly, so playing on
for even one in-game day made every refresh fail with "prior scouting feed is
from a different game date" until the file was deleted by hand. That
enforcement is gone (fixed 18 September 2026): the capture's own `gameDate`
always advances to today's live read, and each carried-forward fact keeps the
date it was actually observed in `attributesObservedAt` /
`footednessObservedAt` alongside it, rather than being silently relabelled as
current. A file written before those fields existed falls back to its own
single `gameDate` for everything it carries. A drift between the base feed's
date and today's is logged (see below), never enforced.

This is deliberately the simple answer for now, not the final one. Tracking
per-attribute observation dates (and match inputs/outputs) properly belongs in
a database once one exists for this project; these JSON files are the
ad-hoc stand-in until then.

### Diagnosing a refresh without reading the live game by hand

Every refresh -- from the CLI directly, or via the web page's Refresh button,
which runs the same CLI as a subprocess -- logs structured events to
`data/logs/fm20-native-calls.jsonl` (the same on-by-default log every native
call in this project uses; see its own docstring). All events from one
refresh share one `call_number`, so `grep` for that number pulls the whole
attempt in order:

| Event | Meaning |
| --- | --- |
| `scouting_refresh_started` | Refresh began; records `allow_rebuild`, the interest margin, base feed date |
| `scouting_pool_read` | The cold read; records the pool size found and the live game date |
| `scouting_refresh_refused_pool_not_built` | Pool was empty and `allow_rebuild` was false; nothing was written to FM |
| `scouting_pool_rebuild_started` / `_completed` / `_failed` | FM's own pool builder ran (the one remaining live-code step); `_completed` records the thread, how it was selected, and the hook used (`hook`, `resting_point`) |
| `scouting_refresh_date_drift` | Base feed's date differs from today's live read; informational only |
| `scouting_sandbox_capture_completed` | The sandbox read attributes and interest for every reachable candidate this run; records how many were requested versus captured and the duration |
| `scouting_sandbox_capture_failed` | The sandbox could not be set up at all this run (an unrecognised search/filter identity); the refresh still completes, with no sandboxed attributes or interest this time |
| `scouting_refresh_completed` | Success; records `rebuilt`, player count, total duration |
| `scouting_refresh_failed` | Any exception, anywhere in the refresh, with its type, message, and duration so far |

`scouting_refresh_failed` wraps the whole refresh, so every failure path logs
something even if a future change adds a new one -- it does not depend on
remembering to add a `log_event` call at each new raise site.

The first automatic feed has identity coverage only. Its candidates are shown
as **Scout first** and have no position match until external position and
attribute visibility have been proven. This is intentional: it is useful for
building the manager's true discovery queue, without pretending to know more
than FM has safely supplied.

### Accepted raw external-position gap

The product owner has accepted a documented short-term exception for
non-owned position data. Every scouting capture records the derived labels:

```bash
uv run --extra research python tools/fm20_scouting_feed.py \
  --output data/scouting-capture.json
```

This derives position labels from raw non-owned familiarity data and stores
them as `rawPositions`, separate from manager-visible `positions`. It does not
store individual raw familiarity ratings. On `/scouting`, tick **Use raw
external positions (accepted visibility gap)** to display and use those labels
for role and position filtering. The page warns that the data can reveal
secondary positions FM has not shown the manager. The checkbox does nothing
until the feed has been recaptured with the command above.

Every external and scouted candidate's visible attributes and transfer/loan
interest are captured automatically through the sandbox (see "Every player's
attributes and interest, through the sandbox" above) -- there is no longer a
separate hydration step or player limit to opt into. `--interest-margin`
(default `0.85`) controls how far below FM's own live interest cut-off a
player still counts as "maybe" interested; `1.0` uses FM's own cut-off
exactly, with no relaxation.

Use `--base-feed` to retain previously captured visible fields (footedness, in
particular, which the sandbox does not capture -- see "Known gaps" above). To
update that same known capture, pair it with `--replace` and name the exact
output file.

The Scouting page can also start with a separately captured, manager-visible
JSON feed:

```bash
fm-web --direct-live --scouting-json data/scouting-capture.json
```

The document is either a player array or an object with a `players` array.
Each player must have an ID, name, positions, and an optional `attributes`
object using the normal visibility contract:

```json
{
  "players": [
    {
      "id": "12345",
      "name": "Example Striker",
      "positions": ["ST"],
      "age": 22,
      "club": "Example FC",
      "nationality": "England",
      "footedness": "Right",
      "transferStatus": "Listed",
      "availability": "available",
      "attributes": {
        "finishing": {"visibility": "range", "minimum": 11, "maximum": 15},
        "pace": {"visibility": "unknown"}
      },
      "facts": {
        "contract": "Full-time",
        "division": "Vanarama National League"
      }
    }
  ]
}
```

`facts` is the extension point for the wider FM Player Search filter set. Each
proven, manager-visible field is displayed as a filter automatically when it
appears in a capture. This avoids pretending a field is known before its
extractor is verified, while allowing the page to gain the full in-game filter
set without a UI redesign.

## Visibility boundary

The feed must be derived from a verified discoverability capture. Manager-
visible values are the default. `rawPositions` is the sole current exception:
it is permitted only through the explicit, documented accepted-gap path above,
and stays opt-in in the page. Footedness is displayed only when its external-
player visibility route is verified.

The page is ready for the Frida Player Search result-ID collector described in
[Frida and player discoverability](frida-discoverability.md). That collector
will become the candidate-feed producer; it must first prove exact agreement
with FM's visible Player Search results.

## Contract / listing filter (not "would he join us")

The filter bar's "Contract / listing" narrows the list to players who are realistically gettable: **free agent** (a contract read that succeeded and found none), **transfer listed**, or **contract running out** within N months (default 6, measured from the capture's game date). "Gettable" is any of the three. Players whose contract could not be read are never treated as gettable. The Contract column shows the same facts plus the expiry date.

Not covered: whether a player *wants* to join (a bigger club's player may have no interest in us). That is not captured yet, so judge it yourself for now. Contract facts appear after the next scouting refresh.

## Transfer value, and estimating "would he join us"

The capture reads each player's transfer value (`person - 0x98`, pounds) — the
same figure FM prints in Player Search's Value column, so it is manager-visible,
not a hidden rating. Verified 19 September 2026 against ten exported players,
allowing for FM's display rounding (14,435 shows as £14.5K).

FM's "interested in transfer" filter is **not** a stored flag. Reading
`PERSON_INTERESTED_FILTER_RULE`'s evaluator (slot 27, `fm.exe+0x1fb27d0`) shows
it computed per player on each search: a routine scores the player against his
club, and the result is compared with a threshold derived from the managing
club. A wide read-only sweep over 17 labelled players (person record, contract,
his club, scout report; 1-, 2- and 4-byte fields) found nothing that separates
interested from not.

Value is **not** a usable proxy, despite first appearances. On a sample of 17
named players the split looked perfect (interested under £3,589, not-interested
over £5,088), but that sample was biased towards players FM names in an export.
Across the whole 4,111-player pool, "value <= £3,589" marks 3,011 players where
FM's own filter marks 1,929, and 1,028 players valued at £0 are *not*
interested, which value alone can never separate. The **Max value** filter is
kept because value is real, manager-visible data worth filtering on -- not as an
interest estimate.

The exact route works and is built: `tools/fm20_search_results.py` reads the
result list FM itself produces for the search currently on screen (see that
module for the signature it matches on). Verified against a live
"interested in transfer" filter: FM reported 1,929 of 4,090, the reader found
exactly 1,929, and 16 of 17 independently labelled players fell on the expected
side. Because the reader cannot see *which* criteria produced the list, anything
built on it must describe the result as "matched the search open in FM" and let
the manager say what that search was.

### Using it (superseded 27 September 2026)

This whole route -- set the filter in FM's Player Search, leave it on screen,
read back FM's own result list (`matchedActiveSearch`, an **FM search match**
filter) -- was a workaround for not being able to compute interest ourselves,
and needed a search left open in FM to answer even that one question. The
sandbox now calls FM's own interest rules directly for every candidate, every
refresh, with no FM screen involved; see "Interest has no stored answer"
above for the real route and the margin decision, and "Running the filter in
the sandbox" in `docs/frida-discoverability.md` for how the rules themselves
were found and confirmed. `matchedActiveSearch`/`activeSearchMatchCount` and
the FM-search-match filter are removed from the feed and the page.
`tools/fm20_search_results.py` (the result-list reader this section
describes) is left in the tree as a reference, unused by the current pipeline.
