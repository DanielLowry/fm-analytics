# Phase 03 — Information visibility

## Outcome

Establish and enforce a tested policy for which players the human manager can
discover and what the manager knows about each one. The Python application and
database receive only manager-visible observations, including uncertainty,
provenance, and staleness where those concepts matter.

This is a governance and data-correctness phase, not merely a different JSON
shape. It is the gate for analytics involving players outside our club.

## Current status

**Summary as of 13 September 2026:** the attribute-visibility half of this
phase is effectively solved as a research capability -- a live, screen-
independent, cache-independent call into FM's own visibility logic, validated
to 0 mismatches across 97 attribute checks on three players with different
knowledge profiles, with a real false-positive bug found and fixed along the
way. See the "Attribute-visibility status snapshot" at the top of
[03.2](03.2-fm-representation-research.md) for the full rollup. It is
research tooling, not a production source: there is still no discoverability
gate, so no external-player data has been wired into `FmDataSource`, the
bridge, or recruitment analytics. **Discoverability is now the active
investigation** and the most important open item in this phase -- see the
dated entries at the end of this section for its progress.
The current No Package versus Senior Players (Vanarama North/South) search
comparison captured 4,320 versus 4,933 unique player IDs: the smaller set
is wholly contained in the larger, with exactly 613 added. This validates
package-sensitive search membership but does not yet expose the package-aware
candidate producer as a screen-independent query.
The [discoverability experiment protocol](discoverability-experiment-protocol.md)
now has a single guided `study` command. In one terminal session it captures
both the FM search source vector and result IDs for No Package and the Senior
Vanarama package, prompts for each in-game action, validates exact membership,
and saves a diagnostic JSON report. A subsequent direct native call rebuilt
the Senior package's 4,953-player **source** without a Player Search refresh,
including when the operator had moved to an unrelated FM screen (report
`cold-source-builder-20260913T181806Z.json`). Both successful calls started
with the same 4,953 IDs and still reused a previously observed search object;
they do not prove fresh-session construction or changed-state recomputation.
A separate native batch confirmed FM's include-own rule accounts for 19 of the 20
source-only IDs; the last is not rejected by the active filter-list callback.
This is not yet the fresh-process, screen-independent discoverability query
required by the application. No exact external-player set is exposed by the
bridge. The next checkpoint is to test the manager-rooted search context
before ever opening Player Search in a fresh process and to identify FM's
final result path, then validate exact IDs against the UI afterward. The protocol
explicitly forbids rerunning the same package A/B or off-screen test without
a new hypothesis and specifies a one-run, machine-readable experiment/report
contract for the next harness.

The search-source owner is now mapped to the active manager: a five-entry
source array at `+0x190` on the manager's `db::HUMAN_NON_PLAYER` interface
contains the player source, and the builder's remaining argument is the
manager's team pointer. The new manager-rooted tool resolved and invoked
the builder without saved search pointers in the current process, matching
all 4,953 Senior source IDs. A guided fresh-process Senior → No Package →
Senior test is ready but not yet run. It will establish whether this manager
array exists before any Player Search screen and whether direct calls respond
to package changes. The 4,953-to-4,933 final-result gap remains open.

The remainder of this section is a chronological log kept for provenance.

In progress. Static research has rejected the pinned framework's raw
`PlayerAttributes` object as a general production visibility source: it
contains exact underlying values and provides neither manager-knowledge states
nor a discoverable-player collection. The bridge now admits exact attributes
only for the verified active manager's first-team roster. External-player
attributes remain excluded. External-player UI/source comparisons remain
outstanding and can be performed without advancing the save.

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

Render-path tracing is a research and validation tool, not a production
extraction option. A bounded
hardware-watchpoint experiment separated FM's raw 1--20 normalization getter
from a downstream function that classifies exact, ranged, and unknown results
for formatting. A research-only resolver locates transient trace addresses and
display-path identifiers without reading attribute values. Production requires
a separately verified discoverable-player collection and a cache-independent
attribute query. The preferred attribute route is now a safe cold invocation
of FM's own visibility logic; reimplementation is Plan B. Passive capture can
compare results but cannot supply a complete queryable dataset.

The same getter/caller path has now been observed while FM redraws an external
club's Physical squad table. At the pre-format boundary FM still exposes the
player object, attribute identifier, and visible result, making a single
visibility-safe table capture hook a useful research comparator, but not a
screen-independent query mechanism. The capture must consume only visible
bound/sentinel bytes and explicitly exclude
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

The visible-result builder's call site has been identified statically. Two
same-cell Acceleration replays matched FM's public two-byte result exactly, but
an experiment that chained a different attribute was followed by an FM crash.
The multi-call path has been removed. Direct invocation is not an application
data source; the retained same-cell option is research-only calibration.

The earlier Plan B research route is a read-only reimplementation of the
verified classification, threshold selection, and range-building logic,
checked against passive captures. All 208 Physical thresholds from 26 players
match the four recovered position profiles, and FM's exact raw-position-rating
selector reproduces every profile choice. The three-way effective-knowledge
merge is also reproduced, but the baseline relationship value, report-object
inputs, and discoverable-player collection still need safe live sources.
Offline disassembly has isolated the baseline function and its final adjustment
helper, including relationship-dependent base levels; their input fields still
need mapping and passive validation before external queries.
Separately, knowing how to calculate visibility is not permission to enumerate
the hidden database.

The new Plan A inspection found non-render callers of FM's visibility core and
builder, plus a manager-to-knowledge-context resolver. A read-only live pointer
join confirmed the sole context belongs to the active human manager. This is
now backed by a native-call proof: a fixed player-interface relation was
validated for 500 loaded players, and a direct `ptrace` call on FM's primary
thread returned two ranges and one unknown result matching earlier UI captures.
A different attribute selector also returned a range. A player at a club not
previously opened in the session was queried before UI verification, which is
pending. The wrappers still fail open when context lookup fails (one returns
raw exact bytes; another returns the `exact` class), and the core updates
lookup caches. The research harness is not a production bridge: it does not
enforce discoverability, batch safely, or finish the side-effect/thread audit.
The previous different-attribute GDB replay crash was avoided by using a
separate direct-call mechanism, but it remains a warning against assuming all
invocation contexts are safe.

The shared cold-call preflight (address resolution, interface adjustment,
active-manager and player-uniqueness checks) now has dedicated tests against a
synthetic memory graph, and both cold-call tools gained a `--dry-run` mode plus
a louder failure when a timed-out call is force-abandoned mid-flight. Fresh
same-session calls reproduced both previously recorded cells for an unopened
Lincoln City player exactly. A fresh-FM-session repeat and in-UI confirmation
then found two false positives (Sheringham's Finishing, Grimshaw's Reflexes).
A passive hook on FM's real builder-call arguments -- never calling into FM --
found the cause: the cold-call tools fabricated the builder's small
caller-context argument's first 8 bytes as the manager pointer, but FM's own
calls always pass zero there. Fixing that eliminated all 11 false positives
across a 97-attribute sweep of three players with no regressions. A second,
call-varying field in that same argument remains unexplained but unproven to
matter; the optional report-object argument's non-null case remains open.

As a concrete MVP checkpoint, an owned-squad source now performs a
fresh, read-only, cache-independent live query by managed team or player. Owned
attributes are guaranteed exact in FM, so the source normalizes them only after
restricting IDs to the active manager's verified first-team collection. The
first run returned 17 players and 697 observations (41 per player); all 136
Physical observations matched the previous UI export. It rejects external
targets. The bridge now consumes this source with independent provenance,
roster/date, and attribute-allowlist checks, but the new bridge integration
still needs a live end-to-end verification run. External players remain gated
by the baseline/report/discoverability work above.

Earlier bounded passive traces detached normally and left FM responsive. A
later chained direct-call experiment caused the crash described above, so that
path has been removed. Identity resolution follows FM's own runtime interface
adjustment, and any future liveness checks use the same host-visible context as
the game process.

**Discoverability, 13 September 2026.** Investigation started. The existing
visible-result render hook does fire on Player Search, contrary to an early
misreading caused by capture sequencing. A correctly timed capture of an
8-player "transfer listed" search resolved exactly the 8 players in FM's own
export of that search, with no extras and none missing. That gives a reliable
comparator for validating any discoverability source against real searches,
but it is render-dependent and is not itself a source. Next: locate the
in-memory result collection behind an open search and the code that builds
it. Details are in [03.2](03.2-fm-representation-research.md), "Discoverability
investigation, first results".

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
