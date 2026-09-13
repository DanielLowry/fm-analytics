#!/usr/bin/env python3
"""Batch-check FM20's native include-own predicate against the saved search pool.

Research only. This uses the search object captured earlier, and this one
rule is not assumed to be the whole discoverability filter. No FM screen
refresh or HTML export is used.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import struct
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_cold_visibility_ptrace import (
    PTRACE_ATTACH, PTRACE_CONT, PTRACE_DETACH, PTRACE_GETREGS, PTRACE_SETREGS,
    UserRegs, ptrace, wait_stopped, write_int,
)
from tools.fm20_discoverability_cold_builder import (
    _phase_from_report, _read_at, derive_builder_arguments, run as builder_preflight,
)
from tools.fm20_discoverability_experiment import _write_report
from tools.fm20_linux_probe import ProbeError, read_exact
from tools.fm20_linux_probe_runtime import choose_pid, probe

RULE_VTABLE_RVA = 0x6DAB260
RULE_EVALUATOR_RVA = 0x54E72E0
RETURN_TRAP_RVA = 0x54E72D6
FILTER_VTABLE_RVA = 0x6D9C9B0
FILTER_EVALUATOR_RVA = 0x5337010
FILTER_RETURN_TRAP_RVA = 0x5337003
FILTER_CONTEXT_VTABLE_RVA = 0x6591BF8
RECORD_WRAPPER_VTABLE_RVA = 0x6591C38
MAX_COLD_RULE_CALLS = 6000


def resolve_native_rule(
    read_bytes, module_base: int, source: int
) -> int:
    """Find the active include-own rule by pinned vtable and list position."""
    u64 = lambda address: struct.unpack("<Q", read_bytes(address, 8))[0]
    filter_object = u64(source + 0x78)
    if not filter_object:
        raise ProbeError("source has no native filter object")
    rule_vector = u64(filter_object + 0x30)
    if not rule_vector:
        raise ProbeError("native filter has no rule vector")
    begin, end = struct.unpack("<QQ", read_bytes(rule_vector, 16))
    if begin <= 0 or end < begin or (end - begin) % 8 or (end - begin) // 8 > 100:
        raise ProbeError("native filter rule vector has invalid bounds")
    rules = struct.unpack(f"<{(end - begin) // 8}Q", read_bytes(begin, end - begin))
    matches = [rule for rule in rules
               if rule and u64(rule) == module_base + RULE_VTABLE_RVA]
    if len(matches) != 1:
        raise ProbeError("expected exactly one active include-own rule")
    rule = matches[0]
    if u64(module_base + RULE_VTABLE_RVA + 0x88) != module_base + RULE_EVALUATOR_RVA:
        raise ProbeError("include-own evaluator differs from the pinned build")
    if read_bytes(rule + 0x10, 1) != b"\x00":
        raise ProbeError("include-own rule is not in the observed default mode")
    return rule


def resolve_full_filter(read_bytes, module_base: int, source: int) -> int:
    u64 = lambda address: struct.unpack("<Q", read_bytes(address, 8))[0]
    filter_object = u64(source + 0x78)
    if not filter_object or u64(filter_object) != module_base + FILTER_VTABLE_RVA:
        raise ProbeError("active full filter differs from the pinned build")
    if u64(module_base + FILTER_VTABLE_RVA + 0x48) != module_base + FILTER_EVALUATOR_RVA:
        raise ProbeError("full filter callback differs from the pinned build")
    return filter_object


def _source_records(read_bytes, source: int) -> dict[int, int]:
    begin, end = struct.unpack("<QQ", read_bytes(source + 0xD0, 16))
    if begin <= 0 or end < begin or (end - begin) % 8:
        raise ProbeError("invalid search source vector")
    count = (end - begin) // 8
    if count > MAX_COLD_RULE_CALLS:
        raise ProbeError("source exceeds cold-rule batch limit")
    wrappers = struct.unpack(f"<{count}Q", read_bytes(begin, count * 8))
    records: dict[int, int] = {}
    for index, wrapper in enumerate(wrappers):
        if not wrapper:
            raise ProbeError(f"null source wrapper at index {index}")
        person = struct.unpack("<Q", read_bytes(wrapper, 8))[0]
        if not person:
            raise ProbeError(f"null source person at index {index}")
        player_id = struct.unpack("<i", read_bytes(person + 0xC, 4))[0]
        if player_id < 0 or player_id in records:
            raise ProbeError(f"invalid/duplicate source player at index {index}")
        records[player_id] = person
    return records


def native_filter_batch(
    pid: int,
    module_base: int,
    filter_or_rule: int,
    evaluator_rva: int,
    trap_rva: int,
    filter_context: int,
    scope: int,
    records: dict[int, int],
    known_own_excluded: set[int],
) -> tuple[dict[int, bool], bool]:
    """Call one FM predicate for samples, then all source members if samples pass."""
    excluded_sample = sorted(known_own_excluded)[:3]
    included_sample = sorted(set(records) - known_own_excluded)[:3]
    sample = excluded_sample + included_sample
    if len(sample) != 6 or not known_own_excluded <= records.keys():
        raise ProbeError("saved excluded/visible samples do not fit the live source")
    ordering = sample + [player_id for player_id in sorted(records) if player_id not in sample]
    results: dict[int, bool] = {}
    fd = -1
    attached = False
    stopped = False
    forced_stop = False
    saved: UserRegs | None = None
    try:
        ptrace(PTRACE_ATTACH, pid)
        attached = True
        wait_stopped(pid, 5.0)
        stopped = True
        current = UserRegs()
        ptrace(PTRACE_GETREGS, pid, ctypes.addressof(current))
        saved = UserRegs.from_buffer_copy(bytes(current))
        fd = os.open(f"/proc/{pid}/mem", os.O_RDWR | os.O_CLOEXEC)
        trap = module_base + trap_rva
        if read_exact(fd, trap, 4) != b"\xcc" * 4:
            raise ProbeError("native filter return trap differs from pinned build")
        call_rsp = ((current.rsp - 0x700) & ~0xF) | 8
        context = call_rsp + 0x80
        record = call_rsp + 0xC0
        write_int(fd, call_rsp, trap)
        write_int(fd, context, module_base + FILTER_CONTEXT_VTABLE_RVA)
        write_int(fd, context + 8, filter_context)
        write_int(fd, context + 0x10, 0)
        write_int(fd, context + 0x18, scope)
        write_int(fd, record, module_base + RECORD_WRAPPER_VTABLE_RVA)
        for index, player_id in enumerate(ordering):
            write_int(fd, record + 8, records[player_id])
            call = UserRegs.from_buffer_copy(bytes(saved))
            call.orig_rax = 0xFFFFFFFFFFFFFFFF
            call.rax = 0
            call.rcx = filter_or_rule
            call.rdx = record
            call.r8 = context
            call.rsp = call_rsp
            call.rip = module_base + evaluator_rva
            ptrace(PTRACE_SETREGS, pid, ctypes.addressof(call))
            ptrace(PTRACE_CONT, pid)
            stopped = False
            stop_signal = wait_stopped(pid, 5.0)
            stopped = True
            after = UserRegs()
            ptrace(PTRACE_GETREGS, pid, ctypes.addressof(after))
            if stop_signal != signal.SIGTRAP or after.rip != trap + 1:
                raise ProbeError(
                    f"native filter call stopped before return for player {player_id}: "
                    f"signal={stop_signal}, rip=0x{after.rip:x}"
                )
            results[player_id] = bool(after.rax & 0xFF)
            if index == len(sample) - 1 and any(
                results[item] == (item in known_own_excluded) for item in sample
            ):
                return results, False
        return results, True
    finally:
        if attached:
            if not stopped:
                os.kill(pid, signal.SIGSTOP)
                forced_stop = True
                try:
                    wait_stopped(pid, 5.0)
                    stopped = True
                except (OSError, ProbeError, TimeoutError):
                    pass
            if stopped:
                if saved is not None:
                    ptrace(PTRACE_SETREGS, pid, ctypes.addressof(saved))
                ptrace(PTRACE_DETACH, pid)
            if forced_stop:
                os.kill(pid, signal.SIGCONT)
        if fd >= 0:
            os.close(fd)
        if forced_stop:
            raise ProbeError("native filter batch was force-abandoned mid-call")


def run(report_path: Path, pid: int, invoke: bool, full_filter: bool = False) -> dict[str, Any]:
    preflight = builder_preflight(report_path, "senior-vanarama", pid, False)
    with report_path.open(encoding="utf-8") as source:
        saved = json.load(source)
    senior = _phase_from_report(saved, "senior-vanarama")
    base = _phase_from_report(saved, "no-package")
    before = probe(pid)
    module_base = int(before.module_base, 0)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        reader = _read_at(fd)
        source, filter_context, scope = derive_builder_arguments(
            reader, senior["sourceCapture"]["sourceEvents"]
        )
        native_object = (
            resolve_full_filter(reader, module_base, source) if full_filter
            else resolve_native_rule(reader, module_base, source)
        )
        records = _source_records(reader, source)
    finally:
        os.close(fd)
    if sorted(records) != senior["sourcePlayerIds"]:
        raise ProbeError("live source IDs differ from saved Senior source")
    expected_excluded = set(base["sourceOnlyPlayerIds"])
    known_own_excluded = set(base["firstTeamSourceOnlyPlayerIds"])
    sample_excluded = expected_excluded if full_filter else known_own_excluded
    result: dict[str, Any] = {
        "researchOnly": True,
        "predicate": "FM search filter list" if full_filter else "PERSON_INCLUDE_OWN_FILTER_RULE",
        "nativeFilterPointer": native_object,
        "sourceCount": len(records),
        "savedExcludedCount": len(expected_excluded),
        "knownFirstTeamExcludedCount": len(known_own_excluded),
        "preflight": preflight,
        "invoked": invoke,
    }
    if not invoke:
        return result
    evaluations, complete = native_filter_batch(
        pid, module_base, native_object,
        FILTER_EVALUATOR_RVA if full_filter else RULE_EVALUATOR_RVA,
        FILTER_RETURN_TRAP_RVA if full_filter else RETURN_TRAP_RVA,
        filter_context, scope, records, sample_excluded
    )
    excluded = {player_id for player_id, included in evaluations.items() if not included}
    after = probe(pid)
    result.update({
        "complete": complete,
        "evaluatedCount": len(evaluations),
        "excludedPlayerIds": sorted(excluded),
        "sampleResults": {str(player_id): evaluations[player_id]
                          for player_id in (sorted(sample_excluded)[:3]
                                            + sorted(set(records) - sample_excluded)[:3])},
        "sameGameDate": before.game_date == after.game_date,
        "sameActiveManager": [manager.id for manager in before.human_managers if manager.active]
        == [manager.id for manager in after.human_managers if manager.active],
        "exactlyMatchesSavedExclusions": complete and excluded == expected_excluded,
        "sourceOnlyNotExcludedByPredicate": sorted(expected_excluded - excluded),
        "ruleExcludedButShownBySearch": sorted(excluded - expected_excluded),
        "allFirstTeamSourceOnlyExcluded": known_own_excluded <= excluded,
        "nativeVisibleCount": len(records) - len(excluded) if complete else None,
    })
    if full_filter:
        result["passed"] = bool(
            complete and result["sameGameDate"] and result["sameActiveManager"]
            and result["exactlyMatchesSavedExclusions"]
            and result["nativeVisibleCount"] == senior["uiReportedCount"]
        )
    else:
        result["passed"] = bool(
            complete and result["sameGameDate"] and result["sameActiveManager"]
            and not result["ruleExcludedButShownBySearch"]
            and result["allFirstTeamSourceOnlyExcluded"]
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--invoke", action="store_true",
                        help="call FM's predicate; default is read-only preflight")
    parser.add_argument("--full-filter", action="store_true",
                        help="evaluate the complete active FM search-filter list")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.report, choose_pid(args.pid), args.invoke, args.full_filter)
        if args.invoke:
            path = _write_report(
                result, args.output,
                "cold-full-search-filter" if args.full_filter else "cold-include-own-rule"
            )
            result = {"report": str(path), **result}
    except (OSError, ProbeError, TimeoutError, ValueError, KeyError,
            json.JSONDecodeError) as exc:
        failure = {"researchOnly": True,
                   "predicate": ("FM search filter list" if args.full_filter
                                 else "PERSON_INCLUDE_OWN_FILTER_RULE"),
                   "invoked": args.invoke, "passed": False, "error": str(exc)}
        if args.invoke:
            failure["report"] = str(_write_report(
                failure, args.output, "cold-include-own-rule-failed"
            ))
        print("RESULT " + json.dumps(failure, sort_keys=True), flush=True)
        return 2
    print("RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
