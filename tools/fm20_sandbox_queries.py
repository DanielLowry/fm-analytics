#!/usr/bin/env python3
"""Product-facing sandbox reads: visible attributes and interest, for any player.

Built on ``tools.fm20_sandbox`` after the 27 September 2026 trial (see
``docs/scouting-workspace.md`` and ``docs/frida-discoverability.md``) proved it
reproduces FM's own answers without running any code inside the live game.
Two independent things live here:

**Visible attributes.** Calls FM's own visibility builder (RVA 0x15a4a90) the
way FM's screens call it: a zeroed 16-byte lookup cache (so the builder does
its own report search) and the player's actual scout -- their report's staff
person, not the report record -- as the explicit ``report`` argument. Getting
both of those right (03.2, "Both caller inputs resolved") is what let the
sandbox match all 741 of a real save's scouted players exactly; the ptrace and
Frida hydration paths before it always passed a null scout and so silently
ignored every scout report.

**Interest.** FM does not store "interested in transfer/loan" anywhere -- its
Player Search filter computes it fresh from the manager's own reputation each
time (see ``docs/frida-discoverability.md``, "Running the filter in the
sandbox"). The two rule evaluators are called directly (bypassing the
composite filter's own-club/national-pool rules, which the caller has already
applied via ``own_contracted_ids``), always at FM's standard "any interest"
level rather than whatever a manager happens to have ticked in the UI.

FM's own computed cut-off was consistently 5-6% stricter than its own
displayed list on the one save this was checked against (never explained; see
``docs/frida-discoverability.md``). Per the product owner's decision on
27 September 2026, a missed interested player is worse than a wrongly
flagged one, so every interest read is margin-adjusted: the real cut-off is
read live (it moves with the manager's reputation, never hard-coded) and then
relaxed by ``DEFAULT_INTEREST_MARGIN``. Each player's result distinguishes
FM's own exact verdict from one that only clears the relaxed margin, so the
manager can see which is which rather than losing that distinction.
"""

from __future__ import annotations

import os
import struct
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Mapping, Sequence

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from fm_analytics.domain import AttributeObservation
from tools.fm20_cold_query_cache import resolve_context_and_manager
from tools.fm20_discoverability_cold_filter import (
    FILTER_CONTEXT_VTABLE_RVA,
    RECORD_WRAPPER_VTABLE_RVA,
)
from tools.fm20_discoverability_manager_builder import _live_context
from tools.fm20_scouted_attributes import read_report_records, resolve_persons_by_row_id
from tools.fm20_linux_probe import ProbeError
from tools.fm20_sandbox import FmSandbox, SandboxError
from tools.fm20_visibility_trace import DISPLAY_ATTRIBUTE_IDS


class SandboxQueryError(RuntimeError):
    """The sandbox could not answer a product query about live FM state."""


VISIBLE_ATTRIBUTE_BUILDER_RVA = 0x15A4A90

# FM's own "any interest" level, read off the rule's own setting whenever a
# manager has that box ticked (verified constant across every observed search
# on the test save); forced here regardless of what is currently ticked in
# FM's UI, so the answer does not depend on a screen the manager may not have
# open. 0.85 keeps every player FM included in two full-pool checks (1,518 of
# 1,518 transfer, 91 of 91 loan) with 12-18 extra players per check who scored
# just under FM's own line -- see docs/frida-discoverability.md for the sweep
# that picked it. Both numbers are read live from the manager's own current
# reputation on every refresh; nothing here is a fixed threshold.
STANDARD_INTEREST_LEVEL = 5000
DEFAULT_INTEREST_MARGIN = 0.85


@dataclass(frozen=True)
class _ThresholdSite:
    """One place in a rule's evaluator that compares a score with a threshold.

    ``register`` names the register holding the *threshold* at that address,
    immediately before the compare instruction runs -- rewriting it in place
    (see ``_evaluate_interest``) lets FM's own subsequent logic (a club's
    interest threshold and a free agent's use two different code paths, and
    loan interest has an unrelated wage-affordability check afterwards) decide
    the final answer, rather than this module reimplementing it.
    """

    offset: int
    register: str


@dataclass(frozen=True)
class InterestRuleSpec:
    rtti_name: str
    threshold_sites: tuple[_ThresholdSite, ...]


# Evaluator entry points (``rule + 0x88``, called directly) and their score
# comparisons, located by offline disassembly of fm.exe 20.4.4 and confirmed
# against FM's own Player Search result list for both rules (27 September
# 2026). PERSON_INTERESTED_FILTER_RULE has two sites because a club-contracted
# player and a free agent take different branches to the same comparison;
# PERSON_INTERESTED_LOAN_FILTER_RULE has one, followed by a separate
# wage-affordability check this module does not touch.
TRANSFER_INTEREST_RULE = InterestRuleSpec(
    "PERSON_INTERESTED_FILTER_RULE",
    (_ThresholdSite(0x1FB2949, "edx"), _ThresholdSite(0x1FB2B7C, "r15")),
)
LOAN_INTEREST_RULE = InterestRuleSpec(
    "PERSON_INTERESTED_LOAN_FILTER_RULE",
    (_ThresholdSite(0x1FB219E, "ecx"),),
)


@dataclass(frozen=True)
class SandboxSearchContext:
    """Everything a sandbox call needs, resolved once per refresh."""

    module_base: int
    knowledge_context: int
    manager_interface: int
    team: int
    manager_person: int
    filter_object: int


def resolve_sandbox_context(pid: int) -> SandboxSearchContext:
    """Resolve the manager/team/filter identity a sandbox call reuses for every player.

    A thin, read-only wrapper over the same identity resolution the pool
    rebuild and the filter research already use -- no native call, and no
    Frida. Raises ``SandboxQueryError`` if the manager-rooted search identity
    (needed for the filter object) or the knowledge context cannot be read.
    """
    try:
        state, (source, manager_interface, team), _pool_ids = _live_context(pid)
    except ProbeError as error:
        raise SandboxQueryError(f"cannot resolve the manager's search identity: {error}") from error
    module_base = int(state.module_base, 0)
    import os

    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        knowledge_context, _manager_interface = resolve_context_and_manager(fd, module_base)
        read = lambda address, size: os.pread(fd, size, address)
        filter_object = struct.unpack("<Q", read(source + 0x78, 8))[0]
        if not filter_object:
            raise SandboxQueryError("the manager's search source has no filter object")
        person_offset = struct.unpack(
            "<i", read(struct.unpack("<Q", read(manager_interface + 8, 8))[0] + 4, 4)
        )[0]
        manager_person = manager_interface + 8 + person_offset
    finally:
        os.close(fd)
    return SandboxSearchContext(
        module_base=module_base,
        knowledge_context=knowledge_context,
        manager_interface=manager_interface,
        team=team,
        manager_person=manager_person,
        filter_object=filter_object,
    )


def read_visible_attributes(
    box: FmSandbox,
    context: SandboxSearchContext,
    interface: int,
    scout_person: int,
    attributes: Sequence[str] = tuple(DISPLAY_ATTRIBUTE_IDS),
) -> dict[str, AttributeObservation]:
    """FM's own visible-attribute answer for one player, exactly as FM's screens ask for it.

    ``scout_person`` is the staff person who wrote the player's scout report
    (0 if none); passing it directly, with a zeroed lookup cache, is the
    combination that reproduced FM's own answers exactly (see module
    docstring). Only the two public bound bytes are ever read back.
    """
    result = box.scratch + 0x100
    caller_cache = box.scratch + 0x120
    box.write(caller_cache, bytes(16))
    observations: dict[str, AttributeObservation] = {}
    for name in attributes:
        attribute_id = DISPLAY_ATTRIBUTE_IDS[name]
        box.write(result, b"\xff" * 16)
        box.call(
            box.module_base + VISIBLE_ATTRIBUTE_BUILDER_RVA,
            context.knowledge_context, result, interface, attribute_id, scout_person, caller_cache,
        )
        lower, upper = box.read(result, 2)
        observations[name] = decode_visible_bound_bytes(lower, upper)
    return observations


def _rtti_name(box: FmSandbox, obj: int) -> str | None:
    try:
        vtable = int.from_bytes(box.read(obj, 8), "little")
        locator = int.from_bytes(box.read(vtable - 8, 8), "little")
        descriptor = box.module_base + int.from_bytes(box.read(locator + 0xC, 4), "little")
        raw = box.read(descriptor + 0x10, 90).split(b"\0")[0].decode("latin1")
        return raw[4:-2] if raw.startswith(".?A") else None
    except SandboxError:
        return None


# Interest-scoring rules override their real evaluator at vtable slot 0xd8,
# not 0x88 -- confirmed by reading both slots' targets straight off the live
# filter's rule vtables on 27 September 2026: slot 0x88 resolved to the same
# address (fm.exe+0x54659e0) for both PERSON_INTERESTED_FILTER_RULE and
# PERSON_INTERESTED_LOAN_FILTER_RULE, a shared/generic method unrelated to
# scoring, while slot 0xd8 gave each rule its own address matching the
# already-disassembled evaluators (fm.exe+0x1fb27d0 and +0x1fb1f30). This is
# a different, more specific rule subclass than the always-on rules
# (PERSON_INCLUDE_OWN_FILTER_RULE etc.), whose own real evaluator genuinely
# does sit behind a slot-0x20 thunk to slot 0x88 (see
# docs/frida-discoverability.md); do not assume 0x88 for a rule class this
# module has not checked.
INTEREST_RULE_EVALUATOR_SLOT = 0xD8


def _vtable_slot(box: FmSandbox, obj: int, offset: int) -> int:
    vtable = int.from_bytes(box.read(obj, 8), "little")
    return int.from_bytes(box.read(vtable + offset, 8), "little")


def _find_rule(box: FmSandbox, filter_object: int, rtti_name: str) -> int:
    vector = int.from_bytes(box.read(filter_object + 0x30, 8), "little")
    begin, end = (int.from_bytes(box.read(vector + offset, 8), "little") for offset in (0, 8))
    if not begin or end < begin or (end - begin) % 8 or (end - begin) > 0x400:
        raise SandboxQueryError("the search filter's rule vector looks malformed")
    for address in range(begin, end, 8):
        rule = int.from_bytes(box.read(address, 8), "little")
        if rule and _rtti_name(box, rule) == rtti_name:
            return rule
    raise SandboxQueryError(f"{rtti_name} is not present in this build's search filter")


def _force_interest_level(box: FmSandbox, rule: int, level: int) -> None:
    """Set a rule's own 'flvl' setting, the same field FM's UI ticks write.

    Every rule this module uses stores its level the same way: a 16-byte
    settings-vector entry (key ``flvl``) holding a pointer to a small typed
    value object whose payload sits at offset 8. Forcing it means the answer
    never depends on which interest boxes a manager currently has ticked.
    """
    entries = int.from_bytes(box.read(rule + 0x10, 8), "little")
    end = int.from_bytes(box.read(rule + 0x18, 8), "little")
    if not entries or end <= entries or (end - entries) % 16:
        raise SandboxQueryError("the interest rule has no readable settings")
    value_object = int.from_bytes(box.read(entries + 8, 8), "little")
    if not value_object:
        raise SandboxQueryError("the interest rule's level setting is missing")
    box.write(value_object + 8, struct.pack("<q", level))


def _register_constant(name: str):
    from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_R15

    return {"edx": UC_X86_REG_EDX, "ecx": UC_X86_REG_ECX, "r15": UC_X86_REG_R15}[name]


@dataclass
class CompiledInterestRule:
    """One interest rule with its threshold hooks installed once, for reuse.

    Adding and removing a Unicorn code hook per player -- the first working
    version of this did exactly that, once per player per rule -- corrupted
    the engine's internal hook table after around 22-24 add/remove cycles and
    crashed the whole Python process outright (SIGSEGV, not a catchable
    error), discovered by bisecting a 12-player smoke test on 27 September
    2026. The hooks are instead installed once when the rule is resolved and
    live for the sandbox's whole short life; only the mutable ``_scale`` flag
    changes between calls, and calling ``evaluate`` for any number of players
    (40 checked directly, whole-pool refreshes since) never installs another
    hook.
    """

    rule: int
    evaluator: int
    _scale: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._scale = {"active": False, "margin": 1.0}

    def evaluate(self, box: FmSandbox, filter_context: int, record: int, *, margin: float) -> tuple[bool, bool]:
        """(exact, margin_relaxed) verdicts from FM's own rule evaluator, twice.

        Run once unmodified for FM's own exact answer, then once more with
        every threshold comparison this rule makes scaled down by ``margin``
        before the branch executes -- so FM's real subsequent logic (a
        second, unrelated wage-affordability gate on the loan rule, for one)
        still decides the final answer; this never re-derives it from the raw
        numbers alone. A margin of 1.0 makes both runs identical, which is how
        this was checked against FM's own displayed list.
        """
        self._scale["margin"] = margin
        self._scale["active"] = False
        exact = bool(box.call(self.evaluator, self.rule, record, filter_context) & 1)
        self._scale["active"] = True
        relaxed = bool(box.call(self.evaluator, self.rule, record, filter_context) & 1)
        return exact, exact or relaxed


def _compile_interest_rule(box: FmSandbox, spec: InterestRuleSpec, rule: int) -> CompiledInterestRule:
    from unicorn import UC_HOOK_CODE

    evaluator = _vtable_slot(box, rule, INTEREST_RULE_EVALUATOR_SLOT)
    compiled = CompiledInterestRule(rule=rule, evaluator=evaluator)

    def rescale(uc, _address, _size, _data, register) -> None:
        scale = compiled._scale
        if not scale["active"]:
            return
        current = uc.reg_read(register)
        uc.reg_write(register, max(0, round(current * scale["margin"])))

    for site in spec.threshold_sites:
        address = box.module_base + site.offset
        register = _register_constant(site.register)
        box.uc.hook_add(
            UC_HOOK_CODE, lambda uc, a, s, d, register=register: rescale(uc, a, s, d, register),
            None, address, address,
        )
    return compiled


@dataclass(frozen=True)
class InterestVerdict:
    """``"yes"`` (FM's own answer), ``"maybe"`` (only within the margin), or ``None``."""

    transfer: str | None
    loan: str | None


def _band(exact: bool, relaxed: bool) -> str | None:
    if exact:
        return "yes"
    if relaxed:
        return "maybe"
    return None


def build_filter_context(box: FmSandbox, context: SandboxSearchContext) -> int:
    """The 6-field context object FM's own Player Search passes to every rule.

    Layout confirmed against a live search context on 27 September 2026 (see
    ``docs/frida-discoverability.md``); offset 0x20 (the manager's *person*
    interface, not the interface itself) is what a September research tool
    got wrong and crashed FM by dereferencing garbage through.
    """
    address = box.scratch + 0x200
    box.write(address, struct.pack(
        "<QQQQQQ",
        box.module_base + FILTER_CONTEXT_VTABLE_RVA,
        context.manager_interface, 0, context.team, context.manager_person, 0,
    ))
    return address


def read_interest(
    box: FmSandbox,
    filter_context: int,
    rules: dict[str, CompiledInterestRule],
    person: int,
    *,
    margin: float = DEFAULT_INTEREST_MARGIN,
) -> InterestVerdict:
    """FM's transfer- and loan-interest verdicts for one player's Person address."""
    record = box.scratch + 0x300
    box.write(record, struct.pack("<QQ", box.module_base + RECORD_WRAPPER_VTABLE_RVA, person))
    verdicts: dict[str, str | None] = {}
    for key, compiled in rules.items():
        exact, relaxed = compiled.evaluate(box, filter_context, record, margin=margin)
        verdicts[key] = _band(exact, relaxed)
    return InterestVerdict(transfer=verdicts.get("transfer"), loan=verdicts.get("loan"))


def resolve_interest_rules(box: FmSandbox, context: SandboxSearchContext) -> dict[str, CompiledInterestRule]:
    """The two interest rules, hooks installed and FM's standard level forced onto each.

    Missing gracefully rather than failing the whole refresh: an unrecognised
    filter object (a build this was never checked against) means interest
    stays unanswered for this refresh, not that the refresh fails outright.
    """
    rules: dict[str, CompiledInterestRule] = {}
    for key, spec in (("transfer", TRANSFER_INTEREST_RULE), ("loan", LOAN_INTEREST_RULE)):
        try:
            rule = _find_rule(box, context.filter_object, spec.rtti_name)
            _force_interest_level(box, rule, STANDARD_INTEREST_LEVEL)
            rules[key] = _compile_interest_rule(box, spec, rule)
        except SandboxQueryError:
            continue
    return rules


def resolve_scout_persons(
    fd: int, module_base: int, knowledge_context: int, player_ids: Sequence[int]
) -> dict[int, int]:
    """Each player's scout (report staff person), keyed by player ID, read-only.

    A report is stored keyed by RowID, not player ID, so this joins it back
    through the same person scan ``capture_scouted_attributes`` already pays
    for -- a player with no report simply has no entry, which callers read as
    "no scout" (``read_visible_attributes``'s widest, safest bound).
    """
    wanted = set(player_ids)
    reports = read_report_records(fd, module_base, knowledge_context)
    if not reports:
        return {}
    persons = resolve_persons_by_row_id(fd, module_base, set(reports))
    scouts: dict[int, int] = {}
    for row_id, person in persons.items():
        try:
            player_id = struct.unpack("<i", os.pread(fd, 4, person + 0xC))[0]
        except OSError:
            continue
        if player_id in wanted:
            scouts[player_id] = reports[row_id].staff_person
    return scouts


@dataclass(frozen=True)
class PlayerCapture:
    attributes: dict[str, AttributeObservation]
    interest: InterestVerdict


# One sandbox per shard scales with real cores: each shard's Unicorn calls
# release the GIL for their duration (they are plain C calls through ctypes),
# and each shard opens its own read-only /proc/<pid>/mem descriptor, so
# concurrent shards do not interfere -- see tools.fm20_sandbox's module
# docstring on why one sandbox's writes never reach another's or FM's own.
DEFAULT_SANDBOX_WORKERS = 8


MAX_CAPTURE_PASSES = 3


def _capture_pass(
    pid: int,
    context: SandboxSearchContext,
    player_ids: Sequence[int],
    interfaces: Mapping[int, int],
    persons: Mapping[int, int],
    scout_by_id: Mapping[int, int],
    *,
    margin: float,
    workers: int,
) -> dict[int, PlayerCapture]:
    """One sharded pass over ``player_ids``, each shard its own fresh sandbox."""
    worker_count = max(1, min(workers, len(player_ids)))
    shard_size = -(-len(player_ids) // worker_count)  # ceiling division
    shards = [player_ids[start:start + shard_size] for start in range(0, len(player_ids), shard_size)]

    def run_shard(shard: list[int]) -> dict[int, PlayerCapture]:
        results: dict[int, PlayerCapture] = {}
        with FmSandbox(pid, context.module_base) as box:
            filter_context = build_filter_context(box, context)
            rules = resolve_interest_rules(box, context)
            for player_id in shard:
                try:
                    attributes = read_visible_attributes(
                        box, context, interfaces[player_id], scout_by_id.get(player_id, 0)
                    )
                    interest = read_interest(box, filter_context, rules, persons[player_id], margin=margin)
                except SandboxError:
                    continue
                results[player_id] = PlayerCapture(attributes=attributes, interest=interest)
        return results

    combined: dict[int, PlayerCapture] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        for shard_result in pool.map(run_shard, shards):
            combined.update(shard_result)
    return combined


def capture_players(
    pid: int,
    context: SandboxSearchContext,
    interfaces: Mapping[int, int],
    persons: Mapping[int, int],
    scout_by_id: Mapping[int, int],
    *,
    margin: float = DEFAULT_INTEREST_MARGIN,
    workers: int = DEFAULT_SANDBOX_WORKERS,
) -> dict[int, PlayerCapture]:
    """FM's visible attributes and interest for many players, sharded in parallel.

    ``interfaces`` and ``persons`` must share the same key set (a player
    missing from either is silently skipped -- both are needed, for the
    attribute builder and the interest rules respectively).

    A player's own read can fail transiently: FM is a live, running process,
    and some of its own internals (a CRT lock or lazily-allocated buffer the
    interest evaluator's floating-point call touches) are themselves under
    continuous mutation by FM's own background threads, not by anything this
    module writes. On 27 September 2026 this showed up as bursts of failures
    -- always the same faulting address across many different players in one
    burst, never a wrong value -- that varied hugely run to run (0 failures to
    over 1,000 of 3,648) with no correlation to worker count, and repeating
    the SAME sandbox's read never recovered it. A second attempt in a BRAND
    NEW sandbox, at a different real moment, did recover most of them, which
    is why this retries only the players still missing, in fresh sandboxes,
    up to ``MAX_CAPTURE_PASSES`` times, rather than failing the batch or
    retrying in place. Whatever is still missing after that is not guessed
    at: the caller (``fm20_scouting_feed.capture_pool``) falls back to that
    player's prior or scouted-calculation attributes, exactly as a Frida
    hydration failure always has.
    """
    remaining = [player_id for player_id in interfaces if player_id in persons]
    combined: dict[int, PlayerCapture] = {}
    for pass_number in range(1, MAX_CAPTURE_PASSES + 1):
        if not remaining:
            break
        captured = _capture_pass(
            pid, context, remaining, interfaces, persons, scout_by_id, margin=margin,
            workers=workers if pass_number == 1 else min(workers, 4),
        )
        combined.update(captured)
        remaining = [player_id for player_id in remaining if player_id not in captured]
    return combined
