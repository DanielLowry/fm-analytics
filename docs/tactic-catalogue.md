# Tactic catalogue

**Generated — do not edit.** Run `uv run python tools/tactic_index.py`
after changing any tactic. Each tactic's full detail (per-slot reasoning,
per-instruction rationale, balance requirements) lives in its own file under
`src/fm_analytics/analytics/data/tactics/`.

52 tactics, 84 roles.

## At a glance

| Tactic | Shape | Mentality | Leans on | Use it when |
| --- | --- | --- | --- | --- |
| [Attacking 4-3-3](#attacking-433) | 4-3-3 (Attacking) | Attacking | stamina, anticipation, work rate, first touch | Against sides that defend deep and cannot get past your press, or when you are clearly the stronger team and want to pin them back |
| [Balanced 4-1-2-1-2 Diamond](#balanced-41212-diamond) | 4-1-2-1-2 DM Narrow | Balanced | stamina, crossing, work rate, acceleration, positioning, anticipation, decisions, teamwork, off the ball, passing, first touch, vision, technique, pace | When your strongest players are central, you can field two complementary strikers, and your wide defenders are capable of supplying the width the shape otherwise lacks |
| [Balanced 4-1-4-1](#balanced-4141) | 4-1-4-1 | Balanced | teamwork, positioning, concentration, stamina, passing, decisions, work rate, off the ball, anticipation, acceleration | As a safe default when you want control without committing many players forward, or away from home against a stronger side |
| [Balanced 4-3-3 DM Wide](#balanced-433dm) | 4-3-3 DM Wide | Balanced | teamwork, positioning, concentration, jumping reach, pace, anticipation, acceleration, stamina, work rate, crossing, decisions, passing, first touch, off the ball, finishing, dribbling | As a stable lower-league default when you have one good striker, a dependable holding midfielder and usable wide attackers |
| [Balanced 4-4-1-1](#balanced-4411) | 4-4-1-1 | Balanced | pace, off the ball, crossing, anticipation | When you have one good striker and a creative player who is not a natural second striker, or as a steady all-round system for a mixed squad |
| [Balanced 4-4-2](#balanced-442) | 4-4-2 | Balanced | teamwork, positioning, concentration, stamina, crossing, pace, acceleration, work rate, off the ball, anticipation | As a solid default, or when you have two good strikers and two decent wingers |
| [Ball-Winning Counter 4-3-3 DM](#ball-winning-counter-433dm) | 4-3-3 DM Wide | Balanced | teamwork, positioning, concentration, jumping reach, pace, anticipation, acceleration, stamina, work rate, crossing, decisions, off the ball, dribbling, finishing, tackling, passing, first touch, vision | When a two-man midfield is being outnumbered and you have a recruitable MC ball-winner, a disciplined holding DM, one dependable passer and three forward threats comfortable in their positions |
| [Enganche 4-2-3-1](#enganche-4231) | 4-2-3-1 DM AM Wide | Balanced | kicking, decisions, positioning, concentration, jumping reach, pace, anticipation, acceleration, stamina, work rate, crossing, aggression, teamwork, off the ball, first touch, passing, vision, technique, flair, composure, strength, heading, finishing | When one attacking midfielder is clearly your best creator, a striker can provide a genuine aerial/hold-up outlet, and the rest of the side is willing to carry the defensive and running load around them |
| [Route One 4-4-2](#route-one-442) | 4-4-2 | Balanced | teamwork, kicking, positioning, concentration, crossing, stamina, pace, work rate, anticipation, strength, aggression, jumping reach, heading, bravery, first touch, off the ball, acceleration | When you have a big target man and a quick second striker, but weak technical midfielders |
| [Vertical 4-4-2](#vertical-442) | 4-4-2 | Balanced | teamwork, positioning, concentration, jumping reach, stamina, work rate, crossing, pace, acceleration, off the ball, anticipation, decisions, passing, first touch, strength | As the primary lower-league default when you want a compact 4-4-2 with quick vertical progression |
| [Counter 3-4-1-2](#counter-3412) | 3-4-1-2 | Cautious | off the ball, positioning, anticipation, concentration | Against stronger sides that will have most of the ball, or when your squad has quick forwards and dependable centre-backs |
| [Direct Counter 4-4-2](#direct-counter-442) | 4-4-2 | Cautious | teamwork, positioning, concentration, anticipation, stamina, pace, acceleration, off the ball, crossing, work rate | Against a stronger or possession-based team that will leave space behind its defence, when you have quick wingers and forwards |
| [Fluid Counter 4-1-4-1](#fluid-counter-4141) | 4-1-4-1 | Cautious | teamwork, positioning, concentration, anticipation, stamina, passing, decisions, first touch, work rate, off the ball, pace, acceleration | Against stronger or possession-based sides when you have a good holding midfielder, quick wingers and a mobile lone striker |
| [Raumdeuter Counter 4-2-3-1](#raumdeuter-counter-4231) | 4-2-3-1 DM AM Wide | Cautious | off the ball, positioning, anticipation, concentration | Against a stronger team that will leave space behind its full-backs, when you have a smart off-the-ball player who scores goals |
| [Solid 4-2-3-1](#solid-4231) | 4-2-3-1 DM AM Wide | Cautious | decisions, kicking, positioning, concentration, marking, tackling, strength, anticipation, jumping reach, pace, acceleration, teamwork, passing, first touch, work rate, stamina, off the ball, dribbling, crossing, heading | Away to a stronger side, when protecting a result, or whenever the priority is reducing transition risk while retaining enough of an outlet to stop the team becoming permanently pinned back |
| [Counter 3-5-2 Wing-Back](#counter-352-wingback) | 3-5-2 | Counter | positioning, concentration, composure, decisions | Against stronger opponents who will dominate the ball, or when you have good wing-backs and forwards but a weaker midfield |
| [Deep Counter 5-4-1](#deep-counter-541) | 5-4-1 | Defensive | kicking, decisions, positioning, concentration, anticipation, jumping reach, pace, acceleration, passing, first touch, technique, composure, tackling, work rate, stamina, off the ball, dribbling, crossing, teamwork, strength, heading | When protecting a lead or playing away against a substantially stronger side, especially when you have a strong aerial striker and quick wide players who can turn clearances into genuine counters |
| [Defensive 4-5-1](#defensive-451) | 4-5-1 | Defensive | teamwork, positioning, concentration, marking, anticipation, tackling, work rate, stamina, jumping reach, strength, heading, bravery | Protecting a lead late in a game, or away against a much stronger side where a draw is a good result |
| [Defensive 5-3-2](#defensive-532) | 5-3-2 | Defensive | positioning, concentration, marking, teamwork | Protecting a lead, or against stronger opponents who will have most of the ball |
| [Low-Block 4-4-2](#lowblock-442) | 4-4-2 (Low Block) | Defensive | teamwork, positioning, concentration, marking, anticipation, work rate, stamina, tackling, off the ball | Protecting a lead, or away against a stronger side |
| [No-Nonsense 5-3-2](#no-nonsense-532) | 5-3-2 | Defensive | command of area, aerial reach, handling, heading, jumping reach, positioning, marking, concentration, strength, anticipation, pace, acceleration, aggression, bravery, stamina, work rate, teamwork, first touch, off the ball | When protecting a result against stronger opposition, particularly with dominant aerial centre-backs and a forward able to hold direct passes |
| [Aerial 3-4-3](#aerial-343) | 3-4-3 | Positive | crossing, anticipation, off the ball, heading | When you have two wing-backs who cross well and three tall forwards, especially against a back four that struggles with aerial balls |
| [Aggressive Playing 3-4-3](#aggressive-playing-343) | 3-4-3 | Positive | anticipation, pace, composure, passing, acceleration, concentration, positioning | When your centre-backs are quick, brave and technically secure, and you want to dominate territory with a back three |
| [Attacking 3-4-3 Wing-Back](#attacking-343) | 3-4-3 | Positive | stamina, anticipation, work rate, passing | When you are clearly the stronger side and expect the opponent to sit deep, or you need goals late |
| [Attacking 4-2-4](#attacking-424) | 4-2-4 | Positive | kicking, decisions, anticipation, positioning, concentration, pace, acceleration, stamina, work rate, aggression, passing, first touch, vision, off the ball, dribbling, finishing, crossing, teamwork | Situationally rather than as a default: when you want to attack an opponent aggressively, particularly a back line that can be stretched or wide areas that can be attacked, or when you are chasing a game and need more players on the opposition back line without a wholesale tactical rewrite |
| [Box Midfield 4-2-3-1](#box-midfield-4231) | 4-2-3-1 DM AM Wide | Positive | composure, technique, positioning, passing | When you want to control the middle of the pitch against a side that defends in a narrow block, and your full-backs are comfortable on the ball |
| [Complete Wing-Back 4-2-3-1](#complete-wingback-4231) | 4-2-3-1 DM AM Wide | Positive | stamina, composure, technique, crossing | When your two full-backs are among your best attacking players, or against a team that defends narrowly and leaves the flanks open |
| [Control Possession 4-2-3-1](#control-possession-4231) | 4-2-3-1 DM AM Wide | Positive | composure, decisions, technique, positioning | When your squad is technically better than the opponent's and you expect them to sit deep, or when you want to protect a lead by keeping the ball |
| [Crossing 4-3-3](#crossing-433) | 4-3-3 | Positive | crossing, stamina, heading, jumping reach | When you have two tall forwards who can play wide, a strong central striker, and full-backs who can cross, especially against defences that are short or slow to turn |
| [False Nine 4-3-3](#false-nine-433) | 4-3-3 DM Wide | Positive | composure, technique, anticipation, stamina | Against a back four that defends deep and narrow, when you have a striker who is a better passer than a finisher and two wingers who can score |
| [Front-Foot 4-4-2](#front-foot-442) | 4-4-2 | Positive | stamina, work rate, aggression, anticipation, pace, acceleration, concentration | When you have an aggressive, aerial stopper, a quick covering partner and forwards able to sustain the first press |
| [Gegenpress 4-2-3-1](#gegenpress-4231) | 4-2-3-1 DM AM Wide | Positive | work rate, aggression, stamina, anticipation | When you have fit, aggressive players with high work rate and stamina, and you want to play in the opponent's half against sides that struggle to play out from the back |
| [High-Press 4-3-3](#highpress-433) | 4-3-3 (High Press) | Positive | stamina, work rate, anticipation, aggression | When you have fit, energetic players and want to play in the opponent's half, especially against sides that build slowly from the back |
| [Inverted Wide 4-4-2](#inverted-wide-442) | 4-4-2 | Positive | stamina, work rate, anticipation, positioning, tackling, marking, acceleration, dribbling, off the ball | When you have a natural flat inverted winger, an energetic attacking full-back and a wide defensive specialist on the opposite side |
| [Inverted Wing-Back 4-3-3](#inverted-wingback-433) | 4-3-3 DM Wide | Positive | composure, technique, stamina, passing | When your full-backs are better passers than crossers, you want to dominate the centre of the pitch, and you have two wingers who are happy to stay wide |
| [Narrow 4-2-2-2](#narrow-4222) | 4-2-2-2 | Positive | first touch, teamwork, stamina, work rate | When your best players are central and you lack wingers, especially against a team with two central midfielders who will be overrun |
| [Positional Play 4-3-3](#positional-play-433) | 4-3-3 | Positive | composure, decisions, technique, passing, positioning, teamwork | When you have a composed central organiser, a hard-working channel midfielder, and a technical half-space player |
| [Positive 3-4-2-1](#positive-3421) | 3-4-2-1 | Positive | composure, technique, stamina, passing | When you have two good creative players and a wing-back pair who can cover the flanks, especially against a back four that has no midfielder in the half-spaces |
| [Positive 4-2-3-1 Wide](#positive-4231) | 4-2-3-1 DM AM Wide | Positive | decisions, kicking, first touch, positioning, concentration, anticipation, passing, pace, acceleration, stamina, work rate, teamwork, vision, technique, off the ball, dribbling, finishing, crossing | As a proactive default when you have a good attacking midfielder, two complementary wide attackers, a striker who can lead pressure and enough quality in the double pivot to build through pressure |
| [Positive 4-3-1-2 Narrow](#positive-4312-narrow) | 4-3-1-2 | Positive | stamina, crossing, first touch, teamwork | When your best players are central and you lack wingers, or against a team with only two central midfielders that you can outnumber |
| [Positive 4-3-3 DM Wide](#positive-433dm) | 4-3-3 DM Wide | Positive | decisions, kicking, first touch, positioning, concentration, anticipation, passing, pace, acceleration, stamina, work rate, teamwork, vision, technique, off the ball, dribbling, finishing, crossing | As an all-round positive system when you have a reliable holding midfielder, two competent passers ahead of him, complementary wide threats and a hard-working striker who can lead the counter-press |
| [Positive Ball-Winning 4-3-3 DM](#positive-ball-winning-433dm) | 4-3-3 DM Wide | Positive | decisions, kicking, first touch, positioning, concentration, anticipation, passing, pace, acceleration, stamina, work rate, teamwork, vision, technique, off the ball, dribbling, finishing, tackling, crossing | When you want a positive possession 4-3-3 with an MC ball-winner and also have a secure holder, a capable playmaker, a supporting winger and a left wing-back who can sustain attacking runs |
| [Possession 4-1-4-1](#possession-4141) | 4-1-4-1 | Positive | composure, decisions, technique, positioning | When your squad is technically better than the opponent's and you want patient control with a linking striker and a right winger capable of turning possession into chances |
| [High-Press 4-4-2](#pressing-442) | 4-4-2 | Positive | teamwork, stamina, work rate, positioning, anticipation, concentration, aggression, off the ball | When you have fit, energetic forwards and midfielders and want to press the opponent's build-up, especially against a side that plays short from the back |
| [Roaming Playmaker 4-3-3](#roaming-playmaker-433) | 4-3-3 | Positive | stamina, work rate, technique, passing, decisions, composure | When a roaming, high-stamina playmaker is one of your best players and you can protect him with a disciplined ball-winner |
| [Trequartista 4-3-1-2](#trequartista-4312) | 4-3-1-2 | Positive | first touch, teamwork, technique, composure | When you have one player of clearly superior creativity who is not suited to a fixed role, and a striker partner who will run and press for him |
| [Trequartista 4-4-2](#trequartista-442) | 4-4-2 | Positive | teamwork, positioning, concentration, stamina, work rate, off the ball, vision, technique, first touch, decisions, flair, composure, passing, aggression, anticipation | When you have a creative forward who is not a natural goalscorer, and a partner with pace and work rate |
| [Vertical Tiki-Taka 4-3-3 DM](#vertical-tikitaka-433dm) | 4-3-3 DM Wide | Positive | anticipation, first touch, technique, pace | When you have good passers and quick forwards, against teams that sit in a mid-block and leave space behind their line |
| [Wide Control 4-1-4-1](#wide-control-4141) | 4-1-4-1 | Positive | composure, decisions, technique, passing, vision, first touch, dribbling, off the ball | When your best technical players are natural ML/MR positions and you want a controlled, low-risk way to use them |
| [Wide Creator 4-4-2](#wide-creator-442) | 4-4-2 | Positive | stamina, work rate, teamwork, passing, vision, technique, first touch, positioning, tackling | When one of your best creators is a natural ML/MR rather than an attacking winger, and you have a tireless defensive wide player to balance him |
| [Wide Playmakers 4-3-3](#wide-playmakers-433) | 4-3-3 DM Wide | Positive | decisions, first touch, passing, stamina, work rate, crossing, pace, technique, composure, positioning, concentration, anticipation, acceleration, teamwork, off the ball, vision, flair, finishing | When your best attacking players are creators rather than conventional touchline wingers and your left full-back and right wing-back have enough engine to supply width for them |
| [Wing Play 4-4-2](#wing-play-442) | 4-4-2 | Positive | teamwork, positioning, concentration, stamina, crossing, work rate, pace, acceleration, dribbling, passing, vision, first touch, decisions, jumping reach, strength, heading, bravery, off the ball, anticipation | When you have two good wingers, full-backs with stamina, and a striker who wins headers |

## Each tactic

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

A compact narrow 4-1-2-1-2 built around central combinations, a holding midfielder, a distributor, a midfield runner and an attacking midfielder, with the wide defenders supplying almost all of the width.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Wing-Back (Support) [DL/DR] * ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Box-to-Box Midfielder (Support), Deep-Lying Playmaker (Support) [MC]
- **Attack:** Attacking Midfielder (Support), Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** stamina +2, crossing +2, work rate +1, acceleration +1 (DL, DR; Wing-Back (Support) [DL/DR], Full-Back (Support)); positioning +2, anticipation +1, decisions +1, teamwork +1 (DM; Defensive Midfielder (Defend)); work rate +2, stamina +2, off the ball +2, teamwork +1 (MC; Box-to-Box Midfielder (Support)); passing +2, first touch +2, vision +2, decisions +1 (MC; Deep-Lying Playmaker (Support) [MC]); first touch +2, vision +2, passing +2, decisions +1, technique +1 (AMC; Attacking Midfielder (Support)); first touch +2, passing +1, decisions +1, teamwork +1 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); off the ball +2, acceleration +2, anticipation +2, pace +1 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1 (ST; Poacher (Attack))
- **Expects at least (tapers below):** stamina 9 (DL, DR; Wing-Back (Support) [DL/DR], Full-Back (Support)); crossing 8 (DL, DR; Wing-Back (Support) [DL/DR], Full-Back (Support)); positioning 9 (DM; Defensive Midfielder (Defend)); work rate 9 (MC; Box-to-Box Midfielder (Support)); stamina 9 (MC; Box-to-Box Midfielder (Support)); off the ball 8 (MC; Box-to-Box Midfielder (Support)); passing 9 (MC; Deep-Lying Playmaker (Support) [MC]); first touch 8 (MC; Deep-Lying Playmaker (Support) [MC]); vision 8 (MC; Deep-Lying Playmaker (Support) [MC]); first touch 9 (AMC; Attacking Midfielder (Support)); passing 8 (AMC; Attacking Midfielder (Support)); vision 8 (AMC; Attacking Midfielder (Support)); decisions 8 (AMC; Attacking Midfielder (Support)); first touch 8 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 9 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack))
- **Needs:** Wide defenders capable of providing the formation's width repeatedly; A disciplined holding midfielder at the base of the diamond; A reliable deep distributor and an energetic midfield runner; An attacking midfielder comfortable receiving and creating in congested central areas; A linking forward paired with a striker who threatens the space beyond
- **Instructions:** Fairly Narrow; Shorter Passing; Counter; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** When the opposition can isolate your wide defenders repeatedly, when your wide defenders cannot cover the flank athletically, or when your central players are not secure enough to combine in congested areas

### Balanced 4-1-4-1

`balanced_4141` · 4-1-4-1 · Balanced · Balanced 4-1-4-1

A compact 4-1-4-1 with a dedicated screen behind a four-man midfield.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) *, Ball-Playing Defender (Defend)
- **Midfield:** Defensive Midfielder (Defend), Wide Midfielder (Support) ×2, Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Poacher (Attack) *

- **Leans on:** teamwork +1 (whole team); positioning +1, concentration +1 (DC); stamina +1, teamwork +1, positioning +1 (DL, DR); positioning +2, teamwork +2, passing +2, decisions +1, concentration +1 (DM); work rate +2, stamina +2, passing +1, teamwork +1, positioning +1 (MC); work rate +2, teamwork +2, stamina +1 (ML, MR); off the ball +2, anticipation +2, acceleration +1 (ST)
- **Expects at least (tapers below):** positioning 7 (DM); passing 7 (DM); work rate 7 (MC); stamina 7 (MC); work rate 7 (ML, MR); teamwork 7 (ML, MR); off the ball 7 (ST)
- **Needs:** Disciplined holding midfielder who can also circulate the ball; Hard-working wide midfielders who recover into shape; One central midfielder able to cover ground and support the lone striker; Compact defensive spacing; A self-sufficient striker with good movement
- **Instructions:** Standard Line of Engagement; Standard Defensive Line; Shorter Passing; Regroup
- **Avoid when:** When you need to chase a goal: there is a single striker and no creative attacking midfielder to feed him

### Balanced 4-3-3 DM Wide

`balanced_433dm` · 4-3-3 DM Wide · Balanced · Balanced 4-3-3 DM

A simple lower-league 4-3-3 with a dedicated holding midfielder, natural width on one side and two additional runners supporting a mobile striker.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Central Midfielder (Support) *, Central Midfielder (Attack)
- **Attack:** Inside Forward (Attack), Winger (Support) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** teamwork +1 (whole team); positioning +2, concentration +2, jumping reach +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); stamina +1, work rate +1, positioning +1, crossing +1 (DL, DR; Full-Back (Support)); positioning +2, concentration +1, anticipation +1, decisions +1, teamwork +1 (DM; Defensive Midfielder (Defend)); passing +1, first touch +1, decisions +1, teamwork +1 (MC; Central Midfielder (Support)); work rate +2, stamina +2, off the ball +2, anticipation +1 (MC; Box-to-Box Midfielder (Support)); off the ball +2, anticipation +2, stamina +1, finishing +1 (MC; Central Midfielder (Attack)); acceleration +2, pace +2, off the ball +2, dribbling +1, finishing +1 (AML; Inside Forward (Attack)); crossing +2, pace +2, acceleration +2, dribbling +1, work rate +1 (AMR; Winger (Support) [AML/AMR]); acceleration +2, pace +2, off the ball +2, anticipation +2 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1 (ST; Poacher (Attack))
- **Expects at least (tapers below):** positioning 7 (DC; Central Defender (Defend)); concentration 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); acceleration 7 (DC; Central Defender (Cover)); stamina 7 (DL, DR; Full-Back (Support)); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 7 (DM; Defensive Midfielder (Defend)); decisions 7 (DM; Defensive Midfielder (Defend)); passing 7 (MC; Central Midfielder (Support)); first touch 7 (MC; Central Midfielder (Support)); work rate 8 (MC; Box-to-Box Midfielder (Support)); stamina 8 (MC; Box-to-Box Midfielder (Support)); off the ball 8 (MC; Central Midfielder (Attack)); stamina 7 (MC; Central Midfielder (Attack)); acceleration 8 (AML; Inside Forward (Attack)); pace 8 (AML; Inside Forward (Attack)); off the ball 8 (AML; Inside Forward (Attack)); finishing 7 (AML; Inside Forward (Attack)); crossing 7 (AMR; Winger (Support) [AML/AMR]); pace 7 (AMR; Winger (Support) [AML/AMR]); acceleration 7 (AMR; Winger (Support) [AML/AMR]); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack)); acceleration 7 (ST; Poacher (Attack))
- **Needs:** A disciplined holding midfielder who protects the centre and keeps the structure intact; One reliable linking central midfielder and one genuine forward runner from midfield; An inside forward who supplies secondary goal threat; A wide player capable of preserving width and delivering from the opposite side; A mobile lone striker who threatens the space behind
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Regroup; Counter; Distribute Quickly; Distribute To Flanks; Take Long Kicks; Standard Line of Engagement; Standard Defensive Line
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

- **Leans on:** teamwork +2 (whole team); positioning +2, concentration +2 (DC); stamina +2, positioning +1, crossing +1 (DL, DR); crossing +2, pace +2, acceleration +2 (ML, MR); work rate +2, positioning +2 (MC); off the ball +2, anticipation +2, acceleration +2 (ST)
- **Expects at least (tapers below):** positioning 7 (DC); concentration 7 (DC); crossing 7 (ML, MR); work rate 7 (MC); off the ball 7 (ST)
- **Needs:** Two complementary strikers, with one linking and one attacking space; Wingers with enough crossing to supply the front two; A disciplined central midfielder paired with a reliable support midfielder; Centre-backs with basic positional discipline; Full-backs able to support without being the main attacking outlet
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Regroup; Counter; Distribute To Flanks; Take Long Kicks; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against a team with three central midfielders who will pass through the middle, since your two are outnumbered

### Ball-Winning Counter 4-3-3 DM

`ball_winning_counter_433dm` · 4-3-3 DM Wide · Balanced · Ball-winning counter 4-3-3 DM

A balanced, more direct 4-3-3 with a dedicated holding midfielder behind a ball-winner and one passing outlet, releasing three forward threats after regains.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Deep-Lying Playmaker (Support) [MC], Ball-Winning Midfielder (Support) [MC]
- **Attack:** Inside Forward (Attack), Winger (Attack) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** teamwork +1 (whole team); positioning +2, concentration +2, jumping reach +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); stamina +1, work rate +1, positioning +1, crossing +1 (DL, DR; Full-Back (Support)); positioning +2, concentration +1, anticipation +1, decisions +1, teamwork +1 (DM; Defensive Midfielder (Defend)); acceleration +2, pace +2, off the ball +2, dribbling +1, finishing +1 (AML; Inside Forward (Attack)); acceleration +2, pace +2, off the ball +2, anticipation +2 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1 (ST; Poacher (Attack)); work rate +2, stamina +2, tackling +1, anticipation +1, decisions +1 (MC; Ball-Winning Midfielder (Support) [MC]); passing +2, first touch +1, vision +1, decisions +2 (MC; Deep-Lying Playmaker (Support) [MC]); acceleration +2, pace +2, crossing +2, off the ball +1 (AMR; Winger (Attack) [AML/AMR]); work rate +2, stamina +2, off the ball +2, acceleration +1 (ST; Pressing Forward (Attack))
- **Expects at least (tapers below):** positioning 7 (DC; Central Defender (Defend)); concentration 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); acceleration 8 (DC; Central Defender (Cover)); stamina 7 (DL, DR; Full-Back (Support)); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 7 (DM; Defensive Midfielder (Defend)); decisions 7 (DM; Defensive Midfielder (Defend)); acceleration 10 (AML; Inside Forward (Attack)); pace 10 (AML; Inside Forward (Attack)); off the ball 8 (AML; Inside Forward (Attack)); finishing 7 (AML; Inside Forward (Attack)); acceleration 10 (ST; Advanced Forward (Attack)); pace 10 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack)); acceleration 10 (ST; Poacher (Attack)); work rate 8 (MC; Ball-Winning Midfielder (Support) [MC]); stamina 8 (MC; Ball-Winning Midfielder (Support) [MC]); tackling 8 (MC; Ball-Winning Midfielder (Support) [MC]); passing 7 (MC; Ball-Winning Midfielder (Support) [MC]); first touch 7 (MC; Ball-Winning Midfielder (Support) [MC]); passing 8 (MC; Deep-Lying Playmaker (Support) [MC]); first touch 8 (MC; Deep-Lying Playmaker (Support) [MC]); decisions 8 (MC; Deep-Lying Playmaker (Support) [MC]); vision 8 (MC; Deep-Lying Playmaker (Support) [MC]); pace 10 (AMR; Winger (Attack) [AML/AMR]); acceleration 10 (AMR; Winger (Attack) [AML/AMR]); crossing 7 (AMR; Winger (Attack) [AML/AMR]); work rate 8 (ST; Pressing Forward (Attack)); stamina 8 (ST; Pressing Forward (Attack)); off the ball 8 (ST; Pressing Forward (Attack)); acceleration 10 (ST; Pressing Forward (Attack)); pace 10 (ST; Pressing Forward (Attack)); pace 10 (ST; Poacher (Attack)); pace 7 (DC; Central Defender (Defend)); pace 8 (DL, DR; Full-Back (Support)); acceleration 7 (DC; Central Defender (Defend)); acceleration 8 (DL, DR; Full-Back (Support))
- **Needs:** A positionally disciplined DM who protects the centre when the ball-winner chases; A BWM with tackling, anticipation, work rate and stamina, plus enough passing and first touch to return the ball securely; One DLP with reliable passing, touch, decisions and vision to turn regains into attacks; An inside forward, attacking winger and lone striker with the movement, pace and acceleration to reach passes into space and supply the box; every permitted striker profile must provide this threat; Full-backs who support behind the wide forwards and centre-backs comfortable defending a standard line, with enough pace and acceleration across the back four to recover when exposed
- **Instructions:** Slightly More Direct Passing; Higher Tempo; Pass Into Space; Regroup; Counter; Distribute Quickly; Distribute To Flanks; Take Long Kicks; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** When the holder follows the ball-winner out of the centre, the DLP cannot move regains forward, or the front three lack the movement, pace and acceleration to exploit space, or the back four cannot recover when exposed

### Enganche 4-2-3-1

`enganche_4231` · 4-2-3-1 DM AM Wide · Balanced · Classic number ten

A 4-2-3-1 built around one specialist number ten who is protected from defensive work by a hard-working double pivot, with genuine width and an aerial outlet ahead of him.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Defensive Midfielder (Defend)
- **Attack:** Winger (Attack) [AML/AMR] ×2, Enganche (Support), Target Man (Support) *

- **Leans on:** kicking +2, decisions +1 (GK; Goalkeeper (Defend)); positioning +2, concentration +2, jumping reach +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); stamina +1, work rate +1, crossing +1, positioning +1 (DL, DR; Full-Back (Support)); work rate +2, stamina +2, aggression +2, anticipation +2, positioning +1 (DM; Ball-Winning Midfielder (Support) [DM]); positioning +2, concentration +2, decisions +1, teamwork +1 (DM; Defensive Midfielder (Defend)); pace +2, acceleration +2, crossing +2, off the ball +1, work rate +2, stamina +1 (AML, AMR; Winger (Attack) [AML/AMR]); first touch +3, passing +3, vision +3, technique +2, decisions +2, flair +2, composure +1 (AMC; Enganche (Support)); strength +3, jumping reach +3, heading +2, first touch +2, teamwork +1 (ST; Target Man (Support)); strength +2, jumping reach +3, heading +2, off the ball +2, anticipation +1, finishing +1 (ST; Target Man (Attack))
- **Expects at least (tapers below):** positioning 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); work rate 8 (DM; Ball-Winning Midfielder (Support) [DM]); stamina 8 (DM; Ball-Winning Midfielder (Support) [DM]); aggression 8 (DM; Ball-Winning Midfielder (Support) [DM]); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 7 (DM; Defensive Midfielder (Defend)); pace 8 (AML, AMR; Winger (Attack) [AML/AMR]); acceleration 8 (AML, AMR; Winger (Attack) [AML/AMR]); crossing 8 (AML, AMR; Winger (Attack) [AML/AMR]); work rate 7 (AML, AMR; Winger (Attack) [AML/AMR]); first touch 8 (AMC; Enganche (Support)); passing 9 (AMC; Enganche (Support)); vision 9 (AMC; Enganche (Support)); technique 8 (AMC; Enganche (Support)); decisions 8 (AMC; Enganche (Support)); strength 8 (ST; Target Man (Support)); jumping reach 9 (ST; Target Man (Support)); heading 8 (ST; Target Man (Support)); first touch 7 (ST; Target Man (Support)); strength 8 (ST; Target Man (Attack)); jumping reach 9 (ST; Target Man (Attack)); heading 8 (ST; Target Man (Attack)); off the ball 7 (ST; Target Man (Attack))
- **Needs:** An exceptional Enganche with strong first touch, passing, vision, technique and decisions; A genuine holding midfielder plus a high-work-rate ball-winner to absorb the defensive load around the number ten; Two quick attacking wingers who can cross and still recover reliably; A strong aerial target man who can turn direct service into controlled possession or box threat; A conventional back four that can remain secure without requiring aggressive overlaps
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Work Ball Into Box; Regroup; Hold Shape; Distribute Quickly; Distribute To Target Man; Take Long Kicks; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against teams able to suffocate or man-mark the Enganche, when the striker cannot dominate direct service, or when the wingers and double pivot lack the work rate to compensate for the free number ten

### Route One 4-4-2

`route_one_442` · 4-4-2 · Balanced · Route One

A deliberately direct system that moves the ball forward early toward a physical target and runners attacking second balls.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Ball-Winning Midfielder (Support) [MC]
- **Attack:** Target Man (Attack), Advanced Forward (Attack) *

- **Leans on:** teamwork +1 (whole team); kicking +2 (GK); positioning +1, concentration +1 (DC); crossing +1, stamina +1 (DL, DR); crossing +2, pace +1, work rate +1 (ML, MR; Winger (Support) [ML/MR]); anticipation +2, work rate +1, strength +1, aggression +1 [new requirement] (MC; Central Midfielder (Defend)); work rate +2, aggression +2, anticipation +2, strength +1 (MC; Ball-Winning Midfielder (Support) [MC]); jumping reach +3, strength +3, heading +2, bravery +2, first touch +1 (ST; Target Man (Attack)); off the ball +2, anticipation +2, acceleration +2, pace +1 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1 (ST; Poacher (Attack))
- **Expects at least (tapers below):** kicking 8 (GK); crossing 8 (ML, MR; Winger (Support) [ML/MR]); anticipation 8 (MC; Central Midfielder (Defend)); aggression 7 (MC; Central Midfielder (Defend)); work rate 8 (MC; Ball-Winning Midfielder (Support) [MC]); aggression 8 (MC; Ball-Winning Midfielder (Support) [MC]); anticipation 8 (MC; Ball-Winning Midfielder (Support) [MC]); jumping reach 10 (ST; Target Man (Attack)); strength 9 (ST; Target Man (Attack)); heading 8 (ST; Target Man (Attack)); bravery 8 (ST; Target Man (Attack)); first touch 7 (ST; Target Man (Attack)); acceleration 9 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 9 (ST; Poacher (Attack)); anticipation 9 (ST; Poacher (Attack)); acceleration 8 (ST; Poacher (Attack))
- **Needs:** A genuinely dominant aerial Target Man who can make long distribution repeatable rather than hopeful; A fast or exceptionally well-timed second striker who attacks knock-downs and the space beyond; A BWM who aggressively competes for second balls while the CM(D) protects the centre; Wide players with reliable early delivery; A goalkeeper with adequate kicking to reach the intended outlet consistently
- **Instructions:** Much More Direct Passing; Higher Tempo; Pass Into Space; Hit Early Crosses; Counter; Regroup
- **Avoid when:** Against tall, strong centre-backs who win the aerial duels, or when your squad is technical and would waste its passing

### Vertical 4-4-2

`vertical_442` · 4-4-2 · Balanced · Vertical 4-4-2

A simple lower-league 4-4-2 that keeps two banks of four but attacks vertically, using early wide service, two complementary forwards and either a midfield runner or a conventional supporting connector alongside the holding midfielder.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Box-to-Box Midfielder (Support) *
- **Attack:** Pressing Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** teamwork +1 (whole team); positioning +2, concentration +2, jumping reach +1 (DC); stamina +1, work rate +1, crossing +1 (DL, DR); pace +2, acceleration +2, crossing +2, work rate +1 (ML, MR; Winger (Support) [ML/MR]); positioning +2, concentration +1, teamwork +1, work rate +1 (MC; Central Midfielder (Defend)); work rate +2, stamina +2, off the ball +2, anticipation +1 (MC; Box-to-Box Midfielder (Support)); decisions +2, passing +2, teamwork +2, first touch +1, work rate +1 (MC; Central Midfielder (Support)); first touch +2, decisions +1, teamwork +1, strength +1 (ST; Deep-Lying Forward (Support), Pressing Forward (Support), Complete Forward (Support)); off the ball +2, anticipation +2, acceleration +2, pace +2 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1 (ST; Poacher (Attack))
- **Expects at least (tapers below):** positioning 7 (DC); pace 7 (ML, MR; Winger (Support) [ML/MR]); acceleration 7 (ML, MR; Winger (Support) [ML/MR]); crossing 7 (ML, MR; Winger (Support) [ML/MR]); positioning 7 (MC; Central Midfielder (Defend)); work rate 8 (MC; Box-to-Box Midfielder (Support)); stamina 8 (MC; Box-to-Box Midfielder (Support)); first touch 7 (ST; Deep-Lying Forward (Support), Pressing Forward (Support), Complete Forward (Support)); decisions 7 (ST; Deep-Lying Forward (Support), Pressing Forward (Support), Complete Forward (Support)); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack)); acceleration 7 (ST; Poacher (Attack)); decisions 7 (MC; Central Midfielder (Support)); passing 7 (MC; Central Midfielder (Support)); teamwork 7 (MC; Central Midfielder (Support))
- **Needs:** A disciplined holding midfielder paired with either a genuinely energetic Box-to-Box runner or a reliable supporting central midfielder; Wide players with enough pace and crossing to make early service worthwhile; A support striker who can work, receive and connect vertical passes; A second striker with enough pace or movement to threaten the space beyond; A conventional back four capable of defending a standard line without specialist demands
- **Instructions:** Hit Early Crosses; Fairly Wide; Slightly More Direct Passing; Higher Tempo; Pass Into Space; Regroup; Counter; Distribute Quickly; Distribute To Flanks; Take Long Kicks; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against a side that heavily overloads central midfield with three high-quality midfielders, or when the front players lack the pace and movement to exploit early, vertical service

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

- **Leans on:** teamwork +1 (whole team); positioning +1, concentration +1, anticipation +1 (DC); positioning +1, stamina +1, teamwork +1 (DL, DR); pace +2, acceleration +2, off the ball +2, crossing +1 (ML, MR); work rate +2, stamina +2, anticipation +1, off the ball +1 (MC); off the ball +2, anticipation +2, acceleration +1, pace +1 (ST)
- **Expects at least (tapers below):** pace 8 (ML, MR); acceleration 8 (ML, MR); off the ball 8 (ML, MR); work rate 8 (MC); stamina 8 (MC); off the ball 8 (ST); anticipation 8 (ST); acceleration 7 (ST)
- **Needs:** Quick wide players who can attack space immediately after regains; A mobile strike pair with enough movement to make direct transitions dangerous; One midfielder able to hold position and one with the engine to join counters; A compact back four comfortable defending without the ball; Opponents willing to leave space behind or around their defensive shape
- **Instructions:** Slightly More Direct Passing; Higher Tempo; Pass Into Space; Counter; Regroup; Lower Line of Engagement; Standard Defensive Line
- **Avoid when:** Against a team that sits deep and does not leave space to run into, since the counter has nothing to attack

### Fluid Counter 4-1-4-1

`fluid_counter_4141` · 4-1-4-1 · Cautious · Fluid Counter-Attack

A compact 4-1-4-1 that counters through short combinations and supporting runs rather than immediately launching long balls.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) *, Central Defender (Cover) *
- **Midfield:** Defensive Midfielder (Defend), Winger (Support) [ML/MR] ×2, Box-to-Box Midfielder (Support), Central Midfielder (Support)
- **Attack:** Advanced Forward (Attack) *

- **Leans on:** teamwork +1 (whole team); positioning +2, concentration +1, anticipation +1 (DC); positioning +1, stamina +1, teamwork +1 (DL, DR); positioning +2, passing +2, decisions +2, first touch +2, teamwork +1 (DM; Defensive Midfielder (Defend)); work rate +2, stamina +2, off the ball +2, passing +1, first touch +1, decisions +1 (MC; Box-to-Box Midfielder (Support)); passing +2, first touch +2, decisions +2, teamwork +1, off the ball +1 (MC; Central Midfielder (Support)); pace +2, acceleration +2, off the ball +2, first touch +1 (ML, MR; Winger (Support) [ML/MR]); acceleration +2, pace +2, off the ball +2, anticipation +2 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1, pace +1 (ST; Poacher (Attack))
- **Expects at least (tapers below):** positioning 8 (DM; Defensive Midfielder (Defend)); passing 8 (DM; Defensive Midfielder (Defend)); decisions 8 (DM; Defensive Midfielder (Defend)); first touch 8 (DM; Defensive Midfielder (Defend)); work rate 8 (MC; Box-to-Box Midfielder (Support)); stamina 8 (MC; Box-to-Box Midfielder (Support)); passing 7 (MC; Box-to-Box Midfielder (Support)); first touch 7 (MC; Box-to-Box Midfielder (Support)); passing 8 (MC; Central Midfielder (Support)); first touch 8 (MC; Central Midfielder (Support)); decisions 8 (MC; Central Midfielder (Support)); pace 8 (ML, MR; Winger (Support) [ML/MR]); acceleration 8 (ML, MR; Winger (Support) [ML/MR]); off the ball 8 (ML, MR; Winger (Support) [ML/MR]); acceleration 9 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 9 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack)); acceleration 8 (ST; Poacher (Attack))
- **Needs:** A reliable DM who can defend positionally and start counters cleanly with his first touch and passing; A Box-to-Box midfielder with the engine to become an extra runner without breaking the midfield structure; A CM(S) technically secure enough to connect short transition combinations; Quick wide players who immediately attack space after regains; A lone striker with enough movement and speed to threaten in behind before support arrives; A compact defensive block that is comfortable conceding harmless possession before countering
- **Instructions:** Slightly Shorter Passing; Pass Into Space; Counter; Regroup; Lower Line of Engagement; Standard Defensive Line
- **Avoid when:** When you need to dominate the ball, or when you have no quick striker to run behind

### Raumdeuter Counter 4-2-3-1

`raumdeuter_counter_4231` · 4-2-3-1 DM AM Wide · Cautious · Counter-attack through space

A cautious 4-2-3-1 that defends in a compact shape and counters through a raumdeuter who finds space on the flank, an attacking midfielder and a quick striker.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Defend) ×2, Central Defender (Defend) *, Central Defender (Cover) *
- **Midfield:** Defensive Midfielder (Defend), Defensive Midfielder (Support)
- **Attack:** Raumdeuter (Attack), Attacking Midfielder (Attack), Winger (Support) [AML/AMR], Complete Forward (Attack)

- **Leans on:** off the ball +2, positioning +2, anticipation +2, concentration +2 (whole team)
- **Needs:** A raumdeuter with good movement and finishing; A quick, mobile striker; Disciplined full-backs; A dependable double pivot
- **Instructions:** Slightly More Direct Passing; Pass Into Space; Counter; Regroup; Lower Line of Engagement; Standard Defensive Line
- **Avoid when:** When you have to dominate the ball, since only two players create

### Solid 4-2-3-1

`solid_4231` · 4-2-3-1 DM AM Wide · Cautious · Compact and disciplined

A cautious 4-2-3-1 built to defend in a compact block, preserve a strong rest defence and still retain one genuine runner plus a reliable central outlet when possession is recovered.

- **Goal:** Goalkeeper (Defend)
- **Defence:** No-Nonsense Full Back (Defend) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Defensive Midfielder (Support)
- **Attack:** Inside Forward (Support), Attacking Midfielder (Support), Winger (Attack) [AML/AMR], Deep-Lying Forward (Support) *

- **Leans on:** decisions +1, kicking +1 (GK; Goalkeeper (Defend)); positioning +2, concentration +2, marking +1, tackling +1, strength +1 (DL, DR; No-Nonsense Full Back (Defend)); positioning +2, concentration +2, anticipation +1, jumping reach +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); positioning +2, concentration +2, decisions +1, teamwork +1 (DM; Defensive Midfielder (Defend)); positioning +1, decisions +2, passing +1, teamwork +2, first touch +1 (DM; Defensive Midfielder (Support)); work rate +2, stamina +1, first touch +1, off the ball +1, dribbling +1 (AML; Inside Forward (Support)); decisions +2, passing +2, first touch +2, teamwork +2, work rate +1 (AMC; Attacking Midfielder (Support)); pace +2, acceleration +2, crossing +2, off the ball +1, work rate +1 (AMR; Winger (Attack) [AML/AMR]); first touch +2, decisions +2, teamwork +1, strength +1 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); strength +3, jumping reach +3, heading +2, first touch +1, teamwork +1 (ST; Target Man (Support))
- **Expects at least (tapers below):** positioning 8 (DL, DR; No-Nonsense Full Back (Defend)); concentration 8 (DL, DR; No-Nonsense Full Back (Defend)); positioning 8 (DC; Central Defender (Defend)); concentration 8 (DC; Central Defender (Defend)); pace 7 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 8 (DM; Defensive Midfielder (Defend)); decisions 7 (DM; Defensive Midfielder (Support)); passing 7 (DM; Defensive Midfielder (Support)); teamwork 7 (DM; Defensive Midfielder (Support)); work rate 7 (AML; Inside Forward (Support)); first touch 7 (AML; Inside Forward (Support)); decisions 8 (AMC; Attacking Midfielder (Support)); passing 8 (AMC; Attacking Midfielder (Support)); first touch 8 (AMC; Attacking Midfielder (Support)); pace 8 (AMR; Winger (Attack) [AML/AMR]); acceleration 8 (AMR; Winger (Attack) [AML/AMR]); crossing 7 (AMR; Winger (Attack) [AML/AMR]); first touch 8 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); decisions 7 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); strength 7 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); strength 8 (ST; Target Man (Support)); jumping reach 9 (ST; Target Man (Support)); heading 8 (ST; Target Man (Support))
- **Needs:** A back four and holding midfielder with strong positioning and concentration; A second DM who can make safe decisions and connect the defensive block to the front four; An AMC with enough touch and passing to make direct possession stick; At least one genuinely quick wide runner so the shape retains a counter-attacking threat; A support striker who can receive under pressure and link play, with a true target man as an alternative when available; Wide attackers willing to contribute enough work rate for the compact defensive block
- **Instructions:** Slightly More Direct Passing; Regroup; Hold Shape; Slow Pace Down; Distribute To Flanks; Take Long Kicks; Lower Line of Engagement; Standard Defensive Line; Less Urgent Pressing
- **Avoid when:** When you need sustained possession or several players attacking the box

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

`deep_counter_541` · 5-4-1 · Defensive · Deep Counter 5-4-1

A deep defensive 5-4-1 that protects the box with a back five and compact midfield, then escapes pressure through a strong target man and two fast wide counter-attacking outlets.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Wing-Back (Defend) [DL/DR] ×2, Central Defender (Defend) * ×3
- **Midfield:** Winger (Attack) [ML/MR] ×2, Central Midfielder (Defend), Central Midfielder (Support)
- **Attack:** Target Man (Support)

- **Leans on:** kicking +2, decisions +1 (GK; Goalkeeper (Defend)); positioning +2, concentration +2, anticipation +1, jumping reach +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); passing +2, decisions +2, first touch +1, technique +1, composure +1 (DC; Ball-Playing Defender (Defend)); positioning +2, concentration +2, tackling +1, work rate +1, stamina +1 (DL, DR; Wing-Back (Defend) [DL/DR]); pace +2, acceleration +2, off the ball +2, dribbling +1, crossing +1, work rate +1 (ML, MR; Winger (Attack) [ML/MR]); positioning +2, concentration +2, decisions +1, teamwork +1, tackling +1 (MC; Central Midfielder (Defend)); passing +2, decisions +2, teamwork +2, first touch +1, off the ball +1 (MC; Central Midfielder (Support)); strength +3, jumping reach +3, heading +2, first touch +2, teamwork +1 (ST; Target Man (Support))
- **Expects at least (tapers below):** positioning 8 (DC; Central Defender (Defend)); concentration 8 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); passing 7 (DC; Ball-Playing Defender (Defend)); decisions 7 (DC; Ball-Playing Defender (Defend)); positioning 8 (DL, DR; Wing-Back (Defend) [DL/DR]); concentration 7 (DL, DR; Wing-Back (Defend) [DL/DR]); pace 8 (ML, MR; Winger (Attack) [ML/MR]); acceleration 8 (ML, MR; Winger (Attack) [ML/MR]); off the ball 7 (ML, MR; Winger (Attack) [ML/MR]); positioning 8 (MC; Central Midfielder (Defend)); concentration 8 (MC; Central Midfielder (Defend)); passing 7 (MC; Central Midfielder (Support)); decisions 7 (MC; Central Midfielder (Support)); teamwork 7 (MC; Central Midfielder (Support)); strength 8 (ST; Target Man (Support)); jumping reach 9 (ST; Target Man (Support)); heading 8 (ST; Target Man (Support)); first touch 7 (ST; Target Man (Support))
- **Needs:** Three dependable centre-backs and defensive wing-backs capable of holding a compact deep block; Two genuinely quick wide midfielders who can turn deep regains into counter-attacks; A strong target man who can win or secure direct balls under pressure; A disciplined holding central midfielder and a reliable supporting connector; Enough concentration and positioning across the defensive unit to tolerate long periods without the ball
- **Instructions:** More Direct Passing; Lower Tempo; Pass Into Space; Regroup; Counter; Distribute Quickly; Distribute To Target Man; Take Long Kicks; Lower Line of Engagement; Drop Off More Defensive Line; Less Urgent Pressing
- **Avoid when:** When you need sustained possession or must create a high volume of chances

### Defensive 4-5-1

`defensive_451` · 4-5-1 · Defensive · Defensive 4-5-1

A conservative five-man midfield shape designed to deny central space and protect a result.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Wide Midfielder (Support) ×2, Central Midfielder (Defend) ×2
- **Attack:** Target Man (Attack)

- **Leans on:** teamwork +1 (whole team); positioning +2, concentration +2, marking +2, anticipation +1 (DC); positioning +2, concentration +1, marking +1, teamwork +1 (DL, DR); positioning +2, concentration +2, teamwork +2, tackling +1 (DM); positioning +2, work rate +2, teamwork +2, concentration +1 (MC); work rate +2, teamwork +2, stamina +2, positioning +1 (ML, MR); jumping reach +2, strength +2, heading +2, bravery +1 (ST)
- **Expects at least (tapers below):** positioning 8 (DC); concentration 8 (DC); positioning 8 (DM); concentration 8 (DM); work rate 8 (ML, MR); teamwork 8 (ML, MR); positioning 8 (MC); teamwork 8 (MC); jumping reach 9 (ST); strength 8 (ST); heading 8 (ST)
- **Needs:** Centre-backs and holding midfielder with strong positioning and concentration; Wide midfielders with the work rate and teamwork to recover into a deep narrow block; Central midfielders disciplined enough to hold shape rather than chase the ball; A genuinely physical Target Man who can win direct balls and relieve pressure; A squad willing to concede territory for long periods
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

- **Leans on:** teamwork +1 (whole team); positioning +2, concentration +2, marking +2, anticipation +1 (DC); positioning +2, marking +1, concentration +1, teamwork +1 (DL, DR); work rate +2, teamwork +2, stamina +1, positioning +1 (ML, MR); positioning +2, work rate +2, teamwork +1, tackling +1, concentration +1 (MC); off the ball +1, anticipation +1 (ST)
- **Expects at least (tapers below):** positioning 7 (DC); concentration 7 (DC); positioning 7 (DL, DR); work rate 7 (ML, MR); teamwork 7 (ML, MR); positioning 7 (MC); work rate 7 (MC)
- **Needs:** Centre-backs with reliable positioning and concentration; Wide midfielders willing and able to recover into the defensive bank; Central midfielders disciplined enough to protect the space in front of the box; One forward who can hold the ball up; One forward who can attack space on the counter
- **Instructions:** Much Lower Line of Engagement; Much Deeper Defensive Line; Narrower; Slower Tempo; Counter; Regroup
- **Avoid when:** When you need to control the ball or score, since the team will be under pressure for long periods

### No-Nonsense 5-3-2

`no_nonsense_532` · 5-3-2 · Defensive · Direct deep block

A pragmatic 5-3-2 for aerially strong defenders: it protects the box, clears danger early, and uses a target man and runner to turn relief into a counter-attack.

- **Goal:** Goalkeeper (Defend)
- **Defence:** No-Nonsense Centre-Back (Defend), No-Nonsense Centre-Back (Cover), No-Nonsense Centre-Back (Stopper), Wing-Back (Support) [WBL/WBR] ×2
- **Midfield:** Central Midfielder (Defend) ×2, Ball-Winning Midfielder (Support) [MC]
- **Attack:** Target Man (Support), Advanced Forward (Attack)

- **Leans on:** command of area +2, aerial reach +2, handling +1 (GK; Goalkeeper (Defend)); heading +2, jumping reach +2, positioning +2, marking +1, concentration +1, strength +1 (DC; No-Nonsense Centre-Back (Defend)); anticipation +2, concentration +2, positioning +1, pace +1, acceleration +1, heading +1, jumping reach +1 (DC; No-Nonsense Centre-Back (Cover)); aggression +2, bravery +2, strength +2, heading +2, jumping reach +2, anticipation +1 (DC; No-Nonsense Centre-Back (Stopper)); stamina +2, positioning +2, work rate +1, teamwork +1, marking +1 (WBL, WBR; Wing-Back (Support) [WBL/WBR]); positioning +2, concentration +1, anticipation +1, teamwork +1 (MC; Central Midfielder (Defend)); work rate +2, aggression +2, anticipation +2, stamina +1 (MC; Ball-Winning Midfielder (Support) [MC]); jumping reach +3, strength +3, heading +2, first touch +1, teamwork +1 (ST; Target Man (Support)); acceleration +2, pace +2, off the ball +2, anticipation +2 (ST; Advanced Forward (Attack))
- **Expects at least (tapers below):** command of area 8 (GK; Goalkeeper (Defend)); heading 9 (DC; No-Nonsense Centre-Back (Defend), No-Nonsense Centre-Back (Cover), No-Nonsense Centre-Back (Stopper)); jumping reach 9 (DC; No-Nonsense Centre-Back (Defend), No-Nonsense Centre-Back (Cover), No-Nonsense Centre-Back (Stopper)); positioning 8 (DC; No-Nonsense Centre-Back (Defend), No-Nonsense Centre-Back (Cover), No-Nonsense Centre-Back (Stopper)); anticipation 8 (DC; No-Nonsense Centre-Back (Cover)); bravery 8 (DC; No-Nonsense Centre-Back (Stopper)); strength 8 (DC; No-Nonsense Centre-Back (Stopper)); stamina 9 (WBL, WBR; Wing-Back (Support) [WBL/WBR]); positioning 8 (MC; Central Midfielder (Defend)); work rate 9 (MC; Ball-Winning Midfielder (Support) [MC]); aggression 8 (MC; Ball-Winning Midfielder (Support) [MC]); anticipation 8 (MC; Ball-Winning Midfielder (Support) [MC]); jumping reach 9 (ST; Target Man (Support)); strength 9 (ST; Target Man (Support)); heading 8 (ST; Target Man (Support)); first touch 7 (ST; Target Man (Support)); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack))
- **Needs:** Three centre-backs who are dominant in the air and comfortable defending the box; A Cover centre-back with enough anticipation and mobility to sweep behind the line; Wing-backs with the stamina and discipline to complete the back five and provide the outlet; A compact midfield with a dedicated second-ball winner; A strong Target Man to make direct clearances useful; A mobile Advanced Forward to turn those first and second balls into counter-attacks
- **Instructions:** Much Lower Line of Engagement; Much Deeper Defensive Line; Narrower; More Direct Passing; Counter; Regroup
- **Avoid when:** When you need sustained possession or your defenders are uncomfortable defending a large number of crosses and second balls

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

### Aggressive Playing 3-4-3

`aggressive_playing_343` · 3-4-3 · Positive · Stopper-cover build-up

A high-line 3-4-3 that pairs an aggressive ball-playing stopper with a ball-playing cover defender and attacks through wing-backs.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Ball-Playing Defender (Stopper), Ball-Playing Defender (Cover), Ball-Playing Defender (Defend), Wing-Back (Attack) [WBL/WBR] ×2
- **Midfield:** Box-to-Box Midfielder (Support), Deep-Lying Playmaker (Support) [MC]
- **Attack:** Winger (Attack) [AML/AMR], Inside Forward (Attack), Pressing Forward (Attack)

- **Leans on:** anticipation +2, pace +2, composure +2, passing +2 (whole team); acceleration +2, concentration +2, positioning +2 (DC)
- **Expects at least (tapers below):** pace 8 (DC); acceleration 8 (DC); anticipation 8 (DC); passing 8 (DC)
- **Needs:** A ball-playing stopper; A fast ball-playing cover defender; Aggressive wing-backs; A pressing forward
- **Instructions:** Much Higher Line of Engagement; Higher Defensive Line; Shorter Passing; Play Out Of Defence; Counter-Press
- **Avoid when:** Against quick direct counters if the cover defender lacks pace or the wing-backs cannot recover

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

### Attacking 4-2-4

`attacking_424` · 4-2-4 · Positive · Attacking 4-2-4

A proactive 4-2-4: four advanced attackers stretch the opposition, a BWM contests central possession, and a DLP supplies them quickly. Positive mentality and a standard defensive line reduce the risk, while the two-man midfield still depends on a coordinated press and recovery work.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Defend) [MC], Deep-Lying Playmaker (Support) [MC]
- **Attack:** Inside Forward (Attack), Winger (Attack) [AML/AMR], Pressing Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** kicking +2, decisions +1, anticipation +1 (GK; Goalkeeper (Defend)); positioning +2, concentration +2, anticipation +1, pace +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); stamina +1, work rate +1, positioning +1 (DL, DR; Full-Back (Support)); work rate +2, stamina +2, aggression +2, anticipation +2, positioning +1 (MC; Ball-Winning Midfielder (Defend) [MC]); passing +2, first touch +2, vision +2, decisions +2, stamina +1 (MC; Deep-Lying Playmaker (Support) [MC]); acceleration +2, pace +2, off the ball +2, dribbling +1, finishing +1, stamina +2 [new requirement], work rate +1 [new requirement] (AML; Inside Forward (Attack)); acceleration +2, pace +2, dribbling +2, crossing +2, stamina +1, work rate +1 (AMR; Winger (Attack) [AML/AMR]); work rate +2, stamina +2, anticipation +1, first touch +1, teamwork +1 (ST; Pressing Forward (Support)); first touch +2, decisions +2, passing +1, teamwork +1, stamina +1 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); acceleration +2, pace +2, off the ball +2, anticipation +2, stamina +1 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1 (ST; Poacher (Attack))
- **Expects at least (tapers below):** positioning 7 (DC; Central Defender (Defend)); concentration 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); acceleration 7 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); work rate 9 (MC; Ball-Winning Midfielder (Defend) [MC]); stamina 8 (MC; Ball-Winning Midfielder (Defend) [MC]); aggression 8 (MC; Ball-Winning Midfielder (Defend) [MC]); positioning 8 (MC; Ball-Winning Midfielder (Defend) [MC]); passing 9 (MC; Deep-Lying Playmaker (Support) [MC]); first touch 8 (MC; Deep-Lying Playmaker (Support) [MC]); vision 8 (MC; Deep-Lying Playmaker (Support) [MC]); decisions 8 (MC; Deep-Lying Playmaker (Support) [MC]); stamina 7 (MC; Deep-Lying Playmaker (Support) [MC]); stamina 7 (AML; Inside Forward (Attack)); acceleration 8 (AML; Inside Forward (Attack)); off the ball 8 (AML; Inside Forward (Attack)); stamina 7 (AMR; Winger (Attack) [AML/AMR]); pace 8 (AMR; Winger (Attack) [AML/AMR]); acceleration 8 (AMR; Winger (Attack) [AML/AMR]); crossing 7 (AMR; Winger (Attack) [AML/AMR]); work rate 8 (ST; Pressing Forward (Support)); stamina 7 (ST; Pressing Forward (Support)); first touch 7 (ST; Pressing Forward (Support)); first touch 8 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); decisions 8 (ST; Deep-Lying Forward (Support), Complete Forward (Support)); acceleration 9 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); stamina 7 (ST; Advanced Forward (Attack)); off the ball 9 (ST; Poacher (Attack)); anticipation 9 (ST; Poacher (Attack)); work rate 7 (AML; Inside Forward (Attack)); work rate 7 (AMR; Winger (Attack) [AML/AMR])
- **Needs:** A disciplined ball-winner and a technically secure distributor who can survive as a two-man midfield; Four attackers with enough movement, athleticism and work rate to stretch the opposition and sustain the first counter-press; A support striker with enough work rate to connect the attack and lead the first press; An Advanced Forward who threatens space behind, with Poacher available as a less mobile movement-and-finishing alternative; Centre-backs reliable enough for a standard line; elite high-line recovery pace is no longer mandatory; Full-backs capable of supporting possession without being relied upon as the main source of width
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Higher Tempo; Pass Into Space; Counter-Press; Counter; Distribute Quickly; Distribute To Flanks; Take Long Kicks; Standard Line of Engagement; Standard Defensive Line; More Urgent Pressing
- **Avoid when:** When you expect to be the better side and want to control the match: with only two central midfielders it is outnumbered by any three-man centre, even more so than the 4-4-2

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
- **Defence:** Full-Back (Attack) ×2, Central Defender (Defend) * ×2
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

### Front-Foot 4-4-2

`front_foot_442` · 4-4-2 · Positive · Stopper-cover high press

A front-foot 4-4-2 that uses a stopper-cover centre-back partnership to squeeze play behind an aggressive two-forward press.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Stopper), Central Defender (Cover)
- **Midfield:** Wide Midfielder (Support) ×2, Ball-Winning Midfielder (Support) [MC], Box-to-Box Midfielder (Support)
- **Attack:** Pressing Forward (Defend), Advanced Forward (Attack)

- **Leans on:** stamina +2, work rate +2, aggression +2, anticipation +2 (whole team); aggression +2 [new requirement] (Advanced Forward (Attack)); aggression +2 [new requirement] (Wide Midfielder (Support)); pace +2, acceleration +2, concentration +2 (DC)
- **Expects at least (tapers below):** pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC); stamina 8 (ML, MR, MC, ST); work rate 8 (ML, MR, MC, ST)
- **Needs:** An aggressive stopper and quick cover defender; Two energetic forwards; Hard-working wide midfielders; A ball-winning midfielder
- **Instructions:** Higher Line of Engagement; Higher Defensive Line; Much More Urgent Pressing; Slightly More Direct Passing; Higher Tempo; Counter-Press
- **Avoid when:** Against direct sides if the cover defender is slow, or when the squad lacks the stamina to press for a full match

### Gegenpress 4-2-3-1

`gegenpress_4231` · 4-2-3-1 DM AM Wide · Positive · Gegenpress

An intense 4-2-3-1 intended to regain the ball immediately after losing it and attack before the opponent reorganises.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Wing-Back (Support) [DL/DR] ×2, Ball-Playing Defender (Defend), Central Defender (Cover) *
- **Midfield:** Ball-Winning Midfielder (Support) [DM], Deep-Lying Playmaker (Support) [DM]
- **Attack:** Inside Forward (Attack), Shadow Striker (Attack), Winger (Attack) [AML/AMR], Pressing Forward (Attack) *

- **Leans on:** work rate +2, aggression +2, stamina +2, anticipation +2 (whole team); work rate +2 [new requirement], stamina +2 [new requirement] (Ball-Playing Defender (Defend), Central Defender (Cover), Central Defender (Defend), Inside Forward (Attack)); aggression +2 [new requirement] (Wing-Back (Support) [DL/DR], Deep-Lying Playmaker (Support) [DM], Inside Forward (Attack), Winger (Attack) [AML/AMR], Advanced Forward (Attack))
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

- **Leans on:** stamina +2, work rate +2, anticipation +2, aggression +2 (whole team); stamina +2 [new requirement], work rate +2 [new requirement] (Ball-Playing Defender (Defend), Central Defender (Cover), Central Defender (Defend), Inside Forward (Attack)); aggression +2 [new requirement] (Wing-Back (Support) [DL/DR], Wing-Back (Attack) [DL/DR], Mezzala (Attack), Winger (Attack) [AML/AMR], Inside Forward (Attack), Advanced Forward (Attack))
- **Needs:** High work rate/stamina; Fast centre-backs; Sweeper keeper; Squad depth
- **Instructions:** Much Higher Line of Engagement; Much More Urgent Pressing; Higher Defensive Line; Shorter Passing; Counter-Press
- **Avoid when:** Against sides that play long over the press, or when your players lack stamina: the press cannot be kept up for 90 minutes

### Inverted Wide 4-4-2

`inverted_wide_442` · 4-4-2 · Positive · Asymmetric inverted counter

A 4-4-2 with a defensive winger securing one side and an inverted winger plus attacking wing-back creating a counter-attacking overload on the other.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Defend), Central Defender (Defend) *, Ball-Playing Defender (Defend), Wing-Back (Attack) [DL/DR]
- **Midfield:** Defensive Winger (Defend) [ML/MR], Central Midfielder (Defend), Box-to-Box Midfielder (Support), Inverted Winger (Attack) [ML/MR]
- **Attack:** Deep-Lying Forward (Support), Advanced Forward (Attack)

- **Leans on:** stamina +2, work rate +2, anticipation +2 (whole team); positioning +2, tackling +2, marking +2 (ML); acceleration +2, dribbling +2, off the ball +2 (MR)
- **Expects at least (tapers below):** work rate 8 (ML); positioning 8 (ML); acceleration 8 (MR); off the ball 8 (MR)
- **Needs:** A defensive winger; A flat inverted winger; An attacking right wing-back; Complementary forwards
- **Instructions:** Fairly Wide; Slightly More Direct Passing; Pass Into Space; Overlap Right; Counter; Regroup; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against an opponent that can repeatedly isolate the attacking right-back, or when the defensive winger cannot carry his side's defensive load

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

### Positional Play 4-3-3

`positional_play_433` · 4-3-3 · Positive · Structured midfield circulation

A 4-3-3 built around a disciplined central triangle, with a Carrilero protecting the inverted side and a Mezzala supporting the wide attack.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Inverted Wing Back (Support), Ball-Playing Defender (Defend), Central Defender (Cover) *, Full-Back (Support)
- **Midfield:** Carrilero (Support) [MC], Deep-Lying Playmaker (Defend) [MC], Mezzala (Support)
- **Attack:** Inside Forward (Support), Winger (Attack) [AML/AMR], Complete Forward (Support)

- **Leans on:** composure +2, decisions +2, technique +2, passing +2 (whole team); positioning +2, teamwork +2 (MC)
- **Expects at least (tapers below):** passing 8 (MC); first touch 8 (MC); stamina 8 (MC; Carrilero (Support) [MC]); technique 8 (MC)
- **Needs:** A composed DLP at MC; A high-stamina Carrilero; A technical Mezzala; Full-backs comfortable in a positional build-up
- **Instructions:** Shorter Passing; Play Out Of Defence; Work Ball Into Box; Hold Shape; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** When your midfield lacks passing security or the opponent can repeatedly isolate the full-backs in wide transition

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

A proactive 4-2-3-1 with a holding midfielder and deep playmaker supporting four advanced attackers, using short build-up, a higher press and complementary wide threats.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Deep-Lying Playmaker (Support) [DM]
- **Attack:** Inside Forward (Attack), Attacking Midfielder (Support), Winger (Attack) [AML/AMR], Pressing Forward (Attack) *

- **Leans on:** decisions +1, kicking +1, first touch +1 (GK; Goalkeeper (Defend)); positioning +2, concentration +2, anticipation +1, passing +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); stamina +1, work rate +1, passing +1, first touch +1 (DL, DR; Full-Back (Support)); positioning +2, concentration +2, decisions +2, teamwork +1, passing +1 (DM; Defensive Midfielder (Defend)); passing +2, first touch +2, vision +2, decisions +2, technique +1, positioning +1 (DM; Deep-Lying Playmaker (Support) [DM]); first touch +2, passing +2, vision +2, decisions +2, technique +1, off the ball +1 (AMC; Attacking Midfielder (Support)); acceleration +2, pace +2, off the ball +2, dribbling +1, finishing +1, first touch +1 (AML; Inside Forward (Attack)); acceleration +2, pace +2, dribbling +2, crossing +2, off the ball +1 (AMR; Winger (Attack) [AML/AMR]); acceleration +2, pace +2, off the ball +2, anticipation +2, finishing +1 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1, finishing +1 (ST; Poacher (Attack)); work rate +2, stamina +2, off the ball +2, acceleration +2, anticipation +1, finishing +1 (ST; Pressing Forward (Attack))
- **Expects at least (tapers below):** positioning 7 (DC; Central Defender (Defend)); concentration 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 7 (DM; Defensive Midfielder (Defend)); decisions 7 (DM; Defensive Midfielder (Defend)); passing 8 (DM; Deep-Lying Playmaker (Support) [DM]); first touch 8 (DM; Deep-Lying Playmaker (Support) [DM]); vision 8 (DM; Deep-Lying Playmaker (Support) [DM]); decisions 8 (DM; Deep-Lying Playmaker (Support) [DM]); positioning 7 (DM; Deep-Lying Playmaker (Support) [DM]); first touch 8 (AMC; Attacking Midfielder (Support)); passing 8 (AMC; Attacking Midfielder (Support)); decisions 8 (AMC; Attacking Midfielder (Support)); vision 8 (AMC; Attacking Midfielder (Support)); acceleration 8 (AML; Inside Forward (Attack)); off the ball 8 (AML; Inside Forward (Attack)); pace 8 (AMR; Winger (Attack) [AML/AMR]); acceleration 8 (AMR; Winger (Attack) [AML/AMR]); crossing 7 (AMR; Winger (Attack) [AML/AMR]); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack)); work rate 8 (ST; Pressing Forward (Attack)); stamina 8 (ST; Pressing Forward (Attack)); acceleration 8 (ST; Pressing Forward (Attack)); off the ball 8 (ST; Pressing Forward (Attack))
- **Needs:** A disciplined holding midfielder who protects the centre while the rest of the attacking structure advances; A technically secure deep playmaker capable of receiving and progressing the ball under pressure; An attacking midfielder with the first touch, decisions and passing to connect the front four; Complementary wide attackers: one inside scoring threat and one genuine source of width; A pressing forward with the work rate, stamina and movement to lead the counter-press and threaten space behind
- **Instructions:** Shorter Passing; Higher Tempo; Play Out Of Defence; Counter-Press; Counter; Distribute Quickly; Distribute To Centre Backs; Take Short Kicks; Higher Line of Engagement; Standard Defensive Line; More Urgent Pressing
- **Avoid when:** Against opponents who dominate the central three-versus-two around your pivot, or when the squad lacks the technical security for shorter build-up and counter-pressing

### Positive 4-3-1-2 Narrow

`positive_4312_narrow` · 4-3-1-2 · Positive · Narrow Combination Play

A narrow 4-3-1-2 using three central midfielders and an advanced playmaker behind two complementary forwards.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Wing-Back (Attack) [DL/DR], Central Defender (Defend) *, Ball-Playing Defender (Defend), Wing-Back (Support) [DL/DR]
- **Midfield:** Central Midfielder (Defend), Deep-Lying Playmaker (Support) [MC], Box-to-Box Midfielder (Support)
- **Attack:** Advanced Playmaker (Attack) [AMC], Deep-Lying Forward (Support) *, Advanced Forward (Attack) *

- **Leans on:** stamina +2, crossing +2, first touch +2, teamwork +2 (whole team)
- **Expects at least (tapers below):** passing 8 (MC); vision 8 (AMC); first touch 8 (AMC); technique 8 (AMC); stamina 9 (DL, DR); crossing 8 (DL, DR)
- **Needs:** Excellent attacking full-backs; Three capable central midfielders; Creative AMC; Complementary strikers
- **Instructions:** Fairly Narrow; Shorter Passing; Work Ball Into Box; Overlap Left; Overlap Right; Counter-Press; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** Against sides that attack the flanks, since your full-backs are the only wide players and will be stretched

### Positive 4-3-3 DM Wide

`positive_433dm` · 4-3-3 DM Wide · Positive · Positive 4-3-3 DM

A positive 4-3-3 built around a genuine holding midfielder, two complementary eights and three forwards who provide both width and penetration.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Defensive Midfielder (Defend), Deep-Lying Playmaker (Support) [MC], Central Midfielder (Support)
- **Attack:** Inside Forward (Attack), Winger (Attack) [AML/AMR], Pressing Forward (Attack) *

- **Leans on:** decisions +1, kicking +1, first touch +1 (GK; Goalkeeper (Defend)); positioning +2, concentration +2, anticipation +1, passing +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); stamina +1, work rate +1, passing +1, first touch +1 (DL, DR; Full-Back (Support)); positioning +2, concentration +2, decisions +2, teamwork +1, passing +1 (DM; Defensive Midfielder (Defend)); passing +2, first touch +2, vision +2, decisions +2, technique +1 (MC; Deep-Lying Playmaker (Support) [MC]); decisions +2, passing +2, teamwork +2, first touch +1, off the ball +1 (MC; Central Midfielder (Support)); acceleration +2, pace +2, off the ball +2, dribbling +1, finishing +1, first touch +1, work rate +1 [new requirement], stamina +1 [new requirement] (AML; Inside Forward (Attack)); acceleration +2, pace +2, dribbling +2, crossing +2, off the ball +1, work rate +1, stamina +1 (AMR; Winger (Attack) [AML/AMR]); acceleration +2, pace +2, off the ball +2, anticipation +2, finishing +1, stamina +1 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1, finishing +1 (ST; Poacher (Attack)); work rate +2, stamina +2, off the ball +2, acceleration +2, anticipation +1, finishing +1 (ST; Pressing Forward (Attack))
- **Expects at least (tapers below):** positioning 7 (DC; Central Defender (Defend)); concentration 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 7 (DM; Defensive Midfielder (Defend)); decisions 7 (DM; Defensive Midfielder (Defend)); passing 8 (MC; Deep-Lying Playmaker (Support) [MC]); first touch 8 (MC; Deep-Lying Playmaker (Support) [MC]); vision 8 (MC; Deep-Lying Playmaker (Support) [MC]); decisions 8 (MC; Deep-Lying Playmaker (Support) [MC]); decisions 7 (MC; Central Midfielder (Support)); passing 7 (MC; Central Midfielder (Support)); teamwork 7 (MC; Central Midfielder (Support)); acceleration 8 (AML; Inside Forward (Attack)); off the ball 8 (AML; Inside Forward (Attack)); work rate 7 (AML; Inside Forward (Attack)); stamina 7 (AML; Inside Forward (Attack)); pace 8 (AMR; Winger (Attack) [AML/AMR]); acceleration 8 (AMR; Winger (Attack) [AML/AMR]); crossing 7 (AMR; Winger (Attack) [AML/AMR]); work rate 7 (AMR; Winger (Attack) [AML/AMR]); stamina 7 (AMR; Winger (Attack) [AML/AMR]); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack)); work rate 8 (ST; Pressing Forward (Attack)); stamina 8 (ST; Pressing Forward (Attack)); acceleration 8 (ST; Pressing Forward (Attack)); off the ball 8 (ST; Pressing Forward (Attack))
- **Needs:** A positionally disciplined holding midfielder who protects the centre-backs rather than chasing the ball; A DLP with enough passing, touch, vision and decisions to progress shorter build-up; A supporting central midfielder who connects play reliably and complements the deep playmaker; An inside forward and winger with enough acceleration and movement to turn possession into penetration, and enough work rate and stamina to sustain the counter-press; A pressing forward with the work rate, stamina and movement to lead the counter-press and threaten space behind; Defenders and full-backs comfortable enough on the ball to make Play Out Of Defence worthwhile
- **Instructions:** Shorter Passing; Higher Tempo; Play Out Of Defence; Work Ball Into Box; Counter-Press; Counter; Distribute Quickly; Distribute To Centre Backs; Take Short Kicks; Higher Line of Engagement; Standard Defensive Line; More Urgent Pressing
- **Avoid when:** When the DM lacks positional discipline, the defenders are too uncomfortable to support short build-up, or the wide forwards lack the movement and pace to turn possession into penetration

### Positive Ball-Winning 4-3-3 DM

`positive_ball_winning_433dm` · 4-3-3 DM Wide · Positive · Positive ball-winning 4-3-3 DM

A positive possession 4-3-3 with a holding DM behind a ball-winner and playmaker, a supporting right winger and an attacking left wing-back.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Wing-Back (Attack) [DL/DR], Central Defender (Defend) * ×2, Full-Back (Support)
- **Midfield:** Defensive Midfielder (Defend), Deep-Lying Playmaker (Support) [MC], Ball-Winning Midfielder (Support) [MC]
- **Attack:** Inside Forward (Attack), Winger (Support) [AML/AMR], Advanced Forward (Attack) *

- **Leans on:** decisions +1, kicking +1, first touch +1 (GK; Goalkeeper (Defend)); positioning +2, concentration +2, anticipation +1, passing +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); stamina +1, work rate +1, passing +1, first touch +1 (DL, DR; Full-Back (Support)); positioning +2, concentration +2, decisions +2, teamwork +1, passing +1 (DM; Defensive Midfielder (Defend)); passing +2, first touch +2, vision +2, decisions +2, technique +1 (MC; Deep-Lying Playmaker (Support) [MC]); acceleration +2, pace +2, off the ball +2, dribbling +1, finishing +1, first touch +1, work rate +1 [new requirement], stamina +1 [new requirement] (AML; Inside Forward (Attack)); acceleration +2, pace +2, off the ball +2, anticipation +2, finishing +1, stamina +1 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1, finishing +1 (ST; Poacher (Attack)); work rate +2, stamina +2, off the ball +2, acceleration +2, anticipation +1, finishing +1 (ST; Pressing Forward (Attack)); work rate +2, stamina +2, tackling +1, anticipation +1, passing +1, first touch +1, decisions +1 (MC; Ball-Winning Midfielder (Support) [MC]); passing +2, first touch +2, decisions +2, crossing +2, teamwork +1, stamina +1, work rate +1 (AMR; Winger (Support) [AML/AMR]); pace +2, acceleration +1, off the ball +2, crossing +2, stamina +2, work rate +1, first touch +1 (DL; Wing-Back (Attack) [DL/DR])
- **Expects at least (tapers below):** positioning 7 (DC; Central Defender (Defend)); concentration 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 7 (DM; Defensive Midfielder (Defend)); decisions 7 (DM; Defensive Midfielder (Defend)); passing 8 (MC; Deep-Lying Playmaker (Support) [MC]); first touch 8 (MC; Deep-Lying Playmaker (Support) [MC]); vision 8 (MC; Deep-Lying Playmaker (Support) [MC]); decisions 8 (MC; Deep-Lying Playmaker (Support) [MC]); acceleration 8 (AML; Inside Forward (Attack)); off the ball 8 (AML; Inside Forward (Attack)); work rate 7 (AML; Inside Forward (Attack)); stamina 7 (AML; Inside Forward (Attack)); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack)); work rate 8 (ST; Pressing Forward (Attack)); stamina 8 (ST; Pressing Forward (Attack)); acceleration 8 (ST; Pressing Forward (Attack)); off the ball 8 (ST; Pressing Forward (Attack)); work rate 8 (MC; Ball-Winning Midfielder (Support) [MC]); stamina 8 (MC; Ball-Winning Midfielder (Support) [MC]); tackling 8 (MC; Ball-Winning Midfielder (Support) [MC]); passing 8 (MC; Ball-Winning Midfielder (Support) [MC]); first touch 8 (MC; Ball-Winning Midfielder (Support) [MC]); decisions 7 (MC; Ball-Winning Midfielder (Support) [MC]); passing 8 (AMR; Winger (Support) [AML/AMR]); first touch 8 (AMR; Winger (Support) [AML/AMR]); decisions 8 (AMR; Winger (Support) [AML/AMR]); crossing 8 (AMR; Winger (Support) [AML/AMR]); work rate 7 (AMR; Winger (Support) [AML/AMR]); stamina 7 (AMR; Winger (Support) [AML/AMR]); stamina 9 (DL; Wing-Back (Attack) [DL/DR]); pace 8 (DL; Wing-Back (Attack) [DL/DR]); off the ball 8 (DL; Wing-Back (Attack) [DL/DR]); crossing 8 (DL; Wing-Back (Attack) [DL/DR]); first touch 7 (DL; Wing-Back (Attack) [DL/DR]); work rate 8 (DL; Wing-Back (Attack) [DL/DR]); pace 7 (DC; Central Defender (Defend)); pace 8 (DR; Full-Back (Support)); acceleration 7 (DC; Central Defender (Defend)); acceleration 8 (DC; Central Defender (Cover)); acceleration 8 (DR; Full-Back (Support)); acceleration 8 (DL; Wing-Back (Attack) [DL/DR])
- **Needs:** A disciplined DM who protects the centre behind the chasing BWM and advancing left wing-back; A BWM with tackling, anticipation, work rate and stamina, plus passing, first touch and decisions suitable for shorter build-up; A DLP and supporting right winger capable of sharing progression and chance creation; A left wing-back with stamina, pace, acceleration, movement and crossing to provide forward runs outside the inside forward and recover after advancing; An inside forward and lone striker who provide box threat while the right winger supports; AF, PF and Poacher offer different attacking profiles; Defenders comfortable enough on the ball for Play Out Of Defence, enough pace and acceleration across the back four for recovery, and players able to sustain the counter-press
- **Instructions:** Shorter Passing; Higher Tempo; Play Out Of Defence; Work Ball Into Box; Counter-Press; Counter; Distribute Quickly; Distribute To Centre Backs; Take Short Kicks; Higher Line of Engagement; Standard Defensive Line; More Urgent Pressing
- **Avoid when:** When the left wing-back cannot contribute and recover, the BWM cannot receive and pass under pressure, or the back line cannot support short build-up

### Possession 4-1-4-1

`possession_4141` · 4-1-4-1 · Positive · Possession

A patient possession structure with a playmaker at the base, a linking striker and an attacking right winger who turns controlled build-up into a goal threat.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support) ×2, Ball-Playing Defender (Defend), Central Defender (Defend) *
- **Midfield:** Deep-Lying Playmaker (Support) [DM], Wide Midfielder (Support), Central Midfielder (Support), Box-to-Box Midfielder (Support), Winger (Attack) [ML/MR]
- **Attack:** Deep-Lying Forward (Support) *

- **Leans on:** composure +2, decisions +2, technique +2, positioning +2 (whole team)
- **Needs:** Technically reliable midfield; Linking striker; Ball-playing defender; Good first touch/decisions; An attacking right winger with the movement and pace to give the linking striker a forward outlet
- **Instructions:** Shorter Passing; Lower Tempo; Play Out Of Defence; Work Ball Into Box; Hold Shape; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** When you need immediate, high-tempo attacks, your defenders and midfield are uncomfortable on the ball, or the right winger lacks the movement to support the dropping striker

### High-Press 4-4-2

`pressing_442` · 4-4-2 · Positive · Two pressing forwards

A 4-4-2 that presses from the front with two pressing forwards, a ball-winning midfielder and a box-to-box runner, and hard-working wide midfielders.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Wide Midfielder (Support) ×2, Ball-Winning Midfielder (Support) [MC], Box-to-Box Midfielder (Support)
- **Attack:** Pressing Forward (Defend), Pressing Forward (Attack)

- **Leans on:** teamwork +1 (whole team); stamina +1, work rate +1, positioning +1 (DL, DR); anticipation +1, concentration +1, positioning +1 (DC); stamina +2, work rate +2, teamwork +2, aggression +1 [new requirement], anticipation +1 (ML, MR; Wide Midfielder (Support)); stamina +2, work rate +2, aggression +2, anticipation +1, teamwork +1 (MC); stamina +2, work rate +2, aggression +2, anticipation +2, off the ball +1 (ST)
- **Expects at least (tapers below):** stamina 7 (DL, DR); work rate 7 (DL, DR); stamina 8 (ML, MR); work rate 8 (ML, MR); stamina 8 (MC); work rate 8 (MC); stamina 8 (ST); work rate 8 (ST); aggression 7 (ST)
- **Needs:** Two forwards with high stamina and work rate to initiate the press; Central midfielders with the engine and aggression to support the first line; Wide midfielders who can repeatedly recover and press the flanks; Full-backs fit enough to step forward behind the wide midfielders; Enough squad depth and fitness to sustain the intensity across a season
- **Instructions:** Higher Line of Engagement; Much More Urgent Pressing; Counter-Press; Slightly More Direct Passing; Higher Tempo; Standard Defensive Line
- **Avoid when:** Against sides that play long over the press, or when your players are tired: a two-man press leaves gaps behind it if it is beaten

### Roaming Playmaker 4-3-3

`roaming_playmaker_433` · 4-3-3 · Positive · Mobile midfield creator

A 4-3-3 built to give an elite roaming playmaker freedom while a ball-winner and an advanced playmaker keep the midfield coherent.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Wing-Back (Support) [DL/DR] ×2, Ball-Playing Defender (Defend), Central Defender (Cover) *
- **Midfield:** Ball-Winning Midfielder (Defend) [MC], Roaming Playmaker (Support) [MC], Advanced Playmaker (Support) [MC]
- **Attack:** Inverted Winger (Attack) [AML/AMR], Winger (Attack) [AML/AMR], Pressing Forward (Attack)

- **Leans on:** stamina +2, work rate +2, technique +2, passing +2 (whole team); decisions +2, composure +2 (MC)
- **Expects at least (tapers below):** stamina 8 (MC; Roaming Playmaker (Support) [MC]); work rate 8 (MC); passing 8 (MC)
- **Needs:** An elite roaming playmaker; A disciplined ball-winner; A second creative midfielder; Energetic pressing support
- **Instructions:** Shorter Passing; Play Out Of Defence; Work Ball Into Box; Counter-Press; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** Against sides that can exploit a midfield that follows the roaming playmaker away from its defensive position, or when the squad lacks work rate

### Trequartista 4-3-1-2

`trequartista_4312` · 4-3-1-2 · Positive · One free creator, everyone else works

A narrow 4-3-1-2 with one trequartista who roams freely behind two strikers, and a hard-working midfield three plus a pressing forward to cover for him.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Ball-Winning Midfielder (Support) [MC], Central Midfielder (Defend), Box-to-Box Midfielder (Support)
- **Attack:** Trequartista (Attack) [AMC], Pressing Forward (Support), Advanced Forward (Attack) *

- **Leans on:** first touch +2, teamwork +2, technique +2, composure +2 (whole team)
- **Expects at least (tapers below):** vision 10 (AMC); technique 10 (AMC); first touch 9 (AMC); composure 9 (AMC); stamina 8 (DL, DR)
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

- **Leans on:** teamwork +1 (whole team); positioning +1, concentration +1 (DC); stamina +1, teamwork +1, positioning +1 (DL, DR); work rate +2, teamwork +2, stamina +2, positioning +1 (ML, MR); positioning +2, teamwork +1, concentration +1 (MC; Central Midfielder (Defend)); work rate +2, stamina +2, off the ball +1, teamwork +1 (MC; Box-to-Box Midfielder (Support)); vision +3, technique +3, first touch +2, decisions +2, flair +2, composure +2, passing +2, off the ball +1 (ST; Trequartista (Attack) [ST]); work rate +3, stamina +2, aggression +2, teamwork +2, anticipation +1, off the ball +1 (ST; Pressing Forward (Support))
- **Expects at least (tapers below):** work rate 8 (ML, MR); stamina 8 (ML, MR); positioning 8 (MC; Central Midfielder (Defend)); work rate 8 (MC; Box-to-Box Midfielder (Support)); stamina 8 (MC; Box-to-Box Midfielder (Support)); vision 10 (ST; Trequartista (Attack) [ST]); technique 10 (ST; Trequartista (Attack) [ST]); first touch 9 (ST; Trequartista (Attack) [ST]); decisions 9 (ST; Trequartista (Attack) [ST]); passing 9 (ST; Trequartista (Attack) [ST]); composure 8 (ST; Trequartista (Attack) [ST]); work rate 9 (ST; Pressing Forward (Support)); stamina 8 (ST; Pressing Forward (Support)); aggression 8 (ST; Pressing Forward (Support)); teamwork 8 (ST; Pressing Forward (Support))
- **Needs:** A genuinely high-quality Trequartista with strong vision, technique, first touch, decisions and passing; A Pressing Forward partner with exceptional work rate and enough stamina, aggression and teamwork to press for both forwards; Wide midfielders with the stamina and work rate to compensate for the Trequartista's defensive freedom; A disciplined Central Midfielder (Defend) behind an energetic Box-to-Box runner; Enough technical quality in the front pair to make Work Ball Into Box worthwhile
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

### Wide Control 4-1-4-1

`wide_control_4141` · 4-1-4-1 · Positive · Flat-wide possession

A 4-1-4-1 that controls the ball through a Wide Playmaker and flat Inverted Winger, rather than relying on AML/AMR roles.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Wing-Back (Support) [DL/DR], Ball-Playing Defender (Defend), Central Defender (Cover) *, Full-Back (Support)
- **Midfield:** Deep-Lying Playmaker (Support) [DM], Wide Playmaker (Support) [ML/MR], Central Midfielder (Defend), Box-to-Box Midfielder (Support), Inverted Winger (Support) [ML/MR]
- **Attack:** Complete Forward (Support)

- **Leans on:** composure +2, decisions +2, technique +2, passing +2 (whole team); vision +2, first touch +2 (ML); dribbling +2, off the ball +2 (MR)
- **Expects at least (tapers below):** passing 8 (ML); vision 8 (ML); first touch 8 (ML); technique 8 (ML)
- **Needs:** A genuine flat wide playmaker; A supporting inverted winger; A deep distributor; Full-backs with disciplined width
- **Instructions:** Fairly Wide; Shorter Passing; Play Out Of Defence; Work Ball Into Box; Hold Shape; Standard Line of Engagement; Standard Defensive Line
- **Avoid when:** When you need constant runners beyond the striker, or when the full-backs cannot provide the width the creators leave behind

### Wide Creator 4-4-2

`wide_creator_442` · 4-4-2 · Positive · Asymmetric wide creation

A 4-4-2 with a defensive winger securing one flank and an attacking wide playmaker creating from the other, supported by an overlap and complementary forwards.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support), Central Defender (Defend) *, Ball-Playing Defender (Defend), Wing-Back (Attack) [DL/DR]
- **Midfield:** Defensive Winger (Support) [ML/MR], Central Midfielder (Defend), Central Midfielder (Support), Wide Playmaker (Attack) [ML/MR]
- **Attack:** Deep-Lying Forward (Support), Advanced Forward (Attack)

- **Leans on:** stamina +2, work rate +2, teamwork +2 (whole team); passing +2, vision +2, technique +2, first touch +2 (MR); positioning +2, tackling +2 (ML)
- **Expects at least (tapers below):** stamina 8 (ML); work rate 8 (ML); passing 8 (MR); vision 8 (MR); technique 8 (MR)
- **Needs:** A technical wide playmaker; A defensive winger with stamina; An overlapping right-back; Complementary linking and running forwards
- **Instructions:** Fairly Wide; Slightly Shorter Passing; Work Ball Into Box; Overlap Right; Counter-Press; Higher Line of Engagement; Standard Defensive Line
- **Avoid when:** Against a side that can overload the space behind the attacking right-back, or if the wide playmaker lacks the technical quality to justify the imbalance

### Wide Playmakers 4-3-3

`wide_playmakers_433` · 4-3-3 DM Wide · Positive · Roaming creators from wide

A possession-oriented 4-3-3 with two different creators starting wide and moving inside, a left full-back and supporting right wing-back supplying width, and a true holding midfielder protecting the structure behind them.

- **Goal:** Sweeper Keeper (Defend)
- **Defence:** Full-Back (Support), Ball-Playing Defender (Defend), Central Defender (Defend) *, Wing-Back (Support) [DL/DR] *
- **Midfield:** Defensive Midfielder (Defend), Box-to-Box Midfielder (Support), Central Midfielder (Support)
- **Attack:** Trequartista (Attack) [AML/AMR], Advanced Playmaker (Attack) [AML/AMR], Pressing Forward (Attack)

- **Leans on:** decisions +1, first touch +1, passing +1 (GK; Sweeper Keeper (Defend)); stamina +2, work rate +2, crossing +2, pace +1 (DL, DR; Full-Back (Support), Wing-Back (Support) [DL/DR]); passing +2, technique +1, decisions +1, composure +1 (DC; Ball-Playing Defender (Defend)); positioning +2, concentration +2, anticipation +1 (DC; Central Defender (Defend)); pace +2, anticipation +2, acceleration +1, concentration +1 (DC; Central Defender (Cover)); positioning +2, concentration +2, decisions +1, teamwork +1, work rate +1 (DM; Defensive Midfielder (Defend)); work rate +2, stamina +2, off the ball +2, anticipation +1 (MC; Box-to-Box Midfielder (Support)); passing +2, decisions +2, teamwork +2, first touch +1, work rate +1 (MC; Central Midfielder (Support)); technique +2, vision +2, passing +2, first touch +2, flair +2, off the ball +1 (AML; Trequartista (Attack) [AML/AMR]); passing +2, vision +2, technique +2, first touch +2, decisions +2, off the ball +1 (AMR; Advanced Playmaker (Attack) [AML/AMR]); work rate +2, stamina +2, off the ball +2, acceleration +2, anticipation +1, finishing +1 (ST; Pressing Forward (Attack))
- **Expects at least (tapers below):** stamina 8 (DL, DR; Full-Back (Support), Wing-Back (Support) [DL/DR]); work rate 8 (DL, DR; Full-Back (Support), Wing-Back (Support) [DL/DR]); crossing 7 (DL, DR; Full-Back (Support), Wing-Back (Support) [DL/DR]); passing 8 (DC; Ball-Playing Defender (Defend)); decisions 7 (DC; Ball-Playing Defender (Defend)); positioning 7 (DC; Central Defender (Defend)); pace 8 (DC; Central Defender (Cover)); anticipation 8 (DC; Central Defender (Cover)); positioning 8 (DM; Defensive Midfielder (Defend)); concentration 8 (DM; Defensive Midfielder (Defend)); work rate 8 (MC; Box-to-Box Midfielder (Support)); stamina 8 (MC; Box-to-Box Midfielder (Support)); passing 7 (MC; Central Midfielder (Support)); decisions 7 (MC; Central Midfielder (Support)); teamwork 7 (MC; Central Midfielder (Support)); technique 8 (AML; Trequartista (Attack) [AML/AMR]); vision 8 (AML; Trequartista (Attack) [AML/AMR]); passing 8 (AML; Trequartista (Attack) [AML/AMR]); first touch 8 (AML; Trequartista (Attack) [AML/AMR]); passing 8 (AMR; Advanced Playmaker (Attack) [AML/AMR]); vision 8 (AMR; Advanced Playmaker (Attack) [AML/AMR]); technique 8 (AMR; Advanced Playmaker (Attack) [AML/AMR]); first touch 8 (AMR; Advanced Playmaker (Attack) [AML/AMR]); decisions 8 (AMR; Advanced Playmaker (Attack) [AML/AMR]); work rate 8 (ST; Pressing Forward (Attack)); stamina 8 (ST; Pressing Forward (Attack)); acceleration 8 (ST; Pressing Forward (Attack)); off the ball 8 (ST; Pressing Forward (Attack))
- **Needs:** Two genuinely high-level creators suited to receiving from wide starting positions and operating between the lines; A left full-back and supporting right wing-back with the stamina, work rate and crossing to provide nearly all of the natural width; A disciplined holding midfielder who protects the centre-backs rather than chasing the ball; A high-engine Box-to-Box midfielder and reliable supporting midfielder to carry the defensive and connective workload; A Pressing Forward with the work rate and movement to stretch the defence and lead pressure; Enough passing quality in the first build-up line to get the ball to the creators consistently
- **Instructions:** Fairly Wide; Shorter Passing; Higher Tempo; Play Out Of Defence; Work Ball Into Box; Counter-Press; Hold Shape; Distribute Quickly; Distribute To Centre Backs; Take Short Kicks; Higher Line of Engagement; Standard Defensive Line; More Urgent Pressing
- **Avoid when:** When the full-backs lack stamina or crossing, the holding midfielder cannot defend space reliably, or the opposition can press the first build-up line so effectively that the two creators rarely receive facing goal

### Wing Play 4-4-2

`wing_play_442` · 4-4-2 · Positive · Wing Play

A width-first 4-4-2 designed to create repeated crossing opportunities through wingers and overlapping full-backs for two complementary forwards.

- **Goal:** Goalkeeper (Defend)
- **Defence:** Full-Back (Support) ×2, Central Defender (Defend) * ×2
- **Midfield:** Winger (Support) [ML/MR] ×2, Central Midfielder (Defend), Deep-Lying Playmaker (Support) [MC]
- **Attack:** Target Man (Attack), Advanced Forward (Attack) *

- **Leans on:** teamwork +1 (whole team); positioning +1, concentration +1 (DC; Central Defender (Defend), Central Defender (Cover)); stamina +2, crossing +2, work rate +1, pace +1 (DL, DR; Full-Back (Support)); crossing +3, pace +2, acceleration +1, dribbling +1 (ML, MR; Winger (Support) [ML/MR]); positioning +2, teamwork +1, work rate +1, concentration +1 (MC; Central Midfielder (Defend)); passing +2, vision +2, first touch +1, decisions +1 (MC; Deep-Lying Playmaker (Support) [MC]); jumping reach +3, strength +3, heading +2, bravery +1 (ST; Target Man (Attack)); acceleration +2, pace +2, off the ball +2, anticipation +2 (ST; Advanced Forward (Attack)); off the ball +3, anticipation +3, acceleration +1 (ST; Poacher (Attack))
- **Expects at least (tapers below):** stamina 8 (DL, DR; Full-Back (Support)); crossing 7 (DL, DR; Full-Back (Support)); crossing 8 (ML, MR; Winger (Support) [ML/MR]); pace 7 (ML, MR; Winger (Support) [ML/MR]); positioning 8 (MC; Central Midfielder (Defend)); passing 8 (MC; Deep-Lying Playmaker (Support) [MC]); vision 7 (MC; Deep-Lying Playmaker (Support) [MC]); jumping reach 9 (ST; Target Man (Attack)); strength 8 (ST; Target Man (Attack)); heading 8 (ST; Target Man (Attack)); acceleration 8 (ST; Advanced Forward (Attack)); pace 8 (ST; Advanced Forward (Attack)); off the ball 8 (ST; Advanced Forward (Attack)); off the ball 9 (ST; Poacher (Attack)); anticipation 8 (ST; Poacher (Attack))
- **Needs:** Wingers with reliable crossing and enough pace to create separation on the outside; Full-backs with the stamina and delivery to overlap repeatedly without destroying the defensive shape; A central midfielder disciplined enough to cover the wide attacks; A distributor capable of moving possession quickly toward the flanks; An aerially strong Target Man to make repeated crossing worthwhile; A mobile second striker who attacks the space around the Target Man
- **Instructions:** Overlap Left; Overlap Right; Fairly Wide; Slightly More Direct Passing; Higher Tempo; Counter
- **Avoid when:** Against tall centre-backs who win the crosses, or when your full-backs cannot get back, since the flanks are left open

`*` marks a slot whose role the optimiser may swap for a declared alternative.
