# Tactic catalogue

**Generated — do not edit.** Run `uv run python tools/tactic_index.py`
after changing any tactic. Each tactic's full detail (per-slot reasoning,
per-instruction rationale, balance requirements) lives in its own file under
`src/fm_analytics/analytics/data/tactics/`.

42 tactics, 84 roles.

## At a glance

| Tactic | Shape | Mentality | Leans on | Use it when |
| --- | --- | --- | --- | --- |
| [Attacking 4-2-4](#attacking-424) | 4-2-4 | Attacking | anticipation, off the ball, pace, stamina | When chasing a game late, or against a much weaker side that will defend deep |
| [Attacking 4-3-3](#attacking-433) | 4-3-3 (Attacking) | Attacking | stamina, anticipation, work rate, first touch | Against sides that defend deep and cannot get past your press, or when you are clearly the stronger team and want to pin them back |
| [Balanced 4-1-2-1-2 Diamond](#balanced-41212-diamond) | 4-1-2-1-2 DM Narrow | Balanced | teamwork, first touch, positioning, pace | When your best players are central (midfielders and two strikers) and you lack quality wingers, or against a side with few central midfielders that you can outnumber |
| [Balanced 4-1-4-1](#balanced-4141) | 4-1-4-1 | Balanced | positioning, teamwork, work rate, passing | As a safe default when you want control without committing many players forward, or away from home against a stronger side |
| [Balanced 4-3-3 DM Wide](#balanced-433dm) | 4-3-3 DM Wide | Balanced | teamwork, positioning, concentration, jumping reach, stamina, work rate, pace, tackling, off the ball, acceleration, finishing, crossing, dribbling, anticipation | As a stable lower-league default when you have one good striker, a dependable holding midfielder and usable wide attackers |
| [Balanced 4-4-1-1](#balanced-4411) | 4-4-1-1 | Balanced | pace, off the ball, crossing, anticipation | When you have one good striker and a creative player who is not a natural second striker, or as a steady all-round system for a mixed squad |
| [Balanced 4-4-2](#balanced-442) | 4-4-2 | Balanced | teamwork, positioning, concentration, crossing, stamina, pace, acceleration, work rate, off the ball, anticipation | As a solid default, or when you have two good strikers and two decent wingers |
| [Enganche 4-2-3-1](#enganche-4231) | 4-2-3-1 DM AM Wide | Balanced | crossing, anticipation, pace, off the ball | When you have one clearly superior creative player who is not suited to a running role, and a target man for him to pass to |
| [Route One 4-4-2](#route-one-442) | 4-4-2 | Balanced | jumping reach, heading, strength, off the ball | When you have a big target man and a quick second striker, but weak technical midfielders |
| [Vertical 4-4-2](#vertical-442) | 4-4-2 | Balanced | teamwork, positioning, concentration, jumping reach, stamina, work rate, crossing, pace, acceleration, off the ball, anticipation | As a proactive lower-league default when the balanced 4-4-2 is too passive, especially when you have pace up front, energetic midfielders and wide players who can deliver early |
| [Counter 3-4-1-2](#counter-3412) | 3-4-1-2 | Cautious | off the ball, positioning, anticipation, concentration | Against stronger sides that will have most of the ball, or when your squad has quick forwards and dependable centre-backs |
| [Direct Counter 4-4-2](#direct-counter-442) | 4-4-2 | Cautious | off the ball, positioning, anticipation, concentration | Against a stronger or possession-based team that will leave space behind its defence, when you have quick wingers and forwards |
| [Fluid Counter 4-1-4-1](#fluid-counter-4141) | 4-1-4-1 | Cautious | passing, first touch, positioning, off the ball | Against stronger or possession-based sides when you have a good holding midfielder, quick wingers and a mobile lone striker |
| [Raumdeuter Counter 4-2-3-1](#raumdeuter-counter-4231) | 4-2-3-1 DM AM Wide | Cautious | off the ball, positioning, anticipation, concentration | Against a stronger team that will leave space behind its full-backs, when you have a smart off-the-ball player who scores goals |
| [Solid 4-2-3-1](#solid-4231) | 4-2-3-1 DM AM Wide | Cautious | positioning, concentration, teamwork, anticipation | Away against a stronger team or when you are protecting a lead, when you want a low-risk shape that can still hit on the break |
| [Counter 3-5-2 Wing-Back](#counter-352-wingback) | 3-5-2 | Counter | positioning, concentration, composure, decisions | Against stronger opponents who will dominate the ball, or when you have good wing-backs and forwards but a weaker midfield |
| [Deep Counter 5-4-1](#deep-counter-541) | 5-4-1 | Defensive | positioning, concentration, off the ball, composure | Protecting a lead, or away against a much stronger side, when you have two quick wide players and a strong striker |
| [Defensive 4-5-1](#defensive-451) | 4-5-1 | Defensive | positioning, concentration, marking, teamwork | Protecting a lead late in a game, or away against a much stronger side where a draw is a good result |
| [Defensive 5-3-2](#defensive-532) | 5-3-2 | Defensive | positioning, concentration, marking, teamwork | Protecting a lead, or against stronger opponents who will have most of the ball |
| [Low-Block 4-4-2](#lowblock-442) | 4-4-2 (Low Block) | Defensive | positioning, concentration, marking, teamwork | Protecting a lead, or away against a stronger side |
| [Aerial 3-4-3](#aerial-343) | 3-4-3 | Positive | crossing, anticipation, off the ball, heading | When you have two wing-backs who cross well and three tall forwards, especially against a back four that struggles with aerial balls |
| [Attacking 3-4-3 Wing-Back](#attacking-343) | 3-4-3 | Positive | stamina, anticipation, work rate, passing | When you are clearly the stronger side and expect the opponent to sit deep, or you need goals late |
| [Box Midfield 4-2-3-1](#box-midfield-4231) | 4-2-3-1 DM AM Wide | Positive | composure, technique, positioning, passing | When you want to control the middle of the pitch against a side that defends in a narrow block, and your full-backs are comfortable on the ball |
| [Complete Wing-Back 4-2-3-1](#complete-wingback-4231) | 4-2-3-1 DM AM Wide | Positive | stamina, composure, technique, crossing | When your two full-backs are among your best attacking players, or against a team that defends narrowly and leaves the flanks open |
| [Control Possession 4-2-3-1](#control-possession-4231) | 4-2-3-1 DM AM Wide | Positive | composure, decisions, technique, positioning | When your squad is technically better than the opponent's and you expect them to sit deep, or when you want to protect a lead by keeping the ball |
| [Crossing 4-3-3](#crossing-433) | 4-3-3 | Positive | crossing, stamina, heading, jumping reach | When you have two tall forwards who can play wide, a strong central striker, and full-backs who can cross, especially against defences that are short or slow to turn |
| [False Nine 4-3-3](#false-nine-433) | 4-3-3 DM Wide | Positive | composure, technique, anticipation, stamina | Against a back four that defends deep and narrow, when you have a striker who is a better passer than a finisher and two wingers who can score |
| [Gegenpress 4-2-3-1](#gegenpress-4231) | 4-2-3-1 DM AM Wide | Positive | work rate, aggression, stamina, anticipation | When you have fit, aggressive players with high work rate and stamina, and you want to play in the opponent's half against sides that struggle to play out from the back |
| [High-Press 4-3-3](#highpress-433) | 4-3-3 (High Press) | Positive | stamina, work rate, anticipation, aggression | When you have fit, energetic players and want to play in the opponent's half, especially against sides that build slowly from the back |
| [Inverted Wing-Back 4-3-3](#inverted-wingback-433) | 4-3-3 DM Wide | Positive | composure, technique, stamina, passing | When your full-backs are better passers than crossers, you want to dominate the centre of the pitch, and you have two wingers who are happy to stay wide |
| [Narrow 4-2-2-2](#narrow-4222) | 4-2-2-2 | Positive | first touch, teamwork, stamina, work rate | When your best players are central and you lack wingers, especially against a team with two central midfielders who will be overrun |
| [Positive 3-4-2-1](#positive-3421) | 3-4-2-1 | Positive | composure, technique, stamina, passing | When you have two good creative players and a wing-back pair who can cover the flanks, especially against a back four that has no midfielder in the half-spaces |
| [Positive 4-2-3-1 Wide](#positive-4231) | 4-2-3-1 DM AM Wide | Positive | first touch, technique, stamina, passing | As a proactive default when you have a good attacking midfielder and two quality wide attackers, or against opponents who defend with two banks of four |
| [Positive 4-3-1-2 Narrow](#positive-4312-narrow) | 4-3-1-2 | Positive | stamina, crossing, first touch, teamwork | When your best players are central and you lack wingers, or against a team with only two central midfielders that you can outnumber |
| [Positive 4-3-3 DM Wide](#positive-433dm) | 4-3-3 DM Wide | Positive | composure, technique, stamina, passing | A good all-round attacking system when you have a reliable holding midfielder and two forwards who can score, against opponents who defend with two banks of four |
| [Possession 4-1-4-1](#possession-4141) | 4-1-4-1 | Positive | composure, decisions, technique, positioning | When your squad is technically better than the opponent's and you want to control the game, or when protecting a lead |
| [High-Press 4-4-2](#pressing-442) | 4-4-2 | Positive | stamina, work rate, aggression, anticipation | When you have fit, energetic forwards and midfielders and want to press the opponent's build-up, especially against a side that plays short from the back |
| [Trequartista 4-3-1-2](#trequartista-4312) | 4-3-1-2 | Positive | first touch, teamwork, technique, composure | When you have one player of clearly superior creativity who is not suited to a fixed role, and a striker partner who will run and press for him |
| [Trequartista 4-4-2](#trequartista-442) | 4-4-2 | Positive | crossing, pace, composure, decisions | When you have a creative forward who is not a natural goalscorer, and a partner with pace and work rate |
| [Vertical Tiki-Taka 4-3-3 DM](#vertical-tikitaka-433dm) | 4-3-3 DM Wide | Positive | anticipation, first touch, technique, pace | When you have good passers and quick forwards, against teams that sit in a mid-block and leave space behind their line |
| [Wide Playmakers 4-3-3](#wide-playmakers-433) | 4-3-3 DM Wide | Positive | stamina, work rate, technique, composure | When your best creative players are wingers or attacking midfielders rather than central playmakers, against sides that defend in a mid-block |
| [Wing Play 4-4-2](#wing-play-442) | 4-4-2 | Positive | crossing, stamina, pace, heading | When you have two good wingers, full-backs with stamina, and a striker who wins headers |

## Each tactic

### Attacking 4-2-4

`attacking_424` · 4-2-4 · Attacking · Attacking 4-2-4

A high-risk structure that immediately puts four players against the opposition back line and is intended to force the game.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) *, Central Defender (Cover) *
- **Midfield:** Ball-Winning Midfielder (Support) [MC], Deep-Lying Playmaker (Support) [MC]
- **Attack:** Inside Forward (Attack), Winger (Attack) [AML/AMR], Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** anticipation +2, off the ball +2, pace +2, stamina +2 (whole team)
- **Needs:** Two midfielders able to cover huge spaces; Fast defenders; Four dangerous attackers; High fitness
- **Instructions:** Fairly Wide; More Direct Passing; Higher Tempo; Pass Into Space; Counter-Press; Counter; Higher Line of Engagement; Higher Defensive Line
- **Avoid when:** Against any side with quick forwards or good passing through the middle: two central midfielders cannot cover the space, and you will be opened up down the centre

### Attacking 4-3-3

`attacking_433` · 4-3-3 (Attacking) · Attacking · Attacking 4-3-3

An aggressive 4-3-3 committing full-backs, midfield runners and wide forwards to attack.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Wing-Back (Attack) [DL/DR] ×2, Central Defender (Defend) *, Ball-Playing Defender (Defend)
- **Midfield:** Central Midfielder (Defend), Box-to-Box Midfielder (Support), Mezzala (Attack)
- **Attack:** Winger (Attack) [AML/AMR], Inside Forward (Attack), Advanced Forward (Attack) *

- **Leans on:** stamina +2, anticipation +2, work rate +2, first touch +2 (whole team)
- **Needs:** Fast recovery defenders; Attacking full-backs; Midfield legs; Wide forwards with end product
- **Instructions:** Much Higher Line of Engagement; Higher Defensive Line; Shorter Passing; Higher Tempo; Counter-Press
- **Avoid when:** Against quick counter-attackers when your full-backs are slow to recover: the space behind both full-backs is the weakness

### Balanced 4-1-2-1-2 Diamond

`balanced_41212_diamond` · 4-1-2-1-2 DM Narrow · Balanced · Balanced Narrow Diamond

A compact narrow 4-1-2-1-2 built around central combinations, two strikers and full-backs supplying most of the width.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Central Midfielder (Support), Deep-Lying Playmaker (Support) [MC]
- **Attack:** Attacking Midfielder (Support), Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** teamwork +2, first touch +2, positioning +2, pace +2 (whole team)
- **Needs:** Full-backs with stamina/crossing; Disciplined DM; Creative AMC; Complementary strikers
- **Instructions:** Fairly Narrow; Shorter Passing; Counter; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against teams that attack down the flanks and outnumber your full-backs, or when your full-backs lack the stamina to cover the whole side of the pitch

### Balanced 4-1-4-1

`balanced_4141` · 4-1-4-1 · Balanced · Balanced 4-1-4-1

A compact 4-1-4-1 with a dedicated screen behind a four-man midfield.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) *, Ball-Playing Defender (Defend)
- **Midfield:** Defensive Midfielder (Defend), Wide Midfielder (Support) ×2, Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Poacher (Attack) *

- **Leans on:** positioning +2, teamwork +2, work rate +2, passing +2 (whole team)
- **Needs:** Disciplined DM; Hard-working wide players; CM support for lone striker; Self-sufficient striker
- **Instructions:** Standard Line of Engagement; Standard Defensive Line; Shorter Passing; Regroup
- **Avoid when:** When you need to chase a goal: there is a single striker and no creative attacking midfielder to feed him

### Balanced 4-3-3 DM Wide

`balanced_433dm` · 4-3-3 DM Wide · Balanced · Balanced 4-3-3 DM

A simple lower-league 4-3-3 with a dedicated holding midfielder, natural width on one side and two additional runners supporting a mobile striker.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Central Midfielder (Support) *, Central Midfielder (Attack)
- **Attack:** Inside Forward (Attack), Winger (Support) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** teamwork +2 (whole team); positioning +2, concentration +2, jumping reach +1 (DC); stamina +2, work rate +1, pace +1 (DL, DR); positioning +2, concentration +2, tackling +2, teamwork +1 (DM); work rate +2, stamina +2, off the ball +1 (MC); acceleration +2, pace +2, off the ball +2, finishing +1 (AML); acceleration +2, pace +2, crossing +2, dribbling +1 (AMR); acceleration +2, pace +2, off the ball +2, anticipation +2 (ST)
- **Needs:** Disciplined holding midfielder; One central midfielder able to make forward runs; Mobile lone striker who threatens space behind; One wide goal threat and one genuine width provider; Full-backs capable of supporting without being the sole attacking outlet
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Counter; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** When you lack a credible lone striker or wide attackers who can threaten the defence

### Balanced 4-4-1-1

`balanced_4411` · 4-4-1-1 · Balanced · Balanced 4-4-1-1

A conventional 4-4-2 defensive shell with one attacker dropping into the number-ten line to connect midfield and the lone striker.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Wide Midfielder (Support), Central Midfielder (Defend), Central Midfielder (Support), Winger (Support) [ML/MR]
- **Attack:** Attacking Midfielder (Support), Advanced Forward (Attack) *

- **Leans on:** pace +2, off the ball +2, crossing +2, anticipation +2 (whole team)
- **Needs:** Intelligent AMC; Mobile striker; Hard-working wide midfielders; Balanced CM pair
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Counter; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** When you need two players to attack the box, or against sides that overload the middle: two central midfielders can be outnumbered

### Balanced 4-4-2

`balanced_442` · 4-4-2 · Balanced · Balanced 4-4-2

A simple two-banks-of-four structure with natural width and two complementary forwards.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Central Midfielder (Support)
- **Attack:** Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** teamwork +2 (whole team); positioning +2, concentration +2 (DC); crossing +2, stamina +2 (DL, DR); crossing +2, pace +2, acceleration +2 (ML, MR); work rate +2, positioning +2 (MC); off the ball +2, anticipation +2, acceleration +2 (ST)
- **Needs:** Hard-working wide midfielders; Balanced CM pair; Complementary strikers; Disciplined full-backs
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Counter; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against a team with three central midfielders who will pass through the middle, since your two are outnumbered

### Enganche 4-2-3-1

`enganche_4231` · 4-2-3-1 DM AM Wide · Balanced · Classic number ten

A 4-2-3-1 built around one free playmaker who does no defensive work, protected by a hard-working double pivot and two attacking wingers, with a target man to finish his passes.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Defensive Midfielder (Defend)
- **Attack:** Winger (Attack) [AML/AMR] ×2, Enganche (Support), Target Man (Support)

- **Leans on:** crossing +2, anticipation +2, pace +2, off the ball +2 (whole team)
- **Needs:** An exceptional creative playmaker; A ball-winning midfielder and a holder in front of the defence; Two wingers who track back; A strong target man
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Work Ball Into Box; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against sides that press hard or man-mark the playmaker, since the team has no other creative source

### Route One 4-4-2

`route_one_442` · 4-4-2 · Balanced · Route One

A deliberately direct system that moves the ball forward early toward a physical target and runners attacking second balls.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Ball-Winning Midfielder (Support) [MC]
- **Attack:** Target Man (Attack), Advanced Forward (Attack) *

- **Leans on:** jumping reach +2, heading +2, strength +2, off the ball +2 (whole team)
- **Needs:** Dominant aerial striker; Fast strike partner; Strong midfield; Reliable crossing
- **Instructions:** Much More Direct Passing; Higher Tempo; Pass Into Space; Hit Early Crosses; Counter; Regroup
- **Avoid when:** Against tall, strong centre-backs who win the aerial duels, or when your squad is technical and would waste its passing

### Vertical 4-4-2

`vertical_442` · 4-4-2 · Balanced · Vertical 4-4-2

A simple lower-league 4-4-2 that keeps two banks of four but attacks more vertically, using a midfield runner, early wide service and a forward running beyond.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** teamwork +2 (whole team); positioning +2, concentration +2, jumping reach +1 (DC); stamina +2, work rate +1, crossing +1 (DL, DR); pace +2, acceleration +2, crossing +2, work rate +1 (ML, MR); work rate +2, stamina +2, positioning +1, off the ball +1 (MC); off the ball +2, anticipation +2, acceleration +2 (ST)
- **Needs:** One holding central midfielder and one energetic runner; Wide players with enough pace and crossing to deliver early; A linking striker paired with a forward who attacks space; Disciplined back four; Enough stamina and work rate to support quick transitions
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Higher Tempo; Pass Into Space; Hit Early Crosses; Counter; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against a side that dominates central midfield with three strong midfielders, or when your forwards lack pace and movement to exploit earlier, more vertical service

### Counter 3-4-1-2

`counter_3412` · 3-4-1-2 · Cautious · Back-Three Counter

A cautious back-three system retaining an AMC and two strikers so regains can become attacks without waiting for many players to advance.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Central Defender (Defend) *, Ball-Playing Defender (Defend), Central Defender (Cover) *, Wing-Back (Support) [WBL/WBR], Wing-Back (Attack) [WBL/WBR]
- **Midfield:** Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Attacking Midfielder (Support), Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** off the ball +2, positioning +2, anticipation +2, concentration +2 (whole team)
- **Needs:** Three reliable centre-backs; High-stamina wing-backs; Strong AMC; Complementary strikers
- **Instructions:** Slightly More Direct Passing; Pass Into Space; Counter; Regroup; Lower Line of Engagement; Standard Defensive Line
- **Avoid when:** When you need to dominate the game, or when your wing-backs cannot defend as well as they run

### Direct Counter 4-4-2

`direct_counter_442` · 4-4-2 · Cautious · Direct Counter-Attack

A compact 4-4-2 that accepts periods without the ball and attacks space quickly after regaining possession.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) *, Central Defender (Cover) *
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** off the ball +2, positioning +2, anticipation +2, concentration +2 (whole team)
- **Needs:** Pace in attack; Hold-up forward; Disciplined two banks of four; Midfield runners
- **Instructions:** Slightly More Direct Passing; Higher Tempo; Pass Into Space; Counter; Regroup; Lower Line of Engagement; Standard Defensive Line
- **Avoid when:** Against a team that sits deep and does not leave space to run into, since the counter has nothing to attack

### Fluid Counter 4-1-4-1

`fluid_counter_4141` · 4-1-4-1 · Cautious · Fluid Counter-Attack

A compact 4-1-4-1 that counters through short combinations and supporting runs rather than immediately launching long balls.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) *, Central Defender (Cover) *
- **Midfield:** Defensive Midfielder (Defend), Winger (Support) [ML/MR] ×2, Box-to-Box Midfielder (Support), Central Midfielder (Support)
- **Attack:** Advanced Forward (Attack) *

- **Leans on:** passing +2, first touch +2, positioning +2, off the ball +2 (whole team)
- **Needs:** Mobile midfield; Pacy striker; Reliable DM; Good transition decisions
- **Instructions:** Slightly Shorter Passing; Pass Into Space; Counter; Regroup; Lower Line of Engagement; Standard Defensive Line
- **Avoid when:** When you need to dominate the ball, or when you have no quick striker to run behind

### Raumdeuter Counter 4-2-3-1

`raumdeuter_counter_4231` · 4-2-3-1 DM AM Wide · Cautious · Counter-attack through space

A cautious 4-2-3-1 that defends in a compact shape and counters through a raumdeuter who finds space on the flank, an attacking midfielder and a quick striker.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full Back (Defend) ×2, Central Defender (Defend) *, Central Defender (Cover) *
- **Midfield:** Defensive Midfielder (Defend), Defensive Midfielder (Support)
- **Attack:** Raumdeuter (Attack), Attacking Midfielder (Attack), Winger (Support) [AML/AMR], Complete Forward (Attack)

- **Leans on:** off the ball +2, positioning +2, anticipation +2, concentration +2 (whole team)
- **Needs:** A raumdeuter with good movement and finishing; A quick, mobile striker; Disciplined full-backs; A dependable double pivot
- **Instructions:** Slightly More Direct Passing; Pass Into Space; Counter; Regroup; Lower Line of Engagement; Standard Defensive Line
- **Avoid when:** When you have to dominate the ball, since only two players create

### Solid 4-2-3-1

`solid_4231` · 4-2-3-1 DM AM Wide · Cautious · Compact and disciplined

A cautious 4-2-3-1 with no-nonsense full-backs, a double pivot, and attacking players who work back.

- **Goal:** Goalkeeper (Defend)
- **Defence:** No-Nonsense Full Back (Defend) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Defensive Midfielder (Support)
- **Attack:** Inside Forward (Support), Attacking Midfielder (Support), Winger (Support) [AML/AMR], Complete Forward (Support)

- **Leans on:** positioning +2, concentration +2, teamwork +2, anticipation +2 (whole team)
- **Needs:** Two defensive full-backs who clear their lines; A dependable double pivot; An inside forward who works back; A striker who holds up the ball
- **Instructions:** Lower Line of Engagement; Standard Defensive Line; Regroup; Hold Shape; Slightly More Direct Passing
- **Avoid when:** When you need to control the ball or create chances, since the full-backs and pivot offer little going forward

### Counter 3-5-2 Wing-Back

`counter_352_wingback` · 3-5-2 · Counter · 3-5-2 Counter

A back-three counter system using wing-backs for width and two forwards as immediate outlets.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Central Defender (Defend) *, Ball-Playing Defender (Defend), Central Defender (Cover) *, Wing-Back (Support) [WBL/WBR], Wing-Back (Attack) [WBL/WBR]
- **Midfield:** Defensive Midfielder (Support), Box-to-Box Midfielder (Support), Mezzala (Attack)
- **Attack:** Complete Forward (Support) *, Poacher (Attack) *

- **Leans on:** positioning +2, concentration +2, composure +2, decisions +2 (whole team)
- **Needs:** Three dependable centre-backs; High-stamina wing-backs; Transition runners; Complementary forwards
- **Instructions:** Fairly Wide; Lower Tempo; Counter; Drop Deeper Line of Engagement; Drop Off More Defensive Line
- **Avoid when:** When you need to dominate the ball, or when your wing-backs are not fit enough to cover the whole flank

### Deep Counter 5-4-1

`deep_counter_541` · 5-4-1 · Defensive · Deep block with wide outlets

A defensive 5-4-1 with three centre-backs and two defensive wing-backs, a flat midfield four with two attacking wide players, and a target man who holds the ball for them.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Wing Back (Defend) ×2, Central Defender (Defend) * ×2, Ball-Playing Defender (Defend)
- **Midfield:** Winger (Attack) [ML/MR] ×2, Central Midfielder (Defend), Central Midfielder (Support)
- **Attack:** Target Man (Support)

- **Leans on:** positioning +2, concentration +2, off the ball +2, composure +2 (whole team)
- **Needs:** Three dependable centre-backs; Two wide midfielders with pace; A target man who holds the ball up; Disciplined wing-backs
- **Instructions:** Drop Deeper Line of Engagement; Drop Off More Defensive Line; Counter; Pass Into Space; Regroup; Slower Tempo
- **Avoid when:** When you need to win rather than draw, or when you cannot get the ball to the striker, since the team will be under pressure for long periods

### Defensive 4-5-1

`defensive_451` · 4-5-1 · Defensive · Defensive 4-5-1

A conservative five-man midfield shape designed to deny central space and protect a result.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Wide Midfielder (Support) ×2, Central Midfielder (Defend) ×2
- **Attack:** Target Man (Attack)

- **Leans on:** positioning +2, concentration +2, marking +2, teamwork +2 (whole team)
- **Needs:** Hard-working midfield; Disciplined wide midfielders; Lone striker able to compete alone
- **Instructions:** Much Lower Line of Engagement; Much Deeper Defensive Line; Narrower; Slower Tempo; Regroup
- **Avoid when:** When you need to win: there is only one striker and the team will invite pressure

### Defensive 5-3-2

`defensive_532` · 5-3-2 · Defensive · Defensive 5-3-2

A deep five-defender system prioritising central protection and counter-attacking through two forwards.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Central Defender (Defend) * ×2, Ball-Playing Defender (Defend), Wing-Back (Support) [WBL/WBR] ×2
- **Midfield:** Central Midfielder (Defend) ×2, Ball-Winning Midfielder (Support) [MC]
- **Attack:** Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** positioning +2, concentration +2, marking +2, teamwork +2 (whole team)
- **Needs:** Aerially strong centre-backs; High-stamina wing-backs; Defensive midfield discipline; Direct-capable forwards
- **Instructions:** Much Lower Line of Engagement; Much Deeper Defensive Line; Narrower; Slower Tempo; Counter; Regroup
- **Avoid when:** When you need to control the ball or score: the shape is built to absorb pressure

### Low-Block 4-4-2

`lowblock_442` · 4-4-2 (Low Block) · Defensive · Low-Block 4-4-2

Two compact banks of four with two forwards retained as direct counter outlets.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Wide Midfielder (Support) ×2, Central Midfielder (Defend), Ball-Winning Midfielder (Support) [MC]
- **Attack:** Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** positioning +2, concentration +2, marking +2, teamwork +2 (whole team)
- **Needs:** Disciplined block; Wide midfield recovery; One hold-up forward; One runner
- **Instructions:** Much Lower Line of Engagement; Much Deeper Defensive Line; Narrower; Slower Tempo; Counter; Regroup
- **Avoid when:** When you need to control the ball or score, since the team will be under pressure for long periods

### Aerial 3-4-3

`aerial_343` · 3-4-3 · Positive · Wing-backs and wide target men

A 3-4-3 with attacking wing-backs supplying crosses for two wide target men and a central target man.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Central Defender (Defend) * ×2, Ball-Playing Defender (Defend), Wing-Back (Attack) [WBL/WBR] ×2
- **Midfield:** Central Midfielder (Defend), Central Midfielder (Support)
- **Attack:** Wide Target Man (Attack) [AML/AMR] ×2, Target Man (Support)

- **Leans on:** crossing +2, anticipation +2, off the ball +2, heading +2 (whole team)
- **Needs:** Two attacking wing-backs with stamina; Two tall wide forwards; A strong central target man; Three centre-backs who defend the box
- **Instructions:** Fairly Wide; More Direct Passing; Hit Early Crosses; Higher Tempo; Regroup
- **Avoid when:** Against quick counter-attackers who target the space behind the wing-backs

### Attacking 3-4-3 Wing-Back

`attacking_343` · 3-4-3 · Positive · Attacking 3-4-3

A front-foot back-three system with wing-backs stretching the pitch and a front three occupying the back line.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Central Defender (Defend) * ×2, Ball-Playing Defender (Defend), Wing-Back (Attack) [WBL/WBR] ×2
- **Midfield:** Box-to-Box Midfielder (Support), Deep-Lying Playmaker (Support) [MC]
- **Attack:** Winger (Attack) [AML/AMR], Inside Forward (Attack), Advanced Forward (Attack) *

- **Leans on:** stamina +2, anticipation +2, work rate +2, passing +2 (whole team)
- **Needs:** Mobile outside centre-backs; Elite wing-back stamina; Midfield pair with defensive range; Fast front three
- **Instructions:** Much Higher Line of Engagement; Higher Defensive Line; Shorter Passing; Play Out Of Defence; Counter-Press
- **Avoid when:** Against quick counter-attacking sides that target the space behind your wing-backs, or if your centre-backs are slow or your wing-backs tire before the hour

### Box Midfield 4-2-3-1

`box_midfield_4231` · 4-2-3-1 DM AM Wide · Positive · Inverted full-backs building a box

A possession 4-2-3-1 in which one full-back tucks into midfield to defend and the other tucks in to attack, forming a box of four in the middle.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Inverted Wing Back (Defend), Ball-Playing Defender (Defend), Central Defender (Defend) *, Inverted Wing Back (Attack)
- **Midfield:** Defensive Midfielder (Defend), Deep-Lying Playmaker (Support) [DM]
- **Attack:** Inverted Winger (Support) [AML/AMR], Attacking Midfielder (Support), Inverted Winger (Attack) [AML/AMR], Complete Forward (Support)

- **Leans on:** composure +2, technique +2, positioning +2, passing +2 (whole team)
- **Needs:** Two full-backs who can play in midfield; A deep-lying playmaker; Two inverted wide players; A sweeper keeper
- **Instructions:** Shorter Passing; Play Out Of Defence; Work Ball Into Box; Hold Shape; Standard Line of Engagement; Higher Defensive Line
- **Avoid when:** Against teams with fast wingers who use the flanks, since nobody is covering the wide areas

### Complete Wing-Back 4-2-3-1

`complete_wingback_4231` · 4-2-3-1 DM AM Wide · Positive · Wide overload

A 4-2-3-1 with two complete wing-backs who provide both the width and the creativity from the flanks, supported by playmakers inside them and a striker who drops to link play.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Complete Wing Back (Attack), Ball-Playing Defender (Defend), Central Defender (Defend) *, Complete Wing Back (Support)
- **Midfield:** Defensive Midfielder (Defend), Ball-Winning Midfielder (Support) [DM]
- **Attack:** Advanced Playmaker (Support) [AML/AMR], Advanced Playmaker (Support) [AMC], Inverted Winger (Attack) [AML/AMR], Deep-Lying Forward (Attack)

- **Leans on:** stamina +2, composure +2, technique +2, crossing +2 (whole team)
- **Needs:** Two complete wing-backs with stamina and skill; Playmakers on the left and in the middle; An inside forward who scores; A double pivot to cover the flanks
- **Instructions:** Shorter Passing; Play Out Of Defence; Work Ball Into Box; Overlap Left; Counter-Press; Higher Line of Engagement
- **Avoid when:** Against quick wingers, if your wing-backs cannot recover

### Control Possession 4-2-3-1

`control_possession_4231` · 4-2-3-1 DM AM Wide · Positive · Control Possession

A patient 4-2-3-1 that controls territory and circulates until space opens between or outside the opposition lines.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support) ×2, Ball-Playing Defender (Defend), Central Defender (Defend) *
- **Midfield:** Defensive Midfielder (Defend), Deep-Lying Playmaker (Support) [DM]
- **Attack:** Inside Forward (Attack), Advanced Playmaker (Attack) [AMC], Winger (Support) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** composure +2, decisions +2, technique +2, positioning +2 (whole team)
- **Needs:** Technically secure defenders/midfielders; High-quality distributor; Intelligent AMC; Good first touch and decisions
- **Instructions:** Shorter Passing; Lower Tempo; Play Out Of Defence; Work Ball Into Box; Hold Shape; Standard Line of Engagement; Higher Defensive Line
- **Avoid when:** Against a well-organised high press if your defenders and pivot are not calm on the ball, and when you need goals quickly: lower tempo makes it slow to change the game

### Crossing 4-3-3

`crossing_433` · 4-3-3 · Positive · Full-backs and wide target men

A 4-3-3 where attacking full-backs overlap two wide target men, and the ball is crossed early to a central target man.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full Back (Attack) ×2, Central Defender (Defend) * ×2
- **Midfield:** Central Midfielder (Defend), Central Midfielder (Support), Box-to-Box Midfielder (Support)
- **Attack:** Wide Target Man (Support) [AML/AMR] ×2, Target Man (Support)

- **Leans on:** crossing +2, stamina +2, heading +2, jumping reach +2 (whole team)
- **Needs:** Two tall wide forwards who win headers; A strong central target man; Full-backs with stamina and crossing; Central midfielders who cover the flanks
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Hit Early Crosses; Overlap Left; Overlap Right; Higher Tempo
- **Avoid when:** Against tall centre-backs who win the crosses, or against quick wingers, since both full-backs are pushed high and the space behind them is open

### False Nine 4-3-3

`false_nine_433` · 4-3-3 DM Wide · Positive · Possession with a false nine

A possession 4-3-3 whose striker drops into midfield, dragging a centre-back with him and leaving space for two inverted wingers to run into from wide.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support) ×2, Ball-Playing Defender (Defend), Central Defender (Defend) *
- **Midfield:** Defensive Midfielder (Support), Box-to-Box Midfielder (Support), Advanced Playmaker (Attack) [MC]
- **Attack:** Inverted Winger (Attack) [AML/AMR] ×2, False Nine (Support)

- **Leans on:** composure +2, technique +2, anticipation +2, stamina +2 (whole team)
- **Needs:** A forward who passes and dribbles better than he finishes; Two wingers who cut in and score; A sweeper keeper who is comfortable on the ball; Midfielders who press together
- **Instructions:** Shorter Passing; Play Out Of Defence; Work Ball Into Box; Counter-Press; Higher Line of Engagement; Higher Defensive Line
- **Avoid when:** Against a back three, or a side that keeps its centre-backs in position, since there is no gap to exploit

### Gegenpress 4-2-3-1

`gegenpress_4231` · 4-2-3-1 DM AM Wide · Positive · Gegenpress

An intense 4-2-3-1 intended to regain the ball immediately after losing it and attack before the opponent reorganises.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Wing-Back (Support) [DL/DR] ×2, Ball-Playing Defender (Defend), Central Defender (Cover) *
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Deep-Lying Playmaker (Support) [DM]
- **Attack:** Inside Forward (Attack), Shadow Striker (Attack), Winger (Attack) [AML/AMR], Pressing Forward (Attack) *

- **Leans on:** work rate +2, aggression +2, stamina +2, anticipation +2 (whole team)
- **Needs:** High work rate/stamina; Fast defenders; Sweeper keeper; Squad depth
- **Instructions:** Shorter Passing; Higher Tempo; Counter-Press; Counter; Much Higher Line of Engagement; Higher Defensive Line; Much More Urgent Pressing; Prevent Short GK Distribution
- **Avoid when:** Against teams that play long balls over the press, or when your players are tired: the press falls apart quickly and leaves large spaces

### High-Press 4-3-3

`highpress_433` · 4-3-3 (High Press) · Positive · High-Press 4-3-3

An aggressive 4-3-3 designed to regain possession high and sustain pressure in the opposition half.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Wing-Back (Support) [DL/DR], Ball-Playing Defender (Defend), Central Defender (Cover) *, Wing-Back (Attack) [DL/DR]
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Box-to-Box Midfielder (Support), Mezzala (Attack)
- **Attack:** Winger (Attack) [AML/AMR], Inside Forward (Attack), Pressing Forward (Attack) *

- **Leans on:** stamina +2, work rate +2, anticipation +2, aggression +2 (whole team)
- **Needs:** High work rate/stamina; Fast centre-backs; Sweeper keeper; Squad depth
- **Instructions:** Much Higher Line of Engagement; Much More Urgent Pressing; Higher Defensive Line; Shorter Passing; Counter-Press
- **Avoid when:** Against sides that play long over the press, or when your players lack stamina: the press cannot be kept up for 90 minutes

### Inverted Wing-Back 4-3-3

`inverted_wingback_433` · 4-3-3 DM Wide · Positive · Build-up with inverted full-backs

A 4-3-3 in which both full-backs step into midfield when the team has the ball, forming a compact central block while the wingers provide all the width.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Inverted Wing Back (Support) ×2, Ball-Playing Defender (Defend), Central Defender (Defend) *
- **Midfield:** Defensive Midfielder (Defend), Central Midfielder (Support), Mezzala (Attack)
- **Attack:** Winger (Attack) [AML/AMR], Inside Forward (Attack), Complete Forward (Attack)

- **Leans on:** composure +2, technique +2, stamina +2, passing +2 (whole team)
- **Needs:** Full-backs who pass well and read the game; Two wingers who provide width; A sweeper keeper; A reliable holding midfielder
- **Instructions:** Shorter Passing; Play Out Of Defence; Work Ball Into Box; Counter-Press; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** Against sides that attack down the flanks, since the full-backs are not covering the wide areas

### Narrow 4-2-2-2

`narrow_4222` · 4-2-2-2 · Positive · Narrow box with two forwards

A narrow 4-2-2-2 with a double pivot, two attacking midfielders in the half-spaces and two strikers, giving six players in the middle of the pitch.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Deep-Lying Playmaker (Support) [DM]
- **Attack:** Shadow Striker (Attack), Attacking Midfielder (Support), Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** first touch +2, teamwork +2, stamina +2, work rate +2 (whole team)
- **Needs:** Full-backs who provide all the width; A ball-winner and a playmaker in the pivot; A shadow striker and a creative attacking midfielder; Two complementary strikers
- **Instructions:** Fairly Narrow; Shorter Passing; Higher Tempo; Counter-Press; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** Against sides that attack down the flanks and outnumber your full-backs, and when your full-backs cannot cover a whole flank

### Positive 3-4-2-1

`positive_3421` · 3-4-2-1 · Positive · 3-4-2-1 Half-Space Attack

A modern back-three system using two central attacking midfielders to occupy the half-spaces behind a single striker.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Central Defender (Defend) *, Ball-Playing Defender (Defend), Central Defender (Cover) *, Wing-Back (Support) [WBL/WBR], Wing-Back (Attack) [WBL/WBR]
- **Midfield:** Central Midfielder (Defend), Deep-Lying Playmaker (Support) [MC]
- **Attack:** Advanced Playmaker (Attack) [AMC], Shadow Striker (Attack), Advanced Forward (Attack) *

- **Leans on:** composure +2, technique +2, stamina +2, passing +2 (whole team)
- **Needs:** Mobile centre-backs; Very strong wing-backs; Two quality AMCs; Midfield pair with defensive range
- **Instructions:** Shorter Passing; Play Out Of Defence; Counter-Press; Higher Line of Engagement; Standard Defensive Line; Work Ball Into Box
- **Avoid when:** Against sides with quick wingers who target the space behind the wing-backs, or if your centre-backs are not comfortable defending wide

### Positive 4-2-3-1 Wide

`positive_4231` · 4-2-3-1 DM AM Wide · Positive · Positive 4-2-3-1

A proactive 4-2-3-1 using a double pivot behind three attacking midfielders and one striker.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Deep-Lying Playmaker (Support) [DM]
- **Attack:** Inside Forward (Attack), Attacking Midfielder (Support), Winger (Attack) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** first touch +2, technique +2, stamina +2, passing +2 (whole team)
- **Needs:** Secure double pivot; Quality AMC; Complementary wide attackers; Mobile striker
- **Instructions:** Shorter Passing; Play Out Of Defence; Higher Tempo; Counter-Press; Counter; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** When you have no ball-winner to pair with a playmaker, or against a team with three central midfielders who outnumber your pivot

### Positive 4-3-1-2 Narrow

`positive_4312_narrow` · 4-3-1-2 · Positive · Narrow Combination Play

A narrow 4-3-1-2 using three central midfielders and an advanced playmaker behind two complementary forwards.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Wing-Back (Attack) [DL/DR], Central Defender (Defend) *, Ball-Playing Defender (Defend), Wing-Back (Support) [DL/DR]
- **Midfield:** Central Midfielder (Defend), Deep-Lying Playmaker (Support) [MC], Box-to-Box Midfielder (Support)
- **Attack:** Advanced Playmaker (Attack) [AMC], Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** stamina +2, crossing +2, first touch +2, teamwork +2 (whole team)
- **Needs:** Excellent attacking full-backs; Three capable central midfielders; Creative AMC; Complementary strikers
- **Instructions:** Fairly Narrow; Shorter Passing; Work Ball Into Box; Overlap Left; Overlap Right; Counter-Press; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against sides that attack the flanks, since your full-backs are the only wide players and will be stretched

### Positive 4-3-3 DM Wide

`positive_433dm` · 4-3-3 DM Wide · Positive · Positive 4-3-3 DM

A modern 4-3-3 with a holder, two eights and complementary wide forwards.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Deep-Lying Playmaker (Support) [MC], Central Midfielder (Support)
- **Attack:** Inside Forward (Attack), Winger (Attack) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** composure +2, technique +2, stamina +2, passing +2 (whole team)
- **Needs:** Reliable DM; Progressive midfielders; Wide forwards with end product; Mobile striker
- **Instructions:** Shorter Passing; Play Out Of Defence; Work Ball Into Box; Counter-Press; Counter; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** When you have no ball-winner to hold the midfield, or against a team that pushes wide players onto your full-backs

### Possession 4-1-4-1

`possession_4141` · 4-1-4-1 · Positive · Possession

A lower-risk possession structure with a playmaker at the base and four midfielders offering short passing options ahead.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support) ×2, Ball-Playing Defender (Defend), Central Defender (Defend) *
- **Midfield:** Deep-Lying Playmaker (Support) [DM], Wide Midfielder (Support), Central Midfielder (Support), Box-to-Box Midfielder (Support), Winger (Support) [ML/MR]
- **Attack:** Deep-Lying Forward (Support) *

- **Leans on:** composure +2, decisions +2, technique +2, positioning +2 (whole team)
- **Needs:** Technically reliable midfield; Linking striker; Ball-playing defender; Good first touch/decisions
- **Instructions:** Shorter Passing; Lower Tempo; Play Out Of Defence; Work Ball Into Box; Hold Shape; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** When you need goals quickly, or when your defenders and midfield are uncomfortable on the ball

### High-Press 4-4-2

`pressing_442` · 4-4-2 · Positive · Two pressing forwards

A 4-4-2 that presses from the front with two pressing forwards, a ball-winning midfielder and a box-to-box runner, and hard-working wide midfielders.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Wide Midfielder (Support) ×2, Ball-Winning Midfielder (Support) [MC], Box-to-Box Midfielder (Support)
- **Attack:** Pressing Forward (Defend), Pressing Forward (Attack)

- **Leans on:** stamina +2, work rate +2, aggression +2, anticipation +2 (whole team)
- **Needs:** Two forwards with high work rate and stamina; A ball-winning midfielder; Wide midfielders who work hard; Fit players who can press for the whole game
- **Instructions:** Higher Line of Engagement; Much More Urgent Pressing; Counter-Press; Slightly More Direct Passing; Higher Tempo; Standard Defensive Line
- **Avoid when:** Against sides that play long over the press, or when your players are tired: a two-man press leaves gaps behind it if it is beaten

### Trequartista 4-3-1-2

`trequartista_4312` · 4-3-1-2 · Positive · One free creator, everyone else works

A narrow 4-3-1-2 with one trequartista who roams freely behind two strikers, and a hard-working midfield three plus a pressing forward to cover for him.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Support) [MC], Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Trequartista (Attack) [AMC], Pressing Forward (Support), Advanced Forward (Attack) *

- **Leans on:** first touch +2, teamwork +2, technique +2, composure +2 (whole team)
- **Needs:** An exceptional creative player with vision and technique; A pressing forward with high work rate; A ball-winning midfielder; Full-backs who provide all the width
- **Instructions:** Fairly Narrow; Shorter Passing; Work Ball Into Box; Counter-Press; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against teams that man-mark the playmaker or overload the flanks, since the full-backs are your only wide players

### Trequartista 4-4-2

`trequartista_442` · 4-4-2 · Positive · Free creator up front

A 4-4-2 in which one striker is a trequartista who drops off and creates, paired with a pressing forward who does the running.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Wide Midfielder (Support) ×2, Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Trequartista (Attack) [ST], Pressing Forward (Support)

- **Leans on:** crossing +2, pace +2, composure +2, decisions +2 (whole team)
- **Needs:** A creative forward who is better at creating than finishing; A pressing forward partner; Wide midfielders who work back; A box-to-box midfielder
- **Instructions:** Fairly Wide; Work Ball Into Box; Counter-Press; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against sides that overload the midfield, since the trequartista does not track back

### Vertical Tiki-Taka 4-3-3 DM

`vertical_tikitaka_433dm` · 4-3-3 DM Wide · Positive · Vertical Tiki-Taka

Short combinations are used to progress quickly rather than simply retain possession, with runners attacking spaces created by circulation.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Wing-Back (Support) [DL/DR], Ball-Playing Defender (Defend), Central Defender (Cover) *, Full-Back (Support)
- **Midfield:** Deep-Lying Playmaker (Support) [DM], Box-to-Box Midfielder (Support), Mezzala (Attack)
- **Attack:** Inside Forward (Attack), Winger (Support) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** anticipation +2, first touch +2, technique +2, pace +2 (whole team)
- **Needs:** Excellent first touch/passing; Mobile midfield; Fast attacking movement; Quick defenders
- **Instructions:** Shorter Passing; Play Out Of Defence; Higher Tempo; Pass Into Space; Counter-Press; Counter; Higher Line of Engagement; Higher Defensive Line
- **Avoid when:** Against sides that press well, or when your defenders are not comfortable on the ball or with a high line

### Wide Playmakers 4-3-3

`wide_playmakers_433` · 4-3-3 DM Wide · Positive · Roaming creators from wide

A 4-3-3 with two creative players starting wide, one a trequartista who roams and one an advanced playmaker, supported by a pressing forward and a strong midfield.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support) ×2, Ball-Playing Defender (Defend), Central Defender (Defend) *
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Box-to-Box Midfielder (Support), Central Midfielder (Support)
- **Attack:** Trequartista (Attack) [AML/AMR], Advanced Playmaker (Attack) [AML/AMR], Pressing Forward (Attack)

- **Leans on:** stamina +2, work rate +2, technique +2, composure +2 (whole team)
- **Needs:** Two creative players who can play wide; A pressing forward with high work rate; A ball-winning midfielder; Full-backs who provide the width
- **Instructions:** Shorter Passing; Work Ball Into Box; Counter-Press; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** Against teams that press hard on the full-backs, since the full-backs supply all the width

### Wing Play 4-4-2

`wing_play_442` · 4-4-2 · Positive · Wing Play

A width-first 4-4-2 designed to stretch the opponent and generate repeated crossing opportunities for two forwards.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Deep-Lying Playmaker (Support) [MC]
- **Attack:** Target Man (Attack), Advanced Forward (Attack) *

- **Leans on:** crossing +2, stamina +2, pace +2, heading +2 (whole team)
- **Needs:** Good crossing; Fast wide players; Stamina at full-back; Aerially strong striker
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Hit Early Crosses; Overlap Left; Overlap Right; Higher Tempo; Counter
- **Avoid when:** Against tall centre-backs who win the crosses, or when your full-backs cannot get back, since the flanks are left open

`*` marks a slot whose role the optimiser may swap for a declared alternative.
