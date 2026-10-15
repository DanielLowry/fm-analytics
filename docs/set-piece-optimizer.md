# Set-piece optimizer

The Set pieces screen is a match-plan builder, not a collection of independent
player rankings. When the role-scoring feed is complete it uses the exact XI
from the selected tactic. On a partial snapshot it remains available as a
clearly labelled squad-wide template.

Player labels in assignments, taker lists and evidence tables include their
selected tactic slot, for example `Ejiro Okosieme (DCR)`. This distinguishes
left/right centre-backs and central midfielders. Provisional squad-wide plans
show the player's known positions instead, or `Position unknown` when absent.

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
For wide and deep defensive free kicks, the optimizer solves several sensible
structures and chooses both the template and its player assignments.

## Editing the weights

All set-piece attribute weights and responsibility importance values live in
[`src/fm_analytics/analytics/data/set_pieces/`](../src/fm_analytics/analytics/data/set_pieces/).
The files are included in the installed package:

| File | Contents |
| --- | --- |
| [attacking_corners.json](../src/fm_analytics/analytics/data/set_pieces/attacking_corners.json) | Corner delivery, box jobs, short support, counter cover and attacking aerial rankings |
| [defending_corners.json](../src/fm_analytics/analytics/data/set_pieces/defending_corners.json) | Goalkeeper, aerial zones, markers, posts, second balls, outlet and defensive aerial rankings |
| [attacking_free_kicks.json](../src/fm_analytics/analytics/data/set_pieces/attacking_free_kicks.json) | Direct, direct small-chance, indirect wide and indirect deep variants, plus dedicated/proxy taker profiles |
| [defending_free_kicks.json](../src/fm_analytics/analytics/data/set_pieces/defending_free_kicks.json) | Each of the four defensive free-kick variants |
| [penalties.json](../src/fm_analytics/analytics/data/set_pieces/penalties.json) | Dedicated and proxy penalty profiles |
| [long_throws.json](../src/fm_analytics/analytics/data/set_pieces/long_throws.json) | Dedicated long-throw profile |
| [model.json](../src/fm_analytics/analytics/data/set_pieces/model.json) | Scoring version and delivery-foot bonus |

Each family defines named `profiles`, which map manager-visible attributes to
weights. Corner `roles` and free-kick `variants` reference those profiles and
set a separate `importance` for each responsibility. For example, defending
corners currently includes:

```json
"def_corner_zonal_centre": {
  "profile": "zonal_defence",
  "importance": 1.6
}
```

Edit `profiles.zonal_defence` to change what makes a suitable aerial zonal
defender. Edit this role's `importance` to change the value of improving central
cover relative to the other jobs. Attribute weights are non-negative ratios;
they need not sum to 100, but their total must be positive. Responsibility
importance must be positive.

Profiles are shared only within their family file. Changing a shared profile
changes every job referencing it there. To tune just one free-kick variant or
zone, copy the profile under a new name and point that job at the copy. Each
variant already has its own responsibility importance values. Repeated wall
players and markers within one variant share their respective job profile.

Routine taker jobs reference a `task`, rather than a second delivery profile:
the specialist rankings and whole-routine assignment use the same taker
scores. For free kicks and penalties, a task's `profile` is the fallback when
the dedicated rating is missing, and `dedicatedProfile` is used when that
rating is available. Dedicated profiles must actually weight the rating they
claim; long throws continue to use only the dedicated Long Throws attribute.

The loader rejects missing jobs or variants, unknown keys or attributes,
duplicate JSON keys, unused profiles, invalid numbers and broken references.
Weights load once when the app starts; restart the app after editing them.
The Python builders retain legal FM instructions and inclusion priorities.
Wide/deep defensive free-kick job counts and approach coverage requirements
also live in `defending_free_kicks.json`, under `templates` and `approaches`.
The extraction initially retained `set-piece-v11`; template selection and
the revised wide/deep profiles shipped as `set-piece-v12`. The two additional
wide/deep structures used `set-piece-v13`. The instruction-availability and
role-profile correction below uses `set-piece-v14`; the assignment solver is unchanged.

## Choosing a defensive free-kick structure

The manager supplied the actual FM20 instruction menus on 14 October 2026.
They are represented per variant in `set_piece_defence.py`, independently
checked against literal expectations in `test_set_piece_availability.py`:

| Variant | Supported outfield instructions |
| --- | --- |
| Direct | Stay forward, Wall, Edge of area, Go back, Man mark |
| Direct, small chance of shot | Direct instructions plus Man mark tall player |
| Indirect wide | Small-chance instructions plus six-yard zonal near, centre and far |
| Indirect deep | The same options as wide, including Wall |

The former shared five-instruction list omitted real options. Its absence of
zonal jobs was an implementation restriction, not a tactical comparison.
`set-piece-v14` corrects this. The existing direct routine retains its five-player
wall and assignments; corners, attacking routines and taker scoring are unchanged.

Small-chance kicks compare six authored templates; wide kicks compare fifteen;
deep kicks compare seventeen. Candidates include ordinary or tall-player
marking for small-chance kicks, one/two/three zonal defenders and marking-led
alternatives for indirect kicks, and wall-free or one/two-player walls for deep
kicks. The goalkeeper and all ten outfield jobs are assigned together.

The loader separates instruction availability from authored balance policy.
Every candidate retains ordinary runner marking, general spare cover, edge
protection and one or two outlets. Wide/deep candidates require at least six
box defenders, including at least two dedicated aerial jobs across tall-player
marking and zonal defence. Small-chance candidates require at least four box
defenders alongside their larger wall. Each named zonal position can appear
only once. Tall-player markers and zonal defenders both count towards box
coverage. No role from another variant can be added, even with a zero count.
The catalogue's wall/count limits are tactical policy, not claimed FM limits.

The existing `risk=secure|balanced|aggressive` control remains **Set-piece
approach**, with its existing attacking effect:

| Approach | Wide/deep minimum box defenders | Small-chance minimum box defenders | Outlets |
| --- | --- | --- | --- |
| Secure | 7 | 5 | Exactly 1 |
| Balanced | 6 | 4 | 1 or 2 |
| Aggressive | 6 | 4 | Exactly 2 |

For each eligible structure, the exact assignment solver allocates each player
once. The optimizer compares complete plans and shows the chosen structure,
zonal and tall-marker counts, and alternatives in **Why this plan?** It does not
force three zonal players or pick by player identity. Near-equal scores express
a modest model preference, not proof of better results in FM.

### Distinct jobs and comparable responsibility budgets

A fixed six-yard zone uses aerial attributes and an actual zonal instruction.
A tall-player marker combines aerial ability with marking. Ordinary marking
tracks other runners. `Go back` uses a separate spare-cover profile emphasizing
anticipation, positioning, concentration and decisions; its displayed zone is
**General box cover**, without invented near/far placement.

For these flexible routines, `budgets` in `defending_free_kicks.json` fixes
the influence of five responsibilities independently of candidate counts:

| Responsibility | Small chance | Wide | Deep |
| --- | --- | --- | --- |
| Goalkeeper | 1.0 | 1.0 | 1.0 |
| Delivery defence: zones, tall markers and spare cover | 3.0 | 4.5 | 4.5 |
| Ordinary runner marking | 2.2 | 1.8 | 1.8 |
| Perimeter: wall and edge guards | 6.6 | 1.5 | 1.8 |
| Counter outlet | 0.8 | 1.2 | 1.2 |

Within a responsibility, each active job type receives a share proportional
to its configured `importance`. Repeated players doing that same job split
its allocation. For indirect delivery defence, centre/near/far zonal jobs have
relative importance 1.6/1.4/1.4, tall marking 1.5 and spare cover 0.9. This gives
central aerial defence more influence than generic spare cover. A plan with
no wall gives its perimeter budget to edge guards, so both wall-free and wall
candidates retain the same total importance. Attribute profiles and budgets
remain explicit football hypotheses in the per-family JSON.

Every candidate within a variant therefore has the same total importance,
including missing jobs on a partial feed. Unfilled jobs contribute zero to
plan comparison while remaining in its denominator. All-attribute-equal teams
receive equal plan scores; deterministic tie-breaking prefers fewer outlets,
more box cover and then the canonical key. Player assignment remains linear.

### Captured Control XIs

The 20 October Control XI chooses a central zonal defender (Okosieme), a
tall-player marker (Bradley-Green), ordinary marking and spare cover for wide
and deep kicks, with two outlets on Balanced.

The 1 November XI chooses Ashby centrally and Okosieme on tall-player marking.
This is a whole-team allocation: the model compares their suitability for both
roles, including the cost of moving the other player. It does not reserve the
central zone for a name. The other zonal and marking-led candidates are solved
and compared too.

The visible live XI copied on 14 October (game date 14 November) has Neufville
at striker. On Balanced, wide kicks select **Central zone with two outlets**:
Ashby central, Okosieme marking tall, Bradley-Green and Lynch marking, Collier
and Holden providing spare cover, Jefford in the wall, Sharpe on the edge,
and Neufville/Sankoh forward. Deep kicks retain that structure with Jefford
as an additional marker and no wall. Small-chance kicks choose a three-player
wall, Okosieme marking tall, Bradley-Green marking, Sharpe/Holden covering,
Lynch on the edge and Neufville/Sankoh forward. De Bie keeps goal throughout.
These are model results for review; the remaining general-cover jobs and
the choice of only one fixed zone remain football trade-offs.

Opposition strengths are not automatically applied. Eligibility remains
separate from assignment and comparison so future opposition requirements
can restrict the reviewed candidates before solving.

## Job suitability and responsibility importance

The scoring model separates the suitability of a player for a job from the value
of improving that responsibility. Individual job-fit scores remain 0–100;
the routine score is their importance-weighted average. Delivery-foot bonuses
influence selection but remain outside the displayed attribute scores.

Defending corners distinguish:

| Responsibility | Principal visible inputs | Importance |
| --- | --- | --- |
| Post guard | Concentration, anticipation, positioning; agility and a small aerial component | 0.7 |
| Central aerial zonal defender | Jumping reach, heading, anticipation, bravery and strength | 1.6 |
| Near/far aerial zonal defender | Same aerial profile as central cover | 1.4 |
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
Direct defensive free kicks weight each wall player at 1.4. The other defensive
free-kick variants use the group budgets explained above, with distinct marking,
zonal, tall-player, spare-cover and second-ball profiles.

`priority` is separate: it decides which responsibilities survive a partial
player feed and their display order. For defensive corners, aerial jobs now
survive before post cover, with the central anchor kept first, followed by
tall-player marking. Importance affects the optimization itself.

The centre has a higher responsibility weight to anchor the main delivery
area. For the captured XI this places Okosieme centrally, Bradley-Green on
the tall-player marking job, Challis in the near zone, and Jefford in the far
zone. This is a general responsibility change, not a player-specific rule.

Equivalent post guards, near/far aerial zones, and repeated responsibilities can
genuinely tie. They retain the same profiles and importance unless there is
a football reason to distinguish them. Canonical player and job ordering
makes these ties stable when the input roster is reordered; the manager can
adjust the equivalent zones to the actual opposition delivery. The existing
routine structures and player counts are unchanged; choosing between
different structures remains separate work.

## Attacking corner profiles

The first-contact near/far-post targets keep the strongest aerial emphasis.
Supporting box jobs also need to contest a delivery; movement and finishing
alone do not describe them. The corner profiles introduced in `set-piece-v9`
are now maintained in `attacking_corners.json`:

| Job | Profile in the config |
| --- | --- |
| Post lurker | `corner_post_lurker` |
| Attack ball from edge | `corner_edge_runner` |
| Mark keeper | `corner_keeper_challenger` |
| Go forward | `corner_box_runner` |
| Come short | `corner_short_option` |
| Stay back | `corner_stay_back` |
| Second stay-back defender | `corner_secondary_cover` |

The edge runner enters the box to attack the delivery and second balls;
the outside-area player collects clearances and threatens from range.
Mark keeper is a goalkeeper challenger and rebound job. Its scoring does
not use conventional defensive marking. The short option now recognises
dribbling as well as passing and a second delivery. Fixed cover values
recovery speed more, while the second fixed defender puts more emphasis on reading
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
fixed cover. Okosieme and Bradley-Green remain the first-contact targets.

`set-piece-v11` makes both primary and secondary cover **Stay back** in the
balanced and secure corner templates. This guarantees two fixed cover
instructions rather than relying on the second player staying back only
when needed. The secure template retains a third **Stay back if needed**
option; aggressive retains one fixed defender. These are general template
instructions, not a special case for Lynch.

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

`tests/test_set_piece_config.py` validates the config and checks that edits
affect the intended jobs, variants and shared taker scores. The frozen
`tests/fixtures/set-piece-v11-config-migration.json` fingerprints pre-extraction
definitions and 24 complete reports: the captured XI plus explicitly synthetic
dedicated ratings/preferred feet, ranged/missing evidence and unavailable
players, across all three attacking risks and both delivery styles. Every
routine variant, assignment, score band and scoring contribution is covered.
Only the old free-kick roles' unused taker placeholder attributes are omitted;
those role descriptions now use the actual task profile. The dedicated and
proxy profiles themselves, and every real taker score, remain covered.
Deliberate tuning should update the model version and review the real-XI
expectations together. The v11 fingerprints remain preserved. Before the v14
edits, `tests/fixtures/set-piece-v13-free-kick-migration.json` independently froze
a projection of all unchanged corner, attacking, direct defensive and taker
outputs across those 24 scenarios, ignoring the model version and selection
metadata. That projection remains checked without regenerating its hashes.

`tests/fixtures/hungerford-control-433dm-2020-10-20.json` preserves the separate
Control XI visible export used in this review. Template tests cover all approach
constraints, complete and partial assignments, constant responsibility budgets,
equal-player comparisons, different squads choosing different structures,
attribute exchanges, ranged/unknown evidence, unavailable players, deterministic
ties, stricter future coverage policies and the actual web assignment cards.
`tests/fixtures/hungerford-control-433dm-2020-11-01.json` preserves the later
visible XI. Regressions pin its complete wide/deep assignments, compare the
zonal plans against marking-led alternatives under the same model, and check
eligibility and coverage at every approach setting. The 14 November fixture
preserves the refreshed live XI. Availability tests use the manager's literal
menu lists rather than deriving expectations from application constants.

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
