# Match analysis plan

**Status: built 29 September 2026.** This un-parked
[active-plan item 7](active-plan.md#7-match-history-and-review) and replaced
the [results-log brief](archive/tasks/medium-results-log.md). The first half of this
document records what was built and how it differs from the plan. The rest is
the plan and the reconnaissance behind it, kept as the record of why.

## As built (29 September 2026)

### Using it

- **The Matches page** (`fm-web`, then **Matches**). **Read matches from FM**
  reads the running game read-only and records what it sees in
  `data/match-history.sqlite3`: every first-team result this season, every
  result of the league (for the table at each kickoff), and full stats for
  every match, taken from the match archive FM keeps on disk. There is
  nothing to do in FM. `fm-web` also records `data/match-capture.json` when
  it starts.
- **The command line:**
  - `uv run fm-matches capture` reads the game and records it, in one step;
  - `review [--group table|relative|rating] [--competitions league|competitive|all]`
    prints the page's figures;
  - `list`, `show KEY`, `status`, `ingest FILE`;
  - `note KEY --tactic KEY --rating N --text ...` records your own notes; and
  - `role-code CODE ROLE_KEY` confirms which role an FM role code is.
- **Read whenever you like.** Every read is checked to add up (each side's
  goals match the score, and its players' shots and shots on target match
  the team's) before anything is kept.

### What it shows

Every figure comes from one computation, `reporting.build_match_review`, which
both the page and `fm-matches review` use.

- **Results against different opposition,** in three groupings:
  - the opponent's league position on the morning of the match, in thirds
    (the default);
  - whether the opponent was above or below us at that point; or
  - your own pre-match rating, when you gave one.

  "Early season" (fewer than 3 games played) and "Not in our league" are
  groups of their own. Each group shows the results, points per game and
  goals per match. For matches with full stats it also shows shots, shots on
  target, clear-cut chances and possession, ours against theirs. A group of
  fewer than 3 matches is greyed out as too few to read.
- **Tactic × opposition.** A match's tactic is the one in your note. If there
  is no note, it is the catalogue tactic whose roles exactly match the
  line-up's role codes, provided only one tactic does. Both full-stats
  matches so far are recognised as Vertical 4-4-2.
- **Home and away.**
- **Where goals come from:** goals by 15-minute period, which roles scored
  and set up our goals, and which opposition roles scored against us.
- **Who creates and shoots:** for each role, appearances, minutes, shots
  (total and per 90), share of the team's shots, goals, assists, goals plus
  assists per 90, clear-cut chances, key passes and chances created (with
  their per-90 rates), dribbles and average rating.
- **A page for each match:** FM's stats panel, the timeline, both line-ups
  with role and stats, and a form for your notes (tactic used, pre-match
  rating, free text).
- **On the Tactics page:** a "Your match record" box for the pinned tactics.
  It is evidence only and changes no score.

### Where it lives

| Layer | Files |
|---|---|
| Reading FM | `tools/fm20_match_layout.py` (byte layouts, tested), `tools/fm20_match_probe.py` (`capture`, plus the research commands) |
| Domain | `domain/matches.py` (`MatchCapture`, `MatchRecord`, `MatchDetail`, …) |
| Storage | `persistence/match_history.py`, with the upgrade runner shared with player knowledge in `persistence/migrations.py` |
| Analysis | `analytics/match_strength.py` (league table at kickoff, strength groups), `analytics/match_roles.py` (role codes, tactic inference, role summaries), `analytics/match_analysis.py` (the review) |
| Shared computation | `reporting.build_match_review`, `reporting.build_match_report` |
| Command line | `match_ingest.py` (`fm-matches`) |
| Web | `web/match_pages.py`, `web/match_render.py`, `web/match_state.py` |
| Tests | `test_match_models`, `test_match_history`, `test_match_analysis`, `test_match_ingest`, `test_web_matches`, `test_fm20_match_layout` |

### Differences from the plan below

- **No form for entering stats.** The live reader supplies them. The form
  keeps only what FM cannot give: the tactic used, the pre-match rating and a
  note.
- **Opposition strength defaults to the league table at kickoff**, rebuilt
  from the league's own results; all 198 National League South results were
  in memory. The pre-match rating is optional, because for matches already
  played it would be given with hindsight.
- **No HTML import.**
- **Roles come from FM's role code** for the position played. Eight codes
  were confirmed by the product owner on 29 September for Vertical 4-4-2's
  roles. On 30 September `0x80000000` was corrected from Deep-Lying Forward
  (the catalogue's default for that slot, not what was played) to Pressing
  Forward (Support), and tactic inference now accepts a slot's listed
  alternative roles. A new code is shown as an unconfirmed role, with a form to confirm
  it once; it is never guessed. On 3 October `0x80000` was confirmed as a
  second code for the left-sided Advanced Forward (Attack).
- **Positions come from FM's record of where each player played** (from 3
  October 2026): the starting position, which of a central pair he started
  in, and the position played, substitutes included. Captures made before
  then have no positions.
- **A match is identified by its date and both club IDs** (a club plays at
  most once a day) rather than by a generated ID.
- **No snapshot of the pre-match recommendation** (Phase 07.4). It is
  deferred: matches are captured after they are played, so it needs its own
  "before the match" step.

### Known limitations

- A rating is withheld for anyone on the pitch under 13 minutes. FM showed
  "–" after 4 minutes and a rating after 13, and its exact cut-off lies in
  between, so the app may hide a rating FM shows but never shows one FM
  hides.
- Penalties and own goals are read (from each result's incidents, below), but
  whether any other goal came from open play or a set piece, and the shot
  zone, are not: the goal descriptor bytes are not decoded.
- `+0x76` in the player record is **not captured**. It matched Jarra's one
  key header, but gave Hargreaves 1 where FM showed 0, so what it counts is
  unknown. Where visibility is uncertain, the value is treated as
  unavailable.
- Sendings-off are read from each result's incidents; yellow cards have not
  been located.
- A role code does not tell duties apart: Central Midfielder (Support) and
  (Defend) both carry `0x20` (28 March 2020, confirmed by the manager). Codes
  name only the role ("Central Midfielder"; a role with one duty keeps it,
  "Advanced Forward (Attack)"). A tactic is matched by role family, and a duty
  is only settled by the slot a player filled (`analytics/appearance_context.py`).
  Since 3 October every per-player role the review, the match page, `fm-matches
  show` and the export show is that settled role (`appearance_roles`), and the
  roles table, goals by role, diagnostics and controlled tests group by it, not
  by code: one code covers every duty, and one role can have two codes.
  Research on 3 October found explicit 64-bit role/duty words in archived
  tactic arrays. The bounded decoder is working, but team/time/player
  attribution and a conflicting historical observation still need validation;
  it does not yet replace this inference. See
  [historical match duty extraction](match-duty-extraction.md).
- One role can have more than one code, and why is not known: the left
  striker's Advanced Forward (Attack) changed from `0x800` to `0x80000` on 28
  December 2019 with nothing else in the record changing, after two late
  substitutes into that position had already shown `0x80000`.
- The position played has no left/right for a central pair: FM leaves that
  byte empty in the managed club's matches (it is set in some matches between
  other clubs). Only the starting position says which of a pair a player was.
- The layout was checked on two matches in one FM session. It has not yet
  been re-checked after an FM restart.

## The questions it has to answer

1. How do our matches play out against sides of different strength: shots,
   shots on target, clear-cut chances, possession, and where goals come from?
2. Which of our tactics holds up against which strength of opponent?
3. Which roles create and take our chances, and does that change against
   stronger sides?
4. What happened the last time we played this opponent?

Answering them with evidence also unblocks work that is waiting on match
data: judging Vertical against Wing Play (item 7), checking the declared
opponent rules
([upgrade plan §2j](tactical-model-upgrade-plan.md)), and calibration
([tactical-system roadmap item 10](tactical-system-roadmap.md)).

## What exists today

| Piece | State | What it gives match analysis |
|---|---|---|
| `OpponentProfile` (`analytics/opponent.py`) | Built. Set per request through `opp_*` query parameters or `--opponent-*` flags. **Never stored.** | `quality` (-2..+2, relative to us) is the app's only measure of opponent strength, and it already drives tactic choice. `FORMATION_DEFINITIONS` provides the keys for the formation an opponent played. |
| Pinned tactics, `bundle.primary` | Built | Prefill: the tactic and XI the app recommended. |
| Catalogue tactic, slot and role keys | Built | The keys for the role question. A lineup stored as slot → role → player can be grouped by role. |
| Player-knowledge store | Built | The storage pattern to copy: its own SQLite file, migrations from v1 with a backup first, the `club:<id>` save key, append-only rows, and a local POST from the web. |
| `imports/fm_html.py` | Built | Parses FM's *Print screen → Web page* tables and binds rows by player name. It could be a cheap source of match stats. |
| Sandbox emulator (`tools/fm20_sandbox.py`) | Trial, used for scouting | The safe way to read fixtures and match stats live without touching the save. |
| Results-log brief | Parked | Score, tactic, XI and sliders only. No shots, no per-player stats, and nothing beyond W/D/L per tactic. |
| Phases [07](phases/07-match-database/README.md), [08](phases/08-opposition-analysis/README.md) and [09](phases/09-tactical-recommendations/README.md) | Outline | The rules this plan must keep: pre-match and post-match facts stay separate, a recommendation is not the same as what was played, no invented xG, and no causal claims. |

Nothing reads fixtures, results or match statistics. There is no bridge
resource, domain type or research recipe for them, and the research catalogue
has no match entries. The largest gap is that opponent strength exists only as
a value in the URL. Even with a notebook, "how do we do against sides I rated
stronger" cannot be answered afterwards, because the rating was never kept.

## Principles that keep it consistent with the rest of the app

1. **One record, several sources.** A `MatchRecord` domain type is filled by
   manual entry, by an FM HTML export and, later, by the live reader. Each
   section of the record says where it came from. Analytics does not care
   which source filled it.
2. **One computation.** `reporting.build_match_review` is the only place match
   figures are aggregated. Both the CLI and the web page render its result, as
   `CLAUDE.md` requires.
3. **History is protected like player knowledge.** Nothing can recover the
   pre-match rating or the recommended XI later, and FM may prune old match
   detail (step 0 checks this). The store therefore gets its own migrations
   from v1, is append-only, and refuses files it does not understand.
4. **Pre-match facts stay pre-match.** The opponent rating and the
   recommendation snapshot record what was believed before kickoff. The form
   asks for the rating "as you judged them before the game", and the rating is
   never adjusted afterwards to fit the result.
5. **One set of keys.** Catalogue tactic, slot and role keys; opponent
   formation keys; the `quality` axis labels as strength bands; and the save
   key `club:<id>`.
6. **Counts before verdicts.** Every aggregate shows how many matches (and, per
   player, how many minutes) it covers. The app never says "tactic X is
   better". A season is about 50 matches, spread across strength bands and two
   or three tactics, so most cells will be small (see the sample-size rule in
   step 3).
7. **Manager-visible only.** Everything here appears on FM's match screens. A
   live reader must still return only what those screens show.

## The match record

This field list is provisional. Step 0 confirms which fields FM20 shows and at
what level of detail.

**Identity and context.** A generated match ID, the save key, the in-game
date, the competition, the venue (home, away or neutral), and the opponent
(their name, plus the FM club ID when a source provides it). Optionally, both
clubs' league positions at kickoff.

**Before the match.** The opponent rating on the `quality` scale, or *not
rated*. Not rated is stored as null and never as 0, because 0 means "similar
to us". The whole `OpponentProfile` if one was set. A recommendation snapshot:
catalogue version, the fit, readiness and familiarity policy versions, and the
recommended primary tactic and XI.

**What we played.** The tactic key (or "other" with a label), the starting XI
as slot → role key → player, the substitutions (minute, player off, player on,
and the slot and role taken), the formation the opponent played (a formation
key), and a note.

**Team stats, for both sides.** The score, and possibly the half-time score.
Possession, shots, shots on target, clear-cut chances, and half chances or
long shots if FM20 shows them. Corners, fouls, offsides, cards, pass
completion, crosses, tackles, headers won, and average rating. These are
stored as key/value pairs per side, like the knowledge store's `facts`, so a
stat added later needs no migration.

**Goals, for both sides.** The minute, the team, the scorer and the assister
(a player ID for our players, a name and position for theirs), and the
situation: open play, corner, indirect free kick, direct free kick, penalty,
throw-in or own goal. The zone the shot came from (six-yard box, penalty area
or outside) and, optionally, the delivery (cross, through ball, cut-back,
individual, rebound).

**Our players' match stats.** Minutes, the slot and role played, goals,
assists, shots, shots on target, key passes, clear-cut chances created (if
FM20 shows it) and rating. These are key/value pairs too.

**xG.** As far as I know, FM20 does not show xG; it arrived in FM21. Step 0
confirms this. Phase 07 rules out inventing it. Clear-cut chances, shots on
target and shot zone are the chance-quality evidence available.

**Role attribution.** A player's match stats count towards the slot and role
they started in or came on into. Moving a player mid-match is not modelled in
the first version; the note records it. This is the one approximation behind
"which roles create and shoot", and the page must say so.

## Where the data comes from

| Source | Effort per match | Covers | Risk |
|---|---|---|---|
| Web form, prefilled | About 3–5 minutes | Everything, including the pre-match rating, which no other source can supply | Typing and typing errors, especially for per-player stats |
| FM *Print screen → Web page* of the match stats and player stats panels | About 1 minute (two exports) | Team and player stats, if FM20 lets those panels print | Unknown whether they print; players are bound by name |
| Live reader (sandbox) | None, and it can backfill the season | Fixtures, results, stats, lineups, possibly events | Specialist research of unknown length; still cannot supply the pre-match rating |

**Recommendation (revised after the reconnaissance below).** The live reader
is the main source. It reads what FM holds in memory without running FM's
code, and the sandbox is used only if calling FM's own code turns out to be
the cleanest way to read something. The form shrinks to what only the manager
knows: the pre-match rating, the opponent profile and a note, plus manual
correction when a capture is missing something. The HTML import is no longer
needed. Each captured match is checked against FM's own match screen before
the reader is trusted (Phase 07.5). The pre-match rating always stays manual,
because it is the manager's judgement.

**Where each match's stats come from.** FM holds full stats in memory only
for the latest match and any match report opened since. Every match's stats
are also in FM's match archive, `Temporary/pks_<n>.obs`, which the reader
decodes directly (30 September 2026; see below). The product owner does
nothing in FM: reading a file FM has already written is as safe as reading
its memory. The archive covered all 19 competitive matches of the season on
the first read. When a match is in memory too, the in-memory copy is used,
because it also has the timeline (assists and clear-cut chances by minute).

## Live-read reconnaissance (29 September 2026)

This used read-only reads of `/proc/<pid>/mem`: nothing was attached to FM, no
FM code ran, and nothing was written. A scan of all 2.2 GB of FM's writable
memory for the class tables of match objects takes about 5 seconds. The ground
truth was Concord Rangers 2–2 Hungerford Town on 2 November 2019 (FM date 9
November 2019), with figures read off FM's match screen by the manager.

**Season results: `FIXTURE_RESULT` (`sicomps`), one 0x80-byte record per
match.** Every Hungerford match from 25 June to 2 November was found, some
held in several copies. The known fields are:

- home team pointer `+0x08` and away team pointer `+0x10`;
- the season, as the year it starts, `+0x30` (u16: 2019 for 2019/20, 0 for a
  friendly). FM keeps every season of a league under one competition, so
  without it the second season's tables added up both (27 teams for a
  22-team league). Checked 7 October 2026 on all 76,320 results FM held;
- date `+0x4c`, in FM's date format;
- apparently the league round `+0x3a` (17 on 2 November) and a running ID
  `+0x58`;
- attendance `+0x5c` (344), and apparently away fans `+0x60` (22);
- home goals `+0x64` and away goals `+0x69`, each five bytes with `0xff`
  for a stage not played: after 90 minutes, after extra time, the penalty
  shootout and the aggregate over two legs (decoded 30 September 2026 from
  all 541 results FM held that went beyond 90 minutes; the FA Trophy replay
  with Slough, 1-1 after 90 and won 2-1 after extra time, first showed that
  only the 90-minute score had been read);
- a result code `+0x78` (`09 09` for a draw); and
- a pointer `+0x70` to the match's incidents, null when there are none
  (decoded 30 September 2026, below).

**A result's incidents (goals and sendings-off), decoded 30 September 2026.**
`+0x70` points to a vector of 8-byte entries in match order: player short ID
`+0x00` (the scorer, or the player sent off), side `+0x04` (0 home, 1 away:
the side a goal counts for, or the sent-off player's side), type `+0x05`,
minute `+0x06` and added time `+0x07` (90+4 is minute 90, added time 4). Type
0 is a goal, 1 an own goal (it counts for the other side and is not in the
scorer's goals: Mason at Slough), 2 a penalty (Johnson v Oxford City, Kearney
for Dulwich) and 3 a sending-off (Klukowski at Weymouth, Tomlinson at
Billericay), confirmed by the manager in FM. Every one of Hungerford's 28
results adds up to its score, and each scorer and side matches the 26 matches'
player stats. Because every result has this, goal minutes cover the whole
season, including matches with no stats; a capture keeps a match's incidents
only when its goals add up to the score, and an unseen type fails the list.

**Latest match detail: `GAME_MATCH_STATS`, 0xd0 bytes.** Its `+0x08` points to
the match's result record. It holds:

- **Timeline, `+0x28`:** a list of 0x30-byte events, each with minute `+0x28`,
  side `+0x29` and type `+0x2b`. Type `0x01` is a goal (19′ and 66′ away, 63′
  and 90′ home, which matches the 2–2), and `0x24` follows every goal, so it
  is probably the assist. Type `0x2f` may be a card. Each goal carries 16
  descriptor bytes (`+0x10`–`+0x1f`), probably goal type, body part and zone.
  The person references (`+0x20`, `+0x24`) are not FM player IDs and are
  still unmapped.
- **Two team blocks, home `+0x58` and away `+0x60`, each 0x1d0 bytes.** Kit
  colours come first, then the counters. Verified against FM's screen:

  | Field | Offset | Concord | Hungerford |
  |---|---|---|---|
  | Possession time, total (1st half, 2nd half) | `+0x68` (`+0x6c`, `+0x70`) | 5131 → 52% | 4739 → 48% |
  | Goals | `+0x122` | 2 | 2 |
  | Shots | `+0x12c` (u8) | 15 | 6 |
  | Shots on target | `+0x12d` (u8) | 6 | 5 |
  | Clear-cut chances | `+0x165` (u8) | 1 | 2 |
  | Corners | `+0x180` (u8) | 3 | 2 |
  | Fouls | `+0x183` (u8) | 9 | 18 |
  | Passes attempted, completed | `+0xda`, `+0xdc` (u16) | 474, 344 | 461, 317 |
  | Tackles attempted, won | `+0xe0`, `+0xe2` (u16) | 10, 8 | 14, 13 |
  | Headers attempted, won | `+0xe4`, `+0xe6` (u16) | 68, 45 | 74, 39 |

  **Checked against FM's own panel for two matches.** The panels were exported
  by Print screen → Web page, and copies are kept in `data/research/matches/`:
  Concord 2–2 on 2 November, and Hampton & Richmond 1–3 Hungerford on 31
  August. Every offset in the table gives FM's figure for both matches.
  FM20's default match stats are shots, on target, off target, clear-cut
  chances, possession, corners, fouls, passes, tackles, headers, yellow cards,
  red cards and average rating. There is no xG.

  - **Off target** (7/0 and 4/1) and **average rating** (6.74/6.79 and
    6.51/7.19) are not in the team blocks. They are probably worked out from
    the player records.
  - **Cards** were 0–0 in both matches, so they cannot be located yet.
  - `+0x188` holds a small value even in empty objects, so it is not a stat.

  About 30 counters are still unlabelled. They include three more
  total/first-half/second-half triples at `+0x7c`, `+0x90` and `+0xa4`, and
  pairs at `+0xd6` (41/19) and `+0xde` (30/63). FM's match stats can be
  customised to show more rows, and adding those rows and exporting again
  should label most of the rest.
- **Player records, `+0x198`:** 23 pointers per team into a pool of 0xb0-byte
  `GAME_MATCH_PLAYER_STATS` records, one per match-squad place. Unused places
  have the ID `0xffffffff`. The fields below were found by checking that each
  one adds up to FM's team total for both sides of the Concord match. The
  ratings of Saydee (8.05, shown as 8.1) and Roast (7.63, shown as 7.6)
  match FM's screen:

  | Field | Offset |
  |---|---|
  | Player (short ID, which is person `+0x08`, next to the unique ID at `+0x0C`) | `+0x10` (u32) |
  | Role code (one bit; see `analytics/match_roles.py`) | `+0x08` (u32) |
  | Starting position (a bit per pitch position, 0 for a substitute), then which of a central pair (`0x10` left, `0x20` right) | `+0x48` (u16), `+0x4a` |
  | Position played (substitutes included) | `+0x50` (u16) |
  | Shirt number / squad place, side (0 home, 1 away) | `+0x60`, `+0x61` |
  | Rating × 100 (6.40 for an unused substitute: ignore it when distance is 0) | `+0x5c` (u16) |
  | Distance covered, metres | `+0x44` (float) |
  | Goals, goals conceded (goalkeeper), assists | `+0x65`, `+0x66`, `+0x79` |
  | Shots, on target | `+0x6a`, `+0x6b` |
  | Clear-cut chances: two columns, each summing to the team figure. Probably one "had" and one "created" | `+0x6e`, `+0x76` |
  | Fouls | `+0x7d` |
  | Passes attempted, completed | `+0x91`, `+0x92` |
  | Tackles attempted, won | `+0x94`, `+0x95` |
  | Headers attempted, won | `+0x97`, `+0x98` |
  | Corners taken | `+0x9f` |

  `tools/fm20_match_probe.py squad` lists the first team with the short IDs,
  and every Hungerford player in the Concord match was named that way.
  The match timeline's `0x2f` events are the clear-cut chances (three, at 14′
  home and 19′ and 66′ away, matching 1 and 2).

**Other clubs' matches are in memory too.** The same objects held Hungerford
matches on 3 and 9 November with crowds of 13–23: the reserve or youth sides.
The reader must keep only matches whose team is the managed first team.

**Tactic and roles.** Six `MATCH_CLIENT_TACTIC` objects exist, made of
per-position lists, which is where formation and roles should be. They are
not decoded yet, and it is not yet known whether one is kept per match.

The executable also names `MATCH_ANALYSIS_MATCH`, `PITCH_GOALS_AREAS`,
`PITCH_ASSIST_AREAS` and `GOAL_DESCRIPTION`, which are the likely home of
"where goals came from". None were decoded in this pass.

**Answered since:**

- The player-record `+0x08` bits are FM's **role codes**, not positions: they
  repeat per role across matches, and the product owner confirmed eight of
  them.
- Goals (`+0x65`), goals conceded (`+0x66`), assists (`+0x79`) and
  clear-cut chances (`+0x6e`) were confirmed on the August match. `+0x76`
  matched in one match only.
- Opening an old match report loads its detail into memory.
- Competitions: result `+0x20` → `db::FIXTURE_NAME` → `+0x18` `db::COMP` →
  names at `+0x58` and `+0x60`. Result `+0x18` is the referee and `+0x28`
  the stadium. Scheduled copies of a fixture have no outcome at `+0x78`.
- Player short ID = person `+0x08`.

**Found on 30 September 2026:**

- **Opposition names.** A player's person object starts with the player class
  table followed by the short ID. One scan for those 12-byte pairs names
  every player in a match, and first and last name are at person `+0x58` and
  `+0x60`. The capture now does this, so opposition players are named, as
  are our own who have left.
- **Goal records.** `db::GOAL_DESCRIPTION` objects (0x70 bytes) repeat each
  goal's eight descriptor bytes (`+0x20`), with the scoring team (`+0x28`),
  the date (`+0x38`), the scorer's shirt (`+0x40`) and the opposing team
  (`+0x50`). Decoding goal type still needs ground truth.
- **Not used: the key-moments list** (`GAME_MATCH_STATS +0x70`, 20-byte
  records with the minute and second of goals and other moments). Alongside
  the shots it holds values between 0 and 1 that FM20 never shows. They are
  probably an internal chance-quality figure, so the list is not read.
- **The match archive, decoded (30 September 2026).**
  `OBJECT_STORAGE<ARCHIVED_MATCH_STATS>` reads C-library files, the four
  `Temporary/pks_<n>.obs` (the file sizes equal the store's recorded sizes
  plus a 9-byte header). Each file is that header followed by one
  zlib-compressed chunk per match. `pks_0` held all of the club's matches;
  the others hold other clubs' matches, which Phase 08 could use.
  - A chunk's header names the stadium, then the home and away club IDs,
    each after a `01` byte. A chunk is matched to a fixture by the two clubs
    (home first) and the score. It holds no match date, so repeat meetings
    at the same ground (two 0-0s at Wealdstone) are told apart by order:
    `pks_0` keeps the club's matches in the order they were played (all 67
    archived matches, checked 7 October 2026). Before that, both meetings
    were dropped as ambiguous; see `fm20_match_archive.find_chunks`.
  - Player records are packed. Each starts `01`, the short ID, four zero
    bytes, shirt, side and `02`. It has a 129-byte fixed part, then one
    entry per shot, usually 15 bytes and sometimes 12. Every live field sits
    at one fixed offset from the short ID: all 25 were checked against all
    32 live records of the Concord match, with no differences.
  - The team's own record holds corners, fouls, passes, tackles, headers and
    possession. It is found by the players' passing and tackling sums, which
    always equal the team's. The team's headers attempted was one fewer than
    its players' sum in three matches, so the team's own figures are read.
    Corners, fouls and headers won matched the players' sums in all 52 team
    records.
  - The August match decoded from the archive reproduces FM's exported panel
    exactly, possession 55/45 included.
  - Shot entries hold the minute and second, then two floats that fit where
    the ball ended up in the goal plane (metres across from the centre and
    up). All goals and saved shots fall inside the frame (under 3.66 across
    and 2.44 up); a miss over the bar is 4.3 up and wide shots are 6–10
    across. Not yet parsed: entries vary in length.
  - Code: `tools/fm20_match_archive.py`, tests in
    `tests/test_fm20_match_archive.py`.
- **Minutes played.** The player record holds the minute a player came on
  (`+0x89`) and the minute he was taken off (`+0x84`), with 0 when neither
  happened. All ten substitution times at Concord match FM's line-up export
  (`data/research/matches/2019-11-02-concord-hungerford-lineups.html`).
  Minutes played = (minute off, else 90) − (minute on, else 0).
- **Ratings FM does not show.** In that export FM showed "–" for Okojie (on
  for 4 minutes), while the record holds 6.67. The reader withholds ratings
  under 13 minutes, the shortest stint FM was seen to rate (Millar).
- **Per-player figures checked against FM's player stats screens** (30
  September 2026, Concord match, read out by the product owner):
  - Fundi's shot outcomes (1 goal, 1 saved, none missed or blocked);
  - Cain's tackles (5 won, 0 lost) and distance (12.2 km, stored as 12,214 m
    at `+0x44`);
  - Jarra's headers (10 won, 3 lost); and
  - Saydee's passes (33 of 44, 75%) and corners (2, `+0x9f`).

  Blocked shots are `+0x6c`: 2 and 1 at Concord, 3 and 1 in August, exactly
  FM's figures. Off target = shots − on target − blocked, which gives FM's
  panel figures in both matches. Key passes (`+0x93`), chances created
  (`+0x7a`) and dribbles (`+0x7b`) each matched FM for two players (Saydee
  3/2/2 and Hargreaves 2/1/1; Cain's 7 dribbles too) and are captured.
- **Print screen does not export the match Analysis tab** (the files come out
  empty). The chalkboard's data (`MATCH_CHALKBOARD_DATA_CACHE`) is in memory
  only while that tab is open.

**Found on 3 October 2026 (positions):**

- **Where each player played.** The record holds a starting position at
  `+0x48` (archive `+11`) and the position played at `+0x50` (archive
  `+96`), each a bit set in FM's own order with right before left: GK, SW,
  DR, DL, DC, WBR, WBL, DM, MR, ML, MC, AMR, AML, AMC, ST. The byte after the
  starting position says which of a central pair he started in (`0x10` left,
  `0x20` right; 0 when alone there). These were the only live offsets that
  gave all 32 players of the 21 March 2020 match the values the archive
  holds for them.
- **Checked against the manager's tactic:** Bevans and Collier, his
  right-backs, decode as DR; Fundi, his left-sided Advanced Forward, as ST
  left; the Pressing Forward as ST right, with a different code (`0x40000`)
  on 14 September, when he says he occasionally plays a Target Man.
- **Checked across the archive:** the 14,000-odd team sheets in the
  archive files decode to real formations (4-4-2, 4-2-3-1, 3-5-2 with
  wing-backs and so on). A starter's position played equals his starting
  position in 99.96% of cases, and the rest are sensible moves (an outfield
  player in goal, a wide midfielder into the middle). 41,705 of 41,707
  substitutes have exactly one position played.
- **FM's line-up list runs right to left** (GK, DR, DC right, DC left, DL,
  MR, ...), so a player's place in the list is not needed to tell sides apart.
- **A substitute does not always take the replaced player's role code.** When
  the shape changes with a substitution (Saydee off from MR, Appau on into
  MC), the substitute carries the code and position of the job he did.

**Still open, in order:**

**Answered on 30 September 2026:** the layout held after an FM restart (a new
process gave the same results, the same stats and a clean self-check), and
the per-player figures were confirmed against FM's screens (see above).

1. Parse the archive's shot entries for shot placement. (Goal minutes for
   every match now come from each result's incidents.) Where a shot was taken
   from does not appear to be stored there.
2. Goal type (open play or set piece): decode the goal descriptor bytes. It
   needs ground truth, which FM's own goal descriptions in its archive may
   provide.
3. Label the remaining team counters, and locate yellow cards on a match with some.
4. Bind the archived tactic duty words to historical appearances. The player
   role code does not distinguish duty; the full tactic word does. See
   [historical match duty extraction](match-duty-extraction.md) for the decoder,
   evidence and remaining gates.

## Delivery steps

The plan as proposed. See [As built](#as-built-29-september-2026) for what was
delivered and how it differs.

### Step 0: survey FM20's match screens and settle the decisions (no code)

Now smaller: the reconnaissance has answered most of this. What remains is FM's
full match stats panel and player ratings for the Concord match, to label the
remaining counters, and question 4 below. The HTML questions (3) no longer
matter. The original list:

1. the exact list of team stats on the match report's stats panel;
2. the per-match player stats columns;
3. whether *Print screen → Web page* works on the team stats, the player stats
   and the goals or events list. Save a sample of each in `data/` for the
   importer tests, with a sanitised copy under `fixtures/`;
4. how far back FM keeps a match's report, stats and analysis tab (open a match
   from August);
5. whether the analysis tab shows goal and shot locations and assist types;
6. that there is no xG.

Update [the match record](#the-match-record) with the answers, and settle
[Decisions](#decisions).

### Step 1: record, store and CLI (medium)

- `domain/matches.py` holds frozen, validated dataclasses: `MatchRecord`,
  `TeamMatchStats`, `GoalEvent`, `PlayerMatchStats`, `LineupSlot`,
  `Substitution` and `RecommendationSnapshot`. A JSON round trip provides the
  import format, which is also the future live reader's output.
- `persistence/match_history.py` stores matches in
  `data/match-history.sqlite3`. Extract the migration runner from
  `player_knowledge.py` (`initialize`, `_apply`, backup and refusal) into
  `persistence/migrations.py` and use it from both stores. That shares one
  runner instead of copying it into a second store, which `CLAUDE.md` asks
  for. An edit is a new revision and the latest revision wins; a delete is a
  tombstone revision.
- A `fm-matches` command alongside `fm-knowledge`, with `status`, `list`,
  `show ID`, `import FILE.json` and `export`, plus `--save NAME` as
  `fm-knowledge` has.
- Tests: `tests/test_match_models.py` and `tests/test_match_history.py`, with
  migration tested through an injected second step. They also check revisions,
  save isolation, and that *not rated* never reads as 0.

**Done when** a JSON match round-trips, re-importing it adds nothing, and an
edit keeps the earlier revision.

### Step 2: enter and browse matches on the web (medium)

- `web/match_pages.py` (a mixin like `scouting_pages.py`) and
  `web/match_render.py`, with **Matches** added to the navigation.
- `/matches` lists matches newest first. `/matches/new` is prefilled from
  `bundle.primary` (tactic, and the XI with slots and roles) and from the game
  date. A **Record a match** link on `/tactics` carries the current `opp_*`
  parameters, so a rating set before the match is kept. `/matches/<id>` shows
  a match and edits it.
- A POST to `/matches` follows the `/scouting/verdict` pattern. `_read_form`
  caps the body at 4096 bytes, and a full match form is roughly 3–6 KB, so
  raise the cap for this route only.
- The pre-match rating must be filled in or explicitly marked *not rated*.
- Nice to have: suggest opponent names from the clubs already in the
  player-knowledge database.

**Done when** a match can be recorded in a few minutes from a prefilled form,
an edit keeps the earlier revision, and the prefill matches what `/tactics`
shows for the same bundle.

### Step 3: match review (medium), the page this plan exists for

- `analytics/match_analysis.py` holds pure functions that turn records into a
  `MatchReview`.
- `reporting.build_match_review(records, filters)` is the only computation.
  Both `/matches/review` and `fm-matches review` render it.

What the review contains:

1. **By opposition strength.** One row per strength band, plus *not rated*.
   Columns: played/won/drawn/lost, points per game, goals for and against per
   match, shots, shots on target and clear-cut chances for and against,
   average possession, conversion (goals per shot on target, goals per
   clear-cut chance) and goal sources. By default it shows three bands:
   weaker (-2 and -1), similar (0) and stronger (+1 and +2). A toggle shows
   all five.
2. **Tactic × strength.** Points per game and the clear-cut-chance
   difference, with the number of matches in each cell.
3. **Where goals come from.** Goals for and against by situation and zone,
   for each band.
4. **Roles.** For each slot and role: shots, shots on target, goals, assists,
   key passes and clear-cut chances created per 90 minutes, and each role's
   share of the team's shots, split by band. For example, the ML Winger's
   share of shots against stronger sides compared with weaker ones.
5. **Trend.** Rolling shot and clear-cut-chance difference over the last 5
   and 10 matches.

Filters: date range, competition, venue and tactic.

**Sample-size rule.** Every cell shows its match count. A cell built from
fewer than three matches is greyed out and labelled "too few matches to
read". The page shows no significance tests and no "better" or "worse"
wording.

**Done when** every figure can be reproduced by hand from the stored rows, and
the CLI and web show the same numbers. Test this the way
`tests/test_pinned_tactics.py` compares a page with a direct computation.

### Step 4a: HTML import (dropped as a data source, kept as a check)

The live reader covers the data. FM's Print screen → Web page export of the
match stats panel does work, and parsing it is the cheapest way to check a
live capture against FM's own numbers (Phase 07.5). Keep the parser for that
job only.

`imports/fm_match_html.py` parses the exported team stats panel (a
three-column table: home value, statistic, away value) and reports every
difference from the stored capture. It never overwrites a capture.

### Step 4b: live reader (senior, now the main source, in parallel from step 1)

The fixture list and one completed match's team stats have been found (see
the reconnaissance above). Finish the open list there, and check each capture
against FM's own match screen. Then: `tools/fm20_match_feed.py` writes a capture
JSON, and `match_ingest.py` records it (in the style of `knowledge_ingest.py`)
with the source marked `live`. When a live row and a manual row disagree, show
the differences rather than overwrite. Promote it to a bridge `/v1/matches`
resource once it is stable.

### Step 5: feed it back into tactic choice (small)

- **Evidence beside the opponent sliders on `/tactics`:** "Against sides you
  rated +1: played, won, drawn, lost; shots and clear-cut chances for and
  against; per pinned tactic." It is read-only, comes from
  `build_match_review`, and changes no score.
- **Opponent history.** When the opponent has been played before, show the
  previous meetings (formation faced, score, stats) on the new-match form and
  on `/tactics`. This is the seed of Phase 08.1.
- Nothing here changes scoring. Adjusting opponent rules or the catalogue
  from outcomes is tactical-roadmap item 10 and needs far more matches.

Once approved, split steps 1–5 into task briefs in [tasks/](tasks/README.md)
in the usual low/medium/senior form.

## Decisions

Settled on 29 September 2026. The recommendations proposed earlier are
superseded where they differ.

| Decision | Settled |
|---|---|
| Priority against the unfinished item 2–3 UI | Match history first. It is now built; items 2–3 carry on. |
| How opponent strength is measured | By default, the opponent's league position at kickoff, rebuilt from the league's results. "Above or below us" and the manager's own pre-match rating are alternative groupings. |
| A database of its own, or a table in player knowledge | Its own file, `data/match-history.sqlite3`, using the shared migration runner. |
| Match identity | Date plus both club IDs. |
| How the XI is stored | As FM's player lines: order in the line-up, whether he started, role code and stats. |
| Recommendation snapshot (Phase 07.4) | **Deferred.** Matches are captured after they are played, so a snapshot taken then would not be what was recommended before kickoff. It needs its own "before the match" step. |
| First data source | The live reader. The form is kept for notes only. |

## Out of scope

- Invented xG, and causal claims drawn from correlations.
- Tactical changes during a match (recorded in the note only) and live
  intervention.
- The opponent's matches against other teams. That is Phase 08, and it needs
  its own visibility rules.
- Learned outcome models (Phase 10).
