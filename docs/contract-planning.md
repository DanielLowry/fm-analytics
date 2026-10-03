# Contract planning

**Status:** built, 3 October 2026. The Contracts page (`/contracts`, under
Squad intelligence) and a *Contract plan* panel on each squad player's report.
One data gate is still open (see below).
**Request:** one screen that shows every player we own, when his contract ends,
and — crucially — a ranked answer to *who do we need to secure?* A player who is
playing well, rates well for the season and has a good position score but whose
contract is ending must rise to the top; one who is playing poorly or scores
low should be marked as someone we could let go.

## The question the screen answers

For each player: **how much would we lose if he left, and how soon could he
leave?** The page crosses those two readings into one verdict and lists the
players that need action first. It is a decision aid in the manager's terms,
not a prediction of what the player will do.

Everything it reads is visible to a human manager: the contract screen,
competitive match ratings, the player's own visible attributes and positions,
and the app's existing Squad and Depth scores. It never reads hidden ability,
potential, personality, ambition or loyalty. It cannot see what a renewal would
cost (wages are [parked](tasks/senior-wage-capture.md)) or whether the player
would agree to terms, and the page says so.

## Inputs

| Reading | Source | Same number as |
| --- | --- | --- |
| Contract type, end date, joined date, squad status, contracted club | bridge `contract` (`PlayerContract`) | Squad player report |
| Average rating, minutes, starts, per-match ratings | match history: competitive matches in the 12 months to the game date (`MatchReview.players`), joined on FM player ID | Matches page |
| Position score: best in-position role score | `reporting.build_player_role_scores(...).in_position` | Squad page ("In-position") |
| XI slot, first cover and its score, weak-cover finding | `bundle.weakness_report` for the primary (first pinned) tactic | Depth page |
| Age | bridge | Squad page |

A rolling twelve-month window, not a season boundary, because the match history
has none. It also means last season's form still counts when contracts are
being decided over the summer. A match history recorded for a different club is
ignored, and the page says so.

## The model

All thresholds live in one versioned `ContractPolicy`
(`analytics/contract_planning.py`).

### 1. Contract risk: how soon could he leave?

| Risk | Rule | What it means in FM |
| --- | --- | --- |
| **Any day** | contract type `non_contract` | Another club can offer him terms at any time. |
| **Within 6 months** | ends within 6 months of the game date (an expired contract counts here) | He can agree a pre-contract with an overseas club, and at expiry he leaves for nothing. |
| **In 6–18 months** | ends within 18 months | Time to renew on our terms before he enters his final six months. |
| **Settled** | ends more than 18 months away | No contract action needed. |
| **On loan** | contracted club is not our club | Listed apart; a permanent deal or loan extension is a separate decision. |
| **Unknown** | no contract read, or a dated contract type with no end date | Shown, not categorised. |

### 2. Value: how much would we lose?

Three readings, each banded so the verdict stays explainable:

- **Form**: average rating, compared with the rest of the first team.
  *Strong* is the top third of players with at least 450 competitive minutes,
  *Poor* the bottom third, and *Solid* is in between. Under 450 minutes counts
  as *No match evidence*. With fewer than three rated players, everyone rated
  is *Solid*. The bands are squad-relative because FM ratings at this level
  cluster tightly around 6.5–7.0.
- **Position score**: compared with the recommended XI's median starter, which
  is the Depth page's reference. *Starter level* is at or above it. *Squad
  level* is at least the Depth page's starter bar (85% of the reference).
  Anything lower, including no eligible role, is *below squad level*.
- **Replaceability**: a starter is *hard to replace* when the weakness report
  finds no available cover for his slot, or cover that drops off sharply (the
  Depth page's own rule, below 80% of him). A non-starter is the *only cover*
  for a slot when he is its sole available backup.

| Value | Rule |
| --- | --- |
| **Core** | Strong form with at least a squad-level position score; **or** a starter-level score with solid form; **or** hard to replace |
| **Unproven** | No match evidence, but a starter-level score or a place in the recommended XI |
| **Marginal** | Not in the XI, and poor form; **or** not in the XI with a below-squad-level score and no strong form; **or** no match evidence, below starter level and not in the XI |
| **Useful** | Everything else |

Core needs form and position score together, unless the player is hard to
replace. A strong rating with a low score, or a starter in poor form, lands in
Useful, and a *Form and position score disagree* reason says which reading
pulls against the other.

### 3. Verdict = value × risk

| | Any day / Within 6 months | In 6–18 months | Settled |
| --- | --- | --- | --- |
| **Core** | **Secure now** | **Renew early** | Settled |
| **Useful** | **Keep if the terms are right** | Review later | Settled |
| **Unproven** | **Your call**: give him minutes before deciding | Review later | Settled |
| **Marginal** | **Let go** | Let it run down | Surplus |

One override: a *Let go* or *Let it run down* player who is the **only cover**
for a slot becomes **Replace first**, because releasing him leaves that slot
with nobody behind the starter. *Surplus* keeps its verdict, since a settled
contract asks for no decision.

Reasons are shown as chips and never change the verdict:

- the form band with the player's rank (e.g. *Strong form: 7.02, 2nd of 19*);
- *Small sample* when a strong rating comes from under 900 minutes;
- the position-score level;
- *Form and position score disagree*;
- *In your XI at …*, *Hard to replace: …* and *Only cover at …*;
- *21 or under*;
- *32+: one year at most*;
- *Joined N days ago* (within 60 days).

The squad status the manager promised is shown on the card but not scored.

### 4. The ranking

The page orders players by verdict (Secure now, Renew early, Keep if the terms
are right, Your call, Replace first, Let go, …). Within a verdict, **Any day**
players come first, because they can go without notice. After that comes a
0–100 **keep value**:

- 40%: his first-team rank on rating. Before ranking, the rating is discounted
  as if he had also played 900 minutes at the squad's median rating, so a short
  hot streak cannot top the list. A player with no rating counts as the median.
- 30%: his first-team rank on position score.
- 30%: how far the XI drops if his first cover replaces him. A 30% drop or more,
  or no cover at all, earns full marks; a player outside the XI gets nothing here.
- +5 for 21 or under; −5 for 32 or over. The result is clamped to 0–100.

Keep value only orders players within a verdict, so a borderline weight can
never move a player between verdicts without a visible reason. Form bands,
ranks and keep value always come from the first team, so adding other club
squads to the view never changes a first-team verdict.

## Worked example: Hungerford Town, 5 February 2020

The as-built code was run on the squad in
`data/hungerford-tactical-data.json`, with Vertical 4-4-2 pinned and the
recorded match history. There were 50 players, 19 of them with 450+
competitive minutes. The form thirds came out at 6.59 and 6.79, and the XI
reference at 45.4. The export has no contract **type**, so here *no end date*
was read as non-contract; the live bridge reads the type directly.

Verdict counts: Secure now 8, Renew early 1, Keep if the terms are right 7,
Your call 8, Replace first 1, Let go 24 (3 played poorly, 21 barely used),
Review later 1. **Ten of the recommended XI's eleven could leave within six
months**; only Victor Fundi is signed beyond this season.

| # | Player | Age | Contract | Rating (mins) | Position score | Replaceability | Keep | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Challis Johnson | 19 | non-contract | 7.02 (2,644) | 45.3 squad | STL; cover 18% worse | 83 | Secure now |
| 2 | Aaron Rodriguez | 24 | non-contract | 6.93 (1,988) | 44.1 squad | not in XI | 55 | Secure now |
| 3 | Cameron Hargreaves | 21 | 30 Jun 2020 | 6.70 (2,856) | 52.5 starter | MCL; cover 10% worse | 80 | Secure now |
| 4 | Baboucarr Jarra | 26 | 30 May 2020 | 6.92 (2,744) | 52.0 starter | not in XI | 68 | Secure now |
| 5 | Jamie Bradley-Green | 20 | 30 Jun 2020 | 6.91 (2,387) | 47.0 starter | DCL; cover as good | 68 | Secure now |
| 6 | Adam Siviter | 19 | 30 Jun 2020 | 6.61 (3,240) | 45.4 starter | GK; **hard to replace**, cover 38% worse | 64 | Secure now |
| 7 | Matt Berry-Hargreaves | 20 | 31 May 2020 | 6.79 (732) | 44.7 squad | not in XI | 59 | Secure now |
| 8 | Liam Ferdinand | 25 | 30 Jun 2020 | 6.85 (633) | 42.0 squad | not in XI | 48 | Secure now |
| 9 | Victor Fundi | 21 | 30 Jun 2021 | 7.19 (3,049) | 45.6 starter | STR; cover 8% worse | 76 | Renew early |
| 10 | Jude Mason | 19 | non-contract | 6.47 (1,916) | 46.6 starter | DL; cover 8% worse | 38 | Keep if the terms are right |
| 23 | Nathan Collier | 33 | 30 Jun 2020 | — (0) | 48.3 starter | DR; cover 4% worse | 40 | Your call |
| 25 | Tommy Rees | 17 | 30 Jun 2020 | — (0) | 27.9 below | only cover at GK | 18 | Replace first |
| — | Joe Tomlinson | 19 | 30 May 2020 | 6.53 (1,281) | 43.2 squad | not in XI | 23 | Let go |

What this shows:

- **Johnson** comes first: he has the squad's second-best rating, is 19, starts,
  and any club can sign him today.
- **Siviter** has a mid-table rating, yet he is Secure now because the backup
  keeper scores 28 against his 45. That backup, **Rees**, is *Replace first*,
  not *Let go*.
- **Mason** has the weakest rating among the regulars but is not *Let go*: he
  starts and his score is starter level. He is young and underperforming, not
  poor.
- **Collier**, **Bellamy** and others have starter-level attributes but almost
  no minutes. *Your call* says to play them before their deadline to find out.
- 21 of the 24 *Let go* players are barely used. The page folds them away so the
  three regulars who really are let-go decisions stay visible.

## Screen

- **Hero**: the headline count of recommended starters who could leave within
  six months, their names, the tactic the XI comes from, and the form
  thresholds in force. If form is missing or partial, a note says why.
- **Verdict tiles**: Secure now (with how many can leave any day), Renew early,
  Keep if the terms are right, Your call, Replace first, and Let go (played
  poorly / barely used). Each tile jumps to its section.
- **Who to act on, in order**: one numbered card per player for every action
  verdict. Each card shows:
  - form, with a sparkline of the last ten competitive ratings on a fixed
    5.5–8.0 scale (dashed line at 7.0);
  - position score with its role and level;
  - XI slot and first cover;
  - contract;
  - risk, keep value, and the reason chips.
- **Let go**: a table of players with real match evidence. The barely used are
  in a collapsed section underneath.
- **When players could leave**: one lane per contract risk, with every player
  as a chip coloured by verdict. *XI* marks a recommended starter.
- **All players**: a sortable, searchable, copyable table in priority order.
  Its position column is headed "Pos" so the shared table script does not
  re-sort it by position.
- **How verdicts are decided**: the rules above, with the live thresholds.
- **Scope**: when other club squads are captured, a *First team / All club
  squads* switch adds them without changing first-team verdicts.
- **Player report**: the squad player page shows the same assessment in a
  *Contract plan* panel. The panel is omitted when the squad cannot be scored.
  The player page still renders.

The page needs complete role attributes, like Tactics and Depth. Without
match history it still renders; every player then has no match evidence.

## As built

- `analytics/contract_planning.py`: pure, with no I/O and no scoring of its own.
  It holds `ContractPolicy`, `contract_risk`, `classify_value`, `verdict_for`,
  `assess_contracts` → `ContractReview` of `ContractAssessment`s.
- `reporting.build_contract_review(bundle, history, include_other_squads=...)`:
  the one computation, behind both the page and the player report's panel. A
  CLI flag or season-export section must call it rather than re-derive a
  verdict.
- `web/contract_pages.py` (route mixin) and `web/contract_render.py` (HTML);
  nav entry in `web/rendering_content.py`; styles at the end of
  `frontend/styles/app.css` (rebuild with `npm run build`).
- Tests:
  - `tests/test_contract_planning.py` covers the risk windows and their edges,
    the verdict matrix cell by cell, the value rules, ordering, the only-cover
    override, and parity with the Squad and Depth figures. It also covers
    other squads not moving first-team verdicts, the competitive-only and
    twelve-month window, and another club's history being ignored.
  - `tests/test_web_contracts.py` covers the page, scope, the player panel,
    missing history, an unscoreable squad and escaping.

### Data gate (open)

With FM running, confirm against the live bridge that our non-contract players
report `contractType: non_contract` with no end date. The worked example had
to assume it. If a non-contract player instead reports no type, he shows as
*Contract unknown*, not *Any day*. Also confirm that every first-team player has
a contract object, so *Unknown* stays rare.

## Deliberately not included

- **Wages and renewal cost.** These are parked. When wages are captured, a cost
  column and a "secure within budget" total belong here.
- **Whether he will sign.** FM's contract-happiness and renewal-willingness
  signals are not captured.
- **Transfer value / sell-now advice.** That is a different question (*cash
  in*), and needs visible valuation facts we do not read.
- **Potential.** It is hidden. Age is the only development signal used.
