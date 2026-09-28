# Senior/specialist task: wages in the scouting capture

**Active-plan status:** parked (see [Parked](../active-plan.md#parked)):
needed eventually, but almost every signing is currently non-contract.

**Prerequisite:** specialist familiarity with the read-only sandbox tooling
(`tools/fm20_sandbox.py`, `tools/fm20_sandbox_queries.py`). Never run FM code
inside the live game.

## Why we are doing this

Wages will limit signings once they go beyond non-contract deals. The
player-knowledge database already has a `facts` key/value column intended for
"Player Search columns, and later wages", so the application side needs no
schema change. What is missing is a manager-visible source for the figure.

## Questions to settle first

- Which wage figure does FM20 show the manager, and for which players: owned
  players, other clubs' players, free agents and non-contract players?
- On which screen, and is it exact, rounded or hidden?
- In what units (weekly, monthly, yearly) and currency setting?

A wage demand, a current wage and FM's internal wage-affordability check are
different things. The loan-interest rule in `fm20_sandbox_queries.py` runs an
affordability check afterwards. That is internal logic, not a displayed value,
and must not be surfaced as a fact.

## Scope

1. Record the visibility finding for each player category, with screen
   evidence, following the method in
   [field-acquisition-workbench.md](../field-acquisition-workbench.md).
2. Find a read-only source through the existing feed and sandbox tools, and
   validate it against FM's screens for a sample of players.
3. Add it to the feed as a `facts` entry with a documented key and unit, and
   update the candidate-feed contract in
   [scouting-workspace.md](../scouting-workspace.md).
4. Application follow-up. This can go to a medium implementer once the feed
   carries the value: check that knowledge ingest records it, and that the
   existing "additional captured facts" filters show it. An affordability
   filter against a budget the manager enters is a separate product decision.

## Constraints

- Manager-visible only. Where visibility is uncertain, treat the value as
  unavailable.
- Nothing writes to FM.
- Report findings in plain language: what works and what does not in FM,
  before any tooling detail.

## Success criteria

- A written visibility finding per player category, with evidence.
- Feed values match FM's screens on the validation sample.
- The knowledge database records the value with no schema change, and a
  change over time produces a new profile row.
- An unknown wage is distinguishable from zero everywhere it appears.

## Likely code and tests

- `tools/fm20_scouting_feed.py`, `tools/fm20_sandbox_queries.py`
- `src/fm_analytics/knowledge_ingest.py`, check only
- `docs/scouting-workspace.md`
