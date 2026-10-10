# Hungerford Town FM2020 — Tactical Diagnosis and Experimentation Reference

**Prepared:** 10 October 2026  
**In-game reference fixture:** Hampton & Richmond Borough (away), 20 October 2020  
**Club:** Hungerford Town, Vanarama National League South  
**Purpose:** Preserve our findings, uncertainties, methodological lessons and next steps so that future tactical decisions can be evidence-led without turning the save into an endless experiment.

## Executive summary

1. **Use estimated attacking shot value minus estimated defensive shot value as the primary tactical comparison.** It measures the net chance-generation advantage, not just goals scored or the number of wins. Your app calls this `balance`. Higher is better.
2. **The Vertical 4-4-2 currently looks more promising than the cautious Ball-Winning Counter 4-3-3.** But the 4-3-3 improved sharply when switched from Cautious to Positive, so its formation alone has not been shown to be the problem.
3. **The leading 4-4-2 mentalities are Balanced and Attacking, with no decisive winner yet.** Against Hampton, Balanced averaged **+0.49** estimated net goals per game and Attacking **+0.83**. Their difference of **+0.34** is not sufficiently clear after only eight runs each.
4. **Balanced generated the superior clear-cut-chance (CCC) differential:** **+1.12** per game versus **+0.75** for Attacking. Attacking generated much more overall shot volume and attacking shot value. This disagreement is informative, especially because the shot-value estimates are not official FM20 xG.
5. **Observed goals and match results were much more variable than the underlying chance values.** Balanced went **7W–0D–1L**, whereas Attacking went **2W–3D–3L**, despite Attacking's higher estimated chance-value balance. Balanced conceded 3 goals against approximately 8.5 of estimated opposition shot value; Attacking conceded 14 against approximately 8.6. This gap may reflect randomness, chance-model miscalibration, differences in chance types and match situations, or a combination—not proven “luck.”
6. **We must not retroactively blame your earlier league results on Cautious mentality.** Your live management normally began Positive against weaker opponents, then switched to Balanced or Cautious when leading. The old match extraction did **not** capture these changes. The experiments instead held the chosen mentality for the full 90 minutes.
7. **The next efficient step is validation against another opponent**, ideally stronger and using a different formation, rather than endless replays against Hampton. Use the best-performing setups in the real season and continue collecting data.

---

## 1. Where this investigation began

Hungerford had fallen to around **10th**, below the standard expected for a promotion challenge. A series of league matches produced inconsistent attacking performances and frustrating results against teams you expected to beat.

**Recurring observations from the original match-by-match analysis:**

- **Woking, 1–1:** Hungerford managed **7 shots to Woking's 15**. The lone Advanced Forward attempted only one shot in 73 minutes.
- **Hampton & Richmond, original 2–2:** Hungerford led **2–0 after ten minutes**, but conceded twice, both from deliveries/crosses. Despite the draw, Hungerford's overall match statistics were comparatively strong: **14–9 shots, 7–5 shots on target, 2–0 CCCs**.
- **Hampton replay after changing defensive corners, 1–0 win:** The result improved but the performance worsened: **9–19 shots, 0–2 CCCs, 39% possession**. We could not conclude from one replay that the corner-defending change improved the team.
- **Late opposition pressure:** In a previous sample of 14 competitive games, Hungerford had **21 shots to opponents' 41 after minute 75**. Several late concessions followed crosses or wide deliveries. This raised a genuine game-management question, but the data was not controlled for scoreline or the mentality actually used.
- **Advanced Forward isolation seemed plausible:** In the Woking and two original Hampton match simulations, the starting striker produced **two shots over approximately 240 minutes**. That observation was real, but it was too small a sample to conclude that the 4-3-3 or the individual striker was intrinsically unsuitable.

We initially discussed changing a 4-3-3 Ball-Winning Midfielder to **CM(A)**, more attacking midfield support, defensive set pieces, full-back duties and potentially returning to the familiar **Vertical 4-4-2**.

**Key correction:** Our earliest tactical interpretations lacked recorded *mentality*. In your actual management you generally started **Positive** against weaker teams, then reduced mentality when two goals ahead or when defending a one-goal lead around minutes 60–70. Therefore, we cannot cleanly ascribe the earlier poor results to a particular mentality or isolate the effects of those in-game switches.

---

## 2. Why we moved to repeated-match experiments

One FM result is a noisy observation: the same tactical setup can dominate chances and lose, or be outplayed and win. The two Hampton games above illustrate this perfectly.

Rather than continuously reshuffling formations during the league season, you used your extraction/analytics app to run **replays of one pre-match fixture** with different tactical configurations. The assistant manager handled the match, preserving your selected tactic and mentality, which made the process fast enough to run several variants.

### What was controlled, and what was not

- **Common scenario:** Hampton & Richmond, away; Hampton were **19th** and Hungerford were **10th** at kickoff. The opponent used a **4-4-2** in these tests.
- **Eight replays per group:** Six groups, **48 total experimental matches**, all from the same fixture context.
- **Formation or mentality varied between groups:** For the 4-3-3, changing Cautious to Positive kept the same CM(A) configuration. For the Vertical 4-4-2, mentality varied across Cautious, Balanced, Positive and Attacking.
- **Assistant manager management:** AM-controlled substitutions and other permitted decisions; no manual mid-game mentality switching in these experimental runs.
- **Not perfectly controlled:** Match randomness, scoreline, red cards, AM substitutions and game-state effects can differ across runs. The 4-3-3 and 4-4-2 necessarily use different shapes, roles and player deployments.
- **Tactical familiarity:** Existing, trained tactics are more appropriate comparison candidates than completely unfamiliar new formations. Familiarity may matter when later assessing a newly built tactic.

### Naming note

The app's group names use **`443`** for the 4-3-3 Counter experiments; this appears to be a naming convention/typo. The actual tactic label is **Ball-Winning Counter 4-3-3 DM**. The `CM(A) Base` group's note specifies that **BWM was replaced by CM(A)**. The Positive version's note confirms it is the same experiment except for the mentality change.

---

## 3. Metric definitions and how to read them

### Primary metric: net estimated shot value

```text
Attack = estimated goals' worth of our shots per game
Defence = estimated goals' worth of opposition shots per game
Net balance = Attack - Defence
```

For example, **1.91 attacking value − 1.08 conceded value = +0.83 net balance**.

Your `worth` values use the valuation available from the match-page-based data and are estimated from the app's available sample. **FM2020 does not report official expected goals.** The experiment export noted **63 matches** contributing to chance valuations at the time. Treat the figures as a useful but imperfect *shot-quality model*, not ground truth.

The aim is to maximise net chance generation, rather than maximise attacks alone or minimise opposition chances alone. More aggressive mentality can create additional chances **and** change how much pressure your side faces; the defensive cost is something to *measure*, not presume from the mentality label.

### Secondary metrics

| Metric | Why it matters | Caution |
|---|---|---|
| **Clear-cut-chance differential** (`CCC for − CCC against`) | Cross-check for especially dangerous chances | Coarse FM category; discards information from less obvious shots |
| **Shot differential** | Identifies who is producing sustained pressure | A high-volume tactic can generate many low-quality attempts |
| **Striker shots and CCCs** | Shows whether attacking players are involved in productive chances | Count both striker positions in a 4-4-2; don't judge one isolated match |
| **Performance while level / ahead / behind** | Separates starting effectiveness from game-state behaviour | Samples can be very unequal; e.g., winning sides spend less time level |
| **Goals, W–D–L and points per game** | What matters in the actual save | Especially noisy over eight matches |
| **Pass completion, possession, headers and deliveries** | Diagnostic clues about how the tactic works | Not intrinsic goals: low possession can be compatible with strong counterattacking play |
| **Run-to-run spread and standard error** | Helps distinguish reproducible improvements from noise | Small samples and shared-fixture effects limit certainty |

**Do not mechanically add a CCC “bonus” to net shot value.** Those chances already contribute to shot value, so doing so risks double-counting. Use CCC differential as an independent validation or warning signal that your shot-value model may be missing something.

Also, **maximising average net shot value is not mathematically identical to maximising expected league points** in every situation. Win/draw probabilities depend on the distributions of goals, and that can matter when playing a much stronger or weaker opponent. Net shot value is the most practical *primary* test metric here; points remain an important outcome check.

---

## 4. Full Hampton experiment results

Each row represents **eight replays**, with all rates calculated per game. In the `Attack / Defence` column, bigger Attack is better and smaller Defence is better.

| Tactical experiment | W–D–L | Goals for–against | Shots for–against | CCC for–against | Attack / Defence value | **Net balance** | SE of balance |
|---|---:|---:|---:|---:|---:|---:|---:|
| 4-3-3 CM(A), **Cautious** | 3–0–5 | 0.75–1.50 | 9.38–12.75 | 0.75–1.13 | 1.03 / 1.56 | **−0.52** | 0.29 |
| 4-3-3 CM(A), **Positive** | 2–4–2 | 1.13–1.25 | 14.88–11.00 | 0.75–1.00 | 1.50 / 1.22 | **+0.28** | 0.18 |
| Vertical 4-4-2, **Cautious** | 3–5–0 | 1.63–1.00 | 13.50–11.38 | 0.38–0.88 | 1.29 / 1.24 | **+0.05** | 0.14 |
| Vertical 4-4-2, **Balanced** | **7–0–1** | **1.88–0.38** | 12.25–10.88 | **1.50–0.38** | 1.55 / 1.06 | **+0.49** | 0.14 |
| Vertical 4-4-2, **Positive** | 4–2–2 | 1.75–1.38 | 14.00–12.75 | 1.25–1.13 | 1.54 / 1.42 | **+0.12** | 0.25 |
| Vertical 4-4-2, **Attacking** | 2–3–3 | 1.88–1.75 | **16.63–9.88** | 1.50–0.75 | **1.91 / 1.08** | **+0.83** | 0.24 |

*Figures rounded; the small differences between 1.12 and 1.13, or 16.62 and 16.63, reflect rounding the eight-run averages. Pairs are always Hungerford / opposition. The `on_goal` field in the export is not always identical to the FM match panel's official shots-on-target statistic; do not conflate them.*

### Main contrasts

**4-3-3 Cautious → Positive:** Net balance improved **−0.52 → +0.28**, a change of **+0.80 per match**. Shot production rose from **9.38 to 14.88**, while opposition shot volume fell from **12.75 to 11.00**. This is evidence that the original 4-3-3's *mentality* mattered enormously against Hampton. It does not prove the 4-3-3 formation is inherently weak.

**4-4-2 Cautious → Balanced:** Net balance improved **+0.05 → +0.49**. CCC differential improved **−0.50 → +1.12** per game. The 7–0–1 record is encouraging, but the chance metrics provide the stronger underlying case.

**4-4-2 Balanced → Positive:** Total shots increased, but net shot value fell **+0.49 → +0.12** because defensive value conceded rose **1.06 → 1.42**. One Positive replay had a sending-off; it was included in the eight-run summary but excluded from score/period breakdowns. Excluding that run gives approximately **+0.31** net balance across the remaining seven—better, but still not enough to crown Positive.

**4-4-2 Balanced → Attacking:** Attack value rose **1.55 → 1.91** (**+0.36**), while defensive value conceded barely changed **1.06 → 1.08** (**+0.02**). Hence the net estimate improved **+0.49 → +0.83**. This is the counterintuitive finding: a more attacking mentality did **not**, in this sample and by this metric, translate into materially greater opposition shot value.

---

## 5. Why Balanced versus Attacking is still unresolved

### Case for Balanced 4-4-2

- **Best recorded results:** **7W–0D–1L**, scoring 15 and conceding only 3 across eight replays.
- **Clear-cut-chance quality:** **1.50 CCC created and only 0.38 conceded per game** (differential **+1.12**).
- **Consistency:** Net shot-value balance was positive in **all eight matches**; the observed balance spread was **0.39**.
- **Defensive control on the CCC measure:** Fewer particularly dangerous chances were conceded than in Attacking.

### Case for Attacking 4-4-2

- **Highest net estimated shot value:** **+0.83**, versus Balanced's **+0.49**.
- **Highest attack value:** **1.91**, versus **1.55**.
- **Much more shot volume:** **16.63 shots per game**, versus **12.25**; Hampton's shot volume was slightly *lower* (**9.88** versus **10.88**).
- **Greater striker involvement:** Fundi took **38 shots** and Challis **29**, versus **25** and **14** in Balanced.
- **Still positive in seven of eight runs:** The mean was not driven by uniformly poor matches rescued by a single huge victory, although its outcome variability was greater.

### The uncertainty

The difference **+0.83 − +0.49 = +0.34 estimated goals per match** is only about **1.2 combined standard errors** (`sqrt(0.24² + 0.14²) ≈ 0.28`). It is a promising signal, **not a reliable winner** after eight runs per mentality.

The estimated balances also disagree with the CCC ranking: Attacking had **1.50–0.75 CCC**, while Balanced had **1.50–0.38 CCC**. Attacking's extra estimated value seems to come from the larger number and valuation of shots *outside* the CCC category rather than additional CCCs.

### Why the goals conceded differ so dramatically

| Eight-run total | Balanced | Attacking |
|---|---:|---:|
| Actual goals conceded | **3** | **14** |
| Estimated opposition shot value | **~8.5** | **~8.6** |
| CCCs conceded | **3** | **6** |

These are not mutually consistent pictures of defensive effectiveness. Plausible contributors are finishing/save variation, chance-model shortcomings, a genuine increase in very dangerous chance types (as the CCC count suggests), set-piece/cross vulnerabilities, and different score states. Attacking conceded **eight goals classified as crosses**, versus **two** in Balanced. A red-card match also appears in the Attacking group and should be considered separately in sensitivity analysis.

**Avoid the categorical claim that Attacking was “just unlucky.”** A more precise statement is that the available shot-value model does not explain the very large difference in observed goals conceded. This merits further observation and possible model calibration.

### Game-state caution

Balanced spent **519 minutes ahead** and only **142 minutes level** in its score-state breakdown. Attacking spent far longer level (**444 minutes**, with a red-card match omitted from that breakdown). Since the formations were often playing in *different score states*, comparing total-match statistics alone can obscure tactical behaviour. Score-state statistics help, but small and unequal denominators make them unreliable as stand-alone proof.

---

## 6. Player- and role-level lessons

### Fundi is not necessarily the underlying problem

| Experiment | Fundi shots / 90 | Goals (eight games) | CCCs (eight games) |
|---|---:|---:|---:|
| 4-3-3 Cautious CM(A) | 2.07 | 1 | 3 |
| 4-3-3 Positive CM(A) | **4.85** | 5 | 3 |
| 4-4-2 Balanced | 3.12 | 5 | 7 |
| 4-4-2 Positive | 3.62 | 4 | 4 |
| 4-4-2 Attacking | 4.75 | **7** | **8** |

He was comparatively isolated in particular original matches, but across controlled replays he generated ample shots in the **Positive 4-3-3** and **Attacking 4-4-2**. Consequently, *poor service and tactical circumstances* are more plausible explanations for his occasional disappearance than a blanket assertion that he cannot lead the line.

Aerial contests remain a concern: he often wins only about a quarter to a third of his headers. However, these totals include unspecified types of aerial challenge; without event origins, we cannot prove that goalkeeper distribution or direct balls to him are the main cause. His limited aerial strength argues for examining *where* these contests originate, not automatically changing every passing instruction.

### Challis and two-striker structure

In the **Balanced 4-4-2**, Fundi scored **5** and Challis **4** in eight games. In **Attacking**, Fundi scored **7** and Challis **3**. The two-forward structure provides an effective outlet and distributes goal threat. Challis has been used as **Pressing Forward (Support)** alongside Fundi as **Advanced Forward (Attack)**.

The results do not demonstrate that the 4-4-2 must outperform all 4-3-3 variants or every other opponent. They do show that the established partnership is productive in this particular matchup.

### Lynch as CM(A)

In the eight-run **Cautious 4-3-3** baseline, David Lynch produced **8 shots, no goals, no assists and one key pass**. Under **Positive 4-3-3**, he produced **14 shots, no goals, no assists and two key passes**. His average rating stayed around **6.46–6.47**. This is not compelling attacking contribution, but it also does not isolate whether the problem is the player, the role, the team instructions or the opponent.

**Implication:** do not retain CM(A) solely because it sounds more attacking. It should earn its place through repeatable chance creation, forward involvement and team-level net balance.

### Wide play and crosses

Crosses are prominent at both ends of the pitch. The 4-4-2 scored many goals from crosses, but cross-related concessions were also common, especially under Attacking. This warrants focused analysis of **source flank, cross origin, marking responsibility, open-play versus dead-ball deliveries, and score state**—not an automatic instruction to make every full-back more defensive.

---

## 7. Mentality: the principle we should actually use

The intuitive hypothesis is understandable:

- **Against weaker opponents:** More attacking intent might exploit superior players and produce more chances.
- **Against stronger opponents:** More caution might limit dangerous transitions and protect a result.

But mentality can change **both sides of the equation**. More attacking pressure might keep the ball away from our defensive third, reducing opposition possession and chances. Conversely, committing extra players forward might expose us to counterattacks. Neither defensive effect follows mechanically from the word “Attacking.”

**Decision principle:** Choose the mentality that offers the best *measured net chance balance against that opponent*, subject to the uncertainty of the estimates and the objective of earning league points. Do not assume a stronger opponent automatically requires Cautious or that a weaker opponent automatically requires Attacking.

We have evidence only from **a weaker, away 4-4-2 opponent**. We do **not** yet know how the ordering changes against a top-third opponent, a possession-heavy 4-3-3, a 4-2-3-1, a low block or a counterattacking side.

Your live policy of starting Positive against weaker sides and dropping to Balanced/Cautious when two goals ahead or narrowly ahead late on remains **untested as a policy**. Fixed-mentality 90-minute replays cannot establish the advantage of changing mentality at minute 60–70. Likewise, a 90-minute Cautious average is not a valid estimate of the cost or benefit of being Cautious for only the final 20 minutes.

---

## 8. What to do now: a bounded, practical programme

### Short-term provisional selection

**Current default:** **Vertical 4-4-2 Balanced**. It has the strongest measured CCC balance and the steadiest positive shot-value outcomes, with existing player familiarity. This is a provisional, risk-conscious choice—not proof it is optimal.

**Primary challenger:** **Vertical 4-4-2 Attacking**. The strongest *estimated* net shot-value figure makes it worth validating, particularly against weaker opponents and when a goal is needed.

**Secondary formation candidate:** **4-3-3 Positive (with CM(A))**. It is much better than its Cautious equivalent, though it did not clearly beat the best 4-4-2 variants in this fixture. Retaining it for opponents that demand a different shape may be useful.

**Deprioritise:** Cautious 4-3-3 CM(A) against weaker teams, and further extensive testing of 4-4-2 Positive at Hampton unless a later result specifically demands it. Do not equate “deprioritise against Hampton” with “never use Cautious in any match.”

### Next experiment: transferability, not Hampton overfitting

Run the **same two leading tactics against a different opponent**:

| Test | Replays | Objective |
|---|---:|---|
| Vertical 4-4-2 **Balanced** | 8 | Baseline performance against a tougher/different setup |
| Vertical 4-4-2 **Attacking** | 8 | Does extra offensive value persist, and does defensive exposure increase? |

Ideal opponent: **top-third** and preferably playing something **other than 4-4-2**. Keep venue, starting availability, set pieces and assistant-manager instructions consistent *within that fixture's comparison*. A different matchup will teach more about generalisation than another long Hampton-only batch.

Compare in this order: **net shot-value balance, attacking and conceded value separately, CCC differential, per-run dispersion, score-level phases, red-card sensitivity, then actual goals and points**.

### When to run an extended experiment

Do **not** automatically extend every close result. Extend only when:

1. Two candidates remain practically close but choosing between them would change how you play;
2. An apparent advantage is reasonably large (roughly **0.3–0.5 net estimated goals/game**) but uncertain; or
3. The result conflicts sharply with CCC data or observed goals and we need to identify a source of model error.

In that case add **six to eight runs per leading candidate**, ideally using another opponent or the most relevant matchup. Review estimates after each batch, rather than committing to an arbitrary number of runs to achieve statistical significance.

### Stop rule and return to playing

After the **16-replay second-opponent validation**, select a working default and play **six to ten actual league matches** before considering a fresh major tactical tournament. Continue extracting matches automatically. Review only if the competitive evidence shows a repeated, significant weakness: sustained negative chance balance, too few striker chances, repeat cross vulnerability, or an opponent-formation mismatch.

Over time, build a modest matchup matrix for **weaker / comparable / stronger** opponents and for different formations—using actual season play as evidence wherever possible. No need for a huge grid of every formation × mentality × opponent combination.

### In-match management until better evidence exists

- Start from the **best-tested baseline** for the opponent rather than a universal “always Positive” rule.
- Do not switch mechanically to **Cautious** merely because the clock has reached minute 65. Check whether the opponent is creating dangerous chances, whether Hungerford still has an attacking outlet, and whether the switch will surrender territory.
- A one-step reduction (Attacking → Positive or Positive → Balanced) may be a reasonable match-management trial, but our experiments have **not** verified an optimal closing-out policy.
- Reserve **Very Attacking** for a possible later test or late chasing situation; we have not compared it in the automated programme.
- Address defensive corners and crosses where actual chances show a recurring problem, but avoid changing several tactical controls simultaneously and then attributing the result to one of them.

---

## 9. Analytics-app improvements worth prioritising

You already have rich match extraction; the next gains are mainly about *preserving context and comparing like with like*.

**High-value, modest-effort additions:**

1. **Record tactical state over time:** active tactic, formation, **mentality**, role/duty adjustments and major team-instruction changes, with match-minute timestamps. This is the largest missing feature for interpreting actual managed games.
2. **Persist a reproducible experiment specification:** fixture/save point, group note, selected XI, mentality, tactic version/hash, set-piece setup, assistant-manager delegation, and any opposition instructions.
3. **Separate the main eight-run averages from sensitivity analyses:** red-card matches, early injuries and extreme outliers should stay in the raw record but also be visible in an alternative comparison.
4. **Show estimated attack and defence separately**, as well as `balance`, CCC differential, sample counts, standard error, and the individual run distribution. Never rank variants on W–D–L alone.
5. **Label match states and minutes:** level, ahead, behind; separately show first 30 minutes and later phases. Suppress or flag per-90 rates based on tiny durations (e.g., a minute spent behind is not informative).
6. **Classify chance origins:** set piece versus open play, crosses, flank and origin zone, passer/crosser, target, and ideally ball recovery/distribution route. This would help distinguish service problems from individual striker limitations and identify exactly where defensive deliveries go wrong.
7. **Validate the shot-value model:** calibration by chance type and shot context; compare sum of estimated values with realised goals over much larger samples. The disagreement between Balanced and Attacking defending is an excellent test case.
8. **Opponent-context metadata:** strength/table position, formation, home/away and ideally formation used during different match periods. This supports later matchup analysis without exhaustive simulation.

A future automated recommendation engine could flag changes only when effect size, sample size and tactical context jointly support them. It should distinguish **observations** (“striker shot rate fell”) from **hypotheses** (“direct distribution may be isolating him”) and from **tested interventions** (“mentality switch improved net chance balance”).

---

## 10. Conclusions: known, likely, and still unknown

### Fairly well supported (for this Hampton fixture)

- **4-3-3 Cautious CM(A) underperformed badly** and improved materially under Positive.
- The **Vertical 4-4-2** is a promising foundation and already makes good use of the **Fundi AF(A) / Challis PF(S)** partnership.
- **Balanced 4-4-2** generated consistently favourable net estimated chance value and the best CCC differential.
- **Attacking 4-4-2** generated the greatest overall offensive shot value and highest net estimated chance-value balance, *without a corresponding increase in estimated conceded value* in this eight-run sample.

### Reasonable, but not established

- Balanced may be the **more robust/safer default**; Attacking may be better for **maximising chances against weaker opposition**.
- Attacking's poor W–D–L may be partly explained by finishing/save variability; the shot-value model may also be missing genuine differences in danger.
- Wide deliveries, aerial mismatches, defensive corners and poor possession transitions may still contribute materially to disappointing live-season performances.
- Some of the late collapses may have involved game-state decisions rather than the starting formation alone.

### Still unknown

- Which of **Balanced versus Attacking** produces the stronger *true* chance balance and expected points across varied opponents.
- Whether either tactic is preferable against **stronger teams** or **different shapes**.
- Whether changing mentality **mid-match** when ahead helps or harms; earlier live-match mentality switches were not captured.
- Whether the `worth` model is sufficiently calibrated to resolve close tactical comparisons, particularly when the CCC metrics disagree.
- Whether squad changes, player roles or instructions can improve the system more than mentality adjustments after the baseline is selected.

## Final decision rule

> **Use experiments to identify strong, repeatable tactical foundations; use net estimated chance value as the primary score; cross-check it against CCCs and outcomes; test against more than one opponent; then return to playing FM.**
>
> **For now, keep Balanced Vertical 4-4-2 as the provisional default and Attacking Vertical 4-4-2 as the leading challenger. The next useful evidence is another opponent—not an endless Hampton replay loop.**

---

## Appendix A — Experiment group names and provenance

| Stored experiment group | Interpretation | Run IDs |
|---|---|---|
| `H&R - 443 Counter CM(A) Base` | Ball-Winning Counter 4-3-3 DM, CM(A), **Cautious** | 1–8 |
| `H&R - 442 Vertical Balanced` | Vertical 4-4-2, **Balanced** | 9–16 |
| `H&R - 442 Vertical Cautious` | Vertical 4-4-2, **Cautious** | 17–24 |
| `H&R - 443 Counter CM(A) Positive` | Same CM(A) 4-3-3 with **Positive** mentality | 25–32 |
| `H&R - 442 Vertical Positive` | Vertical 4-4-2, **Positive** | 33–40 |
| `H&R - 442 Vertical Att` | Vertical 4-4-2, **Attacking** | 41–43 and 45–49 (ID 44 is not present in this export) |

**Export provenance:** The six `fm-analytics/experiment-export` JSON files supplied in this discussion, alongside earlier individual match exports and the 14-match season sample. The underlying saved matches and experiment group metadata remain the definitive source for any subsequent recalculation.

## Appendix B — Reusable checklist for each new experiment

- [ ] Define the *specific question*: mentality, formation, role change, or set piece—not all at once.
- [ ] Select one save/fixture and record opponent, venue and likely formation.
- [ ] Keep all non-target variables as stable as practical; record any unavoidable differences.
- [ ] Run a small matched batch (usually six to eight per option).
- [ ] Compare **Attack**, **Defence**, **Balance**, **CCC differential**, shots and run-to-run spread.
- [ ] Check the score-state splits and whether red cards distort the average.
- [ ] Look at the actual attacking players and chance origins, not just team shots.
- [ ] Treat results and goals as corroboration rather than the first ranking criterion.
- [ ] Ask whether a finding generalises to at least one other opponent.
- [ ] Make a decision, play the save and revisit only when new evidence justifies it.
