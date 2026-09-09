# Delivery roadmap

This directory turns the vision in `initial_plan.md` into gated increments.
Each phase has a useful outcome of its own; later work should not begin merely
because code for the previous phase exists. Its exit criteria must be met and
the important findings recorded.

The roadmap is detailed where decisions are imminent and intentionally lighter
where experiments in earlier phases will change the design. Later phase plans
are hypotheses, not promises about implementation.

## Roadmap

| Phase | Outcome | Status | Detail | Depends on |
| --- | --- | --- | --- | --- |
| [00 — Data access](00-data-access/README.md) | Prove safe, repeatable access to a running FM20 save | In progress | Execution-ready | Existing fixture prototype |
| [01 — Extraction API](01-extraction-api/README.md) | Turn the spike into a stable, observable bridge | Planned | Execution-ready | 00 |
| [02 — Persistence](02-persistence/README.md) | Retain immutable, reproducible snapshots | Planned | Detailed | 01 |
| [03 — Information visibility](03-information-visibility/README.md) | Enforce what the human manager legitimately knows | Planned | Detailed | 00–02 |
| [04 — Squad analytics](04-squad-analytics/README.md) | Explain player suitability and squad depth | Planned | Provisional | 02–03 |
| [05 — XI optimisation](05-xi-optimisation/README.md) | Recommend valid, explainable lineups | Planned | Provisional | 04 |
| [06 — Recruitment](06-recruitment/README.md) | Rank squad improvements under uncertainty and cost | Planned | Provisional | 03–05 |
| [07 — Match database](07-match-database/README.md) | Build a trustworthy history of matches and decisions | Planned | Provisional | 01–03 |
| [08 — Opposition analysis](08-opposition-analysis/README.md) | Produce evidence-backed pre-match reports | Planned | Outline | 07 |
| [09 — Tactical recommendations](09-tactical-recommendations/README.md) | Recommend matchup-specific tactical choices | Planned | Outline | 05, 07–08 |
| [10 — Machine learning](10-machine-learning/README.md) | Learn calibrated models only where they beat baselines | Planned | Outline | 04, 06–09 |
| [11 — Automation and UI](11-automation-and-ui/README.md) | Deliver timely decisions in the normal play loop | Planned | Outline | Capabilities from earlier phases |

The numeric order expresses the default delivery sequence, not a ban on small
research spikes. For example, match-data reconnaissance can happen before the
recruitment feature is complete. A spike must not quietly introduce a hard
dependency on an unfinished later phase.

## Common phase structure

Every phase defines:

- an outcome and non-goals;
- prerequisites and explicit subphases;
- concrete deliverables and exit criteria;
- risks, decisions, and evidence that must be recorded;
- what is intentionally deferred.

Subphases use identifiers such as `00.2`. They are ordered discovery and
delivery checkpoints, not release numbers. A subphase may be revisited when new
FM behaviour is discovered.

## Rules that apply throughout

### No extra knowledge

Manager-visible information is a security boundary. Hidden truth must not enter
analytics storage, logs, fixtures, test failures, or model features. Where
visibility is uncertain, classify the value as unavailable until proven
otherwise.

### Evidence before sophistication

Use fixtures, deterministic rules, and naive baselines before optimisation or
machine learning. Every recommendation should retain its inputs, model/rule
version, constraints, and explanation so it can be reproduced later.

### Stable boundaries

FM-specific object graphs stay inside FMBridge. Transport details stay inside
the Python client. Analytics code consumes domain objects and never reads game
memory or bridge JSON directly.

### Save safety

The extraction path is read-only. Any future capability that writes to FM is a
separate project decision and is outside this roadmap.

### Phase reviews

At each gate, update that phase's README with:

- actual results and supported environment versions;
- decisions made and alternatives rejected;
- remaining limitations;
- sanitized examples or test evidence;
- any changes needed in later phase outlines.
