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

A bounded capture harness now owns debugger attachment, visible-event parsing,
deduplication, timeout, and detachment. It labels output as render-event-only
and incomplete because cached cells need not execute the hook. A fresh squad
table produced all eight Physical-column identifiers and repeated calls, proving
the hook works. Static inspection of FM's UI-to-raw dispatcher then established
the complete eight-column mapping without reading concealed player values. A
subsequent narrowed run resolved all 392 eligible events to stable player UIDs,
yielding 205 unique visible observations across 31 players.

Tracing the downstream knowledge helper established that FM keys its explicit
knowledge records by `Person.RowID`, which can be mapped directly to the stable
`Person.UID`. All 86 player lookups in the latest sample mapped successfully,
but none returned an explicit record. Static analysis shows FM then computes a
separate baseline knowledge value and uses the higher of the two; the report
cache alone cannot reproduce visibility.

A later live sample captured that merge for 83 players. All explicit values
were zero while baseline values ranged over 0, 2, 5, 7, 12, and 22. Baseline 12
corresponded to both ranged and unknown Acceleration cells, leading to the next
verified stage: FM may augment the initial merge from another staff/report
object, then compares final effective knowledge with distinct range and exact
thresholds. A final-comparison sample captured 287 decisions for 79 players
(173 unknown, 109 ranged, and 5 exact) and confirmed that rule. A subsequent
fresh-table capture retained FM's display selector and paired all 26 visible
Acceleration observations with their decisions without a single mismatch. It
also captured a complete 208-cell knowledge matrix for the table's eight
Physical columns. Future decision traces enforce this agreement fail-closed.

The next cache-independent experiment targets FM's visible-result builder
rather than the table's rendered-string cache. Its complete call site has now
been identified statically. Any replay begins with the same player and attribute
on the original render thread and remains research-only until its calling
contract and non-mutation behavior are verified. Separately, the player inputs
must come from a UI-verified discoverable universe; the builder is not permission
to enumerate the hidden database.

As a concrete MVP checkpoint, a standalone owned-squad source now performs a
fresh, read-only, cache-independent live query by managed team or player. Owned
attributes are guaranteed exact in FM, so the source normalizes them only after
restricting IDs to the active manager's verified first-team collection. The
first run returned 17 players and 697 observations (41 per player); all 136
Physical observations matched the previous UI export. It rejects external
targets, for which the builder/discoverability work above remains mandatory.

The latest bounded trace detached normally and FM remained responsive on its
original PID. A contradictory process check came from a restricted namespace
that could not see the external game process and was discarded. The speculative
render-wrapper scan has nevertheless been removed, identity resolution now
follows FM's own runtime interface adjustment, and future runs verify liveness
from the same host-visible context used for attachment.

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
