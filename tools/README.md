# Tool entry points

## Research

Use one command for new FM data-discovery work:

```bash
uv run --extra research python tools/fm20_research.py run RECIPE
```

`fm20_research.py` owns catalogue checks, process/build preflight, bounded
adapter execution, evidence reports, and cleanup. Recipes live in
`research/recipes/`. Do not ask the operator to run the low-level research
modules directly.

Frida is pinned as the optional `research` dependency. The extra is harmless
for non-Frida recipes and keeps the single command consistent.

The Frida adapter is `fm20_frida_trace.py`. It is invoked by the controller,
not directly. It caps duration, target count, event count, and backtrace depth;
captures register and call metadata without dereferencing player values; unloads
its agent; detaches; and produces an automatically ranked summary.

Live FM discovery must have host process visibility. An ordinary Codex sandbox
has an isolated `/proc` and cannot see the desktop process; the probe detects
that condition and fails as “visibility unavailable” rather than “FM absent.”
Direct Linux-to-Wine Frida injection is prohibited after two pre-agent failures
and an FM exit. `fm20_frida_server.py` instead starts a checksum-pinned Windows
server inside FM's Proton prefix, binds it only to loopback, identifies the
exact host process it created, and stops that process after the adapter exits.
This topology passed real FM attach, hook, detach, state-invariant, and cleanup
checks and is the active research backend.

`fm20_pe_symbols.py` answers the offline questions that discovery depends on:
which function contains an address, which vtable slot and class own a function,
and where a four-character property key appears. It reads only the executable
file, so it is safe to run at any time and needs no FM process.

`fm20_frida_attribute_sweep.py` calls FM's proven, UI-verified visible-attribute
builder in-process for many players and every display attribute in one Frida
session, instead of one guarded ptrace call per attribute. Its recipe is
`frida-owned-attributes-cold`; its results are cross-checked against
`fm20_owned_visible_source.py`'s independent raw-byte reader.

`fm20_frida_property.py` is the cold property-read adapter and the first tool
that extracts a new field rather than counting calls. It resolves the managed
first-team squad from read-only memory, then calls FM's own person property
getter for each player through the Windows server, on FM's own UI thread, with
no player screen open. It reports only FM's visible footedness categories and
verifies them against the text FM's label mapper returns; the underlying foot
ratings are never read out of FM. Its recipe is `frida-owned-footedness-cold`.

`fm20_frida_discoverability.py` is research-only. Its observed-context smoke
recipe makes just six full-filter calls on the Player Search thread and does
not establish player membership. `fm20_frida_trace.py` also supports a
one-shot Player Search observation that detaches after the first rebuild call.
The documented next step is a passive result-ID collector, not publishing
replayed-filter results. See [Frida and player discoverability](../docs/frida-discoverability.md).

The many `fm20_*` modules at this directory's top level are currently internal
adapters and libraries. They remain in place because the controller, bridge,
monitor, tests, or the next Frida comparison still imports them. Moving them
before equivalent controller recipes exist would break working evidence paths.

## Current application and operational tools

- `fm20_monitor.py` runs the diagnostic monitor.
- `fm20_owned_visible_source.py` is the constrained managed-squad proof source.
- `phase00_validate.py` captures or compares the established environment
  baseline.
- `validate_research_catalog.py` validates the semantic registry and corpus.

## Archive rule

A low-level research script moves to `tools/archive/` only when its result is
indexed in the corpus and it is either superseded or unsafe to repeat. A script
used by an active recipe or needed for the next instrumentation comparison is
an internal adapter, not an archive candidate.
