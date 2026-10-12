#!/usr/bin/env python3
"""Run FM20's own code in an emulator over a lazily-copied view of its memory.

Every earlier way of getting FM's *exact* visible-attribute answer ran FM's
visibility builder inside the live game -- by ptrace register injection or a
Frida hook -- and that is the prime suspect for the saves that broke on 17 and
26 September 2026 (see ``docs/scouting-workspace.md``). This module runs the
same machine code somewhere else: a Unicorn x86-64 CPU whose memory starts
empty and is filled on demand, a slice at a time, from ``/proc/<pid>/mem``
opened read-only (see ``MemorySnapshot``).

What that buys:

- **FM's own logic, not a reimplementation.** Whatever FM would consult to
  decide what the manager can see -- scout reports, packages, reputation,
  trials, anything -- the emulated code consults the same way.
- **The game cannot be changed.** Nothing here attaches to, stops, or writes to
  FM. Any write FM's code makes (the builder updates lookup caches in the
  knowledge context, for example) lands in the emulator's private copy of that
  page and is discarded with the sandbox.

What it does not buy: a consistent snapshot. Slices are copied when first
touched while FM keeps running, so a slice copied late can disagree with one
copied early. Callers keep the existing before/after identity checks, and a
sandbox should be short-lived -- one refresh, not a session.

Research status: trial. See ``docs/scouting-workspace.md`` before promoting.
"""

from __future__ import annotations

import bisect
import collections
import ctypes
import mmap
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from unicorn import (
    UC_ARCH_X86,
    UC_HOOK_BLOCK,
    UC_HOOK_CODE,
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
# FM's memory is copied in slices this big, each clipped to the FM mapping that
# holds it, and each slice becomes one emulator region. Unicorn's cost per
# region grows with the number it already holds: on 11 October 2026 a sandbox
# built from 64 KB chunks held about 5,000 of them and spent 13 s mapping them
# and 13 s more freeing them, while reading the same memory from FM took
# 0.04 s. A slice this size keeps a sandbox to a few hundred regions.
SLICE = 0x200000
# The fallback when a slice cannot be copied whole (part of it is unreadable):
# this much if it is all readable, otherwise the single page.
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
# FM records its main thread's Windows ID at start-up and some of its code
# (e.g. fm.exe+0x516b230) builds or uses a cache only when GetCurrentThreadId()
# equals it, returning nothing on any other thread. The byte at the flag RVA
# chooses which of the two saved IDs is current (fm.exe 20.4.4).
MAIN_THREAD_FLAG_RVA = 0x7594438
MAIN_THREAD_ID_RVAS = (0x7593598, 0x7594440)  # (flag clear, flag set)
TEB_SELF, TEB_STACK_BASE, TEB_STACK_LIMIT, TEB_THREAD_ID = 0x30, 0x08, 0x10, 0x48
TEB_COPY_SIZE = 0x2000
# Windows' virtual-memory calls, answered by the sandbox itself (see
# ``_install_memory_services``).
STATUS_SUCCESS = 0
ALLOCATION_GRANULARITY = 0x10000
PAGE_READWRITE = 0x04


class SandboxError(RuntimeError):
    """FM's code needed something the sandbox cannot provide."""


@dataclass
class SandboxStats:
    calls: int = 0
    seconds: float = 0.0
    slices_mapped: int = 0
    chunks_loaded: int = 0
    pages_loaded: int = 0
    faults: list[str] = field(default_factory=list)


_libc = ctypes.CDLL(None, use_errno=True)
_libc.mmap.restype = ctypes.c_void_p
_libc.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long)
_libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
_MAP_FAILED = ctypes.c_void_p(-1).value


def _readable_mappings(pid: int) -> list[tuple[int, int]]:
    """FM's readable address ranges, in address order, from its memory map."""
    ranges = []
    with Path(f"/proc/{pid}/maps").open(encoding="utf-8") as maps:
        for line in maps:
            bounds, permissions = line.split(None, 2)[:2]
            if permissions.startswith("r"):
                low, high = (int(value, 16) for value in bounds.split("-"))
                ranges.append((low, high))
    ranges.sort()
    return ranges


def _containing(ranges: list[tuple[int, int]], address: int) -> tuple[int, int] | None:
    index = bisect.bisect_right(ranges, (address, 2**64)) - 1
    if index >= 0 and address < ranges[index][1]:
        return ranges[index]
    return None


class MemorySnapshot:
    """FM's memory, copied a slice at a time on first touch, for one or more sandboxes.

    Each slice is read from ``/proc/<pid>/mem`` once, into an in-memory file,
    and every sandbox maps its own copy-on-write view of it: FM's code writing
    in one sandbox never reaches another sandbox, the snapshot, or FM. Sandboxes
    run side by side in one pass (``tools.fm20_sandbox_queries._capture_pass``)
    share one snapshot, so FM's memory is copied once per pass rather than once
    per sandbox. A retry that needs FM "at a different real moment" -- the
    reason those passes retry at all -- takes a new snapshot.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self.bytes_copied = 0
        self._lock = threading.Lock()
        self._fd: int | None = None
        self._file: int | None = None
        self._size = 0
        self._slices: list[tuple[int, int, int]] = []  # (low, high, file offset), by low
        self._lows: list[int] = []
        self._readable: list[tuple[int, int]] | None = None

    def slice_at(self, address: int) -> tuple[int, int, int] | None:
        """The slice holding ``address`` as (low, high, file offset), copied now if new.

        None when FM has no readable memory there, or the slice could not be
        read as far as ``address``; the sandbox then copies that page alone.
        """
        with self._lock:
            index = bisect.bisect_right(self._lows, address) - 1
            if index >= 0 and address < self._slices[index][1]:
                return self._slices[index]
            mapping = self._mapping(address)
            if mapping is None:
                return None
            window = address & ~(SLICE - 1)
            low, high = max(mapping[0], window), min(mapping[1], window + SLICE)
            # FM's mappings change as it runs; never overlap a slice already copied.
            if index >= 0:
                low = max(low, self._slices[index][1])
            if index + 1 < len(self._slices):
                high = min(high, self._slices[index + 1][0])
            return self._copy(address, low, high, index + 1)

    def private_view(self, offset: int, size: int) -> int:
        """A new copy-on-write mapping of part of the snapshot; the caller unmaps it."""
        with self._lock:
            pointer = _libc.mmap(
                None, size, mmap.PROT_READ | mmap.PROT_WRITE, mmap.MAP_PRIVATE, self._file, offset
            )
        if pointer in (None, _MAP_FAILED):
            raise OSError(ctypes.get_errno(), "could not map the memory snapshot")
        return pointer

    def _mapping(self, address: int) -> tuple[int, int] | None:
        """FM's readable mapping holding ``address``; the map is re-read if it is not found."""
        if self._readable is not None:
            found = _containing(self._readable, address)
            if found is not None:
                return found
        self._readable = _readable_mappings(self.pid)
        return _containing(self._readable, address)

    def _copy(self, address: int, low: int, high: int, position: int) -> tuple[int, int, int] | None:
        if self._fd is None:
            self._fd = os.open(f"/proc/{self.pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
            self._file = os.memfd_create("fm20-sandbox", os.MFD_CLOEXEC)
        offset = self._size
        os.ftruncate(self._file, offset + high - low)
        with mmap.mmap(
            self._file, high - low, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=offset
        ) as target:
            try:
                copied = os.preadv(self._fd, [target], low)
            except OSError:
                copied = 0
        # A read stops at the first unreadable page; keep only what was read.
        high = low + (copied & ~(PAGE - 1))
        if address >= high:
            os.ftruncate(self._file, offset)
            return None
        os.ftruncate(self._file, offset + high - low)
        self._size = offset + high - low
        self.bytes_copied += high - low
        entry = (low, high, offset)
        self._slices.insert(position, entry)
        self._lows.insert(position, low)
        return entry

    def close(self) -> None:
        """Release the snapshot; views sandboxes still hold stay valid until unmapped."""
        with self._lock:
            for fd in (self._fd, self._file):
                if fd is not None:
                    os.close(fd)
            self._fd = self._file = None
            self._size = 0
            self._slices.clear()
            self._lows.clear()

    def __enter__(self) -> MemorySnapshot:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def _free_region(pid: int, size: int, also_used: tuple[tuple[int, int], ...] = ()) -> int:
    """A user-space address range FM has nothing mapped in, for our own use.

    It must not overlap FM's memory: the sandbox would then answer FM's reads
    of that range with our stack instead of FM's data. ``also_used`` is the
    sandbox's own memory, which FM's map knows nothing about.
    """
    used = list(also_used)
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

    def __init__(
        self,
        pid: int,
        module_base: int,
        *,
        snapshot: MemorySnapshot | None = None,
        as_main_thread: bool = False,
        trace_blocks: int = 0,
    ):
        self.pid = pid
        self.module_base = module_base
        # Diagnostics only: the last few code blocks run, named when a call stops.
        self._trace = collections.deque(maxlen=trace_blocks) if trace_blocks else None
        # Shared with the other sandboxes of one pass when given, else this one's own.
        self._owns_snapshot = snapshot is None
        self.snapshot = MemorySnapshot(pid) if snapshot is None else snapshot
        self._views: list[tuple[int, int]] = []
        self.fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
        self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
        self.stats = SandboxStats()
        self._mapped: set[int] = set()
        self._stopped_by: str | None = None
        self._reservations: list[tuple[int, int]] = []

        self.private = _free_region(pid, PRIVATE_SIZE)
        self.uc.mem_map(self.private, PRIVATE_SIZE, UC_PROT_ALL)
        self._mapped.update(range(self.private, self.private + PRIVATE_SIZE, PAGE))
        self.stack_top = self.private + STACK_SIZE - 0x100
        # A fresh, synthetic thread block by default: ``tools.fm20_sandbox_queries``
        # has verified both visible attributes and Player Search interest match
        # FM's own answers exactly on it (27 September 2026), so it is the safe
        # choice until a query is found that genuinely needs FM's real main
        # thread. Passing ``as_main_thread=True`` instead clones FM's actual
        # main-thread block (thread ID, thread-local storage and so on) so code
        # that checks "am I on FM's UI thread" takes the same path it would
        # live. That clone is not provably safe: the same interest query that
        # works cleanly here crashed the whole Python process (SIGSEGV) under
        # it, deep inside the C runtime's ``_set_FMA3_enable`` after cloning a
        # real thread's snapshot -- not a Unicorn or FM error this module can
        # catch and recover from. Treat ``True`` as unverified for any new use
        # until it is checked the same way.
        self.teb = self.private + STACK_SIZE
        main_teb = self._main_thread_teb() if as_main_thread else None
        self.main_thread_cloned = main_teb is not None
        if main_teb is not None:
            self.uc.mem_write(self.teb, os.pread(self.fd, TEB_COPY_SIZE, main_teb))
        else:
            self._build_thread_locals(self.teb + 0x2000, self.teb + 0x3000)
        self.uc.mem_write(self.teb + TEB_STACK_BASE, self.stack_top.to_bytes(8, "little"))
        self.uc.mem_write(self.teb + TEB_STACK_LIMIT, self.private.to_bytes(8, "little"))
        self.uc.mem_write(self.teb + TEB_SELF, self.teb.to_bytes(8, "little"))
        self.uc.reg_write(UC_X86_REG_GS_BASE, self.teb)
        self.scratch = self.teb + 0x8000
        self.return_trap = self.scratch + 0x1000
        self.uc.mem_write(self.return_trap, b"\xf4")  # hlt; never executed

        self.uc.hook_add(
            UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED,
            self._on_unmapped,
        )
        self.uc.hook_add(UC_HOOK_INSN, self._on_syscall, None, 1, 0, UC_X86_INS_SYSCALL)
        if self._trace is not None:
            self.uc.hook_add(UC_HOOK_BLOCK, lambda _uc, address, _size, _data: self._trace.append(address))
        self._install_memory_services()
        self._disable_fma3_math()

    def _main_thread_teb(self) -> int | None:
        """FM's main-thread TEB, found by its self-pointer and saved thread ID.

        Under Wine every TEB is ordinary process memory. Checking one field on
        each writable page takes well under a second; requiring both the
        self-pointer and FM's own record of its main thread ID makes a chance
        match practically impossible. None if FM's record or the TEB is missing.
        """
        base = self.module_base
        flag = os.pread(self.fd, 1, base + MAIN_THREAD_FLAG_RVA)[0]
        thread_id = int.from_bytes(os.pread(self.fd, 8, base + MAIN_THREAD_ID_RVAS[bool(flag)]), "little")
        if not 0 < thread_id < 2**32:
            return None
        matches = []
        with Path(f"/proc/{self.pid}/maps").open(encoding="utf-8") as maps:
            regions = [line.split() for line in maps]
        for fields in regions:
            if not fields[1].startswith("rw"):
                continue
            low, high = (int(value, 16) for value in fields[0].split("-"))
            for page in range(low, high, PAGE):
                try:
                    head = os.pread(self.fd, TEB_THREAD_ID + 4 - TEB_SELF, page + TEB_SELF)
                except OSError:
                    continue
                if (len(head) == TEB_THREAD_ID + 4 - TEB_SELF
                        and int.from_bytes(head[:8], "little") == page
                        and int.from_bytes(head[TEB_THREAD_ID - TEB_SELF:], "little") == thread_id):
                    matches.append(page)
        return matches[0] if len(matches) == 1 else None

    def _build_thread_locals(self, tls_array: int, tls_block: int) -> None:
        """Fallback: fm.exe's thread-local storage as a brand-new thread gets it.

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

    def _module_exports(self, file_name: str) -> dict[str, int]:
        """Exported function addresses of one DLL loaded in FM, by name."""
        base = None
        with Path(f"/proc/{self.pid}/maps").open(encoding="utf-8") as maps:
            for line in maps:
                if line.rstrip().lower().endswith("/" + file_name):
                    base = int(line.split("-", 1)[0], 16)
                    break
        if base is None:
            return {}
        read = lambda address, size: os.pread(self.fd, size, address)
        u32 = lambda address: int.from_bytes(read(address, 4), "little")
        pe = base + u32(base + 0x3C)
        directory = base + u32(pe + 24 + 112)
        count, functions, names, ordinals = (u32(directory + offset) for offset in (24, 28, 32, 36))
        exports = {}
        for index in range(count):
            name = read(base + u32(base + names + 4 * index), 64).split(b"\0")[0].decode()
            ordinal = int.from_bytes(read(base + ordinals + 2 * index, 2), "little")
            exports[name] = base + u32(base + functions + 4 * ordinal)
        return exports

    def _install_memory_services(self) -> None:
        """Answer Windows' virtual-memory calls from the sandbox's own memory.

        When FM's heap has no room left it asks Windows for more
        (``NtAllocateVirtualMemory``). In the sandbox that request used to
        reach Wine's Linux side, which has no thread state for our synthetic
        thread, and stop the call with a write to address 0x70. Whether it
        happens depends only on how full FM's heap is when it is copied: on 27
        September 2026 the same Player Search build succeeded eight times in a
        row, then failed four times in a row an hour later. Handing out
        zero-filled memory here keeps the whole allocation in the sandbox's
        copy. Freeing and re-protecting are accepted and ignored: the sandbox
        is thrown away after one refresh. Every other request to the
        operating system still stops the call.
        """
        exports = self._module_exports("ntdll.dll")
        for name, handler in (
            ("NtAllocateVirtualMemory", self._nt_allocate_virtual_memory),
            ("NtFreeVirtualMemory", lambda: STATUS_SUCCESS),
            ("NtProtectVirtualMemory", self._nt_protect_virtual_memory),
        ):
            address = exports.get(name)
            if address is not None:
                # Installed once, never removed: adding and deleting Unicorn
                # hooks repeatedly corrupts it (see tools.fm20_sandbox_queries).
                self.uc.hook_add(UC_HOOK_CODE, self._answer_os_call, handler, address, address)
        self.os_memory_requests = 0

    def _answer_os_call(self, uc, _address, _size, handler) -> None:
        """Run ``handler`` in place of the Windows function, then return from it."""
        status = handler()
        rsp = uc.reg_read(UC_X86_REG_RSP)
        return_address = int.from_bytes(uc.mem_read(rsp, 8), "little")
        uc.reg_write(UC_X86_REG_RAX, status)
        uc.reg_write(UC_X86_REG_RSP, rsp + 8)
        uc.reg_write(UC_X86_REG_RIP, return_address)

    def _u64(self, address: int) -> int:
        return int.from_bytes(self.read(address, 8), "little")

    def _nt_allocate_virtual_memory(self) -> int:
        # (process, *base, zero_bits, *size, allocation_type, protect)
        base_pointer = self.uc.reg_read(UC_X86_REG_RDX)
        size_pointer = self.uc.reg_read(UC_X86_REG_R9)
        base, size = self._u64(base_pointer), self._u64(size_pointer)
        if base == 0:
            size = (size + ALLOCATION_GRANULARITY - 1) & ~(ALLOCATION_GRANULARITY - 1)
            base = _free_region(
                self.pid, size,
                ((self.private, self.private + PRIVATE_SIZE), *self._reservations),
            )
            self.uc.mem_map(base, size, UC_PROT_ALL)
            self._mapped.update(range(base, base + size, PAGE))
            self._reservations.append((base, base + size))
        else:
            # Committing inside a reservation: one of ours is mapped already;
            # one of FM's own is unreadable in the live game until committed,
            # so the sandbox gives those pages fresh zeroes, as Windows would.
            end = (base + size + PAGE - 1) & ~(PAGE - 1)
            base &= ~(PAGE - 1)
            size = end - base
            run_start = None
            for page in range(base, end + PAGE, PAGE):
                if page < end and page not in self._mapped:
                    run_start = page if run_start is None else run_start
                elif run_start is not None:
                    self.uc.mem_map(run_start, page - run_start, UC_PROT_ALL)
                    self._mapped.update(range(run_start, page, PAGE))
                    run_start = None
        self.write(base_pointer, base.to_bytes(8, "little"))
        self.write(size_pointer, size.to_bytes(8, "little"))
        self.os_memory_requests += 1
        return STATUS_SUCCESS

    def _nt_protect_virtual_memory(self) -> int:
        # (process, *base, *size, new_protect, *old_protect)
        old_protect_pointer = self._u64(self.uc.reg_read(UC_X86_REG_RSP) + 0x28)
        if old_protect_pointer:
            self.write(old_protect_pointer, PAGE_READWRITE.to_bytes(4, "little"))
        return STATUS_SUCCESS

    def _disable_fma3_math(self) -> None:
        """Route the C runtime's float maths to its SSE2 code, in the sandbox only.

        FM ships Microsoft's ucrtbase.dll, which chooses FMA3 (VEX-encoded)
        versions of ``sinf`` and friends at start-up when the CPU has them.
        Unicorn has no AVX/FMA, so the sandbox calls the runtime's own
        documented switch, ``_set_FMA3_enable(0)``, which writes only the
        sandbox's copy. Microsoft documents that the two paths can differ in
        the last bit of a result, so anything built on runtime maths must be
        validated against FM's own answer, not assumed identical.
        """
        setter = self._module_exports("ucrtbase.dll").get("_set_FMA3_enable")
        self.fma3_disabled = setter is not None
        if setter is not None:
            self.call(setter, 0)

    def _describe(self, address: int) -> str:
        with Path(f"/proc/{self.pid}/maps").open(encoding="utf-8") as maps:
            for line in maps:
                bounds, *rest = line.split(None, 5)
                low, high = (int(value, 16) for value in bounds.split("-"))
                if low <= address < high:
                    name = rest[4].strip().rsplit("/", 1)[-1] if len(rest) > 4 else "anonymous"
                    return f"{name}+0x{address - low:x}" if name != "fm.exe" else f"fm.exe+0x{address - self.module_base:x}"
        return f"0x{address:x}"

    def _trace_report(self) -> str:
        if not self._trace:
            return ""
        return "; last blocks: " + " > ".join(self._describe(address) for address in list(self._trace)[-8:])

    def close(self) -> None:
        """Free the emulator and this sandbox's view of FM's memory now.

        Unicorn's hook wrappers hold the emulator they belong to, so one is
        never freed by reference counting. Left alone, each waited for Python's
        full garbage collection, which then freed them one at a time while
        every other thread waited: 83 s of one 136 s scouting refresh on 11
        October 2026. The sandbox must not be used after this.
        """
        uc, self.uc = self.uc, None
        if uc is None:
            return
        os.close(self.fd)
        # The binding's own finalizer: it closes the engine once and marks
        # itself done, so collecting ``uc`` later does nothing.
        release = getattr(uc, "_Uc__finalizer", None)
        if release is not None:
            release()
            # Only once the engine is gone; until then it may still use them.
            for pointer, size in self._views:
                _libc.munmap(pointer, size)
        self._views.clear()
        if self._owns_snapshot:
            self.snapshot.close()

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

    def _map_slice(self, page: int) -> bool:
        """Map the snapshot's slice holding ``page``, as this sandbox's private copy."""
        found = self.snapshot.slice_at(page)
        if found is None:
            return False
        low, high, offset = found
        run_start = None
        # Only the parts not mapped here already, e.g. by an allocation that
        # FM's own map did not show when the slice was copied.
        for address in range(low, high + PAGE, PAGE):
            if address < high and address not in self._mapped:
                run_start = address if run_start is None else run_start
            elif run_start is not None:
                size = address - run_start
                pointer = self.snapshot.private_view(offset + run_start - low, size)
                try:
                    self.uc.mem_map_ptr(run_start, size, UC_PROT_ALL, pointer)
                except UcError:
                    _libc.munmap(pointer, size)
                    return False
                self._views.append((pointer, size))
                self._mapped.update(range(run_start, address, PAGE))
                run_start = None
        return page in self._mapped

    def _on_unmapped(self, uc, access, address, size, _value, _user_data) -> bool:
        first = address & ~(PAGE - 1)
        last = (address + max(size, 1) - 1) & ~(PAGE - 1)
        for page in range(first, last + PAGE, PAGE):
            if page in self._mapped:
                continue
            if self._map_slice(page):
                self.stats.slices_mapped += 1
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

    def _ensure(self, address: int, size: int) -> None:
        """Copy in FM's pages for a direct read or write, as a fault would."""
        first = address & ~(PAGE - 1)
        for page in range(first, address + max(size, 1), PAGE):
            if page not in self._mapped and not self._on_unmapped(self.uc, 0, page, 1, 0, None):
                raise SandboxError(f"FM has no readable memory at 0x{page:x}")

    def read(self, address: int, size: int) -> bytes:
        self._ensure(address, size)
        return bytes(self.uc.mem_read(address, size))

    def write(self, address: int, data: bytes) -> None:
        """Write into the sandbox's copy. FM's own memory is never written."""
        self._ensure(address, len(data))
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
            raise SandboxError(
                f"FM code stopped in the sandbox: {error} ({detail})" + self._trace_report()
            ) from error
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
