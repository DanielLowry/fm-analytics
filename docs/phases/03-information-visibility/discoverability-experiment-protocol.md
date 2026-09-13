# Discoverability experiment protocol (FM20 20.4.4)

This is a research runbook, not an application data source. The target remains
a cold, screen-independent FM query for the manager's discoverable players.
No HTML export or displayed table is used as an interim input. Player Search
is used only to validate research captures.

## Working method: one guided run per distinct hypothesis

Prefer a script that performs **all safe probes for the current question in
one run** over a sequence of chat-led single tests. Before asking for an FM
action, record the hypothesis, the new variable being tested, the prior
result it will distinguish, and a pass/fail/ambiguous decision rule. The
script should preflight build, active manager, in-game date, process identity,
package state where natively available, and any saved pointer/object identity;
announce `ARMED` only after probes are attached. It should prompt for each
necessary operator action in the terminal, run all related observations under
one attachment where practical, detach cleanly, and write a timestamped JSON
report on both success and failure. A chat reply need contain only the report
path (or `RESULT` line); the full output is read from the shared workspace.

Each report should contain the script/version, stated hypothesis, action
sequence and operator-confirmed UI facts, actual native addresses/types,
before/after manager/date/package/process checks, exact source and result ID
sets with counts/deltas (and optional hashes), invocation status and native
return values, validation failures, and a conclusion limited to what was
measured. Report
whether screen state was observed or merely operator-declared. Never treat an
unchanged before/after vector as proof that the builder responds correctly to
changed game state. The existing scripts implement parts of this contract;
the fresh-session harness must implement it in full. Reports live under
git-ignored `data/research/discoverability/` and must not be application
inputs.

Do not repeat a successful experiment with the same state and instrumentation
just to reconfirm its count. A repeat is justified by a *new discriminating
condition* (for example, a fresh process with no search screen opened, a
package change, or a new native output tap); name that difference in the
script and report. The next user-run script should combine its planned
checks and prompts so no chat hand-off is needed mid-run. FM UI remains
verification after the native cold query, never a data-source prerequisite.

## Completed package A/B study (rerun only for a new condition)

This is the completed study's reproducibility procedure, **not** the next
test to run. For a new discriminating condition, start FM at **No Package**,
Player Search with all criteria **Any**. The script conducts both package
states in one terminal run:

```bash
.venv/bin/python -u tools/fm20_discoverability_experiment.py study
```

It tells the operator exactly when to change FM. For each of its two steps:

1. Select the named package; leave all search criteria **Any**. Press Enter
   at the terminal prompt. Do not refresh the search before `ARMED`.
2. At `ARMED`, set **Transfer Listed**, wait for results, then reset every
   criterion to **Any** and wait for the final result count.
3. Type `done <count>` in the same terminal, such as `done 4320` or
   `done 4933`. The debugger detaches and the script reports the phase.

After Step 1, it asks for **Senior Players → Vanarama North/South** and
continues automatically. There is no need for a chat reply between steps.
The final `RESULT` gives the path of a JSON report in the shared, git-ignored
`data/research/discoverability/` directory. It includes exact candidate
IDs, exact upstream source IDs, both package deltas, source-only IDs, and
first-team overlap with the source-only IDs. This tests the own-team exclusion
hypothesis but does not assume it is the complete native rule. Tell Codex only
the report path or that the study ended;
the report can be read directly from the workspace. The tool is research-only:
FM's UI verifies counts, but no HTML or UI-rendered player data is ingested.

The two live breakpoints collect source and result IDs in **one search refresh
per package**. Package state is still operator-declared until its FM memory
field is located. The test does not itself provide a cold discoverability
query; the report is evidence for locating that native provider and exclusion
rule.

## One repeatable capture (diagnostic fallback)

1. Select the package named by `--state`; leave the in-game date unchanged.
2. Set every New Search criterion to **Any**.
3. Run a capture command below in an interactive terminal. Wait for `ARMED`.
4. Set **Transfer Listed**, wait for the count, then return to all **Any**.
5. When FM shows its final unfiltered count, enter `done <count>` in the
   terminal (for example, `done 4320`). The tracer detaches promptly.
6. Inspect the `RESULT` line and saved JSON report. A failed check is a
   failed experiment, not evidence for the underlying search rule.

```bash
.venv/bin/python -u tools/fm20_discoverability_experiment.py capture \
  --state no-package --kind candidates

.venv/bin/python -u tools/fm20_discoverability_experiment.py capture \
  --state senior-vanarama --kind source
```

The `candidates` kind captures exactly the players passing through FM's
search-result property path, resolves both normal and dual-role player IDs,
and requires their unique ID count to equal FM's reported count. The
`source` kind samples the earlier search input vector. Its count is **not**
required to equal the UI count: the difference is the object of the test.
Both kinds verify the same active manager, process, build, and in-game date
before and after. Package state is operator-declared until a native package
field is mapped. Reports are created without overwriting prior reports in
git-ignored `data/research/discoverability/`.

Compare two successful candidate reports with:

```bash
.venv/bin/python tools/fm20_discoverability_experiment.py compare \
  data/research/discoverability/no-package-candidates-TIMESTAMP.json \
  data/research/discoverability/senior-vanarama-candidates-TIMESTAMP.json
```

The comparison fails unless both captures passed, the manager, build, and
game date match, and the No Package ID set is a subset of the Senior package
set. It reports exact additions and removals. These are verification
artifacts, not inputs to the application or its recruitment analytics.

## Decision sequence, not open-ended tracing

| Checkpoint | Status / decisive observation | Next action |
| --- | --- | --- |
| Package A/B source | Complete: 4,340 No Package; 4,953 Senior; 613 added IDs. | Locate the source's screen-independent owner; do not publish the vector directly. |
| Default exclusion | Partial: FM's include-own rule excludes 19 of 20 source-only IDs. | Resolve the last ID via an authoritative final-output path. |
| Off-screen builder | Complete but limited: native call works off Player Search, with an existing search object and unchanged 4,953 IDs. | Construct/resolve context without a prior search screen. |
| Exact cold query | Open: no final 4,933-ID native result or application API. | Obtain final IDs from FM and compare them exactly with UI afterward. |
| Fresh-session validation | Ready to test: manager-rooted argument discovery works in the existing process, but has not been tested before Player Search opens after restart. | Run the guided fresh-process A/B once; knowledge changes remain later. |

Stop expanding passive trace targets once a checkpoint has a decisive
answer. A package-sensitive vector plus a verified FM-native exclusion
predicate is the preferred route. Reimplementing staff knowledge is a
fallback only if the native provider or predicate cannot be invoked/read
without UI state.

## Completed checkpoint: builder invocation off Player Search

The A/B source comparison is complete; do **not** run `study` again to repeat
the 4,340/4,953 counts. A direct call to FM's source builder rebuilt the
Senior vector to the exact saved 4,953 IDs without any search refresh. The
guided off-screen check also passed, saved as
`cold-source-builder-20260913T181806Z.json`, while the operator was on an
unrelated screen. This was its command (shown for provenance, **not** as the
next instruction to run):

```bash
.venv/bin/python -u tools/fm20_discoverability_cold_builder.py \
  --report data/research/discoverability/package-study-20260913T170215Z.json \
  --invoke --guided-offscreen
```

The script asked for **one** action: open an unrelated FM screen, such as
Inbox, then press Enter. It preflighted the pinned build, manager, date,
previous source IDs, object type, and builder arguments before one native
call. No filter refresh, package switch, or HTML export was involved. The
off-screen state was operator-declared. This does **not** test fresh-session
construction of a search object or recomputation after a changed source:
before and after were the same 4,953 IDs.

Separately, `tools/fm20_discoverability_cold_filter.py` has already batched
FM's native include-own predicate across all 4,953 Senior source players,
without user action. It rejected 19 of the 20 source-only IDs and no
search-visible IDs. The Porto-contracted ID was allowed by both that rule
and a six-player probe of the complete active filter-list callback. This
remaining one-player discrepancy may be elsewhere in the search pass or in
the broad result trace. Do not infer an extra exclusion rule from it yet;
locate a more authoritative native output set first.

## Next checkpoint: fresh-process, manager-rooted source A/B

Do **not** restart FM merely to rerun `fm20_discoverability_cold_builder.py`
with the old report. Its saved pointers belong to the current process and
its preflight should fail after restart. Reopening Player Search first to
capture new pointers would answer only whether the call survives a process
restart *after* UI initialization, not whether a genuinely cold query works.

The manager owner has now been found: the player-search source sits in an
array at `+0x190` on the active manager's native search interface. The
builder's three arguments can be resolved from the manager's person/team
records, without a search trace or saved process pointers. A current-process
direct call using this route passed against all 4,953 Senior IDs. The next
distinct test is whether the source object exists **before Player Search has
ever been opened in a fresh FM process**, and whether FM's builder updates it
after package changes. `tools/fm20_discoverability_manager_builder.py`
combines this into one guided run and records full before/after ID sets and
checks for each state.

Restart FM once, reload the same save/date, and leave it on **Inbox** or
another unrelated screen. **Do not open Player Search or Scouting Packages
before starting the script.**
Run the following in an interactive terminal:

```bash
.venv/bin/python -u tools/fm20_discoverability_manager_builder.py \
  --oracle data/research/discoverability/package-study-20260913T170215Z.json \
  --previous-report data/research/discoverability/cold-source-builder-20260913T181806Z.json \
  --guided-ab
```

The script first checks for the manager-owned source **before either relevant
screen is opened**. Then follow its three package prompts: Senior Players → Vanarama
North/South, No Package, then Senior again. Use only the Scouting Packages
screen for these changes; leave Player Search closed and do not advance the
game date. At each step the script resolves the source from the active
manager, invokes FM's builder, and checks the *exact* source IDs against the
saved A/B oracle (4,953 → 4,340 → 4,953). Only after all native steps does
it ask you to open Player Search with all criteria Any and enter the final
UI count (expected 4,933). The result or first failure is saved to one
timestamped JSON report. Give Codex only its `RESULT` line/report path.

Package selection and off-screen state remain operator-declared; the script
does not yet read FM's package field or capture the screen. Passing this test
would prove manager-rooted source access before search rendering and
package-sensitive cold recomputation, **not** the exact final 4,933-ID
discoverability set. The latter still requires the authoritative final
output path, including the unexplained one-player discrepancy, before bridge
integration.
