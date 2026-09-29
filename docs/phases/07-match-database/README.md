# Phase 07 — Match database

## Planning status

In progress. The first slice was built on 29 September 2026; see
[the match analysis plan](../../match-analysis-plan.md) for what it does, the
FM memory layouts behind it and what is still open.

## Implemented slice

- **07.1 source reconnaissance:** done for results, competitions, FM's match
  stats panel, player match stats and the timeline. Each was verified against
  FM's own screens on two matches. Minutes played, goal type and zone, and
  opposition names remain.
- **07.2 identity and lifecycle:** a match is its date plus both club IDs.
  Scheduled copies of a fixture (no outcome yet) are skipped. Full stats for
  every match come from FM's match archive on disk (`Temporary/pks_<n>.obs`),
  so capture can happen at any time, with nothing to do in FM.
- **07.3 schema and ingestion:** `persistence/match_history.py`, append-only,
  with migrations from v1. Ingestion is idempotent. A later capture without
  a match's stats never hides the stats already kept.
- **07.4 decision context:** partial. The tactic actually used is recorded
  (the manager's note, or inferred from the line-up's role codes), kept
  separate from any recommendation. A snapshot of the pre-match
  recommendation is deferred.
- **07.5 reconciliation:** FM's match stats export (Print screen → Web page)
  for two matches is kept in `data/research/matches/` as the check.
- **07.6 derived features:** the league table at each kickoff, opposition
  strength groups and per-role summaries are all computed from stored
  observations on every read, never stored.

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

