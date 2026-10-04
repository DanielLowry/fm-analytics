# Historical match duties: extraction research

Status, 3 October 2026: **explicit duty words found and decoded; historical
appearance attribution remains unverified**. This is research evidence, not
approval to replace `analytics/appearance_context.py`'s current inference.

## What changed in our understanding

The player match-statistics role field does not contain duty. That does **not**
mean FM discards duty from the historical match archive. FM serializes full
64-bit role/duty words in `simatch::TACTICS_CREATOR_ARRAY` records. We can read
those words directly from the existing `.obs` archives, independently of the
app's configured tactics.

The current app resolves a role family against an inferred/recorded catalogue
tactic and, sometimes, the manager's usual setup. That is why two historical
Central Midfielder appearances with the same raw `0x20` can receive different
duties without direct FM duty evidence. The new research reader does not
assign duties to appearances: several tactic records coexist in a match,
including defaults and copies, and selecting the wrong record is still wrong.

## Discovery method and exact-build anchors

This followed the [property-discovery playbook](property-discovery-playbook.md)
and [field-acquisition workbench](field-acquisition-workbench.md), including
the attribute research's distinction between a storage value, FM's displayed
property, and a validated production source. Start from the UI consumer, trace
its property contract, then trace serialization. No native calls, hooks,
ptrace writes, UI automation, game advancement, or app/history writes were
needed.

All RVAs below are for FM20 **20.4.4-1442341**, Windows x86-64 under Proton:

```text
image base:       0x140000000
executable size:  532226560
SHA-256:          fd2c877ef28927dc63b0009ec6a2d46bdba158f456a29ecb342062cb9d82b102
```

| Anchor | RVA | Evidence |
|---|---|---|
| `TACTICAL_ROLE_LABEL` property handler | `0x3f11b30` | Reads separate `tdPT` and `lrPT` entries; combines them for display. |
| `DUTY_POPUP_BUTTON` property handler | `0x3e06a70` | Reads the same two entries. |
| `fmmatchviewer::DUTY_DESCRIPTION_TEXT` | `0x4af6210` | Calls the native label mapper at `0x46990c0`. |
| Tactic-slot property getter | `0x28bf980` | Masks the same stored 64-bit word separately for role and duty. |
| Packed duty converter | `0x1d82590` | Converts the signed high three bits of a compact u16 into the full duty mask. |
| Tactic-array serializer | `0x46712d0` | Writes name, settings, eleven slots, overrides and trailing settings. |
| Team-settings serializer | `0x46803b0` | Establishes the variable-length prefix before the slots. |
| Tactic-slot serializer | `0x46b9350` | Writes position as u32 and the full role/duty word as u64. |
| Slot-instructions serializer | `0x46b8d60` | Establishes the variable-length instruction payload. |
| `MATCH_MANAGER` serializer | `0x47b95f0` | Serializes its tactic state, then its match-person identity. |
| Manager tactic-state serializer | `0x48d0470` | Serializes two complete tactic arrays per manager in this build. |

The property-key integer values are `tdPT = 0x54506474` and
`lrPT = 0x5450726c`. Do not search only for their text spelling in little-endian
instruction bytes. The getter's `tdPT` branch at `0x28bfb15` applies
`0x406e00000`; its `lrPT` branch at `0x28bf9f7` applies
`0x7fffbf91fdeff`. The UI handlers contain chained exception-function
fragments: the first `function_at()` range alone does not cover all cases.

## Duty word and archive layout

For a full tactic-slot word:

```python
role = word & 0x7fffbf91fdeff
duty = word & 0x406e00000
```

| Duty mask | Research label |
|---|---|
| `0x200000` | Defend |
| `0x400000` | Support |
| `0x800000` | Attack |
| `0x2000000` | Unlabelled; Stopper is a lead. |
| `0x4000000` | Unlabelled; Cover is a lead. |
| `0x400000000` | Unlabelled; Automatic is a lead. |

The last mask is above 32 bits. Truncating the word to u32 loses information.
Only the first three labels are emitted by the research tool. None has yet
passed an independent historical-match UI comparison in this investigation.

The native slot occupies `0x50` bytes: full word at `+0`, position at `+8`,
instructions at `+0x10`. Array slots start at `+0x30`, with eleven entries.
The player-override map is at `+0xd70`, its count at `+0xd78`, and the tactic
name at `+0xd98`. These are native object offsets, **not archive offsets**.

The bounded archive prefix decoder follows this serializer sequence:

1. Header `22 21 00 f8 07`, one byte, length-prefixed UTF-8 name, one byte,
   and three further length-prefixed strings.
2. Team settings: version 3, two u32 values; bitmap version/type/count
   `01 02 03`, three u32 words and one byte; string and one u32.
3. Eleven slots: u16 version `0x21`, u8 type 2, u32 position, **u64 word**;
   instruction version 1 and one byte, u32 primary count with 24 bytes per
   instruction, u32 secondary count with 12 bytes per entry, two slot bytes.
4. Override-presence byte; when present, u32 count and, per entry, u32 player
   short ID, u32 slot count, then that many serialized slots.

Instruction contents are skipped, not exposed. Strings and counts are bounded,
markers are checked, unknown word bits are rejected, and truncated prefixes
fail closed. `prefixEnd` stops after the player overrides. It is **not** the
end of the full array. Remaining serializers are `0x46b9df0` (when overrides
are present), `0x4687380` (set pieces), and `0x467d4a0` (trailing settings).
Do not use `prefixEnd` or distance to the next signature to link arrays.

## Why repeated arrays cannot be assigned by proximity

Static analysis found two different enclosing structures:

- `simatch::MATCH_MANAGER` (vtable `0x6d14e98`; game subclass `0x67a27e8`)
  owns arrays at `+0xa20` and `+0x17e0`. Its serializer calls `0x48d0470`
  on `manager + 0x718`. That function serializes arrays at `+0x308` and
  `+0x10c8` relative to that base; the second is present from match version
  `0x792`. They are two arrays **per manager**, not a home/away pair.
- The separate match-view context owns arrays at `+0x1000` and `+0x1dc0`,
  serialized by `0x288bf50`. Its builder at `0x24026e0` copies each side's
  manager `+0xa20` array from the model's `+0x11ac8` manager vector when
  that source is available; otherwise the arrays retain defaults.

`MATCH_MANAGER + 0x668` references the match model/context, and `+0x688`
is used as the side index. In initialization/update paths, including
`0x46be2f0`, the primary `+0xa20` array is copied to `+0x17e0` by
`0x466f9e0`. Further conditional copies occur in `0x47d3220`. These are
leads for identifying the played tactic, not proof that either array describes
kickoff, the final whistle, or the whole appearance. The manager serializer
writes match-person identity through `0x48ca980` after the tactic state; a full
enclosing-record decoder should recover identity and side rather than choose
the first named array.

## Live/archive evidence and the unresolved contrast

The canonical read-only survey completed against the open session at game
date **30 May 2020**, manager **1915435143**, Hungerford club **5103652**.
All controller state invariants and the archive hashes remained stable. It
retained **53** unambiguous first-team fixture candidates containing **566**
valid tactic prefixes. Three candidate matches were rejected because a fixture
matched more than one chunk or a chunk matched more than one fixture. This
uses the existing archive identity/stat validation; it does not prove tactic
ownership. The first exploratory survey (56 candidates) predates that
ambiguity rejection and must not be used for the final counts.

The decisive contrast is Hungerford 2–3 Braintree, **28 March 2020**, in
`pks_0.obs`, decompressed chunk 124. Chunk SHA-256:
`d437316164db0fe4a3fbe4171e4563585486a43314fee300e7ebd93642c3a17a`.
It contains twelve valid tactic prefixes, including:

| Prefix offset | Name | `0x200400` slot | `0x100400` slot |
|---|---|---|---|
| 19624 | Vertical 4-4-2 | `0x400020`: CM Support | `0x200020`: CM Defend |
| 23311 | 4-4-2 | `0x200020`: CM Defend | `0x400020`: CM Support |

The player-statistics record associates Hargreaves (short ID 92314) with start
position `0x200400`, and Bellamy (100628) with `0x100400`. Both have role-only
code `0x20`. The named array agrees with all eleven starting position/role
families, including Pressing Forward Support `0x80400000` and Advanced Forward
Attack `0x880000`. But its midfielder duties are reversed relative to the
manager's earlier confirmation in the [form plan](tactic-role-form-plan.md):
**Hargreaves Defend, Bellamy Support**. The other array has the expected
midfield duties but different striker roles. The named array's overrides
include an empty Hargreaves entry and no Bellamy entry; that does not settle
the conflict.

Do not promote either candidate because its name, some of its duties, or its
eleven role families happen to fit. An in-match change, a different snapshot,
or a mismatch in the earlier observation remains possible. Independent FM
ground truth is needed for the two players and whether their duties changed.

## Repeating the experiment

```bash
uv run --extra research python tools/fm20_research.py run match-duty-archive-survey --json
```

Use `--pid PID` if automatic process discovery is ambiguous. Host process
visibility is required as described in [tools/README.md](../tools/README.md).
The controller pins the build, bounds the run, records state before/after,
and writes immutable reports. The adapter opens `/proc/PID/mem` read-only and
reads existing archive files. It never calls FM code or modifies game files.

Implementation: `tools/fm20_match_tactics.py` (pure prefix decoder),
`tools/fm20_match_duty_survey.py` (passive survey), and
`research/recipes/match-duty-archive-survey.json`. Evidence is indexed in
`research/corpus.json`; large/private reports remain in ignored
`data/research/`. Tests cover full-width words, opposite duties for one role,
variable instructions and overrides, conflicting candidates, truncation,
malformed/bounded data, ambiguous fixtures and controller rejection gates.

## Gates before replacing application inference

1. Decode the enclosing record to bind a tactic to its manager/team and the
   correct historical snapshot. Complete the array tail and record boundaries;
   never select by signature order, name or catalogue similarity.
2. Resolve the 28 March contradiction against FM. Verify a second match,
   opposite duties within one role, and the unlabeled duty masks through FM's
   display path.
3. Prove the meaning of player overrides, starting versus final context,
   substitutions, and changes during the match. A single team tactic cannot
   establish the duty for every appearance.
4. Add optional captured duty/context fields and explicit FM provenance to
   `PlayerMatchStats` and capture/history schemas. Preserve old captures as
   unknown; never relabel existing inference as direct FM evidence.
5. Make the capture path read validated archive duties even when live player
   statistics are available (`fm20_match_probe.build_capture` currently reads
   archive detail primarily for missing live matches). Prefer validated direct
   evidence in `appearance_context`, with transparent fallback provenance.

The remaining problem is historical attribution, not locating the duty bits.
