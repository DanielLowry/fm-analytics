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
python3 tools/fm20_research.py run owned-footedness-survey --dry-run --json
```

With FM20 and the disposable research save running, execute it with:

```bash
python3 tools/fm20_research.py run owned-footedness-survey
```

The controller performs catalogue, process, and exact-build preflight; invokes
the allowlisted passive adapter with a timeout; and writes a session envelope
plus the adapter evidence under `data/research/sessions/`. This first recipe
does not attach GDB and requires no FM interaction.

The validator checks catalogue structure, cross-references, duplicate IDs, and
the path/hash of any runtime artifact that is present locally. Missing runtime
artifacts are reported but are not an error, because they are deliberately not
committed.

Registry confidence is ordered from `lead` through `production-approved`.
Only production-approved facts may feed FMBridge automatically. A corpus entry
may be useful even when its experiment failed: its `outcome`, `limitations`, and
`reusable_for` fields state exactly what can safely be inferred from it.
