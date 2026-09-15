# Research catalogue

This directory is the checked-in index of what the FM20 research tooling knows
and which captured states can be reused.

- `registry.json` records build-specific pseudo-symbols, object relationships,
  property mappings, confidence, safety, and unresolved leads.
- `corpus.json` records reusable reports and the game states and contrasts they
  represent.

JSON is intentional for the first-value iteration: it is machine-queryable with
Python's standard library and does not introduce a YAML or database dependency.
Large or private runtime artifacts remain under the git-ignored
`data/research/` tree; catalogue entries refer to them by path and SHA-256.

Validate both files with:

```bash
python3 tools/validate_research_catalog.py
```

Plan the first controller recipe without touching FM:

```bash
uv run --extra research python tools/fm20_research.py run owned-footedness-survey --dry-run --json
```

The controller performs catalogue, process, and exact-build preflight; invokes
the allowlisted passive adapter with a timeout; and writes a session envelope
plus the adapter evidence under `data/research/sessions/`. This first recipe
does not attach GDB and requires no FM interaction. It is a controller smoke
test, not evidence of improved field discovery, so do not ask the operator to
start FM solely to run it. The first requested FM session belongs to the Frida
new-property trial.

Frida 17.18.0 is pinned in the optional `research` dependency group. Direct
Linux injection into Wine is prohibited: it failed twice before agent readiness
and the reproduced bootstrapper signal 11 was followed by FM exiting. The
supported topology runs the checksum-pinned Windows Frida server inside the
Proton prefix and connects over loopback. That route passed attach, script,
Interceptor, detach, FM-state, and automatic server-cleanup gates. The
controller owns this lifecycle; the operator does not start the server.

Three recipes are available:

- `frida-attach-smoke` checks FM/Proton lifecycle compatibility without UI
  activity;
- `frida-visible-attribute-hook` compares one known hook with existing GDB
  evidence;
- `frida-footedness-candidates` is the first-value trial, arming all three
  existing candidates for one bounded player tour and ranking the resulting
  events automatically.

Run a recipe through the same entry point:

```bash
uv run --extra research python tools/fm20_research.py run RECIPE
```

Live-process commands run by a sandboxed coding agent require host process
visibility. The detector now rejects the Codex PID namespace explicitly instead
of turning its incomplete `/proc` view into a false “FM is not running” result.

The ignored runtime dependency is
`data/research/runtime/frida-server-17.18.0-windows-x86_64.exe`, verified against
the pinned uncompressed SHA-256 in `tools/fm20_frida_server.py`.

The validator checks catalogue structure, cross-references, duplicate IDs, and
the path/hash of any runtime artifact that is present locally. Missing runtime
artifacts are reported but are not an error, because they are deliberately not
committed.

Registry confidence is ordered from `lead` through `production-approved`.
Only production-approved facts may feed FMBridge automatically. A corpus entry
may be useful even when its experiment failed: its `outcome`, `limitations`, and
`reusable_for` fields state exactly what can safely be inferred from it.
