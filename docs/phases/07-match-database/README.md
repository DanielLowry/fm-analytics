# Phase 07 — Match database

## Planning status

Provisional. This phase may require early reconnaissance because FM20 match
statistics and event structures can determine what later tactical work is
possible.

## Outcome

Capture a reliable history of matches, lineups, tactics, events, and available
statistics from the save, with enough provenance to reproduce later analysis.

## Prerequisites

- Stable bridge and snapshot conventions
- Visibility policy for opposition and match information
- Known identifiers linking fixtures, matches, clubs, and players

## Subphases

### 07.1 — Source and semantics reconnaissance

Inventory pre-match fixtures, in-progress data, completed-match summaries,
player statistics, events, formations, roles, and tactics exposed by FM20.
Verify units and UI correspondence; record fields FM20 does not provide.

### 07.2 — Match identity and lifecycle

Model scheduled, rescheduled, in-progress, completed, abandoned, and replayed
matches. Establish stable keys and distinguish fixture facts from observations
captured at different times.

### 07.3 — Schema and ingestion

Add versioned storage for participants, score, lineups, substitutions,
formations, tactical settings, team/player statistics, and events. Ingest
completed matches idempotently and retain partial-capture status.

### 07.4 — Decision context

Store the recommendation version and the actual lineup/tactic observed, without
assuming a recommendation was followed. Preserve pre-match input capture so
future evaluation does not use facts learned after kickoff.

### 07.5 — Data quality and reconciliation

Check score/event consistency, minutes, duplicate events, lineup membership,
rescheduled fixtures, and changing post-match statistics. Reconcile against a
small in-game UI verification corpus.

### 07.6 — Derived match features

Create versioned, rebuildable features such as form, rolling rates, shot or xG
differentials where available, possession profiles, and player usage. Derived
features must not overwrite source observations.

## Phase exit criteria

- A run of completed matches can be imported without duplicates.
- Match records retain pre-match and post-match temporal boundaries.
- Lineups, results, and selected statistics agree with verified FM screens.
- Actual choices are distinguishable from recommendations.
- Derived features can be rebuilt from stored source observations.

## Deferred

- Live match intervention
- Inventing xG when the edition/source does not expose sufficient event data
- Tactical causal claims from simple correlations
- Learned outcome models

