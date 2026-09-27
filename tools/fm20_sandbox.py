#!/usr/bin/env python3
"""Run FM20's own code in an emulator over a lazily-copied view of its memory.

Every earlier way of getting FM's *exact* visible-attribute answer ran FM's
visibility builder inside the live game -- by ptrace register injection or a
Frida hook -- and that is the prime suspect for the saves that broke on 17 and
26 September 2026 (see ``docs/scouting-workspace.md``). This module runs the
same machine code somewhere else: a Unicorn x86-64 CPU whose memory starts
empty and is filled on demand, one page at a time, from ``/proc/<pid>/mem``
opened read-only.

What that buys:

- **FM's own logic, not a reimplementation.** Whatever FM would consult to
  decide what the manager can see -- scout reports, packages, reputation,
  trials, anything -- the emulated code consults the same way.
- **The game cannot be changed.** Nothing here attaches to, stops, or writes to
  FM. Any write FM's code makes (the builder updates lookup caches in the
  knowledge context, for example) lands in the emulator's private copy of that
  page and is discarded with the sandbox.

What it does not buy: a consistent snapshot. Pages are copied when first
touched while FM keeps running, so a page copied late can disagree with one
copied early. Callers keep the existing before/after identity checks, and a
sandbox should be short-lived -- one refresh, not a session.

Research status: trial. See ``docs/scouting-workspace.md`` before promoting.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from unicorn import (
    UC_ARCH_X86,
    UC_HOOK_INSN,
    UC_HOOK_MEM_FETCH_UNMAPPED,
    UC_HOOK_MEM_READ_UNMAPPED,
    UC_HOOK_MEM_WRITE_UNMAPPED,
    UC_MODE_64,
    UC_PROT_ALL,
    Uc,
    UcError,
)
from unicorn.x86_const import (
    UC_X86_INS_SYSCALL,
    UC_X86_REG_GS_BASE,
    UC_X86_REG_R8,
    UC_X86_REG_R9,
    UC_X86_REG_RAX,
    UC_X86_REG_RCX,
    UC_X86_REG_RDX,
    UC_X86_REG_RIP,
    UC_X86_REG_RSP,
)


PAGE = 0x1000
# Copy this much at once when all of it is readable: FM's heap objects cluster,
# so neighbouring pages are usually wanted next, and one emulator region per
# 4 KB page gets slow once thousands exist.
CHUNK = 0x10000
PRIVATE_SIZE = 0x400000  # stack, fake thread block, call arguments, return trap
STACK_SIZE = 0x200000
CALL_TIMEOUT_SECONDS = 5.0
TEB_TLS_POINTER = 0x58
# MSVC's thread-safe function statics compare a guard with this per-thread
# epoch (``_Init_thread_epoch``, offset 0x50 in fm.exe 20.4.4's TLS block):
# a guard above it sends the call through ``_Init_thread_header``, which may
# wait on another thread. Initialised statics hold guards counting up from
# INT_MIN, an uninitialised one holds 0 and one being initialised holds -1.
# An epoch of -2 therefore treats every static FM has already built as
# built, while 0 and -1 still take FM's own initialisation path.
INIT_THREAD_EPOCH_OFFSET = 0x50
SANDBOX_THREAD_EPOCH = -2


class SandboxError(RuntimeError):
    """FM's code needed something the sandbox cannot provide."""


@dataclass
class SandboxStats:
    calls: int = 0
    seconds: float = 0.0
    chunks_loaded: int = 0
    pages_loaded: int = 0
    faults: list[str] = field(default_factory=list)


def _free_region(pid: int, size: int) -> int:
    """A user-space address range FM has nothing mapped in, for our own use.

    It must not overlap FM's memory: the sandbox would then answer FM's reads
    of that range with our stack instead of FM's data.
    """
    used = []
    with Path(f"/proc/{pid}/maps").open(encoding="utf-8") as maps:
        for line in maps:
            low, high = (int(value, 16) for value in line.split()[0].split("-"))
            used.append((low, high))
    used.sort()
    candidate = 0x10000000
    for low, high in used:
        if low >= candidate + size:
            return candidate
        candidate = max(candidate, (high + CHUNK - 1) & ~(CHUNK - 1))
    raise SandboxError("no free address range for the sandbox's private memory")


class FmSandbox:
    """One short-lived emulated CPU over FM's memory, copied on first touch."""

    def __init__(self, pid: int, module_base: int):
        self.pid = pid
        self.module_base = module_base
        self.fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.stats = SandboxStats()
        self._mapped: set[int] = set()
        self._stopped_by: str | None = None

        self.private = _free_region(pid, PRIVATE_SIZE)
        self.uc.mem_map(self.private, PRIVATE_SIZE, UC_PROT_ALL)
        self._mapped.update(range(self.private, self.private + PRIVATE_SIZE, PAGE))
        self.stack_top = self.private + STACK_SIZE - 0x100
        # A minimal Windows thread block: code that checks its stack bounds or
        # asks for its own TEB gets our stack, never FM's real thread's.
        self.teb = self.private + STACK_SIZE
        self.uc.mem_write(self.teb + 0x08, self.stack_top.to_bytes(8, "little"))
        self.uc.mem_write(self.teb + 0x10, self.private.to_bytes(8, "little"))
        self.uc.mem_write(self.teb + 0x30, self.teb.to_bytes(8, "little"))
        self.uc.reg_write(UC_X86_REG_GS_BASE, self.teb)
        tls_array = self.teb + 0x1000
        tls_block = self.teb + 0x2000
        self._build_thread_locals(tls_array, tls_block)
        self.scratch = self.teb + 0x6000
        self.return_trap = self.scratch + 0x1000
        self.uc.mem_write(self.return_trap, b"\xf4")  # hlt; never executed

        self.uc.hook_add(
            UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED,
            self._on_unmapped,
        )
        self.uc.hook_add(UC_HOOK_INSN, self._on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)

    def _build_thread_locals(self, tls_array: int, tls_block: int) -> None:
        """Give the sandbox thread fm.exe's thread-local storage, as a new thread gets it.

        The block is fm.exe's own TLS template, read from the running process,
        so every thread-local starts where Windows would start it for a fresh
        thread -- except the static-initialisation epoch, which is set so that
        statics FM already built are not rebuilt (see ``SANDBOX_THREAD_EPOCH``).
        """
        base = self.module_base
        pe = base + int.from_bytes(os.pread(self.fd, 4, base + 0x3C), "little")
        tls_rva = int.from_bytes(os.pread(self.fd, 4, pe + 24 + 112 + 9 * 8), "little")
        directory = os.pread(self.fd, 40, base + tls_rva)
        start, end, index_address = (
            int.from_bytes(directory[offset:offset + 8], "little") for offset in (0, 8, 16)
        )
        zero_fill = int.from_bytes(directory[32:36], "little")
        template = os.pread(self.fd, end - start, start) + bytes(zero_fill)
        if len(template) < INIT_THREAD_EPOCH_OFFSET + 4 or len(template) > 0x4000:
            raise SandboxError(f"unexpected fm.exe TLS template size {len(template)}")
        index = int.from_bytes(os.pread(self.fd, 4, index_address), "little")
        if index > 0x1F:
            raise SandboxError(f"unexpected fm.exe TLS index {index}")
        self.uc.mem_write(tls_block, template)
        self.uc.mem_write(
            tls_block + INIT_THREAD_EPOCH_OFFSET,
            SANDBOX_THREAD_EPOCH.to_bytes(4, "little", signed=True),
        )
        self.uc.mem_write(tls_array + 8 * index, tls_block.to_bytes(8, "little"))
        self.uc.mem_write(self.teb + TEB_TLS_POINTER, tls_array.to_bytes(8, "little"))

    def close(self) -> None:
        os.close(self.fd)

    def __enter__(self) -> FmSandbox:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _load(self, address: int, size: int) -> bool:
        data = None
        try:
            data = os.pread(self.fd, size, address)
        except OSError:
            pass
        if data is None or len(data) != size:
            return False
        self.uc.mem_map(address, size, UC_PROT_ALL)
        self.uc.mem_write(address, data)
        self._mapped.update(range(address, address + size, PAGE))
        return True

    def _on_unmapped(self, uc, access, address, size, _value, _user_data) -> bool:
        first = address & ~(PAGE - 1)
        last = (address + max(size, 1) - 1) & ~(PAGE - 1)
        for page in range(first, last + PAGE, PAGE):
            if page in self._mapped:
                continue
            chunk = page & ~(CHUNK - 1)
            chunk_pages = range(chunk, chunk + CHUNK, PAGE)
            if not any(p in self._mapped for p in chunk_pages) and self._load(chunk, CHUNK):
                self.stats.chunks_loaded += 1
                continue
            if self._load(page, PAGE):
                self.stats.pages_loaded += 1
                continue
            self.stats.faults.append(f"access {access} at 0x{address:x} (rip 0x{uc.reg_read(UC_X86_REG_RIP):x})")
            return False
        return True

    def _on_syscall(self, uc, _user_data) -> None:
        # Under Wine a syscall leaves the Windows side entirely; the sandbox
        # has no kernel behind it, so stop rather than pretend.
        self._stopped_by = f"syscall at rip 0x{uc.reg_read(UC_X86_REG_RIP):x}"
        uc.emu_stop()

    def read(self, address: int, size: int) -> bytes:
        return bytes(self.uc.mem_read(address, size))

    def write(self, address: int, data: bytes) -> None:
        self.uc.mem_write(address, data)

    def call(self, function: int, *args: int, timeout_seconds: float = CALL_TIMEOUT_SECONDS) -> int:
        """Call ``function`` with the Windows x64 convention; return RAX.

        Arguments beyond the fourth go on the stack above the 32-byte shadow
        space, exactly where MSVC-compiled code expects them.
        """
        rsp = (self.stack_top - 0x100) & ~0xF
        stack_args = args[4:]
        frame = 8 + 0x20 + 8 * len(stack_args)
        rsp -= (frame + 0xF) & ~0xF
        rsp -= 8  # entry sees rsp % 16 == 8, as after a real call
        self.write(rsp, self.return_trap.to_bytes(8, "little"))
        for index, value in enumerate(stack_args):
            self.write(rsp + 0x28 + 8 * index, (value & (2**64 - 1)).to_bytes(8, "little"))
        for register, value in zip((UC_X86_REG_RCX, UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9), args):
            self.uc.reg_write(register, value & (2**64 - 1))
        self.uc.reg_write(UC_X86_REG_RSP, rsp)
        self._stopped_by = None
        started = time.perf_counter()
        try:
            self.uc.emu_start(function, self.return_trap, timeout=int(timeout_seconds * 1_000_000))
        except UcError as error:
            rip = self.uc.reg_read(UC_X86_REG_RIP)
            detail = self.stats.faults[-1] if self.stats.faults else f"rip 0x{rip:x}"
            raise SandboxError(f"FM code stopped in the sandbox: {error} ({detail})") from error
        finally:
            self.stats.calls += 1
            self.stats.seconds += time.perf_counter() - started
        if self._stopped_by is not None:
            raise SandboxError(f"FM code needed the operating system: {self._stopped_by}")
        rip = self.uc.reg_read(UC_X86_REG_RIP)
        if rip != self.return_trap:
            raise SandboxError(
                f"FM code did not return within {timeout_seconds:g}s (stopped at rip 0x{rip:x})"
            )
        return self.uc.reg_read(UC_X86_REG_RAX)
