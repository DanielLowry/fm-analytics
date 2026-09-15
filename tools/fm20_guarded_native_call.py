#!/usr/bin/env python3
"""Shared, crash-safe primitive for injecting one native call into FM.

Every research tool that cold-calls into FM's own code follows the same
shape: attach, save the thread's registers, point a scratch stack entry at
a pinned single-byte return trap, set up the call's arguments, resume, wait
for the trap, then restore the original registers and detach -- whatever
happened. That sequence was previously duplicated, slightly differently,
in `fm20_discoverability_cold_builder.cold_build`,
`fm20_discoverability_cold_filter.native_filter_batch`, and one-off
research scripts. This module is the single, tested implementation; a
fault *inside* the injected call (FM's own code segfaulting, say) is
reported back as data via `GuardedCallResult`, not raised -- only a
genuinely unrecoverable condition (the tracee cannot be safely restored
and detached afterwards) raises.
"""

from __future__ import annotations

import ctypes
import os
import signal
from dataclasses import dataclass
from typing import Callable

from tools.fm20_cold_visibility_ptrace import (
    PTRACE_ATTACH,
    PTRACE_CONT,
    PTRACE_DETACH,
    PTRACE_GETREGS,
    PTRACE_SETREGS,
    UserRegs,
    ptrace,
    wait_stopped,
)
from tools.fm20_linux_probe import ProbeError, read_exact

Configure = Callable[[int, UserRegs, int], None]


@dataclass(frozen=True)
class GuardedCallResult:
    """The outcome of exactly one guarded native call.

    Exactly one of the two shapes is populated: a clean return
    (`succeeded=True`, `return_value` set), or a fault the call never
    returned from (`succeeded=False`, `fault_signal`/`fault_rip` set from
    whatever the tracee's registers showed when it stopped -- a genuine
    hardware fault inside FM's code, not our own bookkeeping). In both
    cases FM's own registers have already been restored to their pre-call
    state and the tracer has detached before this is returned.
    """

    succeeded: bool
    return_value: int | None
    fault_signal: int | None
    fault_rip: int | None


def guarded_native_call(
    pid: int,
    trap_address: int,
    configure: Configure,
    *,
    timeout_seconds: float = 5.0,
    stack_reserve: int = 0x700,
) -> GuardedCallResult:
    """Attach, run exactly one native call to completion or fault, detach.

    `configure(memory_fd, call_regs, call_rsp)` must set `call_regs.rip`
    and whichever argument registers the call needs (rcx/rdx/r8/r9 for the
    Windows x64 convention every FM call site uses), and may use
    `memory_fd` to write further scratch-stack or shadow-space arguments.
    `call_regs` starts as a copy of the tracee's real registers with
    `rsp` already repointed at a `stack_reserve`-byte-deep, 16-byte-aligned
    scratch area below the real stack (matching every existing call site);
    `configure` may raise its own reservation by setting `call_regs.rsp`
    to something even lower before returning. `configure` must not touch
    ptrace itself or attempt to restore/detach -- that is this function's
    job, unconditionally, regardless of how the call turns out.

    `trap_address` must already hold a single pinned `0xCC` byte (padded
    to 4 bytes, matching every existing call site's verification) for the
    callee to return into; this is checked before ever resuming FM, and
    `guarded_native_call` writes the scratch stack's return-address slot
    itself (`[call_rsp] = trap_address`) -- `configure` does not need to.

    A fault inside the injected call (FM's own code faulting on bad
    arguments, say) is reported as data (`succeeded=False`, `fault_signal`
    and `fault_rip` set) -- not raised -- because it is safely
    recoverable: the tracee stopped exactly where we could observe it, so
    its pre-call registers are restored and it is detached before this
    function returns, and FM resumes exactly as if the call had never
    happened. A call that never stops at all within `timeout_seconds`
    (a hang, or a fault deep enough that no signal is ever delivered) is
    different: recovery there requires forcibly stopping the tracee, and
    even if that succeeds, there is no way to know what the call did
    before it was interrupted. That case always raises `ProbeError`
    -- matching every existing call site's "force-abandoned" behaviour --
    rather than being reported as a normal result.
    """
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
        if read_exact(fd, trap_address, 4) != b"\xcc" * 4:
            raise ProbeError("native call return trap differs from the pinned build")
        call_rsp = ((current.rsp - stack_reserve) & ~0xF) | 8
        os.pwrite(fd, trap_address.to_bytes(8, "little"), call_rsp)
        call_regs = UserRegs.from_buffer_copy(bytes(saved))
        call_regs.orig_rax = 0xFFFFFFFFFFFFFFFF
        call_regs.rax = 0
        call_regs.rsp = call_rsp
        configure(fd, call_regs, call_rsp)
        ptrace(PTRACE_SETREGS, pid, ctypes.addressof(call_regs))
        ptrace(PTRACE_CONT, pid)
        stopped = False
        stop_signal = wait_stopped(pid, timeout_seconds)
        stopped = True
        after = UserRegs()
        ptrace(PTRACE_GETREGS, pid, ctypes.addressof(after))
        if stop_signal == signal.SIGTRAP and after.rip == trap_address + 1:
            return GuardedCallResult(
                succeeded=True, return_value=after.rax,
                fault_signal=None, fault_rip=None,
            )
        return GuardedCallResult(
            succeeded=False, return_value=None,
            fault_signal=stop_signal, fault_rip=after.rip,
        )
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
                "native call was force-abandoned mid-call; FM's registers "
                "could not be safely restored"
            )


def verify_process_alive(pid: int) -> bool:
    """True if the process still exists, without needing `ps` or /proc text parsing."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
