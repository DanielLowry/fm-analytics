# Football Manager Analytics Project

> This is the original vision document. The maintained delivery breakdown is
> in the [phase roadmap](phases/README.md); the roadmap may refine ordering and
> scope as evidence is gathered. The current first-product definition is the
> [early-game decision-support MVP](mvp.md).

## Background

The aim of this project is to play Football Manager while delegating as much decision-making as possible to an external analytics system.

Rather than simply building a scouting tool or exposing hidden Football Manager data, the goal is to create something closer to a **quantitative football analytics department**.

Football Manager remains responsible for simulating the football world. The external system observes the information available to the human manager and uses that information to recommend decisions.

Potential decisions include:

* Squad selection
* Formation and tactical setup
* Player roles and duties
* Opposition-specific adjustments
* Recruitment
* Player sales
* Contract decisions
* Squad development
* Rotation and fitness management
* Scouting priorities

Over time, statistical and machine-learning models could replace increasingly large parts of the decision process.

---

# Key Principle: No Extra Knowledge

The analytics system should ideally only use information that the Football Manager player could legitimately know.

For example, the system should not use:

* Hidden Current Ability (`CA`)
* Hidden Potential Ability (`PA`)
* Exact attributes for unscouted players
* Hidden personality variables
* Other internal values unavailable through the FM interface

It should be able to use:

* Our own players' known attributes
* Attributes revealed through scouting
* Attribute ranges where only ranges are known
* Match statistics
* League statistics
* Player history
* Fixtures and results
* Opposition information available in-game
* Scout reports
* Known injuries, fitness and suspensions

This distinction is important because otherwise the project becomes essentially an automated Genie Scout rather than an analytics system.

Where Football Manager exposes both underlying truth and manager knowledge internally, the extraction layer should expose the latter.

---

# Initial Target

Start with **Football Manager 2020**, since it is already available and existing tooling appears capable of accessing FM20's running game state.

The initial technical route is to use the FMScout framework / related FM20 memory-reading tooling rather than manually exporting Football Manager screens.

This provides the automation we want:

```text
Football Manager 2020
        |
        v
FMScoutFramework / FM memory access
        |
        v
C# Adapter
        |
        v
Local JSON/HTTP API
        |
        v
Python Analytics Application
```

The important distinction is that the C# component should be extremely small.

Its job is **data extraction, not analytics**.

## Current early-game MVP

Phase 0 has proved live read-only access. The first useful product now targets
the decisions that arise immediately after starting a save:

1. compare a small set of opponent-neutral tactical templates against the
   current available squad;
2. recommend a valid starting XI and substitutes jointly with the best-fitting
   template;
3. explain weak starters, poor depth, simultaneous-coverage conflicts, and
   temporary availability gaps; and
4. turn structural weaknesses into recruitment briefs and uncertainty-aware
   shortlists drawn only from players the manager can legitimately discover.

Visibility applies both to whether a player can enter the candidate universe
and to whether each field is exact, ranged, unknown, unavailable, or stale.
Opposition-specific tactical adjustments, automation, and learned models remain
later extensions.

---

# Why C# + Python?

The existing FM extraction libraries are .NET-based, making C# the natural language for communicating with Football Manager.

However, most of the interesting work will involve:

* Data exploration
* Statistics
* Optimisation
* ML
* Visualisation
* Rapid experimentation

Python is considerably more convenient for that work.

Therefore:

## C#

Responsible for:

* Finding/attaching to the Football Manager process
* Loading Football Manager data
* Translating FM objects into simple structures
* Exposing those structures through a stable API

Example conceptual endpoints:

```text
GET /game
GET /clubs
GET /clubs/{id}
GET /players
GET /players/{id}
GET /squad
GET /fixtures
GET /matches
GET /competitions
```

Responses should be straightforward JSON objects.

Football-specific decision logic should **not** live here.

---

## Python

Responsible for essentially everything else.

Examples:

```text
fm_analytics/
    data/
    models/
    scouting/
    recruitment/
    tactics/
    opposition/
    squad/
    optimisation/
    reporting/
```

Python can periodically query the C# service:

```python
players = fm.get_squad()
fixtures = fm.get_fixtures()
```

From the Python application's perspective, Football Manager should eventually look like another data source.

---

# Phase 0 — Prove Data Access

Before designing anything substantial, establish that FM20 can actually be accessed reliably.

Goal:

> Start Football Manager, load a save, run our application and automatically retrieve basic game information.

Extract:

* Current in-game date
* Human manager
* Human-controlled club
* Club name
* First-team squad
* Player names
* Positions
* Basic attributes

Example output:

```text
Game date: 14 August 2020

Club: Arsenal

Players:
------------------------------------------------
Bernd Leno          GK
Hector Bellerin     DR
Kieran Tierney      DL
...
```

Success here proves the fundamental architecture.

---

# Phase 1 — Build the Extraction API

Turn the proof-of-concept into a small reusable C# service.

Suggested project:

```text
src/
    FMBridge/
```

Responsibilities:

```text
Football Manager
      |
      v
FMBridge
      |
      +---- GET /game
      +---- GET /players
      +---- GET /clubs
      +---- GET /fixtures
```

The API should deliberately avoid exposing complicated FM-specific .NET objects.

Instead:

```json
{
    "id": 12345,
    "name": "Example Player",
    "age": 24,
    "position": "MC",
    "club_id": 100,
    "attributes": {
        "passing": 15,
        "vision": 14
    }
}
```

This creates a stable boundary between FM reverse engineering and the analytics application.

---

# Phase 2 — Persistence

Create a local database, probably SQLite initially.

```text
FMBridge
    |
    v
Python importer
    |
    v
SQLite
```

Store snapshots rather than simply maintaining the latest state.

That allows us to answer questions such as:

* How has a player's attribute profile developed?
* How has his estimated value changed?
* How has our tactical performance changed?
* Which players improve most?
* How accurate were our recruitment predictions?

Potential tables:

```text
players
player_attributes
clubs
fixtures
matches
player_match_stats
scouting_reports
squad_status
injuries
```

---

# Phase 3 — Information Visibility

This is probably the most important infrastructure problem after basic extraction.

Determine how Football Manager represents:

* Completely unknown attributes
* Attribute ranges
* Fully known attributes
* Scout knowledge
* Knowledge of our own players
* Knowledge of opposition players

Create a data model that distinguishes:

```text
True FM value
        vs
Manager-visible value
```

The analytics layer should only receive the second.

Example:

```json
{
    "passing": {
        "known": false,
        "minimum": 10,
        "maximum": 14
    }
}
```

Rather than:

```json
{
    "passing": 13
}
```

Ideally the Python application should never even receive hidden values.

---

# Phase 4 — Squad Model and Baseline Tactics

Build the first genuinely useful football model.

Initially use transparent deterministic models rather than ML.

For example, define a suitability function:

```text
Ball Playing Defender:

Marking          15%
Tackling         15%
Positioning      15%
Anticipation     10%
Passing          10%
Composure        10%
Decisions        10%
Strength          5%
Pace              5%
Jumping Reach     5%
```

Calculate:

```text
player_role_score(player, role)
```

Then produce:

```text
Best Goalkeepers

1. Player A       82.4
2. Player B       77.1
3. Player C       69.8
```

Add a small versioned catalogue of complete baseline tactical templates—three
to five formations with coherent roles, duties, mentality, and a limited set of
instructions. This immediately becomes useful for:

* Player comparison
* Squad depth
* Starting XI selection
* Identifying weak positions
* Comparing how well the squad supports different tactical shapes
* Distinguishing weak starters, poor depth and simultaneous-coverage problems

---

# Phase 5 — Joint Tactic and Starting XI Optimisation

Move from individual player rankings to jointly evaluating each supported
baseline tactic and its best valid player assignment.

Example objective:

```text
Maximise:
    expected team quality

Subject to:
    exactly 11 players
    valid positional structure
    minimum fitness
    suspensions excluded
    injuries excluded
    tactical role compatibility
```

Eventually additional constraints could include:

* Rotation
* Match importance
* Player happiness
* Youth development
* Fixture congestion
* Home/away
* Opposition strength

The MVP keeps the tactic opponent-neutral and returns the chosen template,
starting XI, substitutes, binding constraints, and close alternatives. Current
condition and match sharpness affect readiness but remain separate from a
player's intrinsic role suitability.

This could naturally become an optimisation problem using something such as OR-Tools.

---

# Phase 6 — Recruitment and Further Scouting

Build a recruitment model using only legitimately discoverable players and
manager-visible fields.

Questions:

```text
Where is the squad weakest?

Which available players improve it?

How much improvement per £ of transfer fee?

How much improvement per £ of salary?

How risky is the signing?

What is the likely resale value?
```

Eventually produce rankings such as:

```text
Central Midfield Recruitment

                     Quality   Cost   Value Score
Player A               84       £8m      91
Player B               88      £30m      72
Player C               81       £3m      94
```

This could become one of the most interesting parts of the project.

The first recruitment slice should be simpler than the table above. A
tactic-aware weakness becomes a recruitment brief; every candidate is compared
with the current squad using lower, central and upper role-fit estimates. The
system should say `scout more` and name the consequential unknown fields when
additional knowledge could change the decision. A central estimate must record
its policy and must not conceal the original ranges or unknowns.

Entity discoverability is separate from attribute visibility. A player being
reachable in FM's internal database does not make that player a legitimate
candidate. Candidate collections must match verified in-game player-search or
manager-knowledge structures and direct lookup must not enable hidden-ID
probing.

---

# Phase 7 — Match Database

Capture every match automatically.

Store:

* Lineups
* Formation
* Tactical setup
* Player roles
* Result
* Shots
* xG where available
* Possession
* Chances
* Player performance
* Opposition setup
* Match events

The aim is eventually to create our **own historical football dataset generated by the save**.

---

# Phase 8 — Opposition Analysis

Before each match automatically generate an opposition report.

Example:

```text
Opponent: Chelsea

Likely formation:
4-3-3

Characteristics:
- Strong attacking left side
- High possession
- Vulnerable against transitions
- Right back frequently advances
- Poor aerial central defence

Suggested approach:
- Lower defensive line slightly
- Attack right channel
- Counter quickly after turnovers
- Target crosses toward striker
```

Initially this could use rules.

Later it could become statistical.

---

# Phase 9 — Opposition-Specific Tactical Recommendation Engine

Start from the opponent-neutral baseline tactic and XI selected in Phase 5, then
estimate which small adjustments should help against a specific opponent.

Inputs might include:

```text
Our squad
Opponent squad
Opponent formation
Opponent tendencies
Home/away
Recent matches
Fitness
Player availability
```

Output:

```text
Formation:
4-2-3-1

Mentality:
Positive

Press:
High

Defensive line:
Standard

Primary attacking route:
Right flank

Recommended XI:
...
```

---

# Phase 10 — Machine Learning

ML should come relatively late.

Football Manager already provides a simulator capable of generating huge amounts of structured labelled data.

That makes the save itself potentially very useful for modelling.

Possible models include:

### Match outcome

```text
P(win | players, tactics, opponent)
```

### Player performance

```text
Expected match rating
Expected goals
Expected assists
```

### Tactical effectiveness

```text
Expected xG differential
given tactical setup + opposition
```

### Player development

```text
Expected attribute development
given age, game time, training and history
```

### Recruitment

```text
Expected future contribution
Expected transfer value
```

One attractive possibility is to gradually replace hand-designed player-role weights with weights learned from actual match performance.

---

# Possible Longer-Term Architecture

```text
                      Football Manager
                             |
                             v
                     +---------------+
                     |   FMBridge     |
                     |      C#       |
                     +---------------+
                             |
                           HTTP
                             |
                             v
                     +---------------+
                     | Python Core   |
                     +---------------+
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
      SQLite             Optimisation          ML
          |                  |                  |
          +------------------+------------------+
                             |
                             v
                       Decision Engine
                             |
          +------------------+------------------+
          |                  |                  |
          v                  v                  v
        Squad            Recruitment          Tactics
```

---

# UI

Initially, don't build one.

CLI output, Jupyter notebooks and simple reports will probably be substantially faster for development.

Eventually a browser-based dashboard could expose:

```text
Today's Decisions

[ Team Selection ]
[ Opposition Report ]
[ Transfers ]
[ Squad Analysis ]
[ Scouting ]
[ Development ]

Next Match
Arsenal vs Chelsea

Recommended system: 4-2-3-1
Expected win probability: 48%
```

The UI should sit on top of the analytics system rather than becoming part of its architecture.

---

# Automation Goal

Eventually the ideal workflow is:

```text
1. Open Football Manager
2. Load save
3. Start analytics application
4. Play
```

The system automatically detects changes in game state.

For example:

```text
Game advances to next day
        |
        v
FMBridge detects new state
        |
        v
Python synchronises database
        |
        v
Models rerun where necessary
        |
        v
New recommendations become available
```

No repeated CSV exports or manual data entry should be required.

---

# Completed Feasibility Milestone and Current Product Milestone

The initial feasibility milestone was deliberately small:

> Automatically connect to FM2020 and retrieve the current squad from Python.

That means:

```text
FM2020
   ↓
C# FMBridge
   ↓
GET /squad
   ↓
Python
   ↓
print(players)
```

Once this works, most of the uncertainty around the project disappears.

Everything after that can be built incrementally.

That milestone is now complete on the supported Linux/Proton FM20 build. The
current product milestone is the [early-game MVP](mvp.md): a reproducible
baseline tactic/XI recommendation, squad weakness report, and visible-player
recruitment shortlist with useful further-scouting guidance.

---

# Initial Repository Structure

```text
fm-analytics/
│
├── README.md
│
├── docs/
│   └── architecture.md
│
├── src/
│   ├── FMBridge/
│   │   ├── FMBridge.csproj
│   │   └── ...
│   │
│   └── fm_analytics/
│       ├── api/
│       ├── data/
│       ├── squad/
│       ├── recruitment/
│       ├── tactics/
│       ├── opposition/
│       ├── optimisation/
│       └── models/
│
├── notebooks/
│
├── tests/
│
└── data/
    └── .gitkeep
```

---

# Immediate Next Steps

1. Stabilise and version the Phase 01 API contract around the squad inputs the
   MVP requires.
2. Complete the deferred live date-advance and squad-membership-change soak
   checks.
3. Add narrow snapshot persistence so recommendations are reproducible.
4. Verify manager-visible attribute states and the discoverable-player universe
   against controlled FM20 UI cases.
5. Define the first three to five baseline tactics and their role catalogue from
   the real squad data.
6. Build deterministic role, depth, and weakness reports.
7. Add joint tactic/XI selection and explainable alternatives.
8. Turn weaknesses into briefs and rank visible candidates under uncertainty.
