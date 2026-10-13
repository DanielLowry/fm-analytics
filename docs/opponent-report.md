# Opponent report

**Status: built 11 October 2026.** The first pre-match opposition report of
[Phase 08](phases/08-opposition-analysis/README.md): before each match, who
supplies the opponent's goals and who finishes them, how they score and
concede (crosses, the far side, set pieces), their formation and likely XI,
their style, and suggested opposition instructions.

## Using it

- **The Opponent page** (`fm-web`, then **Opponent** under Matchday) opens on
  our next opponent, from FM's own fixture list. The picker reports on any
  club in the league (the next opponent first, each with our next fixture
  against them), from their last 10, 20 (the default) or 40 matches.
  **Copy report to clipboard** copies the whole report as JSON.
- **The command line:** `uv run fm-matches opponent` prints the same report;
  `fm-matches opponent oxford` names a club by part of its name (or its FM
  ID); `--window 10|20|40`; `--before YYYY-MM-DD` reads it as it would have
  stood that morning; `--json` gives the page's copy.
- **Reading the data:** **Read matches from FM** on the Matches page (or
  `fm-matches capture`) now also reads every other league club's archived
  matches and our fixtures still to play. There is nothing to do in FM. The
  capture took 22 seconds on 11 October 2026, as long as before: the archive
  files are now decompressed once for ours and theirs together.

Every figure is `reporting.build_opponent_report`, which both the page and the
command line render (the one-computation rule in `CLAUDE.md`).

## Where it comes from

FM keeps a full report of thousands of other clubs' matches in its archive
(`Temporary/pks_1.obs` to `pks_3.obs`; ours are in `pks_0.obs`), the same
packed records our own matches are read from. FM shows any of these match
reports to the manager, so reading them is within the app's rules; as for our
own matches, the archive's highlights list (FM's private chance-quality
figure) is never read.

- **Which matches:** every competitive result FM holds for the other first
  teams of our league, league and cups (friendlies are left out). Each is
  matched to its archive chunk by both clubs and the score (`fm20_match_archive.find_results`).
- **Replayed match days:** reloading and replaying a match day re-plays every
  other club's match too, so the archive can hold a fixture once per
  playthrough. FM's own result names each goal's scorer and minute, and only
  the playthrough that counts has that timeline, so that is the one kept. A
  goalless draw with more than one goalless playthrough cannot be told apart
  and is left out. On 11 October 2026 this found 566 of the 580 other clubs'
  league results of the save's two seasons, plus 103 of their cup matches.
- **Players:** each archived person record names the player and carries his
  FM unique ID (`fm20_match_archive.person_ids`), the ID the league read uses,
  so a player's visible attributes come from the latest league read. Only
  values FM shows count; a rule reads a range only by the end that makes it
  certain (a composure "4-7" is certainly 8 or less).
- **Their shape:** FM saves an AI side's tactic under its formation's name
  ("4-2-1-3 DM Wide"); it is matched by the starters' positions alone.
- **Our fixtures:** `sicomps::FIXTURE` (RVA `0x6D3AE80`, 0x58 bytes), found
  11 October 2026, holds every scheduled match of every competition with the
  same first fields as a result record: teams `+0x08`/`+0x10`, competition
  `+0x20`, season `+0x30`, date `+0x4C`. It is kept after the match is
  played, so a fixture with a played result is dropped. It read all 32 of
  Hungerford's remaining league fixtures in FM's own order. The latest
  capture's list is used (FM reschedules); a capture keeps its list in the
  history's `capture_fixtures` table.

Both are stored in the match history, schema v7: the other clubs' matches in
`club_match_versions` (append-only, like `match_versions`), read with
`MatchHistoryStore.load_club_matches` and never part of `load_history`, so no
other page changes.

## What it shows

Everything rests on the club's most recent competitive matches with full
stats **before the fixture**: a report never uses a match played on or after
its day.

- **Key points:** the shape, the top scorer and supplier, and any way of
  scoring or conceding that is more (or less) than the league's share by more
  than luck explains.
- **Suggested game plan** (a guess, labelled as one): which kind of control
  suits playing them, from their possession, pass completion and headers
  contested ranked against their league, and whether they are above us
  (`analytics/game_plan_suggestion.py`). A club above us gets counter-attack;
  one that keeps the ball and passes it well, or one that goes long, gets
  territorial control; one that lets opponents have the ball gets possession or
  chance control; anything else chance control. "Marked" means the top or
  bottom third of the league for that figure, and it needs six league teams to
  rank against. It links to the tactics of that plan (`/tactics?plan=`), and is
  in `fm-matches opponent` and the JSON copy as `suggested_game_plan`. See
  [control-tactics-plan.md](control-tactics-plan.md).
- **Suggested opposition instructions** (below).
- **Shape:** the likely XI on a pitch (the eleven who started most of the last
  five, each at the position he most often started in), every formation FM
  names with home and away counts, the last five, and the shape they used
  against us last time.
- **Who finishes, who supplies:** goals (penalties, headers, from crosses),
  shots, on target, clear-cut chances and shots per 90; assists (from
  crosses), chances created, key passes and dribbles; and partnerships
  (who set up whom at least twice).
- **How their goals come, scored and conceded:** how (headers from crosses,
  other finishes from crosses, possibly from corners, penalties, direct free
  kicks, other open play, own goals), where from (six-yard box, area, edge,
  outside), crosses by flank, which line scored them, and when. Each has the
  league's share over the same weeks beside it; a share luck alone reaches
  less often than 1 time in 10 is marked "more (or fewer) than the league",
  as the season Diagnosis does.
- **Style:** possession, shots, on target, clear-cut chances, corners, pass
  completion, passes, headers contested, tackles, fouls and bookings per
  match: theirs, their opponents', the league's, and their rank.
- **Against us:** every recorded meeting, linked to its match page.
- **Every player they used**, with appearances, starts, minutes and last match.

### Two guesses, always labelled

FM's goal record marks neither of these, so both are guesses from positions:

- **Possibly from a corner:** a goal from a cross by a player who took corners
  in that match (`match_timeline.CORNER_GUESS`, as on the match page). These are
  kept out of the flank counts.
- **Met at the far side** ("back post"): the crosser played on one flank and
  the scorer on the other, for example a cross from the left met by the right
  striker of a pair or a right winger (`opponent_goals.FAR_SIDE_GUESS`).

Crosses are counted by the flank the crosser played, from the reported club's
side: a cross they conceded from an attacker's right came down their left.

## Suggested opposition instructions

FM's Opposition Instructions are set per player: closing down, tackling,
marking and showing onto a foot. The rules are declared football rules of
thumb applied to what FM shows, not fitted to results
(`opposition_instructions.suggest_instructions`). Only players who started at
least 2 of the last 5 get one, never the goalkeeper, at most six.

| Evidence | Suggestion |
|---|---|
| Their goal threat: 2+ non-penalty goals and a fifth of the team's, or the top scorer with 3 | Marking: tight. Mostly headers: says the marking matters at crosses. Mostly with the foot: show onto weaker foot |
| 3+ shots a match | Marking: tight |
| Their supplier: 2+ assists and a fifth of the team's, or the team's most chances created at 1+ a match | Closing down: always in the middle; more out wide, plus show onto weaker foot. Left alone if his assists were mostly possible corners |
| Their best dribbler, 3+ dribbles a match | Tackling: ease off; show onto weaker foot |
| FM shows composure or first touch of 8 or less, for certain | Closing down: always (not for a striker: it pulls a centre-back out) and tackling: get stuck in. A dribbler keeps "ease off". At most two players beyond those already named |

Nobody FM shows as two-footed is shown onto a foot, and a known preferred foot
is named ("He is left-footed: show him onto his right").

## Where it lives

| Layer | Files |
|---|---|
| Reading FM | `tools/fm20_match_probe.py` (the capture), `tools/fm20_club_matches.py` (fixtures, other clubs' results, formations and names), `tools/fm20_match_archive.py` (`index_chunks`, `find_results`, `person_ids`), `tools/fm20_match_layout.py` (`FIXTURE`) |
| Domain and storage | `domain/matches.py` (`ScheduledFixture`, `MatchCapture.club_matches`/`fixtures`), `persistence/match_history.py` (v7) |
| Analysis | `analytics/opponent_report.py` (the report), `analytics/opponent_players.py`, `analytics/opponent_goals.py`, `analytics/opposition_instructions.py`; `analytics/match_timeline.goal_moments` is the match page's own goal reading, shared |
| Shared computation | `reporting.build_opponent_report`, `reporting.opponent_choices`, `reporting.build_opponent_export` (`opponent_export.py`) |
| Command line | `opponent_cli.py` (`fm-matches opponent`) |
| Web | `web/opponent_pages.py`, `web/opponent_render.py`, `frontend/styles/opponent-report.css` |
| Tests | `test_opponent_report`, `test_opponent_pages`, `test_fm20_club_matches`, and the v7 and archive tests in `test_match_history` and `test_fm20_match_archive` |

## Known limits

- **A league read's squad list can miss a player FM still has at the club**
  (Oxford City's regular keeper on 20 October 2020), so it supplies attributes
  only and never says who has left. A player not in it simply has none.
- **The evidence spans seasons** when the season is young (the last 20 can
  reach back to April); players who have left since still appear in "Every
  player", with the date they last played.
- **Cup matches** count only against clubs whose results FM holds; a
  goalless replayed fixture is left out (above).
- The instructions are named for FM's four columns; check the wording on
  FM20's Opposition Instructions screen the first time.
- Not done yet (Phase 08.6): scoring a report afterwards against what the
  opponent actually did.
