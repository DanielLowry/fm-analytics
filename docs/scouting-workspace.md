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
shows every player the manager has a scouting-knowledge record for, with
real, read-only-calculated visible attributes -- see "Scouted-player
attributes" below. `/scouting?view=all` (the default, for URL and test
compatibility with the position/role browsing this page already did) is the
existing Player Search pool, unchanged. Both tabs read the same
`ScoutingCandidate` list, so a player who is both scouted and in the pool
never has two different answers depending which tab you're looking at --
that is `ScoutingCandidate.is_scouted()` and `.scouting_knowledge`, not a
second computation.

A player whose knowledge record has since disappeared (retired, sold
abroad, a database-only entry now -- FM's own reason for this is not
observable from outside) stays in the Scouted tab with his last-known
knowledge level and attributes, flagged rather than silently dropped:
*"This player used to be in the scouted pool but can't be found in the
scout reports anymore."* See `dropped_from_scout_reports_ids` in
`fm20_scouting_feed.capture_pool`.

## Ranking: who to scout next (19 September 2026)

With no role chosen, the Scouted tab ranks every player, and choosing a
position ranks everyone for that position. Each player is scored in whichever
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

**Known gap: players known only through reputation.** A manager can know
something about a well-known player never explicitly scouted; that
knowledge path is not yet implemented, so such a player still reads as
entirely unknown here even though FM may show something. Not a regression
-- this project's `positions`/attribute fields have always failed towards
"unknown" rather than a guess.

## Frida hydration still exists, now for a different purpose

`--hydrate-player-id` (up to 64 players) still calls FM's own builder
directly and still needs the same explicit approval as the pool rebuild.
It is no longer the only way to get real attributes -- the read-only path
above covers every scouted player automatically -- so its remaining use is
narrower: getting FM's *exact* answer to spot-check the read-only
calculation above, or covering a player who is discoverable but not yet
scouted (where the read-only path has nothing to compute from). A player
hydrated this way outranks the read-only calculation for that player in
the merge order (prior capture, then this run's calculation, then this
run's hydration, each layer overriding the last).

Its own native-call timing was fixed alongside the pool-rebuild agent on
18 September 2026 (`tools/fm20_frida_attribute_sweep.py`,
`tools/fm20_frida_property.py`): the call now prefers FM's message pump
over a `QueryPerformanceCounter` tick, for the same reason and the same
evidence recorded in `docs/property-discovery-playbook.md`.

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
manager's Player Search pool, removes the managed club's own contracted
players, and leaves all remaining filtering to this page.

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
| `scouting_refresh_started` | Refresh began; records `allow_rebuild`, hydrate count, base feed date |
| `scouting_pool_read` | The cold read; records the pool size found and the live game date |
| `scouting_refresh_refused_pool_not_built` | Pool was empty and `allow_rebuild` was false; nothing was written to FM |
| `scouting_pool_rebuild_started` / `_completed` / `_failed` | The one step that runs FM's own code; `_completed`/`_failed` record which thread hook was used (`hook`) and whether it was the message-pump resting point or the timing-call fallback (`resting_point`) |
| `scouting_refresh_date_drift` | Base feed's date differs from today's live read; informational only |
| `scouting_hydration_started` / `_completed` | `--hydrate-player-id` requests, with counts |
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

To hydrate a small set of known candidates with all of FM's manager-visible
attribute values and footedness, repeat `--hydrate-player-id` (up to 64 players). This is
bounded deliberately while the external-player route is validated:

```bash
uv run --extra research python tools/fm20_scouting_feed.py \
  --hydrate-player-id 9214 \
  --output data/scouting-capture-hydrated.json
```

Use `--base-feed` to retain previously captured visible fields. To update that
same known capture, pair it with `--replace` and name the exact output file.

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

### Using it

Set the filter you want in FM's Player Search, leave the results on screen, then
refresh the scouting data. The capture records `matchedActiveSearch` per player
and `source.activeSearchMatchCount`; the page shows an **FM search** column and
an **FM search match** filter. If no search is showing, or two are live at once,
the field is absent rather than guessed, and the column reads "—".

The sweep adds roughly a minute to a refresh, because finding the session means
scanning writable memory for its vtable.
