# Decision-support design: where we are and where we are going

This document takes a whole-system view of the five decisions the manager
actually wants help with, states honestly which parts of the system already
serve them, and proposes the seams that let manual data now become automated
data later without rewriting the analytics.

It complements rather than replaces the [phase roadmap](phases/README.md).
The roadmap sequences *capabilities*; this document sequences *the manager's
questions* and shows which capability each one is really waiting on.

## The five target questions

| # | Question | Blocked on |
| --- | --- | --- |
| 1 | Best player for each position, and the best role for each player | Catalogue breadth, not analytics |
| 2 | Best tactics for this squad | Catalogue breadth, not analytics |
| 3 | Best tactic *now* vs. the one to aim for | Position familiarity (mostly plumbing), tactic familiarity (genuine research) |
| 4 | Where the squad lacks depth | Scope: depth is tactic-local, needs to be squad-wide |
| 5 | Scouting targets for our weaknesses | Phase 03 discoverability — the one genuinely blocked item |

The important conclusion is that **four of the five are not blocked on FM data
extraction.** They are blocked on the size of the football catalogue and on a
byte we already read and then discard. Question 5 is the only one that has to
wait for the discoverability gate, so it should not be allowed to hold up the
other four.

## Honest assessment of the current system

The analytics core is in better shape than the surface suggests.

What is genuinely solid and should not be rewritten:

- `score_role` keeps lower/central/upper bands instead of collapsing ranged and
  unknown observations into a number, and `information_gaps` already ranks what
  further scouting would change. This is the hard part and it is done.
- `evaluate_tactic` solves slot assignment exactly, and `_best_fit_state`
  optimises the mean/weakest blend rather than greedily filling slots.
- `assess_weaknesses` distinguishes structural, simultaneous, and temporary
  gaps. That taxonomy is the right one and question 4 builds directly on it.
- `compare_role_scores` already refuses to claim certainty when intervals
  overlap. That honesty is worth preserving as the catalogue grows.
- The visibility boundary is enforced consistently, with 254 passing tests
  at the time this was written (324 as of the 15 September implementation
  pass below).

What was actually holding the product back, as first written:

1. **The football catalogue is far too small.** Thirteen roles and four tactics.
   Questions 1–3 are search problems, and the search space is currently a
   rounding error against FM20's real role and formation set. Everything
   downstream is correct and uninteresting because of this.
2. **Facts we hold are being thrown away.** See the next section.
3. **There is no product surface.** A CLI text dump and two research HTML pages
   in `tools/`. Nothing lets the manager browse, sort, or compare.
4. **Manual data entry is framed as legacy.** The README calls HTML import
   "research-only" and "not the product workflow", yet it is the only path that
   can supply facts the probe cannot yet reach. That framing fights the
   near-term need.

All four are addressed in code as of 15 September 2026 -- see the status note
at the top of [Recommended sequence](#recommended-sequence) below for what
changed and, just as importantly, what still has not been run against a live
FM20 process.

## The unlock we already own

[`tools/fm20_linux_probe.py:406`](../tools/fm20_linux_probe.py#L406) reads the
full array of raw position-rating bytes, then collapses it:

```python
positions = tuple(
    code for code, rating in zip(POSITION_CODES, ratings) if rating >= 15
)
```

Every byte of familiarity granularity is discarded at that line.

Separately, [`tools/fm20_position_familiarity.py`](../tools/fm20_position_familiarity.py)
already maps those same raw bytes onto FM's own UI labels — Natural,
Accomplished, Competent, Unconvincing, Ineffectual — with a fail-closed band
table validated against the in-game position diagram. It is deliberately not
wired into anything.

**Question 3 is largely a plumbing job, not a research job.** The two halves
exist and have never been connected. Connecting them is the highest
value-per-hour item on the board, and it needs no new memory research beyond
filling the two acknowledged band gaps (raw 2–8 and 17–18) by checking a couple
of players' position diagrams in FM.

Note also that the current `>= 15` cut is *not* FM's own eligibility rule — it
is an approximation, and `tools/fm20_field_workbench.py:473` says so. Today a
Competent full-back and a Natural full-back are indistinguishable to
`score_player_for_slot`, while an Unconvincing one is invisible to it entirely.

## Proposed architecture

Four layers, with one seam that carries all the "manual now, automated later"
weight.

```text
     probe        HTML import      manual file       fixture
        \              |               |               /
         +-------------+---------------+--------------+
                             |
                    field resolution          <- THE SEAM
                 (per field group, with per-field provenance)
                             |
                     SquadObservation
                             |
          versioned football catalogue (data, not code)
                             |
        role fit  ·  tactic fit  ·  depth  ·  recruitment
                             |
                      report objects
                        /         \
                     CLI          web app
```

### 1. Field resolution is per field group, not per source

Today a source is all-or-nothing: `linux-proton`, `fixture`, or an HTML overlay
bolted on in the CLI via `overlay_squad_export`. That is why partial automation
gives no partial benefit.

Instead, resolve each *field group* independently:

| Field group | Probe today | Realistic near-term source |
| --- | --- | --- |
| identity, club, date | yes | probe |
| readiness, availability | yes | probe |
| contract | yes | probe |
| attributes (41) | yes | probe |
| positions | approximated | probe, once familiarity lands |
| position familiarity | **bytes already read, discarded** | probe — small change |
| footedness | no | manual or HTML until workbench proves it |
| player traits (PPMs) | no | manual or HTML |
| tactic familiarity | no | manual until workbench proves it |

Each group declares an ordered provider list. The winning provider is recorded
per field in the snapshot, so the app can always show what is still hand-fed.
Switching a group from manual to automated then becomes a configuration change
plus a contract addition, with no analytics change at all — which is exactly
the property asked for.

Concretely this means adding a `source` column alongside the existing
`player_attributes` rows in `persistence/store.py`, and promoting
`overlay_squad_export` from a CLI special case into a general merge over
provider outputs.

This also retires the "HTML import is research-only" framing. Manual import
becomes a legitimate, provenance-tagged provider — still never an oracle for
what is *visible*, which remains a separate and non-negotiable gate.

### 2. The catalogue becomes data

`analytics/catalogue.py` is 336 lines of Python literals for 13 roles and 4
tactics. Reaching a useful role and formation set means roughly 800–1,200 more
lines of the same, which is where this will stall.

Move role and tactic definitions to versioned data files loaded and validated
into the existing frozen dataclasses. Keep `CATALOGUE_VERSION`, keep every
existing invariant check in `FootballCatalogue.__post_init__` — only the
authoring medium changes. The existing tests keep working, and adding a role
stops being a code change.

### 3. Familiarity is a separate channel, and gives question 3 for free

`role_scoring.py:121` already states the principle: eligibility must not fold
familiarity into intrinsic quality. Keep that. Add a `FamiliarityPolicy`
alongside the existing `ReadinessPolicy` and `TacticFitPolicy`, applied as its
own penalty channel with its own version string, exactly as readiness is.

Then question 3 is two runs of the existing `recommend_tactic` and a diff:

- **effective** — familiarity applied; what to play on Saturday.
- **potential** — familiarity ignored; what to train towards.

A tactic that ranks far higher in *potential* than in *effective* is precisely
"the one we should be aiming for". The gap size is the retraining cost. No new
optimiser is needed.

Tactic (team) familiarity — FM's fluidity bars — is genuinely not yet available
and is the correct next target for the
[field-acquisition workbench](field-acquisition-workbench.md). Until it lands,
manual entry through the same seam is a reasonable interim provider.

### 4. Question 1 needs one small module

A role fit matrix over every player × every eligible role, reusing `score_role`
and `compare_role_scores`. Reads both ways round: best player per role, and
best role per player. This is a modest amount of code on top of what exists,
and it is the single most-used screen in the eventual app.

### 5. Question 4 lifts depth from tactic-scope to squad-scope

`assess_weaknesses` is scoped to one `TacticEvaluation`. That answers "where is
this XI thin", not "where is the squad thin". Run it across the shortlist of
tactics we would realistically play and aggregate: a slot that is thin in every
plausible shape is a real squad weakness; one thin only in a shape we will not
play is noise. The taxonomy and thresholds carry over unchanged.

## A scaling risk to measure before expanding the catalogue

`_assignment_states` is O(players × 2^slots × slots) — about 560k operations for
25 players and 11 slots, which is fine. But `_best_fit_state` re-runs that whole
DP once per distinct candidate score threshold, and there can be one threshold
per player/slot pairing. That is roughly quadratic in squad size on top of the
DP, per tactic.

At four tactics and 17 players this is invisible. At thirty tactics, a larger
squad, and a dual effective/potential run it may not be. **Measure it before
expanding the tactic library, not after.** If it bites, the fix is well
understood — binary search over thresholds, or memoising the DP across
thresholds — but it is worth knowing which regime we are in first.

## Application layout

The research pages in `tools/` (`fm20_monitor.py`'s `DASHBOARD`,
`fm20_attribute_page.py`) are diagnostics and belong where they are. They
should not become the product.

Propose a separate application under `src/fm_analytics/web/`, with pages that
map one-to-one onto the manager's questions:

| Page | Question | Content |
| --- | --- | --- |
| `/squad` | 1 | Roster, readiness, best role per player |
| `/roles` | 1 | Role fit matrix; best player per role, with certainty shown |
| `/tactics` | 2, 3 | Tactic ranking, effective vs potential, XI per tactic |
| `/depth` | 4 | Squad-wide depth chart and weakness list |
| `/recruit` | 5 | Briefs and shortlists, once Phase 03 opens |
| `/data` | — | Field coverage and provenance; what is still manual, and import |

The `/data` page is the one that is easy to skip and should not be. It makes the
seam visible: which facts are automated, which are hand-fed, how stale each is.
That is the page that tells us what to automate next.

One boundary rule matters here. The existing architecture note says analytics
consumes domain objects and never reads bridge JSON. A web layer makes that
easy to violate. So introduce plain report dataclasses between analysis and
presentation, and have **both** the CLI and the web app render the same report
objects. The CLI stays useful, the web app cannot grow its own private
analytics, and report shapes become testable without a browser.

## Recommended sequence

Ordered by value per unit of effort, with the research-blocked work last.
**Status as of 15 September 2026: steps 1–6 and 8 are implemented** --
probe/bridge/domain/persistence/CLI/web code, all with unit tests against
synthetic and fixture data. None of it has been run against a live FM20
process yet; that remains outstanding for every item below, including the
raw position-rating values the whole familiarity feature rests on. Steps 7
and 9 remain undone for the reasons already in the roadmap (new FM research;
Phase 03 gate).

**A — unblocks questions 1 and 3, needs no new FM research**

1. **Done.** Position familiarity is wired end to end: the probe emits the
   full raw 1-20 rating per position (`position_familiarity_map`, previously
   discarded after the `>= 15` eligibility check), the bridge validates and
   carries it, the domain `Player` and `PlayerSelectionInput` models hold it
   as an additive `positionFamiliarity` field, and `persistence/store.py` has
   a matching table. One simplification from the original plan, at the
   user's direction: it is used as a **continuous raw number**, not mapped
   onto FM's Natural/Accomplished/.../Ineffectual labels first, on the
   reasoning that those labels are themselves believed to be a projection of
   this same number. That sidesteps `fm20_position_familiarity.py`'s
   unconfirmed raw-value bands (2-8, 17-18) for scoring purposes; they would
   still matter if something later wants to *display* FM's own label.
2. **Done.** The catalogue moved from Python literals to versioned JSON
   (`analytics/data/catalogue.json`, loaded and validated by
   `catalogue.load_catalogue`), and grew from 13 roles / 4 tactics
   (`fm20-mvp-v2`) to 28 roles / 7 tactics (`fm20-mvp-v3`). Still well short
   of every FM20 role by design -- Phase 04 treats that as a non-goal.
3. **Done.** `analytics/role_matrix.py` answers both directions from one
   pass: `RoleMatrix.best_for_role` and `.best_role_for_player`, reusing
   `score_role`/`compare_role_scores` unchanged.

**B — makes the app real**

4. **Done, in reduced form.** Rather than a full report-object hierarchy
   across every analysis, `reporting.build_recommendation_bundle` is the one
   shared computation the CLI and a new stdlib-`http.server` web app
   (`fm_analytics.web`, `fm-web`) both call, so a number on a page and a
   number the CLI prints are the same number computed the same way. Pages:
   `/squad`, `/roles`, `/tactics` (with training targets), `/depth`, and
   `/data` for field coverage -- the last one deliberately still renders on
   an incomplete squad, since showing the gap is its whole purpose. Sources
   are composable functions (`fixture_provider`, `snapshot_provider`,
   `live_provider`, `html_overlay_provider`) rather than server special
   cases, which is the concrete form the "manual now, automated later" seam
   takes.

**C — questions 2 and 3 properly**

5. **Done.** `FamiliarityPolicy` plus
   `recommend_tactic_effective_and_potential`: the same tactic comparison run
   twice, once with the familiarity penalty applied and once with it forced
   to zero via `.potential()`. The gap between the two is surfaced as a
   `TrainingTarget` in both the CLI and `/tactics`.
6. **Measured, not yet acted on.** A synthetic benchmark (7 tactics, 28
   roles, dual effective/potential) measured 0.19s at 17 players, 2.1s at 25,
   3.0s at 30 on ordinary development hardware -- fine for a CLI command, a
   real constraint for a web page computing synchronously per request. See
   [Phase 05](phases/05-xi-optimisation/README.md#05.4). No optimisation has
   been attempted; the catalogue can keep growing for now.
7. Tactic familiarity through the workbench remains undone; it needs new FM
   research this session had no game access to perform.

**D — question 4, then 5**

8. **Done.** `analytics/squad_depth.py` aggregates `assess_weaknesses` across
   several tactics by *position* (not slot key, which is tactic-specific),
   distinguishing a position weak in every evaluated tactic from one weak in
   only some. Wired into both the CLI (`--recommend`) and `/depth`.
9. Recruitment stays blocked on the Phase 03 discoverable-player gate, as
   before.

Step 4's placement was a judgment call, not a settled roadmap change; see
[Phase 11](phases/11-automation-and-ui/README.md)'s note on it. Building it
early paid off in one concrete way already: `/data` immediately made the
`positionFamiliarity`-was-being-discarded gap (item 1) the obvious next thing
to fix, which is exactly the self-prioritising effect it was meant to have.

## Deliberately not now

Machine learning (Phase 10), opposition analysis (Phases 08–09), and match
history (Phase 07) all stay where the roadmap puts them. None of the five
questions needs them, and each would consume the effort that questions 1–4
actually require.
