# Phase 08 — Opposition analysis

## Planning status

Outline only. The available match history and opposition visibility will shape
the report far more than an up-front feature wish list.

**Update, 3 October 2026:** [league team comparison](../../league-comparison-plan.md)
now has a concrete plan: verified league rosters, ranked players, best-XI
floor/central/ceiling optimisation through the existing scorer, and a league
overview. This personnel-comparison slice needs verified membership and player
knowledge, rather than the match-history prerequisites for the pre-match
reports below. Actual opponent lineup and tendency forecasting remain deferred.

The first implementation slice now supports lower/central/upper XI reselection
through the shared scorer. A passive identity inventory read stable roster
vectors for 22 National League South clubs without reading external attributes
or positions. Dated capture history, team/player drilldowns, and a league
overview now work with supplied captures, using a bounded background job.
Live membership, rosters, visible attributes and FM's own visible rival
positions are now read by `tools/fm20_league_capture.py` (and the League
page's read button), pending a check of a few players and squads against FM's
screens; see the plan's "Live league capture" record.

**Update, 11 October 2026:** the first pre-match report is built; see the
[opponent report](../../opponent-report.md). It covers 08.1 (the last 10, 20
or 40 competitive matches before the fixture, with counts and what FM's
archive lacks), 08.2 (formations, likely XI from the last five), 08.3 (how
goals are scored and conceded, by flank, line and period, against the league's
share, and style figures with ranks), 08.4 (suggested opposition instructions
from declared rules, kept apart from the evidence) and 08.5 (the Opponent page
and `fm-matches opponent`). A report never uses a match played on or after its
day. 08.6, scoring a report afterwards, is still open.

## Outcome

Generate a concise pre-match opposition report that separates observed facts,
uncertain projections, and rule-based suggestions.

## Prerequisites

- Trusted opponent and match histories
- Time-correct features that use only information available before the match
- A defined target fixture and our available squad context

## Subphases

### 08.1 — Opponent sample selection

Choose relevant prior matches with explicit recency, competition, home/away,
manager, and formation-change rules. Show sample size and coverage.

### 08.2 — Shape and personnel profile

Estimate likely formation, lineup, roles, substitutions, and important absences
with confidence levels rather than presenting the last match as certainty.

### 08.3 — Tendency detection

Describe repeatable patterns such as attack side, possession, pressing proxies,
chance creation, transition exposure, set pieces, and aerial performance only
where supported by available data.

### 08.4 — Strengths, weaknesses, and matchups

Compare opponent tendencies with our squad/shape. Keep descriptive evidence
separate from the rule that turns it into a suggested response.

### 08.5 — Report delivery

Produce a short report containing evidence window, confidence, key threats,
likely setup, opportunities, and questions that remain unknown.

### 08.6 — Evaluation

After the match, score formation/lineup forecasts and whether claimed tendencies
persisted. Record usefulness feedback without rewriting the original report.

## Phase exit criteria

- Reports are reproducible from a pre-match capture.
- Every claim links to evidence, sample size, and uncertainty.
- Forecast accuracy and report usefulness can be evaluated after the match.
- No post-match information leaks into regenerated pre-match reports.

## Deferred

- Claiming causal weaknesses from small samples
- Fully automated tactical recommendations
- Computer-vision analysis of the match engine
