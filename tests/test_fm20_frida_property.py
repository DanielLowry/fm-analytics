import unittest

from tools.fm20_frida_property import (
    FOOT_KEY,
    FOOTEDNESS_LABELS,
    LEFT_FOOT_KEY,
    MAX_PEOPLE,
    RIGHT_FOOT_KEY,
    PropertyReadError,
    build_agent_source,
    extract,
    four_cc,
    summarize_footedness,
)


PEOPLE = [
    {"id": "1", "name": "Left Back", "address": "0x1000"},
    {"id": "2", "name": "Right Back", "address": "0x2000"},
    {"id": "3", "name": "Unknown Trialist", "address": "0x3000"},
]
FM_LABELS = {str(index): text for index, text in FOOTEDNESS_LABELS.items()}


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


class FridaPropertyTests(unittest.TestCase):
    def test_property_keys_match_fm_four_character_codes(self):
        self.assertEqual(four_cc(FOOT_KEY), "tofP")
        self.assertEqual(four_cc(LEFT_FOOT_KEY), "GflP")
        self.assertEqual(four_cc(RIGHT_FOOT_KEY), "GfrP")

    def test_agent_reports_categories_not_ratings(self):
        source = build_agent_source("0x140000000", PEOPLE)

        self.assertIn('"address": "0x3000"', source)
        self.assertIn("footCategory(ratings[config.leftKey], ratings[config.rightKey])", source)
        self.assertIn("send({kind: 'players', players})", source)
        self.assertNotIn("__CONFIG__", source)
        self.assertNotIn("Interceptor.replace", source)
        for payload_line in (line for line in source.splitlines() if "send(" in line):
            self.assertNotIn("ratings", payload_line)

    def test_agent_person_count_is_bounded(self):
        with self.assertRaises(PropertyReadError):
            build_agent_source("0x140000000", [])
        too_many = [{"id": str(index), "name": "", "address": "0x1000"} for index in range(MAX_PEOPLE + 1)]
        with self.assertRaises(PropertyReadError):
            build_agent_source("0x140000000", too_many)

    def test_extract_collects_results_and_releases_session(self):
        device = FakeDevice([
            {"kind": "ready", "people": 3},
            {"kind": "thread", "thread": 372, "sample": {"372": 6000, "356": 200}},
            {"kind": "players", "players": [{"id": "1", "found": True, "category": 0}]},
            {"kind": "labels", "labels": FM_LABELS},
            {"kind": "finished"},
        ])

        result = extract(device, 352, "source", timeout_seconds=1)

        self.assertEqual(device.pid, 352)
        self.assertTrue(result["attached"])
        self.assertTrue(result["agentReady"])
        self.assertEqual(result["thread"]["id"], 372)
        self.assertEqual(result["players"][0]["category"], 0)
        self.assertEqual(result["labels"], FM_LABELS)
        self.assertEqual(result["agentErrors"], [])
        self.assertTrue(result["scriptUnloaded"])
        self.assertTrue(device.session.script.unloaded)
        self.assertTrue(result["detached"])

    def test_extract_reports_timeout_and_attach_failure_as_evidence(self):
        timed_out = extract(FakeDevice([{"kind": "ready"}]), 352, "source", timeout_seconds=0.01)
        self.assertEqual(timed_out["agentErrors"][0]["kind"], "timeout")
        self.assertTrue(timed_out["detached"])

        failed = extract(FailingDevice(), 352, "source", timeout_seconds=0.01)
        self.assertFalse(failed["attached"])
        self.assertFalse(failed["detached"])
        self.assertEqual(failed["agentErrors"][0]["kind"], "capture-error")

    def test_summary_uses_fm_labels_and_leaves_unknown_unlabelled(self):
        capture = {
            "players": [
                {"id": "1", "found": True, "category": 0},
                {"id": "2", "found": True, "category": 3},
                {"id": "3", "found": True, "category": "unknown"},
            ],
            "labels": FM_LABELS,
        }

        summary = summarize_footedness(PEOPLE, capture)

        self.assertTrue(summary["labelsVerified"])
        self.assertEqual(summary["requestedCount"], 3)
        self.assertEqual(summary["resolvedCount"], 2)
        self.assertEqual(
            [(row["id"], row["footedness"], row["status"]) for row in summary["players"]],
            [("1", "Left Only", "visible"), ("2", "Right", "visible"), ("3", None, "unknown")],
        )

    def test_summary_fails_closed_when_fm_labels_differ(self):
        labels = dict(FM_LABELS, **{"4": "Uses Both Feet"})
        capture = {"players": [{"id": "1", "found": True, "category": 4}], "labels": labels}

        summary = summarize_footedness(PEOPLE[:1], capture)

        self.assertFalse(summary["labelsVerified"])
        self.assertEqual(summary["resolvedCount"], 0)
        self.assertEqual(summary["players"][0]["status"], "unverified-category")
        self.assertIsNone(summary["players"][0]["footedness"])

    def test_summary_records_per_player_errors(self):
        capture = {"players": [{"id": "1", "error": "Error: access violation"}], "labels": FM_LABELS}

        summary = summarize_footedness(PEOPLE[:2], capture)

        self.assertEqual(summary["players"][0]["status"], "error")
        self.assertIn("access violation", summary["players"][0]["error"])
        self.assertEqual(summary["players"][1]["status"], "not-found")


if __name__ == "__main__":
    unittest.main()
