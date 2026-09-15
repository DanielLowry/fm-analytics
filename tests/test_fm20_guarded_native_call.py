import ctypes
import unittest
from unittest.mock import patch

from tools.fm20_cold_visibility_ptrace import (
    PTRACE_ATTACH,
    PTRACE_CONT,
    PTRACE_DETACH,
    PTRACE_GETREGS,
    PTRACE_SETREGS,
    UserRegs,
)
from tools.fm20_guarded_native_call import (
    GuardedCallResult,
    guarded_native_call,
    verify_process_alive,
)
from tools.fm20_linux_probe import ProbeError

PID = 4242
TRAP_ADDRESS = 0x1400ABCD0
SAVED_RSP = 0x7FFFDEAD0000


class FakePtrace:
    """Simulates PTRACE_GETREGS/SETREGS by writing/reading real ctypes memory,
    the way the kernel would via the `data` pointer -- everything else is a
    recorded no-op, since the real behaviour of ATTACH/CONT/DETACH is not
    something a unit test can observe directly.
    """

    def __init__(self, getregs_queue):
        self.calls: list[tuple[int, int, int]] = []
        self._getregs_queue = list(getregs_queue)
        self.setregs_snapshots: list[UserRegs] = []

    def __call__(self, request: int, tid: int, data: int = 0) -> None:
        self.calls.append((request, tid, data))
        if request == PTRACE_GETREGS:
            regs = UserRegs.from_address(data)
            ctypes.memset(ctypes.addressof(regs), 0, ctypes.sizeof(UserRegs))
            for field, value in self._getregs_queue.pop(0).items():
                setattr(regs, field, value)
        elif request == PTRACE_SETREGS:
            self.setregs_snapshots.append(UserRegs.from_buffer_copy(
                (ctypes.c_char * ctypes.sizeof(UserRegs)).from_address(data)
            ))


def _configure(fd: int, call_regs: UserRegs, call_rsp: int) -> None:
    call_regs.rip = 0x1400001000
    call_regs.rcx = 0x1111
    call_regs.rdx = 0x2222


class GuardedNativeCallTests(unittest.TestCase):
    def _patch_common(self, fake_ptrace, *, wait_stopped_side_effect, trap_bytes=b"\xcc" * 4):
        return (
            patch("tools.fm20_guarded_native_call.ptrace", fake_ptrace),
            patch("tools.fm20_guarded_native_call.wait_stopped", side_effect=wait_stopped_side_effect),
            patch("tools.fm20_guarded_native_call.read_exact", return_value=trap_bytes),
            patch("os.open", return_value=99),
            patch("os.pwrite", return_value=8),
            patch("os.close"),
        )

    def test_successful_call_restores_registers_and_detaches(self):
        fake_ptrace = FakePtrace(getregs_queue=[
            {"rsp": SAVED_RSP, "rip": 0x1400009999},
            {"rsp": SAVED_RSP, "rip": TRAP_ADDRESS + 1, "rax": 42},
        ])
        patches = self._patch_common(
            fake_ptrace, wait_stopped_side_effect=[5, __import__("signal").SIGTRAP],
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = guarded_native_call(PID, TRAP_ADDRESS, _configure)

        self.assertEqual(
            result,
            GuardedCallResult(succeeded=True, return_value=42, fault_signal=None, fault_rip=None),
        )
        self.assertIn((PTRACE_ATTACH, PID, 0), fake_ptrace.calls)
        self.assertIn((PTRACE_DETACH, PID, 0), fake_ptrace.calls)
        self.assertTrue(fake_ptrace.setregs_snapshots)
        # the very last SETREGS before detach must restore the pre-call rip
        self.assertEqual(fake_ptrace.setregs_snapshots[-1].rip, 0x1400009999)

    def test_fault_inside_call_is_reported_not_raised(self):
        import signal as signal_module
        fake_ptrace = FakePtrace(getregs_queue=[
            {"rsp": SAVED_RSP, "rip": 0x1400009999},
            {"rsp": SAVED_RSP, "rip": 0x14001FB286B},
        ])
        patches = self._patch_common(
            fake_ptrace, wait_stopped_side_effect=[5, signal_module.SIGSEGV],
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = guarded_native_call(PID, TRAP_ADDRESS, _configure)

        self.assertFalse(result.succeeded)
        self.assertIsNone(result.return_value)
        self.assertEqual(result.fault_signal, signal_module.SIGSEGV)
        self.assertEqual(result.fault_rip, 0x14001FB286B)
        # still restored and detached even though the call faulted
        self.assertIn((PTRACE_DETACH, PID, 0), fake_ptrace.calls)
        self.assertEqual(fake_ptrace.setregs_snapshots[-1].rip, 0x1400009999)

    def test_timeout_force_abandons_and_raises(self):
        fake_ptrace = FakePtrace(getregs_queue=[
            {"rsp": SAVED_RSP, "rip": 0x1400009999},
        ])
        patches = self._patch_common(
            fake_ptrace, wait_stopped_side_effect=[5, TimeoutError("no trap"), TimeoutError("still stuck")],
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
                patch("os.kill") as fake_kill:
            with self.assertRaises(ProbeError):
                guarded_native_call(PID, TRAP_ADDRESS, _configure)
        # SIGSTOP attempted as part of the force-abandon recovery
        self.assertTrue(any(call.args[1] == __import__("signal").SIGSTOP for call in fake_kill.call_args_list))

    def test_trap_bytes_mismatch_raises_before_any_resume(self):
        fake_ptrace = FakePtrace(getregs_queue=[
            {"rsp": SAVED_RSP, "rip": 0x1400009999},
        ])
        patches = self._patch_common(
            fake_ptrace, wait_stopped_side_effect=[5], trap_bytes=b"\x90\x90\x90\x90",
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with self.assertRaises(ProbeError):
                guarded_native_call(PID, TRAP_ADDRESS, _configure)
        self.assertNotIn(PTRACE_CONT, [call[0] for call in fake_ptrace.calls])
        self.assertIn((PTRACE_DETACH, PID, 0), fake_ptrace.calls)


class VerifyProcessAliveTests(unittest.TestCase):
    def test_true_when_process_exists(self):
        with patch("os.kill", return_value=None):
            self.assertTrue(verify_process_alive(PID))

    def test_false_when_process_is_gone(self):
        with patch("os.kill", side_effect=ProcessLookupError()):
            self.assertFalse(verify_process_alive(PID))

    def test_true_when_permission_denied_but_process_exists(self):
        with patch("os.kill", side_effect=PermissionError()):
            self.assertTrue(verify_process_alive(PID))


if __name__ == "__main__":
    unittest.main()
