# Acquiring another manager-visible FM20 field

## Why this is a product capability

Most improvements to the recommendation model will require another fact that
FM shows the manager: footedness, position proficiency, tactic familiarity,
registration, scout-report age, and so on. Discovering each fact by a fresh
series of manually coordinated memory probes is too slow and too easy to
misinterpret. The objective is a repeatable path from a visible FM question to
a *cold, screen-independent, visibility-safe* query. FM screens are validation
oracles, never production inputs. A hidden byte's existence is not evidence
that the manager may see it.

The workbench is a research tool under `tools/`, not an FMBridge source. It
reuses the pinned executable profile and the existing live manager/squad probe.
It never outputs raw position ratings, unverified foot bytes, CA/PA, or other
hidden player facts. Its reports are git-ignored under `data/research/fields/`.

## Evidence ladder for each field

1. **Field contract.** State the question, entity and manager scope, FM's
   visible forms (exact, category, range, unknown, stale), freshness, and how
   the recommender would use it. Select contrasting owned players automatically
   where possible. This is a hypothesis, not yet an extraction mapping.
2. **Static leads.** Search the pinned executable for UI labels and class
   metadata; map file offsets to module RVAs and MSVC RTTI to candidate
   vtables/methods. This narrows what to trace but does not identify a getter.
3. **Passive provenance.** Arm a bounded trace on selected candidate paths,
   then have FM display several contrasting players once in a guided session.
   Record the player identity and *visible output boundary*, real arguments,
   call/return relationship, and any cache/screen dependence. Do not record
   an underlying hidden value merely because it is nearby.
4. **Cold query.** Resolve objects from a fresh process and the active manager,
   invoke FM's verified visible getter or read its approved visible state with
   no relevant screen open. Prefer FM's own semantics to a reimplementation.
   If invocation has side effects, document them and test on the disposable
   save; do not silently classify a raw field as visible.
5. **Differential validation.** Compare the cold result with UI-visible values
   *after* the query for contrasting players, positions/feet, unknown states,
   screen changes, and a fresh FM process. Record exact results and mismatches,
   not only counts. A repeat needs a new discriminating condition.
6. **Promotion.** Only then add a versioned domain observation, bridge mapping,
   regression corpus, and separate football-model policy. External-player
   queries additionally require the discoverability gate. Research artifacts
   must not become an interim app data source.

The reusable code should own the boring parts: build/process preflight, stable
identity and manager resolution, bounded tracing and native-call logging,
before/after checks, controlled prompts, and one machine-readable report even
on failure. Field-specific adapters describe anchors, expected visible
semantics, and any proven getter ABI. A generic native-call engine must never
guess a function signature from a vtable address.

## First checked-in slice: position proficiency and footedness

Run the static pass without FM:

```bash
python3 tools/fm20_field_workbench.py static --disassemble-top 4
```

With FM running and a save loaded, one command also surveys the managed squad
through the existing probe, chooses a small diverse set of players for later
UI verification, and checks that manager/date/squad identity stayed fixed:

```bash
python3 tools/fm20_field_workbench.py run --require-live --disassemble-top 4
```

Both modes write one timestamped JSON report and print its `RESULT` path. Use
`--field footedness` or `--field position_proficiency` for a narrower scan,
`--executable` for a different installation of the *same pinned build*, and
`--pid` when several FM processes exist. `run` without `--require-live`
retains a partial static report if FM is absent. The report records an explicit
`productionFieldQueryProven: false` until a later evidence gate changes that.
`--disassemble-top` is optional and records short, bounded offline snippets
for candidate methods; it never executes them. The scanner also recognizes
nearby UI property-selector comparisons such as `value` and `format`, which
are more focused trace leads than class names alone.

The next guided run is now scripted too. With FM running, start from any
unrelated screen and run this in an interactive terminal:

```bash
python3 -u tools/fm20_field_workbench.py trace --disassemble-top 4
```

It repeats the static scan and managed-squad preflight, chooses at most five
`value`-property leads per field, and reuses the existing bounded passive GDB
caller tracer. Only after it prints `ARMED` should the operator open the
listed players' Positions/profile pages, then type `done` once. It detaches,
checks the manager, date, and complete squad-ID hash again, and writes one
report with hit counts and callers. `--duration` bounds the run (default 120
seconds); no memory value or FM function result is captured at this stage.
The tool therefore cannot yet tell us a player's footedness. A no-hit report
is useful negative evidence about these specific candidate methods, not proof
the field has no cold getter. The guided mode has unit tests and has now been
run once against live FM; it remains a research-only fallback for provenance.
All modes verify the executable's exact SHA-256 against the already-proven
cold-call build, not just its file size, before using module-relative leads.

On the pinned FM20 20.4.4 executable, the first offline run found:

- `FOOTEDNESS_LABEL`, `FOOT_LABEL`, and a `preferred_foot` UI resource;
- `PLAYER_POSITION_LEVEL_LABEL`, `PLAYER_POSITIONS_DETAILS_PANEL`, and
  `PLAYER_POSITIONS_INDICATOR_PANEL`;
- valid MSVC RTTI complete-object locators and candidate vtables for all five
  named classes, with module-relative method addresses in the JSON report.
- a `value`-property branch near `FOOTEDNESS_LABEL` RVA `0x55521a0` and
  `FOOT_LABEL` RVA `0x5551cd0`; the position-label path has similar `value`
  dispatch around RVA `0x3eab4a0`. These are UI property handlers or nearby
  plumbing, not yet known player-foot or proficiency getters.

These are concrete entry points for a passive trace, **not** proof of the
displayed foot values or position-level calculation. The current production
position list is derived from FM's 15 position bytes using a threshold of 15
and a highest-rating fallback, collapsing proficiency. Separate, ongoing
[position-familiarity research](phases/03-information-visibility/03.2-fm-representation-research.md)
has now checked several category bands against FM and introduced a standalone
fail-closed mapping for the confirmed values; it is not yet wired into the
domain or scorer. The workbench deliberately reports only the existing
position list, not raw ratings. Its position UI leads can help resolve the
remaining gaps and independently verify the mapping. No footedness source is
in the bridge or analytics input yet. An initial sandboxed `run` report was
partial because the tool process could not see the host's FM PID namespace,
**not** because FM was stopped. A host-side process check found FM PID 8754;
a live `run` report (`field-workbench-20260914T195827290288Z.json`) then
surveyed 17 managed-squad players, verified the manager/date/squad identity,
and selected six verification players. This proves the survey works live,
not that either field has been extracted. When driving this workbench from
an isolated tool session, explicitly check host-process visibility before
interpreting `no FM process found` as game state.
Some vtable methods are destructors or common UI code; the report's rare-method
ranking is a search aid, not a semantic classification.

The first live guided trace (`field-workbench-20260914T200147643859Z.json`)
visited six owned players and returned with the same manager, date, and squad
hash. Three of seven selected methods fired, all from the foot-label family:
RVAs `0x3dd6940`, `0x5551cc0`, and `0x5551cd0`. None of the three selected
position-label methods fired. These counts only narrow the call path; they do
not establish which player or foot value a call represented. Static
disassembly of the `FOOT_LABEL` `value` handler at `0x5551cd0` shows it
obtaining two provider results keyed `GflP` and `GfrP`, applying boundaries
at 8 and 15, and building text/style output. Another non-UI property path
near `0x1daa7a3` also accesses both keys. Those are stronger leads for
finding a native, cold property source than further page-count traces, but
the provider's ownership, visibility semantics, and off-screen invocation
have **not** been verified. An attempted X11 screen driver was unreliable and
was removed rather than promoted into this workflow.

## Next experiment, batched rather than chat-led

The first `trace` run answered which selected property leads execute. The
next experiment must start from a loaded player interface and stay off-screen:

1. Map the `GflP`/`GfrP` provider interface and the position-level provider
   from the pinned executable, using the already-proven cold player resolver.
   Record the exact object, virtual slot, arguments, ownership, and result
   contract before calling anything; the presence of raw foot/position bytes
   is not a visibility proof.
2. Make one bounded native-call experiment with no player page open. Require
   stable manager/player identity and classify exact/category/unknown without
   exposing hidden ratings. Only then compare the cold result with the UI.

The UI is a final verification oracle, never the acquisition path. A
footedness or proficiency value enters the recommender only after the
cold-query and visibility gates pass. Further manual page visits are not the
default experiment and must have a new, specific hypothesis.

## Acceptance for a reusable acquisition workflow

- A new field can declare anchors and expected visible semantics without
  copying process discovery, report writing, and identity checks.
- One guided run collects all planned cases and emits a full report on success
  or failure; a user need send only the `RESULT` path.
- Reports separate *static lead*, *passive observation*, *cold query*, and
  *validated production source* rather than collapsing them into “found”.
- Tests cover PE mapping/RTTI extraction, stable sample selection, coherent
  manager/date checks, report boundaries, and each proven field decoder.
- No unverified raw value enters FMBridge, logs, fixtures, or recommendations.
