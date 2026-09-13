#!/usr/bin/env python3
"""Research-only cold FM20 visibility call using direct Linux ptrace registers.

The target player must already have been established as discoverable. This
does not implement the discoverability gate and is not a production bridge.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from tools.fm20_cold_visibility_call import preflight
from tools.fm20_linux_probe import ProbeError
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_visibility_trace import DISPLAY_ATTRIBUTE_IDS


class UserRegs(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "r15", "r14", "r13", "r12", "rbp", "rbx", "r11", "r10",
            "r9", "r8", "rax", "rcx", "rdx", "rsi", "rdi", "orig_rax",
            "rip", "cs", "eflags", "rsp", "ss", "fs_base", "gs_base",
            "ds", "es", "fs", "gs",
        )
    ]


LIBC = ctypes.CDLL(None, use_errno=True)
LIBC.ptrace.restype = ctypes.c_long
LIBC.ptrace.argtypes = [
    ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p
]
PTRACE_CONT = 7
PTRACE_GETREGS = 12
PTRACE_SETREGS = 13
PTRACE_ATTACH = 16
PTRACE_DETACH = 17
WAIT_ALL = 0x40000000


def ptrace(request: int, tid: int, data: int = 0) -> None:
    ctypes.set_errno(0)
    result = LIBC.ptrace(request, tid, None, ctypes.c_void_p(data))
    if result == -1:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def wait_stopped(tid: int, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waited, status = os.waitpid(tid, os.WNOHANG | WAIT_ALL)
        if waited == tid:
            if not os.WIFSTOPPED(status):
                raise ProbeError(f"FM thread exited during native call (status {status})")
            return os.WSTOPSIG(status)
        time.sleep(0.01)
    raise TimeoutError("FM did not stop at the native-call return trap")


def write_int(fd: int, address: int, value: int, size: int = 8) -> None:
    encoded = value.to_bytes(size, "little")
    if os.pwrite(fd, encoded, address) != size:
        raise ProbeError("short write to disposable FM thread stack")


def cold_query(pid: int, player_id: int, attribute: str) -> tuple[int, int]:
    inputs = preflight(pid, player_id, attribute)
    module_base = int(inputs["FM_COLD_MODULE_BASE"], 0)
    context = int(inputs["FM_COLD_CONTEXT"], 0)
    player = int(inputs["FM_COLD_PLAYER_INTERFACE"], 0)
    manager = int(inputs["FM_COLD_MANAGER_INTERFACE"], 0)
    builder = module_base + 0x15A4A90
    return_trap = module_base + 0x15A4A84  # verified INT3 padding
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

        call_rsp = ((current.rsp - 0x400) & ~0xF) | 8
        result = call_rsp + 0xA0
        small_context = call_rsp + 0x80
        write_int(fd, call_rsp, return_trap)
        write_int(fd, call_rsp + 0x28, 0)  # optional report object
        write_int(fd, call_rsp + 0x30, small_context)
        write_int(fd, small_context, manager)
        write_int(fd, small_context + 8, 1)
        write_int(fd, result, 0xFFFFFFFFFFFFFFFF)

        current.orig_rax = 0xFFFFFFFFFFFFFFFF  # do not restart interrupted syscall
        current.rax = 0
        current.rcx = context
        current.rdx = result
        current.r8 = player
        current.r9 = DISPLAY_ATTRIBUTE_IDS[attribute]
        current.rsp = call_rsp
        current.rip = builder
        ptrace(PTRACE_SETREGS, pid, ctypes.addressof(current))
        ptrace(PTRACE_CONT, pid)
        stopped = False
        stop_signal = wait_stopped(pid, 10.0)
        stopped = True
        after = UserRegs()
        ptrace(PTRACE_GETREGS, pid, ctypes.addressof(after))
        if stop_signal != signal.SIGTRAP or after.rip != return_trap + 1:
            raise ProbeError(
                "native call stopped before its return trap: "
                f"signal={stop_signal}, rip=0x{after.rip:x}"
            )
        public = os.pread(fd, 2, result)
        if len(public) != 2:
            raise ProbeError("short read of public visibility bytes")
        return public[0], public[1]
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
            raise ProbeError(
                "native call did not reach its return trap within the timeout "
                "and was force-abandoned mid-flight; the builder may have "
                "partially executed (it can lazily write lookup/report state) "
                "before being interrupted, so verify FM is still healthy "
                "before attempting another cold call"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--player-id", type=int, required=True)
    parser.add_argument("--attribute", choices=sorted(DISPLAY_ATTRIBUTE_IDS), required=True)
    parser.add_argument("--acknowledge-native-call", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run preflight only; never attach or call into FM",
    )
    args = parser.parse_args()
    if not args.dry_run and not args.acknowledge_native_call:
        parser.error("--acknowledge-native-call is required unless --dry-run is set")
    try:
        if args.dry_run:
            print(json.dumps(preflight(choose_pid(args.pid), args.player_id, args.attribute), sort_keys=True))
            return 0
        bounds = cold_query(choose_pid(args.pid), args.player_id, args.attribute)
        observation = decode_visible_bound_bytes(*bounds)
    except (OSError, ProbeError, TimeoutError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "playerId": str(args.player_id),
        "attribute": args.attribute,
        "visibility": observation.visibility.value,
        "value": observation.value,
        "minimum": observation.minimum,
        "maximum": observation.maximum,
        "researchOnly": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
