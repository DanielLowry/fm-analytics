"""The sandbox's own answers to Windows' virtual-memory calls.

FM's heap asks Windows for more memory when it runs out of room; in the
sandbox that request used to reach Wine's Linux side and stop the call (see
``FmSandbox._install_memory_services``). Whether it happens depends on how full
FM's heap is at the moment it is copied, so a live refresh cannot be relied on
to exercise it. These tests run the sandbox over this test process instead of
FM: nothing under test reads FM's memory.
"""

import os
import struct
import unittest
from pathlib import Path
from unittest import mock

from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_R9, UC_X86_REG_RDX

from tools import fm20_sandbox as sandbox


def _mapped_by_this_process(address: int) -> bool:
    with Path("/proc/self/maps").open(encoding="utf-8") as maps:
        for line in maps:
            low, high = (int(value, 16) for value in line.split()[0].split("-"))
            if low <= address < high:
                return True
    return False


class MemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # Thread-local setup reads fm.exe's own header, which this process has none of.
        with mock.patch.object(sandbox.FmSandbox, "_build_thread_locals"):
            self.box = sandbox.FmSandbox(os.getpid(), 0x140000000)

    def tearDown(self) -> None:
        self.box.close()

    def _allocate(self, base: int, size: int) -> tuple[int, int, int]:
        slot = self.box.scratch + 0x400
        self.box.write(slot, struct.pack("<QQ", base, size))
        self.box.uc.reg_write(UC_X86_REG_RDX, slot)
        self.box.uc.reg_write(UC_X86_REG_R9, slot + 8)
        status = self.box._nt_allocate_virtual_memory()
        return (status, *struct.unpack("<QQ", self.box.read(slot, 16)))

    def test_a_fresh_request_gets_zeroed_writable_memory_outside_the_game(self) -> None:
        status, base, size = self._allocate(0, 0x12345)

        self.assertEqual(status, sandbox.STATUS_SUCCESS)
        self.assertEqual(size, 0x20000)  # rounded up to Windows' 64 KB granularity
        self.assertEqual(base % sandbox.ALLOCATION_GRANULARITY, 0)
        self.assertFalse(_mapped_by_this_process(base))
        self.assertEqual(self.box.read(base, 16), bytes(16))
        self.box.write(base + size - 4, b"test")
        self.assertEqual(self.box.read(base + size - 4, 4), b"test")

    def test_two_requests_never_share_memory(self) -> None:
        _status, first, first_size = self._allocate(0, 0x10000)
        _status, second, _size = self._allocate(0, 0x10000)

        self.assertFalse(first <= second < first + first_size)

    def test_committing_inside_an_unreadable_reservation_gives_fresh_pages(self) -> None:
        # A range the "game" has reserved but not yet committed cannot be read
        # live; committing it must give zeroes, as Windows would.
        free = sandbox._free_region(
            os.getpid(), 0x10000, ((self.box.private, self.box.private + sandbox.PRIVATE_SIZE),)
        )
        status, base, size = self._allocate(free + 0x1234, 0x2000)

        self.assertEqual(status, sandbox.STATUS_SUCCESS)
        self.assertEqual((base, size), (free + 0x1000, 0x3000))  # whole pages
        self.assertEqual(self.box.read(base, size), bytes(size))

    def test_the_answer_replaces_the_windows_function_and_returns_to_its_caller(self) -> None:
        # A stand-in "Windows function" that would return 5: mov eax, 5; ret
        stub = self.box.scratch + 0x2000
        self.box.write(stub, bytes.fromhex("b805000000c3"))
        self.box.uc.hook_add(UC_HOOK_CODE, self.box._answer_os_call, lambda: 0, stub, stub)

        self.assertEqual(self.box.call(stub), 0)


if __name__ == "__main__":
    unittest.main()
