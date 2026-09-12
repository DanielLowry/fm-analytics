# Phase 03 — Information visibility

## Outcome

Establish and enforce a tested policy for which players the human manager can
discover and what the manager knows about each one. The Python application and
database receive only manager-visible observations, including uncertainty,
provenance, and staleness where those concepts matter.

This is a governance and data-correctness phase, not merely a different JSON
shape. It is the gate for analytics involving players outside our club.

## Current status

In progress. Static research has rejected the pinned framework's raw
`PlayerAttributes` object as a production visibility source: it contains exact
underlying values and provides neither manager-knowledge states nor a
discoverable-player collection. The bridge still excludes these attributes.
External-player UI/source comparisons remain outstanding and can be performed
without advancing the save.

A strict manager-visible HTML import candidate now supports exact, ranged, and
unknown attribute cells without using memory truth. The first real-save squad
comparison has verified stock headers, exact physical cells, and selected-row
coverage. External Player Search membership and ranged/unknown real cells
remain behind the visibility gate.

The importer now also has a fail-closed completeness check: the caller supplies
the count displayed by the unchanged FM view, and the merged export must have
exactly that many unique player UIDs. This detects missed pages, unrendered
rows, unexpected duplicates, and exporting a different result set. It proves
count agreement, not yet that FM's export includes all manager-discoverable
players; that still needs the controlled real-save comparison.

The unchanged-save owned-squad comparison found the same 17 sanitized squad
identities in two stock FM20 exports and the live bridge. Stock views omit UID
and split position and attribute columns, so owned-squad pages are merged by
unique normalized name and then bound to live IDs. Duplicate squad names fail
closed; this narrow exception does not apply to external-player searches.

Render-path tracing is now a first-class automatic extraction option. A bounded
hardware-watchpoint experiment separated FM's raw 1--20 normalization getter
from a downstream function that classifies exact, ranged, and unknown results
for formatting. A research-only resolver locates transient trace addresses and
display-path identifiers without reading attribute values. The preferred result
is a verified reimplementation of FM's visibility calculation; passive capture
at the newly identified result boundary is second, and invoking an internal
function remains the riskiest option.

The same getter/caller path has now been observed while FM redraws an external
club's Physical squad table. At the pre-format boundary FM still exposes the
player object, attribute identifier, and visible result, making a single
visibility-safe table capture hook a plausible route to bulk discovery. The
capture must consume only visible bound/sentinel bytes and explicitly exclude
the structure's concealed-value byte.

`decode_visible_bound_bytes` now enforces that rule in the bridge: it accepts
exactly the two visible bytes, maps equal values to `known`, ordered unequal
values to `range`, and the paired `0xff` sentinel to `unknown`. Partial
sentinels, reversed bounds, and values outside 1--20 fail closed. Its API has no
argument for the concealed third byte.

## Prerequisites

- Phase 00 has proved safe live reads on the supported environment
- Phase 01 can expose allowlisted visibility-aware fields
- Phase 02 preserves observation time and uncertainty
- Test saves can exercise different scouting and knowledge levels

## Subphases

| ID | Subphase | Result |
| --- | --- | --- |
| 03.1 | [Knowledge taxonomy](03.1-knowledge-taxonomy.md) | Entity-discoverability states and field-level policy |
| 03.2 | [FM representation research](03.2-fm-representation-research.md) | Evidence mapping player-search and knowledge structures to visible UI |
| 03.3 | [Boundary enforcement](03.3-boundary-enforcement.md) | Hidden players and hidden field truth cannot cross FMBridge |
| 03.4 | [Uncertainty model](03.4-uncertainty-model.md) | Analytics-safe ranges, absence, and staleness |
| 03.5 | [Verification corpus](03.5-verification-corpus.md) | Repeatable cases across knowledge levels |
| 03.6 | [Visibility audit](03.6-visibility-audit.md) | Release gate and ongoing regression process |

## Phase exit criteria

- Field-level policy covers our players, known opposition, partially scouted
  players, unscouted players, injuries, fitness, reports, and contextual data
  used by the next phases.
- A paginated candidate collection enumerates all and only players legitimately
  discoverable by the manager for controlled verification saves, with a
  traceable inclusion reason and coherent snapshot semantics.
- Direct player lookup cannot reveal a player outside that approved universe.
- Bridge mapping is derived from manager-knowledge structures, not hidden truth
  relabelled after reading.
- UI comparisons validate exact, ranged, unknown, stale, and not-applicable
  cases.
- Contract, persistence, logging, fixtures, and tests have passed a leakage
  audit.
- Analytics APIs force callers to acknowledge uncertainty instead of silently
  converting it to an exact value.

## Non-goals

- Solving uncertainty with one universal midpoint
- Inferring hidden PA/CA or personality variables from memory
- Guaranteeing identical visibility semantics across other FM editions
- Recruitment rankings; this phase only makes them safe to build
- Deciding that every player object reachable in memory is manager-visible
