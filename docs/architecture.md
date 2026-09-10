# Architecture

## First vertical slice

```text
Football Manager 2020 via Proton       sample-game.json
                |                           |
  read-only Linux process probe        fixture source
                \                           /
                    IFmDataSource
                          |
                   FMBridge (C#)
                          |
           manager-visible JSON over HTTP
                     /          \
          Python BridgeClient   local monitor
```

`FMBridge` is an anti-corruption layer. It knows how to read FM data, but it
does not rank players or make football decisions. The Python application does
not know about memory addresses or third-party extraction-library types.

## API contract

The initial API is intentionally small.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Process health and active source |
| `GET /game` | Current date, human manager, and controlled club |
| `GET /squad` | First-team squad and visible attributes |

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

`IFmDataSource` has fixture and `linux-proton` implementations. The live
implementation runs the narrow probe with a ten-second bound, validates its
projection, caches successful observations for one second, and converts source
failures into structured health states. Probe implementation details do not
cross the interface.

Phase 01 should replace the subprocess seam if measurements justify it, while
preserving these answers:

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

## Near-term sequence

1. Stabilise and version the Phase 01 extraction contract.
2. Add source lifecycle telemetry and contract-level bridge tests.
3. Run the deferred live advancement and membership-change soak check.
4. Investigate manager-visible player attributes without reading hidden truth.
5. Only then add SQLite snapshots and role-scoring analytics.

The delivery gates and open questions live in the
[phase roadmap](phases/README.md), beginning with
[Phase 00: data access](phases/00-data-access/README.md).
