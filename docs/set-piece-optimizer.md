# Set-piece optimizer

The Set pieces screen is a match-plan builder, not a collection of independent
player rankings. When the role-scoring feed is complete it uses the exact XI
from the selected tactic. On a partial snapshot it remains available as a
clearly labelled squad-wide template.

## What it produces

- left- and right-side orders for corners, direct free kicks, and indirect
  free kicks;
- a penalty order and, when the dedicated rating is present, a long-throw
  order;
- attacking corner and attacking wide-free-kick routines from both sides;
- defensive corner and defensive wide-free-kick routines;
- one named player, FM instruction, field zone, purpose, score, and strongest
  visible inputs for every routine job; and
- secure, balanced, and aggressive attacking commitments with three, two, or
  one rest-defence jobs respectively.

Each routine is solved as one exact assignment. A player can fill only one job,
so the taker cannot also be placed in the box and the same aerial specialist
cannot occupy the near, central, and far-post zones. The objective maximizes
the sum of each job's **responsibility importance × player suitability**, with
the existing small preferred-foot bonus applied to side-specific delivery.
This remains a single global assignment: jobs are never filled greedily.

## Job suitability and responsibility importance

`set-piece-v9` separates the suitability of a player for a job from the value
of improving that responsibility. Individual job-fit scores remain 0–100;
the routine score is their importance-weighted average. Delivery-foot bonuses
influence selection but remain outside the displayed attribute scores.

Defending corners distinguish:

| Responsibility | Principal visible inputs | Importance |
| --- | --- | --- |
| Post guard | Concentration, anticipation, positioning; agility and a small aerial component | 0.7 |
| Aerial zonal defender | Jumping reach, heading, anticipation, bravery and strength | 1.4 |
| Tall-player marker | Jumping reach, heading, marking, strength and bravery | 1.5 |
| Man marker | Marking, anticipation, positioning, concentration and tracking movement | 1.1 |
| Spare cover | Anticipation, positioning, concentration and decisions | 0.9 |
| Edge guard | Anticipation, positioning, concentration and acceleration | 1.0 |
| Counter outlet | Pace, acceleration, first touch and off-the-ball movement | 0.8 |

These weights express the relative value of improving a job, not the chance
of a goal. Aerial ability is still useful to a post guard, but contributes
much more to contesting the delivery. There are no player-name rules or
absolute ability cutoffs. A weak squad still receives a complete assignment
when it has enough available players.

The attacking routines also distinguish delivery (1.5; 2.0 for direct free
kicks), aerial first contact (1.4), rest defence (1.3, with third wide cover
1.1), short support (0.9), goalkeeper challengers (0.8), and other runners (1.0).
Defensive free kicks weight the wall more for direct shots (1.4) and aerial
cover more for indirect deliveries (1.4). Their runner-marking profile is
distinct from their aerial-cover profile.

`priority` is separate: it decides which responsibilities survive a partial
player feed and their display order. For defensive corners, aerial jobs now
survive before post cover. Importance affects the optimization itself.

Equivalent post guards, aerial zones, and repeated responsibilities can
genuinely tie. They retain the same profiles and importance unless there is
a football reason to distinguish them. Canonical player and job ordering
makes these ties stable when the input roster is reordered; the manager can
adjust the equivalent zones to the actual opposition delivery. The existing
routine structures and player counts are unchanged; choosing between
different structures remains separate work.

## Attacking corner profiles

The first-contact near/far-post targets keep the strongest aerial emphasis.
Supporting box jobs also need to contest a delivery; movement and finishing
alone do not describe them. `set-piece-v9` adds distinct corner profiles:

| Job | Visible attribute weights (total 100) |
| --- | --- |
| Post lurker | Off the ball 18, anticipation 18, finishing 14, jumping reach 12, heading 12, strength 10, bravery 8, decisions 4, composure 4 |
| Attack ball from edge | Jumping reach 18, heading 18, off the ball 18, anticipation 18, strength 8, finishing 8, bravery 4, acceleration 4, decisions 4 |
| Mark keeper | Strength 20, jumping reach 18, bravery 16, heading 14, anticipation 14, off the ball 8, finishing 6, decisions 4 |
| Go forward | Jumping reach 18, heading 16, off the ball 18, anticipation 14, strength 10, finishing 10, bravery 8, decisions 6 |
| Come short | Crossing 20, passing 20, dribbling 15, technique 15, decisions 15, first touch 10, acceleration 5 |
| Stay back | Positioning 20, anticipation 18, pace 18, acceleration 12, tackling 12, marking 10, decisions 6, concentration 4 |
| Stay back if needed | Positioning 20, anticipation 20, tackling 14, marking 12, decisions 12, concentration 8, pace 6, acceleration 4, first touch 2, passing 2 |

The edge runner enters the box to attack the delivery and second balls;
the outside-area player collects clearances and threatens from range.
Mark keeper is a goalkeeper challenger and rebound job. Its scoring does
not use conventional defensive marking. The short option now recognises
dribbling as well as passing and a second delivery. Fixed cover values
recovery speed more, while conditional cover puts more emphasis on reading
and intercepting clearances. These are authored football judgments: the
[FM20 attacking-corner guide](https://www.passion4fm.com/football-manager-set-piece-guide-attacking-corners/)
supports the job interpretations and relevant inputs, not the numeric weights.

Corner-specific profiles keep the free-kick variants independent pending
their separate review. The taker still comes from the same delivery scoring
as the specialist rankings, but is selected with the whole routine. For the
captured balanced XI, Odunston's slightly better delivery is less valuable
than retaining him as the fixed counter defender: Saydee takes the corner,
Holden comes short, Fundi lurks at the far post, Challis attacks from the edge,
Jefford challenges the keeper, Sharpe stays outside, and Lynch supplies
conditional cover. Okosieme and Bradley-Green remain the first-contact targets.

The risk settings retain their existing job counts. An aggressive routine
therefore still requires weaker box players when the XI lacks enough strong
aerial players; the scores expose that compromise rather than inventing
extra physical ability or leaving jobs unfilled.

## Regression evidence

`tests/fixtures/hungerford-vertical-442-2020-10-20.json` preserves the exact
selected XI's manager-visible attribute export from the running app on
10 October 2026. Attributes omitted from that export remain unknown. It is
a fixed starting XI, not a complete squad or a new live read; see its source
metadata for the uncaptured identity and readiness fields.

Behavioral tests cover scarce aerial strength, player-profile exchanges,
weak squads, ranged and unknown observations, roster-order stability,
availability and goalkeeper restrictions, attacking first contact, and
indirect free-kick aerial cover, attacking box-job physical inputs, short-option
dribbling, the delivery/cover tradeoff, and complete assignments at every
corner risk setting. Small synthetic problems are checked against
exhaustive assignment enumeration, including a case where choosing the best
player for the first job loses to the global optimum.

## Evidence boundary

The model uses only `Player.attributes`, availability, positions, and verified
preferred foot. Unknown observations stay at the current-ranking floor and
retain their uncertainty range.

`freeKickTaking`, `penaltyTaking`, and `longThrows` are recognized from custom
FM HTML views (`Fre`, `Pen`, and `L Th`). If present, the first two replace their
fallback proxy profile and the UI labels the result **Dedicated rating**. The
live FM20 reader still lacks verified offsets/display IDs for these fields:

- direct and indirect free kicks fall back to transparent technical profiles;
- penalties fall back to finishing, composure, and technique; and
- long throws are withheld rather than inferred from unrelated attributes.

This is source coverage, not unfinished optimizer behavior. Adding verified
live-reader mappings later will activate the dedicated scoring path without a
set-piece model or UI change.

## Interpretation

The weights are reviewable football hypotheses, not reverse-engineered match
engine coefficients, and the 0–100 values are comparisons rather than expected
goal probabilities. Opponent-specific aerial matchups are not inferred: the
manager should still move the primary and secondary markers onto the actual
opposition threats in FM.
