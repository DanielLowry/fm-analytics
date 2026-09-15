# Phase 11 — Workflow automation and user interface

## Planning status

Outline only. Automation is introduced incrementally alongside useful earlier
features; a substantial dashboard waits until recurring workflows are proven.
The disposable Phase 00 live monitor supplies immediate visibility and should
inform this phase, but does not dictate its architecture.

## Outcome

Make recommendations arrive reliably in the normal play loop:

```text
open FM20 → load save → start analytics → play
```

The system detects relevant state changes, captures data, reruns affected
analysis, and presents fresh decisions without repeated manual exports.

## Prerequisites

- Reliable bridge lifecycle and persistence
- At least one recommendation worth delivering repeatedly
- Defined freshness and failure semantics for that recommendation

## Subphases

### 11.1 — Manual workflow baseline

Document and time the current commands for attachment, capture, analysis, and
report generation. Preserve an explicit manual trigger as a recovery path.

### 11.2 — Change detection

Detect new in-game day, target fixture, squad/availability change, completed
match, and new scouting knowledge using bounded polling and snapshot
fingerprints. Debounce loading/advancing states.

### 11.3 — Job orchestration

Run only analyses invalidated by a change. Make jobs idempotent, observable,
cancellable, and safe to retry. Track dependency/input versions and distinguish
stale output from failed output.

### 11.4 — Decision inbox and reports

Provide a CLI or generated local report for today's decisions, next match,
squad alerts, scouting actions, and recruitment briefs. Establish information
hierarchy and feedback capture before building a rich UI.

The early-game MVP should add its first usable generated report while Phases
04–06 are delivered; this subphase later unifies and automates that proven
workflow rather than delaying all presentation until Phase 11.

### 11.5 — Local dashboard

If recurring use justifies it, add a browser UI over Python application APIs.
Show capture freshness, recommendation version/confidence, explanations, and
source health. Keep analytics logic outside view/controller code.

The [decision-support design](../../decision-support-design.md) proposes a page
structure for this, one page per manager question, plus a data page showing
per-field coverage, provenance, and staleness — the page that makes the
extraction backlog self-prioritising. It also proposes the mechanism for the
"analytics logic outside view code" rule above: plain report objects between
analysis and presentation, rendered by both the CLI and the browser UI, so the
view layer cannot grow private analytics and report shapes stay testable
without a browser.

That design argues for building a thin version of this earlier than Phase 11,
on the grounds that an engine which is tedious to consult does not get
consulted. That is a sequencing proposal, not a settled change to this
roadmap; the 11.5 gate ("if recurring use justifies it") still applies.

### 11.6 — Operational hardening

Add startup configuration, graceful shutdown, local access controls if needed,
backup status, resource bounds, and clear degraded modes when FMBridge or the
game is unavailable.

### 11.7 — Human feedback loop

Record accepted, modified, or rejected recommendations and optional reasons.
Never assume a recommendation was followed; verify actual choices from later
observations where possible.

## Phase exit criteria

- The routine workflow requires no CSV export or repeated manual data entry.
- Game state changes trigger idempotent captures and only relevant analyses.
- Users can tell fresh, stale, unavailable, and failed recommendations apart.
- The manual path remains usable when automation fails.
- Feedback and actual decisions are distinct from recommended decisions.

## Deferred

- Writing selections or tactics into Football Manager
- Remote multi-user hosting
- Mobile/native applications
- UI complexity unsupported by an established repeated workflow
