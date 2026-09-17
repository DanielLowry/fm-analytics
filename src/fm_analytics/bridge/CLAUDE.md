# Bridge

The HTTP boundary between the FM20 game process and everything else
(`fm_analytics.analytics`, the CLI, the web view). This is the
highest-stakes directory in the repo to get wrong, because a mistake here
doesn't cause a bad recommendation — it leaks data the manager couldn't
actually see, which breaks the product's entire premise.

## The rule

**Only manager-visible data crosses this boundary.** Concretely, every
attribute this bridge returns must be one of exactly three things (see
`Visibility` in `fm_analytics.domain`):

- a known exact value,
- a scouted minimum/maximum range, or
- unknown.

Never Current Ability, Potential Ability, true underlying attribute values
hidden behind a range, match-engine internals, or anything else the FM UI
itself wouldn't show this manager for this player. `visibility_result.py`
is deliberately narrow about this: its docstring notes the render structure
it decodes also contains a byte that can hold the true attribute even when
FM displays nothing, and the decoder intentionally cannot accept that byte.
That's the pattern to follow anywhere new decoding is added here — narrow
the type/function so the hidden data literally cannot flow through, rather
than trusting every caller to discard it correctly.

`fm20_visibility_algorithm.py` mirrors FM's own classification/threshold
logic so the bridge can reason about what *should* be visible; it does not
itself discover manager knowledge, and its docstring says as much — don't
call these functions as a shortcut past the "sourced through a verified
manager-visible path" requirement.

## Sources (`protocol.py:FmDataSource`)

`fixture.py` (deterministic JSON fixture) and `linux_proton.py` (the live
read-only game-process probe) both implement the same small `FmDataSource`
protocol: `get_health`, `get_game`, `get_squad`. `server.py` picks one via
`FM_BRIDGE_SOURCE` and is otherwise source-agnostic. Adding a new source
means implementing that protocol, not special-casing `server.py`.

## Errors

`BridgeSourceError` means "a configured source cannot provide a valid
manager-visible snapshot right now" (mismatched club/date/roster, probe
failure, etc.) — it's expected and handled, not a bug to silence. Don't
catch it and substitute cached or partial data to keep a request "working";
callers (CLI, web) are written to fail closed on this, on purpose.

## Read-only, always

The live source only ever reads game-process memory. If you're touching
`linux_proton.py`, that's a hard invariant, not an implementation detail —
this bridge has no business writing to or otherwise influencing a running
FM20 process.
