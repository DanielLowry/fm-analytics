import unittest

from fm_analytics.domain import Visibility
from tools.fm20_frida_attribute_sweep import (
    AttributeSweepError,
    MAX_PEOPLE,
    build_agent_source,
    decode_capture,
    extract,
)


PEOPLE = [
    {"id": "1", "interface": "0x1000"},
    {"id": "2", "interface": "0x2000"},
]
ATTRIBUTES = ["aerialReach", "pace"]


class FakeScript:
    def __init__(self, messages):
        self.messages = messages
        self.callback = None
        self.unloaded = False

    def on(self, _signal, callback):
        self.callback = callback

    def load(self):
        for payload in self.messages:
            self.callback({"type": "send", "payload": payload}, None)

    def unload(self):
        self.unloaded = True


class FakeSession:
    def __init__(self, messages):
        self.script = FakeScript(messages)
        self.detached = False
        self.callback = None

    def on(self, _signal, callback):
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
    def __init__(self, messages):
        self.session = FakeSession(messages)

    def attach(self, pid):
        self.pid = pid
        return self.session


class FailingDevice:
    def attach(self, pid):
        raise RuntimeError("unable to attach")


class FridaAttributeSweepTests(unittest.TestCase):
    def test_agent_calls_builder_with_six_win64_arguments(self):
        source = build_agent_source("0x140000000", 0x12345, PEOPLE, ATTRIBUTES)

        self.assertIn(
            "['pointer', 'pointer', 'pointer', 'uint32', 'pointer', 'pointer']", source
        )
        self.assertIn('"context": "0x12345"', source)
        self.assertIn('"address": "0x1000"', source)
        self.assertIn("readByteArray(2)", source)
        self.assertNotIn("__CONFIG__", source)
        self.assertNotIn("Interceptor.replace", source)

    def test_agent_never_reads_more_than_the_two_visible_bytes(self):
        source = build_agent_source("0x140000000", 1, PEOPLE, ATTRIBUTES)
        for line in source.splitlines():
            if "readByteArray" in line or "readU" in line and "callOne" in source:
                self.assertNotIn("readByteArray(3)", line)
                self.assertNotIn("readU16", line)
                self.assertNotIn("readU32", line)

    def test_agent_person_count_and_context_are_bounded(self):
        with self.assertRaises(AttributeSweepError):
            build_agent_source("0x140000000", 1, [], ATTRIBUTES)
        with self.assertRaises(AttributeSweepError):
            build_agent_source("0x140000000", 0, PEOPLE, ATTRIBUTES)
        too_many = [{"id": str(i), "interface": "0x1000"} for i in range(MAX_PEOPLE + 1)]
        with self.assertRaises(AttributeSweepError):
            build_agent_source("0x140000000", 1, too_many, ATTRIBUTES)

    def test_agent_rejects_unsupported_attributes(self):
        with self.assertRaises(AttributeSweepError):
            build_agent_source("0x140000000", 1, PEOPLE, ["notAnAttribute"])

    def test_extract_collects_players_and_releases_session(self):
        device = FakeDevice([
            {"kind": "ready", "people": 2},
            {"kind": "thread", "thread": 372, "sample": {"372": 5000, "356": 100}},
            {"kind": "players", "players": [
                {"id": "1", "error": None, "attributes": {"aerialReach": {"lower": 15, "upper": 15}}},
            ]},
            {"kind": "finished"},
        ])

        result = extract(device, 352, "source", timeout_seconds=1)

        self.assertEqual(device.pid, 352)
        self.assertTrue(result["attached"])
        self.assertTrue(result["agentReady"])
        self.assertEqual(result["thread"]["id"], 372)
        self.assertEqual(result["players"][0]["id"], "1")
        self.assertEqual(result["agentErrors"], [])
        self.assertTrue(result["scriptUnloaded"])
        self.assertTrue(result["detached"])

    def test_extract_reports_timeout_and_attach_failure_as_evidence(self):
        timed_out = extract(FakeDevice([{"kind": "ready"}]), 352, "source", timeout_seconds=0.01)
        self.assertEqual(timed_out["agentErrors"][0]["kind"], "timeout")
        self.assertTrue(timed_out["detached"])

        failed = extract(FailingDevice(), 352, "source", timeout_seconds=0.01)
        self.assertFalse(failed["attached"])
        self.assertFalse(failed["detached"])
        self.assertEqual(failed["agentErrors"][0]["kind"], "capture-error")

    def test_decode_capture_produces_domain_shaped_observations(self):
        capture = {"players": [
            {"id": "1", "error": None, "attributes": {
                "aerialReach": {"lower": 15, "upper": 15},
                "pace": {"lower": 8, "upper": 14},
            }},
        ]}

        summary = decode_capture(PEOPLE[:1], ATTRIBUTES, capture)

        self.assertEqual(summary["resolvedCount"], 1)
        row = summary["players"][0]["attributes"]
        self.assertEqual(row["aerialReach"], {"visibility": Visibility.KNOWN.value, "value": 15})
        self.assertEqual(
            row["pace"], {"visibility": Visibility.RANGE.value, "minimum": 8, "maximum": 14}
        )

    def test_decode_capture_never_forwards_raw_bytes(self):
        capture = {"players": [
            {"id": "1", "error": None, "attributes": {
                "aerialReach": {"lower": 0xFF, "upper": 0xFF},
                "pace": {"lower": 5, "upper": 5},
            }},
        ]}

        summary = decode_capture(PEOPLE[:1], ATTRIBUTES, capture)

        row = summary["players"][0]["attributes"]
        self.assertEqual(row["aerialReach"], {"visibility": Visibility.UNKNOWN.value})
        self.assertNotIn("lower", row["aerialReach"])
        self.assertNotIn("upper", row["pace"])

    def test_decode_capture_fails_closed_on_missing_or_errored_player(self):
        capture = {"players": [{"id": "1", "error": "Error: fault", "attributes": None}]}

        summary = decode_capture(PEOPLE, ATTRIBUTES, capture)

        self.assertEqual(summary["resolvedCount"], 0)
        self.assertEqual(summary["players"][0]["error"], "Error: fault")
        self.assertIsNone(summary["players"][0]["attributes"])
        self.assertIsNone(summary["players"][1]["attributes"])  # player 2 never reported at all


if __name__ == "__main__":
    unittest.main()
