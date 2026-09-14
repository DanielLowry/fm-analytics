#!/usr/bin/env python3
"""Research-only cold invocation of FM20's package-sensitive search source builder.

This tests native recomputation without refreshing Player Search. It is not a
discoverability service: the source includes players excluded by FM's later
filter, and this probe currently reuses a previously observed search object.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import signal
import struct
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_cold_visibility_call import EXPECTED_SHA256
from tools.fm20_cold_visibility_ptrace import (
    PTRACE_ATTACH,
    PTRACE_CONT,
    PTRACE_DETACH,
    PTRACE_GETREGS,
    PTRACE_SETREGS,
    UserRegs,
    ptrace,
    wait_stopped,
    write_int,
)
from tools.fm20_discoverability_experiment import (
    _write_report,
    resolve_source_vector_ids,
)
from tools.fm20_linux_probe import ProbeError, read_exact
from tools.fm20_linux_probe_runtime import choose_pid, probe
from tools.fm20_native_call_log import log_event, next_call_number

BUILDER_RVA = 0x52778C0
RETURN_TRAP_RVA = 0x52778BC  # four INT3 bytes before the builder
EXPECTED_SOURCE_TYPE = 1  # player-search source object in the pinned build


def _read_at(fd: int) -> Callable[[int, int], bytes]:
    return lambda address, size: read_exact(fd, address, size)


def _vector_ids(
    read_bytes: Callable[[int, int], bytes], module_base: int, source: int
) -> list[int]:
    begin, end = struct.unpack("<QQ", read_bytes(source + 0xD0, 16))
    return resolve_source_vector_ids(read_bytes, module_base, [{
        "source_pointer": source,
        "vector_begin": begin,
        "vector_end": end,
        "vector_count": (end - begin) // 8 if end >= begin else -1,
    }])


def derive_builder_arguments(
    read_bytes: Callable[[int, int], bytes],
    events: Sequence[dict[str, int]],
) -> tuple[int, int, int]:
    """Recover (source, filter context, scope) from one stable UI trace."""
    if not events:
        raise ProbeError("saved report has no search-source events")
    identities = {
        (event["source_pointer"], event["filter_pointer"], event["context_pointer"])
        for event in events
    }
    if len(identities) != 1:
        raise ProbeError("search-source call arguments changed within the capture")
    source, filter_context, call_context = identities.pop()
    if min(source, filter_context, call_context) <= 0 or call_context < 0x30:
        raise ProbeError("invalid saved search-source arguments")
    if read_bytes(source + 0x24, 1)[0] != EXPECTED_SOURCE_TYPE:
        raise ProbeError("source object is not the player-search source type")
    source_filter = struct.unpack("<Q", read_bytes(source, 8))[0]
    request_filter = struct.unpack("<Q", read_bytes(call_context - 0x28, 8))[0]
    if source_filter != filter_context or request_filter != filter_context:
        raise ProbeError("saved filter context no longer matches the live source/request")
    scope = struct.unpack("<Q", read_bytes(call_context - 0x20, 8))[0]
    if scope == 0:
        raise ProbeError("search request's manager/scope pointer is missing")
    return source, filter_context, scope


def cold_build(pid: int, module_base: int, arguments: tuple[int, int, int]) -> int:
    """Invoke one FM-native builder call on the main thread, restoring registers."""
    source, filter_context, scope = arguments
    builder = module_base + BUILDER_RVA
    trap = module_base + RETURN_TRAP_RVA
    call_number = next_call_number()
    log_event(
        "cold_build_started", call_number=call_number, pid=pid,
        source=hex(source), filter_context=hex(filter_context), scope=hex(scope),
    )
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
        if read_exact(fd, trap, 4) != b"\xcc" * 4:
            raise ProbeError("native builder return trap bytes differ from pinned build")
        call_rsp = ((current.rsp - 0x600) & ~0xF) | 8
        write_int(fd, call_rsp, trap)
        current.orig_rax = 0xFFFFFFFFFFFFFFFF
        current.rax = 0
        current.rcx = source
        current.rdx = filter_context
        current.r8 = scope
        current.rsp = call_rsp
        current.rip = builder
        ptrace(PTRACE_SETREGS, pid, ctypes.addressof(current))
        ptrace(PTRACE_CONT, pid)
        stopped = False
        stop_signal = wait_stopped(pid, 60.0)
        stopped = True
        after = UserRegs()
        ptrace(PTRACE_GETREGS, pid, ctypes.addressof(after))
        if stop_signal != signal.SIGTRAP or after.rip != trap + 1:
            raise ProbeError(
                "native source builder stopped before its return trap: "
                f"signal={stop_signal}, rip=0x{after.rip:x}"
            )
        return int(after.rax)
    except BaseException as exc:
        log_event(
            "cold_build_failed", call_number=call_number, pid=pid,
            exception_type=type(exc).__name__, exception=str(exc),
        )
        raise
    finally:
        if attached:
            if not stopped:
                log_event("cold_build_force_stopping", call_number=call_number, pid=pid)
                os.kill(pid, signal.SIGSTOP)
                forced_stop = True
                try:
                    wait_stopped(pid, 5.0)
                    stopped = True
                except (OSError, ProbeError, TimeoutError) as exc:
                    log_event(
                        "cold_build_force_stop_failed", call_number=call_number,
                        pid=pid, exception_type=type(exc).__name__, exception=str(exc),
                    )
            if stopped:
                if saved is not None:
                    ptrace(PTRACE_SETREGS, pid, ctypes.addressof(saved))
                ptrace(PTRACE_DETACH, pid)
                log_event("cold_build_detached", call_number=call_number, pid=pid)
            if forced_stop:
                os.kill(pid, signal.SIGCONT)
        if fd >= 0:
            os.close(fd)
        if forced_stop:
            raise ProbeError(
                "native source builder did not return within 60 seconds and was "
                "force-abandoned mid-call; FM may have partial search-state changes"
            )


def _phase_from_report(report: dict[str, Any], state: str) -> dict[str, Any]:
    phases = [phase for phase in report.get("phases", []) if phase.get("stateLabel") == state]
    if len(phases) != 1 or not phases[0]["sourceCapture"]["passed"]:
        raise ProbeError(f"saved report has no valid {state} source capture")
    return phases[0]


def run(report_path: Path, state: str, pid: int, invoke: bool) -> dict[str, Any]:
    with report_path.open(encoding="utf-8") as source:
        saved_report = json.load(source)
    phase = _phase_from_report(saved_report, state)
    before = probe(pid)
    if before.game_date != phase["gameDate"]:
        raise ProbeError("in-game date differs from the saved source capture")
    active = [manager.id for manager in before.human_managers if manager.active]
    if active != [phase["activeManagerId"]]:
        raise ProbeError("active manager differs from the saved source capture")
    module_base = int(before.module_base, 0)
    with Path(before.executable).open("rb") as image:
        if hashlib.file_digest(image, "sha256").hexdigest() != EXPECTED_SHA256:
            raise ProbeError("FM executable hash differs from the pinned build")
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        reader = _read_at(fd)
        arguments = derive_builder_arguments(
            reader, phase["sourceCapture"]["sourceEvents"]
        )
        before_ids = _vector_ids(reader, module_base, arguments[0])
    finally:
        os.close(fd)
    expected_ids = phase["sourcePlayerIds"]
    if before_ids != expected_ids:
        raise ProbeError(
            "live source vector does not match the saved state; this probe "
            "will not infer package state from a stale search object"
        )
    result: dict[str, Any] = {
        "researchOnly": True,
        "stateLabel": state,
        "pid": pid,
        "gameDate": before.game_date,
        "activeManagerId": active[0],
        "sourcePointer": arguments[0],
        "filterContextPointer": arguments[1],
        "scopePointer": arguments[2],
        "beforeCount": len(before_ids),
        "beforeMatchesSavedSource": True,
        "invoked": invoke,
    }
    if not invoke:
        return result
    result["nativeReturnValue"] = cold_build(pid, module_base, arguments)
    after = probe(pid)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        after_ids = _vector_ids(_read_at(fd), module_base, arguments[0])
    finally:
        os.close(fd)
    result.update({
        "afterCount": len(after_ids),
        "addedPlayerIds": sorted(set(after_ids) - set(before_ids)),
        "removedPlayerIds": sorted(set(before_ids) - set(after_ids)),
        "sameGameDate": before.game_date == after.game_date,
        "sameActiveManager": active == [manager.id for manager in after.human_managers
                                    if manager.active],
        "afterMatchesSavedSource": after_ids == expected_ids,
    })
    result["passed"] = all((
        result["sameGameDate"], result["sameActiveManager"],
        result["afterMatchesSavedSource"],
    ))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True,
                        help="saved package-study report")
    parser.add_argument("--state", choices=("no-package", "senior-vanarama"),
                        default="senior-vanarama")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--invoke", action="store_true",
                        help="execute one native builder call; default is dry-run")
    parser.add_argument("--guided-offscreen", action="store_true",
                        help="prompt you to leave Player Search before the native call")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.guided_offscreen and not args.invoke:
        parser.error("--guided-offscreen requires --invoke")
    if args.guided_offscreen and not sys.stdin.isatty():
        parser.error("--guided-offscreen requires an interactive terminal")
    if args.guided_offscreen:
        print(
            "OFF-SCREEN TEST: leave Player Search and open an unrelated FM screen "
            "such as Inbox. Do not change the scouting package or advance the "
            "in-game date. This tests whether FM can rebuild the player pool "
            "while Player Search is not open.\n"
            "Press Enter here only after the unrelated screen is fully visible.",
            flush=True,
        )
        input("READY: ")
    try:
        result = run(args.report, args.state, choose_pid(args.pid), args.invoke)
        if args.guided_offscreen:
            result["screenEvidence"] = "operator-declared unrelated screen; no UI capture"
        if args.invoke:
            path = _write_report(result, args.output, "cold-source-builder")
            result = {"report": str(path), **result}
    except (OSError, ProbeError, TimeoutError, ValueError, KeyError,
            json.JSONDecodeError, EOFError) as exc:
        failure = {
            "researchOnly": True,
            "stateLabel": args.state,
            "invoked": args.invoke,
            "screenEvidence": (
                "operator-declared unrelated screen; no UI capture"
                if args.guided_offscreen else "not recorded"
            ),
            "passed": False,
            "error": str(exc),
        }
        if args.invoke:
            path = _write_report(failure, args.output, "cold-source-builder-failed")
            failure["report"] = str(path)
        print("RESULT " + json.dumps(failure, sort_keys=True), flush=True)
        return 2
    print("RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
