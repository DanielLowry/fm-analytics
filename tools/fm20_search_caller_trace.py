#!/usr/bin/env python3
"""Research-only: record which code calls FM's knowledge and filter functions.

Used to locate Player Search's filtering code: while the user changes a
search filter, passive breakpoints on already-identified functions count
their callers' return addresses and distinct arguments. Selected filter-rule
evaluators receive a reusable wrapper in the second argument, so the trace
also counts distinct candidate pointers at wrapper + 8. Reads only registers,
return addresses, and candidate pointers; never reads attribute values or
calls into FM.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import monotonic
from typing import Callable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_linux_probe import FM20_4_4_STEAM, ProbeError
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_visibility_capture import (
    ERROR_PREFIX,
    CaptureError,
    _LineReader,
    _detach_gdb,
    _validated_module_base,
    _verify_inferior_alive,
    _wait_until_ready,
)

CALLER_PREFIX = "FMVIS_CALLER "
PLAYER_PREFIX = "FMVIS_SEARCH_PLAYER "
PLAYER_OFFSET_PREFIX = "FMVIS_SEARCH_PLAYER_OFFSET "
SOURCE_PREFIX = "FMVIS_SEARCH_SOURCE "
GDB_SCRIPT = Path(__file__).with_suffix(".gdb")
TRACE_TARGETS = {
    "visible_result_builder": "0x15A4A90",
    "classification_core": "0x15A4DC0",
    "baseline_knowledge": "0x15A53F0",
    "explicit_knowledge_lookup": "0x15A5D80",
    "knowledge_context_resolver": "0x22DC630",
    "builder_wrapper": "0x22DC790",
    "classification_wrapper": "0x50A0450",
    "knowledge_level": "0x1FB1860",
    "field_visibility": "0x1FB1910",
    "classify_with_masking_override": "0x1FB19E0",
    "masking_heavy_function": "0x5231A30",
    "large_field_switch": "0x1D859B0",
    "rule_person_position": "0x547C390",
    "rule_person_transfer_listed": "0x547BB70",
    "rule_person_interested_loan": "0x1FB1F30",
    "rule_player_scouted": "0x553A2B0",
    "rule_person_include_own": "0x5469890",
    "rule_database_size": "0x6FD2660",
    "rule_can_be_scouted_slot5": "0x54E8B40",
    "rule_can_be_scouted_slot15": "0x54E77E0",
    "rule_can_be_scouted_slot16": "0x54E77B0",
    "rule_can_be_scouted_slot17": "0x54E8A10",
    "generic_filter_slot9": "0x42C96A0",
    "search_filter_pass": "0x52769E0",
    "person_search_slot4": "0x1D62750",
    "person_search_slot5": "0x1D65010",
    "person_search_slot6": "0x1D635F0",
    "person_search_slot7": "0x1D63F50",
    "person_search_slot8": "0x1D62E50",
    "person_search_slot9": "0x1D63340",
    "person_search_slot10": "0x1D66930",
    "person_search_slot11": "0x1D671D0",
    "person_search_slot12": "0x1D67110",
    "scouted_person_slot4": "0x1DA87D0",
    "scout_manager_a": "0x25894C0",
    "scout_manager_b": "0x25A5520",
    "shortlist_man_a": "0x25C4120",
    "shortlist_man_b": "0x25E3660",
}


def trace_callers(
    pid: int,
    *,
    duration_seconds: float,
    targets: Mapping[str, str] | None = None,
    candidate_only: bool = False,
    source_only: bool = False,
    combined_only: bool = False,
    stop_requested: Callable[[], bool] | None = None,
    settle_seconds: float = 2.0,
    ready_callback=None,
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    if duration_seconds <= 0:
        raise CaptureError("trace duration must be positive")
    if sum((candidate_only, source_only, combined_only)) > 1:
        raise CaptureError("capture modes are mutually exclusive")
    if settle_seconds < 0:
        raise CaptureError("settle_seconds cannot be negative")
    if targets is not None:
        if candidate_only or source_only or combined_only:
            raise CaptureError("custom targets cannot use search-capture modes")
        if not 1 <= len(targets) <= 16:
            raise CaptureError("custom trace requires 1 to 16 targets")
        for label, rva in targets.items():
            try:
                address = int(rva, 0)
            except (TypeError, ValueError) as exc:
                raise CaptureError(f"invalid trace RVA for {label!r}") from exc
            if not label or not 0 < address < FM20_4_4_STEAM.expected_executable_size:
                raise CaptureError(f"invalid trace target {label!r}")
    module_base = _validated_module_base(pid, proc_root)
    environment = dict(os.environ)
    environment["FMVIS_MODULE_BASE"] = hex(module_base)
    environment["FMVIS_MODULE_END"] = hex(
        module_base + FM20_4_4_STEAM.expected_executable_size
    )
    if targets is not None:
        active_targets = dict(targets)
    elif candidate_only:
        active_targets = {"large_field_switch": TRACE_TARGETS["large_field_switch"]}
    elif source_only:
        active_targets = {"search_filter_pass": TRACE_TARGETS["search_filter_pass"]}
    elif combined_only:
        active_targets = {
            name: TRACE_TARGETS[name]
            for name in ("large_field_switch", "search_filter_pass")
        }
    else:
        active_targets = TRACE_TARGETS
    environment["FMVIS_TRACE_TARGETS"] = json.dumps(active_targets)
    environment["FMVIS_CAPTURE_CANDIDATES"] = "1" if candidate_only or combined_only else "0"
    environment["FMVIS_CAPTURE_SOURCE"] = "1" if source_only or combined_only else "0"
    command = [
        "gdb", "-q", "-nx", "-ex", "set pagination off",
        "-ex", "set confirm off", "-ex", "set print thread-events off",
        "-ex", "handle SIGUSR1 nostop noprint pass",
        "-ex", f"source {GDB_SCRIPT}",
        "-p", str(pid),
    ]
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env=environment,
        )
    except OSError as exc:
        raise CaptureError(f"cannot start GDB: {exc}") from exc
    reader = _LineReader(process)
    result: dict[str, object] = {}
    candidate_pointers: dict[int, int | None] = {}
    player_offsets: set[int] = set()
    source_events: list[dict[str, int]] = []
    pending_error: CaptureError | None = None
    try:
        _wait_until_ready(process, reader)
        if ready_callback is not None:
            ready_callback()
        deadline = monotonic() + duration_seconds
        done_at: float | None = None
        while monotonic() < deadline:
            if done_at is None and stop_requested is not None and stop_requested():
                done_at = monotonic()
            if done_at is not None and monotonic() >= done_at + settle_seconds:
                break
            wait_seconds = deadline - monotonic()
            if stop_requested is not None:
                wait_seconds = min(wait_seconds, 0.25)
            if done_at is not None:
                wait_seconds = min(wait_seconds, done_at + settle_seconds - monotonic())
            line = reader.read_line(max(0.0, wait_seconds))
            if line is None:
                if process.poll() is not None:
                    raise CaptureError(
                        f"GDB exited unexpectedly with status {process.returncode}"
                    )
                continue
            if line.startswith(ERROR_PREFIX):
                raise CaptureError(line.removeprefix(ERROR_PREFIX))
            if line.startswith(PLAYER_PREFIX):
                candidate = json.loads(line.removeprefix(PLAYER_PREFIX))
                candidate_pointers[int(candidate["pointer"])] = candidate["player_id"]
                continue
            if line.startswith(PLAYER_OFFSET_PREFIX):
                player_offsets.add(int(line.removeprefix(PLAYER_OFFSET_PREFIX)))
                continue
            if line.startswith(SOURCE_PREFIX):
                source_events.append(json.loads(line.removeprefix(SOURCE_PREFIX)))
                continue
            if line.startswith(CALLER_PREFIX):
                event = json.loads(line.removeprefix(CALLER_PREFIX))
                caller = (
                    hex(event["caller_rva"]) if event["caller_rva"] >= 0 else "outside-module"
                )
                entry = result.setdefault(
                    event["function"],
                    {"callers": {}, "distinct_second_args": 0,
                     "distinct_record_payloads": 0},
                )
                callers = entry["callers"]
                callers[caller] = max(callers.get(caller, 0), event["count"])
                entry["distinct_second_args"] = max(
                    entry["distinct_second_args"], event.get("distinct_rdx", 0)
                )
                entry["distinct_record_payloads"] = max(
                    entry["distinct_record_payloads"],
                    event.get("distinct_record_payloads") or 0,
                )
    except CaptureError as exc:
        pending_error = exc
    finally:
        detach_error = _detach_gdb(process, reader)
    if pending_error is not None:
        raise pending_error
    if detach_error is not None:
        raise detach_error
    _verify_inferior_alive(pid, proc_root)
    if candidate_only or combined_only:
        result["_candidate_pointer_ids"] = sorted(
            (pointer, player_id) for pointer, player_id in candidate_pointers.items()
        )
        result["_candidate_identity_offsets"] = sorted(player_offsets)
    if source_only or combined_only:
        result["_search_source_events"] = source_events
    return result


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument(
        "--candidate-only", action="store_true",
        help="capture player IDs observed by an in-game search pass",
    )
    args = parser.parse_args(argv)
    try:
        result = trace_callers(
            choose_pid(args.pid),
            duration_seconds=args.duration,
            candidate_only=args.candidate_only,
            ready_callback=lambda: print("ARMED", flush=True),
        )
    except (CaptureError, ProbeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
