# League page: the hidden-attribute view

**Status:** built 11 October 2026 at the manager's request. `/league/hidden`,
linked from the League page as "Hidden attributes: is it the squad, or is it us?".

**The question it answers:** are recent results down to the players, or to
something else (tactics, selection, match management)? The League page can only
estimate other squads from what FM shows. This view measures every squad, and
every XI fielded this season, from the real values FM keeps.

## The one exception to "manager-visible only"

Everything else in this project uses only what a manager can see in FM. This
view deliberately does not: it reads the true value of every attribute FM shows
on a profile, and FM's real 1-20 rating at every position, for every player,
however little the manager knows him. The manager asked for exactly that, for
this analysis, and every page of it says so in an amber banner.

The data is quarantined:

- It lives in its own file, `data/hidden-capture.json`, with its own format
  (`fm-analytics/hidden-attributes`) and its own loader (`domain/hidden.py`).
  The league capture's contract still refuses hidden values.
- Only `hidden_reporting.build_hidden_strength_report` (and its JSON export)
  reads it, through `analytics/hidden_strength.py`, and only the hidden view's
  web modules call that. It is kept out of `reporting.py`, so the
  recommendation path never even imports it.
  `tests/test_hidden_strength.py::BoundaryTests` fails if any other module
  imports a hidden module, or if importing `reporting` or the CLI loads one.
- Nothing it computes feeds a recommendation, the visible League comparison,
  Scouting or any export other than its own.

Current Ability, Potential Ability and FM's hidden personality attributes
(consistency, important matches and so on) are **not** read. The manager chose
true attributes only on 11 October 2026.

## Reading it

`tools/fm20_hidden_capture.py`, run by the page's **Read hidden attributes from
FM** button (or directly; `--match-db`, `--output`). Plain read-only reads of
FM's memory: no FM code runs, in the game or in the sandbox.

- **Clubs and squads**: the League read's own functions
  (`fm20_league_capture.league_members`, `read_squad`, `shared_players`), so
  both pages compare the same squads. Our row is our first-team list, read the
  same way (on 20 October 2020: the same 45 players as the League read).
- **Starters**: every player in a starting line-up the match history holds
  for the save, ours and the other league clubs', wherever he plays now. A
  line-up names players by FM's short match ID; a player's person part holds it
  at +0x08 and his unique ID at +0x0C, so one pass over FM's person list
  (404,589 people, 160,534 players) indexes everyone in about 0.3 s.
- **Values**: the block at player + 0x164: the fifteen position ratings, then
  each attribute at FMScoutFramework's offsets, converted to 1-20 exactly as
  our own squad's read converts them (`normalize_attribute_byte`).

Checked 11 October 2026 on the National League South save: every starter the
read resolved had the same name and unique ID as the match record (all
appearances over two seasons, about 15,800), so short IDs are stable across sessions. 201 of
1,665 starters were no longer players in FM's database: last season's
retirements, and players FM made up for lower-league FA Cup opponents and later
removed. Every league starter this season was found. A whole read took 1.8 s.

The analysis also refuses to guess: a starter whose short ID now names someone
else (a different name) counts as missing, and an XI with a missing starter is
not scored.

## What the page shows

Every score is the team model's XI score (0-100), computed exactly as the
League and Tactics pages compute it (`xi_selection.recommend_tactic`, central
objective, neutral opponent, no recent form), but from true attributes and
position ratings, with every player fully fit. So it compares players and
nothing else. (On the visible League page, rivals' unknown condition costs them
about 10 points each through the readiness fallback; that does not apply here.)

1. **The XIs in our matches.** Both XIs exactly as they started each
   competitive match of the season, each player in the position he started.
   The XI is scored in whichever catalogue tactic of that shape suits those
   eleven best (same rule for both sides). Where the catalogue has no tactic of
   that shape (FM's "4-2-3-1 Wide" with two MCs, "4-3-3 Narrow" with three
   strikers), the nearest shape stands in: the one needing the fewest, shortest
   moves across the pitch, and only the players it moves may change position.
2. **Best XI in our tactics.** Every club's best XI from its whole first-team
   squad in each tactic we played this season (from the match note, else
   inferred from the line-up, as the form code does), plus any one picked.
   A squad with nobody FM rates able to play some slot (no DM, say) still
   fields one: then everyone may play anywhere at his real rating there.
3. **Best XI in the formations they've played.** The same, restricted to the
   shapes each club has started a league match in this season, each scored in
   every catalogue tactic of that shape (or the nearest).
4. **Results against strength.** Every club's league points and goals against
   what its fielded XIs predicted.
5. **Defence, midfield and attack** (added 12 October 2026). Every XI split by
   where each player was placed: goalkeeper; defence (SW, DL, DC, DR, WBL,
   WBR); midfield (DM, ML, MC, MR); attack (AML, AMC, AMR, ST). A unit's score
   combines its players' own slot scores as the XI does (the square-root mean),
   before the tactic's balance factor (`XiStrength.units`). Three tables: each
   club's fielded XIs by unit (league average, with its rank in each unit), each
   club's best XI in our main tactic by unit, and our matches unit against unit
   (ours minus theirs), with our defence against their attack and our attack
   against their defence. Which line a wide player is in depends on the
   formation (a 4-4-2's ML is midfield, a 4-3-3's AML attack), so units compare
   best between similar shapes; the two match-ups compare different jobs on the
   same 0-100 scale and are a rough guide.

Above them, the verdict: our points against expected, over the season and the
last five league matches, with the usual run of luck (the standard deviation of
points those matches would give if replayed with the same XIs), our rank by
points, by the XIs we fielded and by our best XI in our main tactic, and our
rank in each unit. Its wording ("better than / worse than / in line with your
squad") is `Verdict.reading`, so the page and the copies say the same.

Every table has **Copy for a spreadsheet** (tab-separated) and **Copy as
Markdown**, both of the rows as filtered and sorted. Signed figures use a plain
minus, and the page's * marks and unit ranks are drawn by CSS, so a copied table
pastes into a spreadsheet as numbers. **Copy the whole page** copies one
Markdown document: the verdict, every table (marks and ranks written out) and
both XIs of every match, about 40 KB for a season (`hidden_markdown.py`).
**Copy everything as JSON** copies the same with every field (`hidden_export.py`).
The footer figures (league totals and averages) are worked out once in
`OurTotals`, so the page and both copies cannot disagree.

First unit reading, 12 October 2026 (2020/21, 170 league matches): our fielded
XIs ranked goalkeeper 4th, defence 8th, midfield 5th and attack 14th of 24; our
best XI in Ball-Winning Counter 4-3-3 DM ranks the same units 6th, 6th, 5th and
13th. On average our attack was only +0.4 against the defences it met, while
every other unit was 2-4 points ahead of its opposite number.

## The expected-result model

Each side's goals are a Poisson count whose log mean moves linearly with the
XI-score gap (home minus away): `home_base + slope × gap` for the home side,
`away_base − slope × gap` for the away side. Fitted by maximum likelihood
(Newton's method, no third-party packages) on every league match this season
with both XIs scored; win, draw and defeat odds follow from the two rates.
At least 40 matches are needed.

First fit, 11 October 2026, 168 league matches of 2020/21: slope 0.050 ± 0.013
(about 4 standard errors from zero); a 1-point XI-score advantage is worth about
0.13 goals a match; at equal strength the home side scores 1.44 to 1.23.
Hungerford Town: 25 points from 15 league matches against 23.2 expected (usual
run of luck ±5.0); 7 against 8.1 in the last five; 5th on points, 7th by XIs
fielded, 6th by best XI in Ball-Winning Counter 4-3-3 DM.

## Limits

- **Attributes are today's.** FM keeps no past values, so an August XI is
  scored with October attributes.
- **League matches come from the match history.** Other clubs' matches arrive
  with **Read matches from FM** on the Matches page; without them the page
  shows our own matches only and no model. The league is recognised by name:
  FM's match records and its competition object give it different IDs (148 and
  5123055 for the National League South).
- **Not modelled:** tactics, instructions, mentality, substitutes, in-match
  injuries, morale and personality. Whatever they are worth is the gap between
  points and expected points, which is the point of the page.
- **Small samples.** Fifteen matches carry about ±5 points of luck; read the
  gap against that spread, as the verdict does.

## Cost

Building the whole view on the real league (336 fielded XIs, 24 squads, three
tactics, every formation) takes about 6.5 s, almost all of it scoring each
fielded XI in every catalogue tactic of its shape. It runs in a background
thread (`web/hidden_state.py`), like the League comparison, and is kept until
the read, the match history or the choices change.
