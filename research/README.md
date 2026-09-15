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

Frida 17.18.0 is pinned in the optional `research` dependency group. The host
attach/load/event/unload/detach smoke test passes, but the first FM/Proton gate
failed during injection with `ptrace pokedata: EIO` and FM may then have exited.
Do not retry Frida against FM until that failure is isolated with a disposable
Wine/Proton child. Three Frida recipes remain available for that investigation:

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

The validator checks catalogue structure, cross-references, duplicate IDs, and
the path/hash of any runtime artifact that is present locally. Missing runtime
artifacts are reported but are not an error, because they are deliberately not
committed.

Registry confidence is ordered from `lead` through `production-approved`.
Only production-approved facts may feed FMBridge automatically. A corpus entry
may be useful even when its experiment failed: its `outcome`, `limitations`, and
`reusable_for` fields state exactly what can safely be inferred from it.
