# Frida and player discoverability

## Current answer

Discoverability is solvable cold. The candidate universe is the **pool** of
players FM lets this manager know about, and it can be read without an observed
runtime context and without any operator interaction.

**Qualification added 17 September 2026.** "Without opening Player Search" holds
only for an FM process that has already built the pool. The pool is process
memory, not save data, so it starts empty at every launch. Every reading in the
table below came from PID 53593, a session already in use. The one run on a
fresh process, `manager-rooted-source-20260913T185503Z.json`, was testing
exactly this hypothesis and read **0** before its builder call and 4,340 after,
for the same manager and the same in-game date. That report is marked
`passed: false`. So: read the pool first and use it if it is populated; treat an
empty pool as "FM has not built it in this process yet", not as "the cold read
does not work".

| Measurement | No package | Vanarama North/South |
| --- | --- | --- |
| Pool read cold | 4,340 | 4,953 |
| FM displays, criteria cleared | 4,320 | 4,933 |
| Replay accepts | not run | 4,934 |

The pool tracked an in-game package change with no change on the reading side,
which is the behaviour the application needs: scouting coverage is a real
knowledge boundary and the pool respects it automatically.

Two earlier conclusions were wrong and are corrected below. The cold replay was
never broken, and the object everyone was trying to replay is not the
discoverability gate.

## What the application should do

Take the pool, drop the manager's own club players, and do all remaining
filtering in Python. Do not drive or replay FM's search criteria. They are a
convenience for a human browsing a list, they change whenever the manager edits
the search form, and feeding them into recruitment would silently narrow
candidates by whatever was last typed.

## Known tolerance

The full-pool replay accepts 4,934 where FM displays 4,933. All 19 rejections
are the manager's own club players, which is exactly how many of the club's 20
are in the pool. One further player is displayed-excluded for a reason not yet
identified, and the same single-player anomaly appears in earlier research.

The difference is in the unsafe direction, so the replayed set is a superset of
FM's by one player and must not be described as an exact match. The product
owner accepted this tolerance on 16 September 2026 rather than block on it.
Anyone revisiting it should hook FM's own per-player verdicts during a real
rebuild and diff against the cold result; that pinpoints the player directly.

## What the filter is made of

The object at `source + 0x78` is a composite. `filter + 0x30` holds a vector of
sub-rule pointers, and the evaluator ANDs together every rule whose own
is-active check returns true. Resolving each rule's vtable through RTTI names
them outright:

| # | Rule class | Active on 16 September |
| --- | --- | --- |
| 0 | `PERSON_INCLUDE_OWN_FILTER_RULE` | always, hard-coded |
| 1 | `PERSON_INTERESTED_FILTER_RULE` | yes |
| 2 | `PERSON_INTERESTED_LOAN_FILTER_RULE` | no |
| 3 | `PERSON_INTERESTED_DP_FILTER_RULE` | no |
| 4 | `PERSON_INTERESTED_MQ_FILTER_RULE` | no |
| 5 | `PERSON_IN_NATIONAL_POOL_RULE` | always, hard-coded |
| 6 | `PERSON_VALID_FOR_NATION_RULE` | no |
| 7 | `PLAYER_WILLING_TO_CONSIDER_REPRESENTING_NATION_FILTER_RULE` | no |
| 8 | `PERSON_TRANSFER_LISTED_FILTER_RULE` | yes |

Rules 1 through 4 and 8 are gated by a byte at `rule + 0x28`; rules 6 and 7 by
a byte at `rule + 0x10`. Those bytes are what change when the manager edits the
search form. `PERSON_TRANSFER_LISTED_FILTER_RULE` being active is a manager
criterion, nothing to do with what the manager is permitted to see.

Two call-chain details matter for anyone reading this code. The function at
`0x5337010` is a thin wrapper: it does a thread check and some bookkeeping,
then tail-jumps to the real composite at `0x42c96a0`. And each rule's vtable
slot `0x20` is itself a thunk that forwards to slot `0x88`, where the rule's
real evaluator lives. An empty rule vector returns true, not false.

Call `0x42c96a0` directly rather than the wrapper. The wrapper's thread check
forces the batch onto a thread chosen to fail that check, and such a thread may
never wake, which is what made an earlier synthetic-context attempt appear to
hang. Calling the composite directly removes the constraint and lets the batch
run on FM's busy UI thread.

With the manager's criteria cleared, only the always-on include-own and
national-pool rules remain, and both read just two fields from the context: the
manager interface at offset `0x8` and the team at offset `0x18`. A synthetic
context supplying those is enough, which is why no observed runtime context is
needed. With more rules active a captured context may still be required.

## Running the filter in the sandbox (27 September 2026)

`tools/fm20_sandbox.py` runs the composite at `0x42c96a0` on a read-only copy
of FM's memory, so the thread check the wrapper enforces is irrelevant and
nothing in the live game is touched. On the test save, with the manager's own
search open in FM, the composite over the whole 3,648-player pool accepted
exactly the 295 players FM's own result list held for that search (same 295,
none extra, none missing). With every optional rule switched off in the
sandbox's copy except `PERSON_INTERESTED_FILTER_RULE`, it accepted 1,506 of
3,610 -- FM's search with only "interested in transfer" ticked.

The filter context the evaluators receive, as FM's Player Search builds it
(call sites around `fm.exe+0x1d641e4`):

| Offset | Value |
| --- | --- |
| `+0x00` | vtable `fm.exe+0x6591bf8` |
| `+0x08` | the manager interface (the pool builder's second argument) |
| `+0x10` | byte, 0 |
| `+0x18` | the managed team |
| `+0x20` | the manager's **person** interface: `manager_interface + 8 + int32([[manager_interface + 8] + 4])` |
| `+0x28` | byte, 0 |

`+0x20` is what `PERSON_INTERESTED_FILTER_RULE` asks for the managing club
(its slot `0x700`), whose reputation sets the interest threshold. Left null,
the rule returns "interested" for everyone. The September ptrace tool put the
manager's knowledge context there instead -- the wrong type, so FM called
through a non-function pointer and crashed; that is the "intermittent segfault
deep in a full-filter batch" recorded in `fm20_discoverability_cold_filter.py`.

Each interest rule reads its level from its own settings list (`rule + 0x10`,
16-byte entries keyed by a four-character code; `flvl` holds 5000 on the test
save). The interest score calls `sinf` in FM's `ucrtbase.dll`, whose FMA3 path
Unicorn cannot run; the sandbox calls the runtime's own `_set_FMA3_enable(0)`
in its copy, which Microsoft documents can change the last bit of a result.
The exact 295-player match suggests that does not matter here, but it has not
been proven for borderline players.

Cost: the interest score is much heavier than a visibility check -- about 7 ms
per player in the sandbox, 20-26 s for the whole pool.

### Shipped, with two corrections and a margin (27 September 2026 evening)

`tools.fm20_sandbox_queries` calls each interest rule's evaluator directly
(vtable slot `0xd8`, not the composite at `0x42c96a0` above and not slot
`0x88`) rather than replaying the composite with rules ticked/unticked --
simpler, and it does not depend on the manager's own club-exclusion rule
(the caller already excludes the first-team squad separately). Two things
found while wiring this in:

- **Slot `0x88` is not the interest rule's own evaluator.** Reading `[[rule]
  + 0x88]` for both `PERSON_INTERESTED_FILTER_RULE` and
  `PERSON_INTERESTED_LOAN_FILTER_RULE` gave the *same* address
  (`fm.exe+0x54659e0`, a shared, non-scoring method), while `[[rule] + 0xd8]`
  gave each rule its own address matching the evaluators already
  disassembled above (`0x1fb27d0`, `0x1fb1f30`). Calling slot `0x88` directly
  is the always-on rules' pattern (slot `0x20` thunks to slot `0x88` there);
  it does not generalise to this rule subclass.
- **Cloning FM's real main thread crashes on this code path.** The sandbox
  can either clone FM's actual main-thread block or build a synthetic one.
  The clone crashed the whole Python process (SIGSEGV, not a catchable
  error) at `_set_FMA3_enable`, for reasons not fully understood; a
  synthetic thread does not, and has been checked correct for both
  attributes and interest. See `docs/scouting-workspace.md`'s sandbox
  section for the fuller account, including a separate, non-deterministic
  read-failure pattern this also surfaced.

**FM's own cut-off is more lenient than its own formula by 5-6%, unexplained.**
Re-running the full-pool check computed live thresholds instead of a fixed
8,560 (correct: the threshold moves with the manager's own reputation) but
still came up short against FM's own lists: 1,507 of FM's 1,518 interested-in-transfer,
90 of FM's 91 interested-in-loan. A sweep of the reputation-check comparison
found any cut-off from about 94-95% of FM's computed value down to about 78%
reproduced *both* full lists exactly; below about 70% started admitting extra
players FM's own lists did not have. Ruled out as the cause: floating-point
rounding, which OS thread the call ran on, which manager/team object was
used, and the search criteria currently ticked in FM's UI (the standard
"any interest" level, `flvl = 5000`, is forced regardless). The product
owner's decision on missing-versus-wrongly-flagging players is recorded in
`docs/scouting-workspace.md`, "Interest has no stored answer"; the margin
constant is `tools.fm20_sandbox_queries.DEFAULT_INTEREST_MARGIN` (0.85).

## Why the earlier replay looked broken

The six-player sample expected three external players to be included. All six
came back false, and that was read as the replay failing.

It was not. `PERSON_TRANSFER_LISTED_FILTER_RULE` was active, and none of the
three expected-included players are transfer listed:

| Player | Transfer status | Filter verdict |
| --- | --- | --- |
| Jo Tessem | none | false, correct |
| Gianluigi Buffon | not set | false, correct |
| Chris Winterton | none | false, correct |

The filter was behaving correctly the whole time. The expectation was wrong.

## The positive control

Adam Mann of Bath City is in the source and is transfer listed, so an active
transfer-listed criterion should admit him. Replaying the filter against the
observed Player Search context gave:

| Player | Expected | Actual |
| --- | --- | --- |
| Adam Mann, transfer listed, external | true | true |
| Gianluigi Buffon, not transfer listed | false | false |
| Matt Jones, own squad | false | false |

Manager, date, source, and process state were unchanged, and the Windows Frida
server was released. This is the control the original experiment lacked: it
proves the replay can return true, which is what makes the false results
interpretable at all.

**Never run this experiment again without at least one player the filter is
expected to accept.** A predicate that returns false for everything is
indistinguishable from a broken call unless something in the sample is
expected to pass.

## How the identification was confirmed

The check was run on 16 September 2026. With every Player Search criterion
cleared, FM displayed 4,320 under no package and 4,933 under the Vanarama
North/South package. The cold pool read 4,340 and 4,953 for the same two
states, a constant difference of 20, which is the number of the manager's own
club players. The pool is therefore the manager-visible universe, and the
package dimension is carried for free because the pool itself changes when
coverage changes.

Note that the rule table above is a point-in-time snapshot. Which rules are
active changes as the manager edits the search form, so always record the
active set alongside any result.

## Safety rules

- Use the Windows-side Frida server; direct Linux-to-Wine injection is
  prohibited.
- Passive observers may collect IDs and call metadata, never raw attributes.
- Every filter experiment includes a player expected to pass and a player
  expected to fail.
- A full result set is compared against FM's displayed count before it becomes
  a candidate production source. An exact match is no longer required: the
  accepted tolerance is the single-player superset described above, agreed on
  16 September 2026. Any larger or differently-shaped gap needs investigating
  before use.
- The filter's rule set reflects live UI state. Record which rules were active
  alongside any result, or the result cannot be interpreted later.
