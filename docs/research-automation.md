# FM20 research automation strategy

## Outcome

Make a request such as “I want player contracts” sufficient to start a mostly
autonomous, evidence-backed investigation. The system should reuse previous
discoveries and recorded game states, run bounded experiments, and ask for a
human FM action only when the required state is genuinely absent from the
research corpus.

The desired loop is:

```text
natural-language field request
             |
             v
field contract + capability lookup
             |
       already known? ---------------------- yes --> verified extraction
             |
             no
             v
select recorded state + experiment recipe
             |
             v
replay / persistent instrumentation / static analysis
             |
             v
differential evidence + ranked candidates
             |
       enough evidence? -------------------- no --> one bounded human session
             |
             yes
             v
cold-query validation --> semantic registry --> production review
```

This is a research capability, not permission to weaken the application's
manager-visible information boundary. UI observations remain validation
oracles; they are not production data sources.

## Why this work is needed

The existing research tools have proved that FM20 data can be recovered safely,
but most new categories of information still require a sequence of agent-led
GDB captures and operator actions. That creates four problems:

- a single screen state may need to be recreated many times;
- evidence is spread across scripts, JSON reports, documentation, and chat;
- experiments tend to be written for one hypothesis rather than composed from
  reusable operations;
- the operator becomes the synchronization mechanism between FM, GDB, and the
  analysis agent.

The current attribute work is the model for the desired result: one difficult
discovery became a reusable player × attribute query. The automation programme
should make that conversion routine for other visible properties.

## Principles

1. **Replay before repetition.** If a game interaction can be recorded and
   replayed, do not ask the operator to recreate it for every new breakpoint.
2. **Persistent instrumentation before chat-led probes.** A research controller
   should arm, modify, and remove observations without repeatedly restarting a
   debugger session.
3. **UI automation is research infrastructure.** It may create and verify known
   screen states, but production extraction must be cold and screen-independent.
4. **Search for dispatchers, not isolated fields.** A generic person/property or
   visible-value boundary is worth substantially more than one field offset.
5. **Every discovery becomes structured knowledge.** Addresses, ABIs, object
   relationships, safety classifications, and evidence belong in a registry.
6. **Fail closed.** A plausible offset, matching integer, or reachable player
   object is not sufficient evidence for manager visibility or discoverability.
7. **One human session per missing state.** Before requesting interaction, the
   experiment must state what evidence is missing and collect all useful
   contrasts during that session.
8. **Research mutations are explicit.** Passive observation is the default.
   Calling FM code requires a verified ABI, a safety classification, a bounded
   call policy, and a disposable saved game.

## First-value thin slice

Do not build a general research platform before it proves that it can discover
something. The first iteration has one acceptance criterion:

> Using the new framework, discover one property not currently supplied by the
> bridge, with no interactive GDB session and at most one short FM interaction.

Contract expiry is already extracted for the managed squad, so the concrete
trial should be either **external-player visible contract expiry** (including
its knowledge/visibility semantics) or **footedness**, depending on which has
the strongest existing static leads when the controller is ready. This keeps
the intended contracts example without pretending the owned-squad field is new.

Footedness met this criterion on 15 September 2026, and needed no FM
interaction at all. The method is written up as the
[property-discovery playbook](property-discovery-playbook.md). The decisive step was offline: reading FM's own code to
find the keyed person-property getter behind the foot label, rather than
running more instrumented UI tours. The generic-dispatcher objective below is
therefore no longer speculative, and external-player visibility now has a
named target in `GAME_SCOUTED_PERSON`.

The minimum machinery permitted before this result is:

- a small registry seeded with facts the repository already relies upon;
- a corpus manifest indexing existing reusable states and evidence;
- one experiment recipe and one controller command;
- one passive Frida hook, with the existing GDB path as a fallback;
- JSON/JSONL evidence and a deterministic report.

Defer a database, broad capability CLI, generic promotion command, rich query
language, and exhaustive schemas until the thin slice succeeds. Safety checks
needed to protect FM and the visibility boundary are not optional
infrastructure and remain part of the first iteration.

## Existing assets to preserve

The new system should compose the current proven components rather than replace
them indiscriminately:

- executable/build verification and automatic process discovery;
- active-manager, club, date, squad, team, and player identity resolution;
- bounded GDB capture and clean detach behaviour;
- screen-independent owned-squad extraction;
- cold player-attribute queries with exact/range/unknown decoding;
- the manager-rooted Player Search source and experimental full-filter query;
- process-lifetime identity caches;
- structured native-call logging;
- guarded single-call work now being introduced;
- timestamped JSON reports under `data/research/`;
- the existing field-acquisition evidence ladder and visibility policy.

Existing research reports must remain immutable evidence. A new index may refer
to them, but should not rewrite them.

## Tool strategy

Delivery priority is the semantic registry and corpus manifest, followed by the
thin controller, Frida, state capsules, differential analysis, and a generic-
dispatcher experiment. UI driving is added only for a state the corpus cannot
supply. `rr` may be investigated alongside that sequence, but it is never a
prerequisite for it.

### Optional, aggressively time-boxed `rr` feasibility spike

`rr` offers the greatest reduction in repeated human interaction if FM20 and
Proton can be recorded reliably. One operator tour could then be replayed many
times with different breakpoints, watchpoints, and reverse-execution questions.

It is a high-upside go/no-go experiment, not the foundation and not an assumed
dependency. Give the initial environment/native/Wine checks a small fixed time
budget and stop on the first hard incompatibility; do not spend time patching
FM or Proton merely to keep the spike alive. `rr` emulates a
single-core machine, requires supported performance counters and syscalls, and
cannot record processes that share memory with processes outside the recording
tree. Steam, Proton, graphics, audio, and FM's workload may exercise each of
those limitations.

Local baseline recorded on 15 September 2026:

| Check | Result | Consequence |
| --- | --- | --- |
| CPU | AMD Ryzen 9 9900X3D, family 26, Zen 5/Granite Ridge | Explicit support is uncertain and must be tested |
| Kernel | Linux 7.0 | New enough for current `rr` |
| `kernel.perf_event_paranoid` | `4` | Hardware-counter recording is currently blocked |
| `kernel.yama.ptrace_scope` | `1` | Launching the recorded tree should be preferred to attaching |
| Ubuntu package | `rr` 5.7 available, not installed | Too old to be the preferred Zen 5 trial |
| Hardware event | `ex_ret_cond` advertised by `perf` | Necessary but not sufficient; a non-zero count still needs testing |
| `rr` executable | Absent | Installation requires explicit approval |

Use a recent upstream build for the spike. Current upstream code has Zen 5 PMU
support, but its automatic detector does not explicitly list the Granite Ridge
CPUID observed for this machine. A forced Zen 5 microarchitecture or a minimal
detector patch may be needed, and neither should be trusted until `rr`'s own
tests and repeated replay pass. AMD Zen systems may also require the upstream
SpecLockMap workaround.

Authoritative references:

- [rr project and limitations](https://rr-project.org/)
- [rr system check](https://github.com/rr-debugger/rr/wiki/Will-rr-work-on-my-system)
- [rr AMD Zen notes](https://github.com/rr-debugger/rr/wiki/Zen)
- [current x86 CPU detection](https://github.com/rr-debugger/rr/blob/master/src/PerfCounters_x86.h)

Run the spike as an ordered acceptance ladder:

1. Install a current `rr` build without changing permanent host configuration.
2. Record and replay a trivial native program.
3. Confirm a non-zero AMD retired-conditional-branch counter, then repeat with
   the least-permissive temporary kernel setting that works.
4. Record and replay a trivial Wine program.
5. Launch a Proton process inside the recording tree without FM.
6. Launch FM20 and load only the disposable research save.
7. Record a five-minute tour covering Inbox, Player Search, a player profile,
   attributes, a scout report, squad, tactics, opposition, and staff.
8. Replay the tour twice and prove a known FM breakpoint and watchpoint can be
   revisited reliably.
9. Verify reverse-continue and stable module-relative/object evidence.
10. Record launch time, tour slowdown, trace size, replay time, unsupported
    syscalls, graphics/audio failures, and divergence.

The `rr` spike passes only if the FM tour replays repeatedly, GDB can inspect a
known event, and performance/storage are tolerable. It fails fast on an
unsupported CPU/counter, Proton launch failure, replay divergence, unusable
single-core performance, or unbounded trace growth. A slow no-counter mode may
diagnose compatibility but is not by itself an acceptable routine workflow.

Do not make a persistent sysctl, kernel-command-line, MSR, or kernel-module
change as part of the spike without a separate explicit decision.

### Frida attach-and-hook spike

Frida is the preferred candidate for a persistent live instrumentation backend.
Its Interceptor, NativeFunction, and Stalker APIs correspond closely to the
operations the current tools implement through one-off GDB sessions. Frida
documents a Windows x64 native calling convention, but attachment and code
instrumentation inside this exact Wine/Proton process must be proven rather
than assumed.

The first spike stays deliberately narrow:

1. install the pinned Python/CLI and agent versions in an isolated environment;
2. attach to the live FM host PID;
3. resolve `fm.exe` and validate its pinned build identity;
4. intercept one already-known, frequently reached function;
5. record entry arguments, return value, thread, timestamp, and bounded
   backtrace;
6. compare the event with existing GDB evidence;
7. detach/unhook and verify FM remains healthy;
8. measure event loss, frame-rate impact, save-processing impact, and log rate.

Only after this passes should the work expand to dynamic hook sets, call-tree
summaries, Stalker, or native invocation. A broad trace must be bounded by
thread, module, time, event type, and maximum stored events.

References:

- [Frida JavaScript API](https://frida.re/docs/javascript-api/)
- [Frida Stalker](https://frida.re/docs/stalker/)

### GDB remains a precision backend

GDB is already proven against this FM build. It remains useful for instruction-
level confirmation, watchpoints, ABI validation, and as a fallback when Frida
cannot instrument a particular location. The goal is to invoke it through the
same controller and experiment schema, not require the operator to coordinate
it manually.

### UI automation is an oracle driver

The previous coordinate-oriented X11 experiment was unreliable and must not be
revived unchanged. A research UI driver should use a fixed FM skin, window size,
resolution, and scaling plus verified checkpoints after every transition.

Each action must have:

- a named starting and ending state;
- a screenshot or recognisable text/image assertion;
- a timeout and bounded retry count;
- a recovery route to a known screen;
- manager, game-date, and selected-player checks where relevant;
- a failure artifact showing the last screen rather than silently continuing.

UI recipes should cover stable research personas rather than arbitrary current
players: owned, fully scouted, partly scouted, unknown, loaned, injured,
contract-expiring, and other states required by a field contract.

## Research controller

The eventual command surface should be small and intention-oriented:

```bash
fm-research capabilities
fm-research inspect player.contract_expiry
fm-research run player-contracts
fm-research compare inbox player-profile contract-tab
fm-research replay RECORDING --experiment player-contracts
fm-research promote player.contract_expiry
```

The thin-slice controller should initially implement only one equivalent of
`fm-research run RECIPE`. It may call existing Python helpers internally and
write JSON/JSONL directly. Add the other commands only after the first new
property is found and their repeated need is demonstrated.

An experiment recipe declares:

- field question, entity scope, and expected visible representations;
- required and available contrasting personas;
- start state and UI route, when a UI oracle is necessary;
- known object roots and identity checks;
- candidate functions, instructions, dispatch IDs, or memory regions;
- instrumentation backend and event bounds;
- whether the experiment is passive, guarded-call, or prohibited;
- before/after invariants;
- pass, fail, and ambiguous decision rules;
- artifacts and registry facts it may produce.

The controller owns process discovery, build validation, attachment, timeouts,
clean detach, report creation, and failure capture. Field adapters should not
duplicate those responsibilities.

## Research trace store

Start with immutable JSON reports and bounded JSONL event streams, plus the
research corpus manifest below. They are sufficient for the first experiment
and work with the repository's existing conventions. Add a SQLite index only
when real trace volume or repeated cross-report queries demonstrate that flat
artifacts are the bottleneck.

Minimum logical records:

```text
sessions       build, process, save/date, manager, backend, start/end status
experiments    hypothesis, recipe/version, state labels, decision rules
events         thread, timestamp/order, module RVA, kind, call/return pairing
arguments      event, position/register, raw pointer, resolved semantic identity
backtraces     event, bounded ordered module RVAs
snapshots      label, selected object graph/pages, screenshot and hashes
conclusions    outcome, confidence, limitations, supporting artifacts
```

Raw hidden values must not be copied into this artifact store merely because the
instrumentation could read them. Each experiment declares its permitted event
and value fields before attachment.

## Research corpus manifest

Reports and capsules need a machine-queryable inventory so the controller can
prove whether a requested state already exists before asking for human help.
The manifest indexes artifacts; it does not duplicate their full event data.

An entry should contain at least:

```yaml
id: partly-scouted-player
build: fm20-20.4.4-1442341
save: research-save
game_date: 2019-06-24
manager_id: "..."
entity:
  kind: player
  id: "..."
knowledge_state: partly-scouted
screens:
  - player-profile
  - scout-report
captures:
  - kind: frida-trace
    artifact: data/research/traces/frida-trace-017.jsonl
  - kind: state-capsule
    artifact: data/research/capsules/capsule-004.json
known_contrasts:
  - fully-scouted-player
  - unknown-player
verified_facts:
  - attribute-range-visible
limitations:
  - contract-tab-not-captured
```

The controller checks this manifest, then the referenced artifacts, before it
may request a new FM interaction. Entries carry enough build/save/manager/date
identity to reject stale or incomparable evidence. Runtime artifacts stay
git-ignored; the checked-in manifest uses stable logical IDs and may include
hashes or sanitized evidence references rather than private raw values.

## Semantic registry

The registry is the durable pseudo-symbol and capability database for the
pinned FM20 build. It should be reviewable text in version control, with report
paths/hashes referring to ignored runtime evidence.

Minimum concepts:

```yaml
builds:
types:
object_resolvers:
functions:
properties:
dispatchers:
visibility_rules:
discoverability_rules:
experiments:
```

A function entry should be able to express:

```yaml
key: visible_attribute_builder
build: fm20-20.4.4-1442341
rva: 0x15a4a90
abi: win64
arguments: [knowledge_context, player_interface, attribute_id, result, report, caller_context]
result: visible_attribute_bounds
safety: guarded-call
confidence: ui-verified
evidence:
  - exact-player-report
  - ranged-player-report
  - unknown-player-report
```

Registry confidence progresses through explicit states:

```text
lead
observed
signature-mapped
cold-query-proven
ui-verified
production-approved
rejected
```

Only `production-approved` entries may be consumed automatically by FMBridge.
Research tools may use lower-confidence entries only within the operations
allowed by their safety classification.

## Differential analysis

The normal discovery question should be “what differs between these labelled
states?” rather than “where is this one value stored?”

For states A and B, rank functions and properties using:

- present in B but not A;
- frequency or call-tree increase in B;
- receipt of the verified target object/interface pointer;
- return/output matching a manager-visible value;
- access to a registered object field or collection;
- proximity to a known property selector, table-column dispatcher, formatter,
  or UI provider;
- repeatability across contrasting players;
- persistence after leaving the relevant screen.

The analyser should produce a bounded shortlist with reasons. It must not turn
correlation into a field mapping without an ABI/provenance and cold-query test.

## Generic-dispatch objective

After the instrumentation backend is proven, prioritize boundaries shaped like:

```text
GetPersonProperty(person, property_id)
GetVisiblePersonProperty(manager, person, property_id, context)
PopulateTableRow(person, columns)
FormatProperty(property_id, value, visibility)
```

The existing attribute dispatcher and `GflP`/`GfrP` property evidence make this
a concrete objective. A verified high-level dispatcher may unlock contracts,
wages, value, morale, fitness, positions, descriptions, and other visible facts
by registering IDs and result contracts rather than reversing each field from
scratch.

## State capsules and replay fallback

If deterministic execution replay is unavailable, capture compact state
capsules at named UI states. A capsule may include:

- process/build/save/manager identity;
- module mappings;
- stable entity IDs and resolved interface pointers;
- bounded registered object graphs;
- explicitly permitted memory pages around known objects;
- screenshot and screen-state assertion;
- relevant trace window and event hashes.

Capsules cannot answer execution-flow or mutation questions, but they can make
many pointer, layout, vtable, string, and relationship investigations repeatable
without another FM interaction. They are also useful alongside `rr` or Frida.

## Human-intervention contract

The controller or coding agent may request an FM action only when:

1. it identifies the missing state or contrast;
2. no existing recording, capsule, report, or registered cold query supplies it;
3. the action has a stated decision rule;
4. every useful case for that state has been batched into one session;
5. instrumentation is attached and reports `ARMED` before the action begins;
6. success or failure will produce a durable report.

The operator should never have to relay verbose debugger output. Returning the
report path or final `RESULT` line is sufficient.

## Safety model

Classify every experiment operation:

| Class | Meaning | Default policy |
| --- | --- | --- |
| Offline | Static executable/report/capsule analysis | Autonomous |
| Passive live | Observe bounded calls/registers/approved memory | Autonomous after preflight |
| UI-driving | Navigate the disposable research save | Recipe must be checkpointed |
| Guarded native call | Invoke a verified FM function and restore state | Explicit registered ABI and disposable save |
| Hidden diagnostic | May reveal underlying non-visible truth | Separate acknowledgement; never application input |
| Prohibited | Unbounded mutation, guessed ABI, or production visibility bypass | Refuse |

Every native call should eventually use one guarded primitive with register
restoration, clean detach, timeout handling, liveness checks, structured call
logging, and failure evidence. Batched calls need an equally explicit guarded
batch implementation; a single-call guard must not be assumed to make an
arbitrary call sequence safe.

## Delivery plan

| Order | ID | Deliverable | Gate | Status |
| --- | --- | --- | --- | --- |
| 1 | RA.3 | Minimal semantic registry plus research corpus manifest, seeded from proven discoveries | Existing attribute/source facts and reports are indexed without reinterpretation | Initial seed complete |
| 2 | RA.4 | One-recipe controller skeleton using JSON/JSONL | Automated planning, success, failure, evidence, and resource-release paths pass; a live smoke run is not treated as value evidence | Complete |
| 3 | RA.2 | Frida attach-and-one-hook prototype | Event agrees with known GDB evidence; clean detach | Windows-side server passed: 1,126 calls reproduced all three GDB targets; controller-owned attach/detach/server cleanup and FM invariants passed. Direct Linux injection is prohibited. |
| 4 | RA.7 | Minimal state-capsule capture and lookup | One human-created state is reanalysed without help | Planned |
| 5 | RA.5 | Differential analyser over real flat-file traces | Ranks a known call path from labelled states | Planned |
| 6 | RA.8 | Generic person-property dispatcher campaign and first-value thin slice | One property absent from the bridge is obtained with no interactive GDB and at most one short FM interaction | Acceptance met for footedness with zero FM interaction: FM's own keyed person-property getter was called cold for all 17 managed players, repeatably across an FM restart. A UI comparison is still owed before promotion. |
| 7 | RA.6 | Checkpointed research UI driver, only for missing corpus states | Completes and verifies one necessary bounded route | Conditional |
| parallel, strictly bounded | RA.1 | `rr` environment and FM/Proton feasibility report | Adopt only after repeatable FM replay; otherwise reject quickly | Optional spike |
| after proven value | RA.9 | Field promotion workflow | Verified field reaches bridge through an auditable gate | Deferred |

The first six steps form the value path. RA.1 does not block any of them and
becomes part of the permanent toolkit only if it succeeds convincingly.

## First checkpoint: RA.3 and RA.4

The immediate work is deliberately small. RA.3 now has its initial checked-in
implementation in [`research/registry.json`](../research/registry.json) and
[`research/corpus.json`](../research/corpus.json):

1. define the minimal checked-in registry representation;
2. seed it from the build profile, known object resolvers, visible-attribute
   builder, manager-rooted search builder/filter, and their existing evidence;
3. create the corpus manifest and index the most reusable current reports and
   screen states;
4. define one experiment recipe/report envelope;
5. make one existing passive experiment run through a thin controller without
   changing its proven low-level implementation.

This checkpoint passes when the controller can answer whether the corpus
contains a requested state, run the selected existing experiment, and produce a
report linked back to the relevant registry facts. It should be small enough to
discard or reshape after the new-property thin slice.

RA.4's automated tests prove only controller plumbing. Do not request an FM
session merely to repeat the old passive survey through a new wrapper; that
would not test the programme's goal.

The first useful operator-facing pause is after RA.2 has attached Frida, matched
one known GDB observation, detached cleanly, and converted that backend into a
controller recipe aimed at the first new property. Run the Frida property trial
then—not before—and apply the acceptance criterion at the top of this document
before starting RA.7 or RA.5. If it has not discovered one bridge-absent
property with no interactive GDB and at most one short FM interaction, do not
build capsules, differential infrastructure, a dispatcher campaign, or UI
automation; redesign the controller/instrumentation loop first.

## Optional RA.1 report contract

If the `rr` spike is run, its go/no-go report should contain:

- exact `rr` source/version and installation method;
- CPU detection and any forced-microarchitecture setting;
- temporary host settings and their original/restored values;
- results at each acceptance-ladder step;
- FM/Proton launch command and process tree;
- record/replay timings and trace sizes;
- debugger and reverse-execution proof;
- unsupported syscall, shared-memory, graphics, audio, or divergence evidence;
- a final `adopt`, `limited-use`, or `reject` decision.

If RA.1 rejects `rr`, the programme continues unchanged. If it succeeds only
for native/Wine programs but not the full FM tour, retain that limited finding
without expanding the spike. Adopt `rr` only after the complete test succeeds
convincingly.

## Definition of success

This programme is successful when a new manager-visible field can usually be
researched without live operator coordination, previously captured states can
be reinvestigated with different probes, every accepted discovery is reusable
through the registry, and the operator is asked only for genuinely missing FM
states in one bounded session. Its first proof is narrower: discover one new
property with no interactive GDB session and at most one short FM interaction.
