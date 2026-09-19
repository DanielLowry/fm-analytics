# Architecture

## First vertical slice

```text
Football Manager 2020 via Proton       sample-game.json
                |                           |
  read-only Linux process probe        fixture source
                \                           /
                    FmDataSource
                          |
                   Python bridge
                          |
           manager-visible JSON over HTTP
                     /          \
          Python BridgeClient   local monitor
```

The Python bridge is an anti-corruption layer. It knows how to read FM data, but it
does not rank players or make football decisions. The Python application does
not know about memory addresses or third-party extraction-library types.

## API contract

The initial API is intentionally small.

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/health` | Process health and active source |
| `GET /v1/game` | Current date, human manager, and controlled club |
| `GET /v1/squad` | First-team squad and visible attributes |

The unversioned Phase 00 routes remain temporary compatibility aliases.

Identifiers are strings because their size and exact representation in the
extraction framework are not yet confirmed. Dates use ISO 8601. Positions use
FM's familiar short labels for now, but are arrays because players can cover
more than one position.

An attribute is an observation, not necessarily a number:

```json
{ "visibility": "known", "value": 15 }
{ "visibility": "range", "minimum": 10, "maximum": 14 }
{ "visibility": "unknown" }
```

The bridge must construct these values from manager/scout knowledge. It must
not fetch a hidden exact value and merely label it unknown after serialisation.
Keeping hidden values out of the DTOs makes accidental leakage harder.

## Data-source seam

`FmDataSource` has fixture and `linux-proton` implementations. The live
implementation runs the narrow probe with a ten-second bound, validates its
projection, caches successful observations for one second, and converts source
failures into structured health states. Probe implementation details do not
cross the interface.

The subprocess seam remains acceptable until measurements justify replacing
it. Any replacement must preserve these answers:

1. Can it reliably identify the human manager and club?
2. Can it enumerate the club's first team while the save advances?
3. Can it read the manager-visible form of attributes, including ranges and
   unknowns, without exposing underlying truth?

Do not add persistence or analytics to the bridge.

## Python boundary

`BridgeClient` handles transport and decoding. Domain dataclasses validate the
wire representation. Callers therefore receive `GameState`, `Player`, and
`AttributeObservation` values rather than arbitrary dictionaries.

The CLI can also consume the fixture directly. That mode is useful for Python
development; it is not intended to become a second production extraction path.

## MVP decision path

The first useful product is defined in the [early-game MVP](mvp.md). Its Python
side keeps observations, football definitions, optimisation, and reporting
separate:

```text
FMBridge observations
        |
        v
snapshot + visibility provenance
        |
        v
role and baseline-tactic catalogue
        |
        v
joint tactic/XI evaluation
        |
        +-------------------+
        |                   |
        v                   v
team recommendation   weakness model
                            |
                            v
                     recruitment brief
                            |
                            v
              discoverable-player shortlist
```

Baseline tactical definitions are versioned JSON data loaded and validated by
the Python analytics layer. FMBridge exposes facts, not role weights, tactical
judgments, or candidate rankings.

External-player access has two gates. First, the player must belong to a
verified manager-discoverable collection; the existence of an internal player
object is insufficient. Second, every returned field must carry its approved
knowledge semantics. Direct lookup must not permit hidden-player ID probing.

Analytics does not implicitly turn a ranged or unknown observation into a
number. Suitability results retain lower/central/upper estimates, the policy
used for a central estimate, and the source observations. Readiness inputs such
as condition and match sharpness remain separate from intrinsic role quality.

## Current application boundary

The bridge contract, snapshot store, versioned catalogue, joint tactic/XI
selection, role matrix, weakness/depth analysis, recruitment briefs, CLI, and
local web view all exist. External-player acquisition is available through a
manager-visible research capture consumed by the scouting page, but it is not
yet a stable bridge resource and the CLI HTML and web JSON recruitment paths
have not been unified.

`reporting.build_recommendation_bundle` is the single owned-squad calculation
used by CLI and web. The browser currently caches source reads and bundles on
separate short TTLs; the active [application improvement
review](app-improvement-review.md) defines the move to one input-keyed,
single-flight cache and the connected player/depth/scouting workflow.

Capability gates and open research questions live in the [phase
roadmap](phases/README.md). Deliberate football-model changes live in the
[tactical-system roadmap](tactical-system-roadmap.md).
