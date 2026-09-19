# Phase 11 — Workflow automation and user interface

## Planning status

In progress through a thin local web application. Squad, roles, tactics, depth,
scouting, and data pages exist over the shared reporting path. The current
focus is making that surface responsive and connected: input-keyed caching,
observable background refresh, a player view, named depth evidence, and a
decision-oriented dashboard. The disposable Phase 00 monitor remains a
diagnostic rather than the product UI.

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

The thin dashboard and its data page were built early, following the now
completed [decision-support proposal](../../archive/plans/decision-support-design-2026-09-15.md).
CLI and web share `reporting.build_recommendation_bundle`, so analytics logic
remains outside view/controller code. The active [application improvement
review](../../app-improvement-review.md) defines the next UI and operational
slice.

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
