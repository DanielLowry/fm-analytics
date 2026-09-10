# Early-game decision-support MVP

## Goal

Give a manager who has just started an FM20 save useful, explainable answers to
four questions:

1. Which tactical setup best fits the players available today?
2. Which valid starting XI and substitutes should play in that setup?
3. Where is the squad weakest or too thin?
4. Which legitimately discoverable players could address those weaknesses, and
   which of them require more scouting before a decision?

The MVP is a decision aid. It will not submit teams, change tactics, issue scout
assignments, or make transfer offers inside FM.

## Product boundary

The MVP uses only information visible to the human manager. Visibility has two
independent dimensions:

- **Entity discoverability:** whether a player may legitimately appear in the
  manager's player-search or scouting universe.
- **Field knowledge:** whether each fact about that player is exact, ranged,
  unknown, unavailable, not applicable, or stale.

Being reachable in FM's internal object graph does not make a player
discoverable. A candidate collection must be constructed from verified
manager-knowledge or player-search structures and checked against the UI.

Hidden CA, PA, exact unscouted attributes, and other unavailable internal truth
must never cross FMBridge or enter fixtures, logs, persistence, or analytics.

## First supported football model

Start with a deliberately small, versioned catalogue rather than trying to
encode every FM20 choice:

- three to five common formations that cover materially different squad shapes;
- one coherent role/duty set for each formation;
- a small set of compatible team instructions and mentality choices;
- explicit role eligibility and required/desirable attribute weights.

A tactic template is a complete baseline setup, not an opponent-specific game
plan. The MVP evaluates the tactic and XI jointly because the best eleven is
conditional on the shape and roles, while the best shape is conditional on the
players available.

## Recommendation pipeline

```text
current visible squad + availability
                 |
                 v
       role suitability intervals
                 |
                 v
  tactic template + valid XI evaluation
                 |
       +---------+---------+
       |                   |
       v                   v
recommended setup     squad weaknesses
                           |
                           v
                   recruitment briefs
                           |
                           v
              visible candidate shortlist
```

Every result records its input capture, rule/configuration version, uncertainty
policy, constraints, and explanation.

## Required outputs

### Team and tactic recommendation

- recommended formation, mentality, roles, duties, and supported instructions;
- starting XI and substitutes, with unavailable players excluded;
- current condition and match sharpness shown separately from intrinsic role
  suitability;
- binding constraints, close alternatives, and the reason for material choices;
- alternative tactic/XI combinations when their scores are close.

The first version does not tailor the recommendation to the next opponent.

### Weakness report

- weak first-choice roles;
- roles with inadequate backup or simultaneous coverage;
- weaknesses caused only by current injuries, suspension, or fitness;
- weaknesses that disappear or emerge under another supported tactic;
- explicit recruitment briefs tied to a role and tactical context.

### Recruitment shortlist

- candidates drawn only from the verified discoverable-player universe;
- traceable reason for candidate inclusion;
- role-fit lower/central/upper estimates rather than one unexplained score;
- comparison with the relevant current player or depth threshold;
- dominant unknowns and a `scout more` recommendation when resolving them could
  change the decision;
- visible cost and attainability information when its semantics are verified.

An unknown or wide range must not silently become an advantage or a precise
fact. Any central estimate uses an explicit, versioned policy; the original
observation and bounds remain available.

## Delivery slices

1. **Trustworthy squad capture:** stabilize the API and persist a reproducible
   squad/availability observation containing the inputs needed by the football
   model.
2. **Visibility and player universe:** prove exact/range/unknown mappings and
   enumerate all and only players discoverable by the current manager.
3. **Squad model:** implement the small role and baseline-tactic catalogue,
   suitability intervals, depth, and weakness explanations.
4. **Joint recommendation:** rank valid tactic/XI combinations using condition,
   sharpness, availability, familiarity, and role suitability.
5. **Recruitment loop:** create briefs from weaknesses and rank visible
   candidates while exposing uncertainty and useful next scouting actions.
6. **Usable report:** present the result through a CLI or generated local report
   before committing to a substantial dashboard.

Phases 01–06 in the delivery roadmap implement these slices. Persistence is
kept deliberately narrow for reproducibility; opposition analysis, match-based
learning, rich cost modelling, automation, and a large UI remain later work.

## MVP acceptance criteria

- A live, stored squad capture can reproduce a recommendation.
- At least three supported tactic templates can be compared against the same
  available squad.
- The selected result contains a legal XI of unique eligible players and an
  explainable bench.
- Condition, sharpness, availability, and role quality are not collapsed into
  one opaque player rating.
- The weakness report distinguishes first-choice quality, depth, simultaneous
  coverage, and temporary availability problems.
- The external-player collection matches the manager-visible search universe
  for controlled verification cases and cannot expose hidden database players.
- Exact, ranged, unknown, unavailable, and stale observations survive capture
  and remain visible in derived explanations.
- A recruitment brief produces a shortlist with score bounds, comparison to
  the existing squad, and targeted `scout more` guidance.
- No recommendation uses opposition-specific information in the MVP; that is a
  later extension with its own evidence and evaluation gate.
