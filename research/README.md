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

Four recipes are available:

- `frida-attach-smoke` checks FM/Proton lifecycle compatibility without UI
  activity;
- `frida-visible-attribute-hook` compares one known hook with existing GDB
  evidence;
- `frida-footedness-candidates` arms all three existing candidates for one
  bounded player tour and ranks the resulting events automatically;
- `frida-owned-footedness-cold` reads footedness for the managed first team by
  calling FM's own property getter, with no player screen and no operator
  action;
- `frida-owned-attributes-cold` reads every display attribute for the managed
  first team by calling FM's own proven visible-attribute builder in-process,
  in one session instead of one guarded ptrace call per attribute.

## Scaling the proven attribute builder

`tools/fm20_cold_visibility_ptrace.py` proved the visible-attribute builder is
safe and correct, one player/attribute pair per ptrace attach and detach.
`tools/fm20_frida_attribute_sweep.py` calls the same builder, with the same
ABI, in-process through Frida, for a whole squad and every attribute in one
session: 697 calls for the managed first team. Every one of those 697 values
matched the existing production owned-squad reader (`fm20_owned_visible_source.py`,
which reads the raw bytes directly, since the manager fully knows their own
squad) exactly. This is the mechanism the app's "extract all attributes"
capability is meant to use once it needs more than the owned squad, where
range and unknown outcomes will actually occur.

Scope today is still the managed first team. FM's builder itself already
takes a knowledge context and returns visible bounds regardless of scope, so
the ABI generalises; requesting a broader population is a discoverability
question, catalogued as unresolved, not a Frida limitation.

## First extracted field: footedness

The method is documented in the
[property-discovery playbook](../docs/property-discovery-playbook.md), and its
offline half is `tools/fm20_pe_symbols.py`.

FM asks a person object for the property key `tofP`, which returns a record
holding `GflP` and `GfrP`. The label handler turns that pair into one of five
categories using boundaries at 8 and 15. The cold path calls the same getter
FM calls, through virtual slot `0x10` on the person interface the probe already
resolves, and runs it on FM's own UI thread inside a QueryPerformanceCounter
hook so FM executes its own code at an idle point.

Four runs, including one after FM was restarted into a different process,
returned the same footedness for all 17 managed players, and FM's own label
mapper supplied the category text. Only those five categories are reported;
the underlying foot ratings are never read out of FM. Footedness is therefore
`cold-query-proven`, not `ui-verified`: the values have not yet been compared
with FM's player screens, and nothing may reach FMBridge before that gate and
promotion pass.

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
