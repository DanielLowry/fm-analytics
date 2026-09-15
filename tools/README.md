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
Two FM/Proton Frida injections failed before agent readiness. The second
reported a bootstrapper signal 11 and FM then exited, so Frida is rejected as a
routine backend on the current stack. The controller-backed GDB path is the
active fallback.

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
