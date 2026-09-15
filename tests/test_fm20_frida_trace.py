import argparse
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.fm20_frida_trace import (
    build_agent_source,
    capture,
    parse_target,
    process_alive,
    summarize_events,
)


class FakeScript:
    def __init__(self):
        self.callback = None
        self.unloaded = False

    def on(self, signal, callback):
        self.callback = callback

    def load(self):
        self.callback({"type": "send", "payload": {
            "kind": "ready", "module": "fm.exe", "modulePath": "/games/fm.exe",
            "moduleBase": "0x140000000", "moduleSize": 1000, "targetCount": 1,
        }}, None)
        self.callback({"type": "send", "payload": {
            "kind": "enter", "sequence": 1, "target": "known",
            "threadId": 7, "win64Arguments": {"rcx": "0x1"},
        }}, None)
        self.callback({"type": "send", "payload": {
            "kind": "leave", "sequence": 1, "target": "known",
            "threadId": 7, "returnValue": "0x0",
        }}, None)

    def unload(self):
        self.unloaded = True


class FakeSession:
    def __init__(self):
        self.script = FakeScript()
        self.detached = False
        self.callback = None

    def on(self, signal, callback):
        self.callback = callback

    def create_script(self, source, name):
        self.source = source
        self.name = name
        return self.script

    def detach(self):
        self.detached = True
        if self.callback:
            self.callback("application-requested", None)


class FakeDevice:
    def __init__(self):
        self.session = FakeSession()

    def attach(self, pid):
        self.pid = pid
        return self.session


class FailingDevice:
    def attach(self, pid):
        raise RuntimeError("unable to perform ptrace pokedata: Input/output error")


class FailingFrida:
    __version__ = "test"

    def get_local_device(self):
        return FailingDevice()


class FakeFrida:
    __version__ = "test"

    def __init__(self):
        self.device = FakeDevice()

    def get_local_device(self):
        return self.device


class FridaTraceTests(unittest.TestCase):
    def test_target_parser_is_bounded(self):
        self.assertEqual(parse_target("known=0x123"), {"label": "known", "rva": 0x123})
        for value in ("bad", "../bad=1", "zero=0", "huge=0x80000000"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                parse_target(value)

    def test_agent_uses_win64_registers_without_reading_pointed_to_memory(self):
        source = build_agent_source(
            "0x140000000", [{"label": "known", "rva": 0x123}], 20, True
        )
        self.assertIn("this.context.rcx", source)
        self.assertIn("this.context.r9", source)
        self.assertIn("Thread.backtrace", source)
        self.assertIn("timestampMs: Date.now()", source)
        self.assertNotIn("Memory.read", source)
        self.assertNotIn("Interceptor.replace", source)

    def test_capture_attaches_reports_events_unloads_and_detaches(self):
        api = FakeFrida()
        result = capture(
            123, "0x140000000", [{"label": "known", "rva": 0x123}],
            duration_seconds=0, max_events=20, capture_backtraces=False,
            frida_api=api, wait=lambda _seconds: None,
        )

        self.assertTrue(result["attached"])
        self.assertTrue(result["agentReady"])
        self.assertEqual(result["entryEventCount"], 1)
        self.assertTrue(result["scriptUnloaded"])
        self.assertTrue(result["detached"])
        self.assertTrue(api.device.session.script.unloaded)
        self.assertTrue(api.device.session.detached)
        self.assertEqual(result["agentErrors"], [])

    def test_capture_preserves_injection_failure_as_evidence(self):
        result = capture(
            123, "0x140000000", [], duration_seconds=0, max_events=20,
            capture_backtraces=False, frida_api=FailingFrida(),
            wait=lambda _seconds: None,
        )

        self.assertFalse(result["attached"])
        self.assertFalse(result["detached"])
        self.assertEqual(result["agentErrors"][0]["kind"], "capture-error")
        self.assertIn("ptrace pokedata", result["agentErrors"][0]["description"])

    def test_capture_uses_explicit_remote_device(self):
        api = FakeFrida()
        remote = FakeDevice()

        result = capture(
            456, "0x140000000", [{"label": "known", "rva": 0x123}],
            duration_seconds=0, max_events=20, capture_backtraces=False,
            frida_api=api, device=remote, wait=lambda _seconds: None,
        )

        self.assertTrue(result["attached"])
        self.assertEqual(remote.pid, 456)
        self.assertFalse(hasattr(api.device, "pid"))

    def test_process_health_requires_live_fm_mapping(self):
        with TemporaryDirectory() as directory:
            proc_root = Path(directory)
            process = proc_root / "123"
            process.mkdir()
            (process / "maps").write_text(
                "140000000-140001000 r--p 00000000 00:00 1 "
                "/games/Football Manager 2020/fm.exe\n",
                encoding="utf-8",
            )
            self.assertTrue(process_alive(123, proc_root))

            (process / "maps").write_text("", encoding="utf-8")
            self.assertFalse(process_alive(123, proc_root))

    def test_event_summary_pairs_calls_and_ranks_active_candidates(self):
        events = [
            {
                "kind": "enter", "sequence": 1, "target": "quiet", "threadId": 8,
                "returnAddress": {"module": "fm.exe", "rva": "0x10"},
                "win64Arguments": {"rcx": "0x1", "rdx": "0x2", "r8": "0x3", "r9": "0x4"},
            },
            {
                "kind": "leave", "sequence": 1, "target": "quiet", "threadId": 8,
                "returnValue": "0x0",
            },
            {
                "kind": "enter", "sequence": 2, "target": "active", "threadId": 9,
                "returnAddress": {"module": "fm.exe", "rva": "0x20"},
                "win64Arguments": {"rcx": "0x1", "rdx": "0x5", "r8": "0x3", "r9": "0x4"},
            },
            {
                "kind": "enter", "sequence": 3, "target": "active", "threadId": 9,
                "returnAddress": {"module": "fm.exe", "rva": "0x20"},
                "win64Arguments": {"rcx": "0x1", "rdx": "0x6", "r8": "0x3", "r9": "0x4"},
            },
        ]

        result = summarize_events(events)

        self.assertEqual(result["candidateRanking"], ["active", "quiet"])
        self.assertEqual(result["targets"]["quiet"]["completedCallCount"], 1)
        self.assertEqual(result["targets"]["active"]["distinctArgumentCounts"]["rdx"], 2)
        self.assertEqual(
            result["targets"]["active"]["callerCounts"],
            {'{"module": "fm.exe", "rva": "0x20"}': 2},
        )


if __name__ == "__main__":
    unittest.main()
