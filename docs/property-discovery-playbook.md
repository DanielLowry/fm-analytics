# Finding a visible FM field: static analysis, then Frida

This is the method that produced footedness, written down so the next field
does not have to rediscover it. It is deliberately specific about what worked,
what wasted time, and which step changed the outcome.

The headline: **the discovery was static, and Frida was the execution
vehicle.** No breakpoint, no call stack, no watchpoint. Reading FM's compiled
code found the answer; Frida only ran the call that FM itself would run.

## When to use this

Use it when FM visibly shows a fact the bridge cannot supply, and the fact has
a UI label somewhere. Do not start by tracing. Passive call tracing tells you
which functions execute, not what they mean, and this codebase has already paid
for that lesson twice: a labelled six-player tour produced over a thousand
call records that resolved nothing, and every backtrace in that trace came back
empty because the accurate backtracer does not work in this Wine environment.

## The method

Each step below has a command. `tools/fm20_pe_symbols.py` is the offline half;
it reads the executable file and never touches a live process.

**1. Start from a string.** Find the UI label for the fact, and any nearby
property handler, using the existing static scan in
`tools/fm20_field_workbench.py`. This gives a code address worth reading.

**2. Read the handler.** Disassemble it and read it properly. Look for a
comparison against a four-character code early in the function. FM's UI objects
receive property requests keyed that way, so such a comparison means you are
in a property dispatcher, not in field-specific code.

```bash
objdump -d -M intel --no-show-raw-insn \
  --start-address=0x145551cd0 --stop-address=0x145552100 "$FM_EXE"
```

**3. Follow the keys the handler asks for.** If the handler requests keys of
its own, search the image for them. Where else they appear tells you which
other code paths produce the same fact.

```bash
python3 tools/fm20_pe_symbols.py --executable "$FM_EXE" key GflP GfrP
```

**4. Turn addresses into functions.** The executable carries an exception
table naming every function's bounds, about 239,000 of them. Use it instead of
guessing where a function starts, and resolve chained unwind information so a
cold chunk maps back to its real parent function.

```bash
python3 tools/fm20_pe_symbols.py --executable "$FM_EXE" function 0x5235061
```

**5. Name the class that owns the code. This is the step that matters.**
Search read-only data for a pointer to the function, walk back to the start of
its vtable, and read the MSVC type information in front of it. A function you
thought was foot-specific may turn out to be one slot of a general interface.

```bash
python3 tools/fm20_pe_symbols.py --executable "$FM_EXE" owner 0x5231a30
```

**6. Confirm the call chain statically before calling anything.** Follow
adjustor stubs and subclass overrides down to the implementation, and read the
default branch. Read the argument registers and the result contract out of the
instructions. Never infer a signature from a vtable address alone.

**7. Check the object layout against live memory.** Static reasoning gets the
class right and the address wrong easily. Read the vtable pointers inside one
real object and see which subobject actually carries the interface.

**8. Only now call it, through Frida.** See the execution pattern below.

## Worked example: footedness

| Step | Result |
| --- | --- |
| String lead | `FOOT_LABEL` and a value handler at RVA `0x5551cd0` |
| Handler read | Asks for keys `GflP` and `GfrP`, bands them at 8 and 15 into five categories |
| Key search | About three dozen sites, including a second non-UI path |
| Function bounds | The second path belongs to one large function, not the fragment it looked like |
| Class naming | The producer is virtual slot `0x10` of `db::PLAYER`; the second path is slot `0x20` of `GAME_SCOUTED_PERSON`; the handler is `FOOT_LABEL` |
| Layout check | The interface is the person address the probe already resolves, not the player address plus eight |
| Chain | Person slot `0x10`, adjustor stub, `ACTUAL_PLAYER` override, then the `db::PLAYER` producer for unhandled keys |
| Contract | Getter takes the interface, a four-character key, and a 16-byte value wrapper; the record case re-enters the same getter once per sub-key |

The important realisation is in the class-naming row. The foot label is not
served by foot code. It is served by a generic keyed property getter that every
person object implements, which is why the same call shape should reach many
other visible fields.

## The Frida execution pattern

`tools/fm20_frida_property.py` implements this; reuse it rather than writing
another agent.

- **Run FM's code on FM's thread.** Sample `QueryPerformanceCounter` calls per
  thread for a second and take the dominant thread. That is FM's UI thread, so
  no foreign thread touches the database.
- **Do the work at a resting point, not at any timing call.** This page used to
  say the timing hook was "FM's UI thread at an idle point". That does not
  follow, and it is the likeliest cause of saves that write and then fail to
  load. Being the dominant caller of `QueryPerformanceCounter` identifies the
  UI thread; it says nothing about what that thread is in the middle of, and FM
  times things precisely *because* it is doing them. Hook the message pump
  (`GetMessageW`/`PeekMessageW`) instead: the UI thread returns there between
  units of work, so the call lands at a boundary FM itself chose.
  `fm20_frida_discoverability.builder_agent_source` prefers the pump, falls
  back to the timing export only when no pump export is reachable, and reports
  which it used in its `thread` message. A capture whose `restingPoint` is
  false was timed the old way.
- **Refuse to proceed if the thread is ambiguous.** No dominant thread means
  stop, not guess.
- **Validate before calling.** Check the module base against preflight, check
  each object's vtable pointer, and check that every resolved virtual slot
  lands inside the FM module.
- **Let FM format the answer.** Calling FM's own label mapper gives the visible
  text, so the category names are FM's rather than an assumption. Fail closed
  if that text is not what the registry expects.
- **Report only the visible form.** The underlying ratings stay in FM. They are
  never sent, logged, or persisted.
- **Prove it is not a fluke.** Repeat across an FM restart. A different process
  with different addresses and a different UI thread must give the same answer.

## What this does not settle

A cold result is `cold-query-proven`, not `ui-verified`. Comparing the values
with FM's own screens is a separate gate, and promotion into FMBridge is
another one after that. Scope also matters: the managed squad is the easy case
because the manager knows those players fully. External players must go through
the scouting-aware view, which is the named next target.
