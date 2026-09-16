import unittest

from tools.fm20_frida_discoverability import (
    DiscoverabilityError,
    builder_agent_source,
    decode_filter_capture,
    extract,
    filter_agent_source,
    filter_order,
)


RECORDS = {1: 0x1000, 2: 0x2000, 3: 0x3000, 10: 0xA000, 11: 0xB000, 12: 0xC000}


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
        self.callback = None
        self.detached = False

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


class FridaDiscoverabilityTests(unittest.TestCase):
    def test_builder_uses_known_win64_three_argument_contract(self):
        source = builder_agent_source("0x140000000", (0x1000, 0x2000, 0x3000))

        self.assertIn("'uint64', ['pointer', 'pointer', 'pointer']", source)
        self.assertIn('"builderRva": 86472896', source)
        self.assertIn('"source": "0x1000"', source)
        self.assertIn("QueryPerformanceCounter", source)
        self.assertNotIn("Interceptor.replace", source)
        self.assertNotIn("__CONFIG__", source)

    def test_filter_orders_expected_owned_exclusions_before_batch(self):
        rows, sample_count = filter_order(RECORDS, {1, 2, 3})

        self.assertEqual(sample_count, 6)
        self.assertEqual([row["id"] for row in rows[:6]], ["1", "2", "3", "10", "11", "12"])
        self.assertEqual([row["expected"] for row in rows[:6]], [False, False, False, True, True, True])

    def test_filter_agent_constructs_native_context_and_chunks(self):
        rows, sample_count = filter_order(RECORDS, {1, 2, 3})
        source = filter_agent_source(
            "0x140000000", filter_object=0x4000, manager_interface=0x5000,
            team=0x6000, knowledge_context=0x7000, rows=rows,
            sample_count=sample_count, chunk_size=2, thread_id=356,
        )

        self.assertIn("'uint8', ['pointer', 'pointer', 'pointer']", source)
        self.assertIn("filterContext.add(0x20).writePointer", source)
        self.assertIn("record.add(8).writePointer", source)
        self.assertIn("stackPointer.sub(0x4000)", source)
        self.assertIn("config.chunkSize", source)
        self.assertIn("native full-filter sample disagrees", source)
        self.assertIn("sampleMismatches", source)
        self.assertIn('"threadId": 356', source)
        self.assertNotIn("readByteArray", source)

    def test_filter_agent_rejects_unbounded_or_invalid_rows(self):
        rows, sample_count = filter_order(RECORDS, {1, 2, 3})
        with self.assertRaises(DiscoverabilityError):
            filter_agent_source(
                "0x140000000", filter_object=1, manager_interface=2, team=3,
                knowledge_context=4, rows=rows, sample_count=sample_count, chunk_size=101, thread_id=1,
            )
        with self.assertRaises(DiscoverabilityError):
            filter_agent_source(
                "0x140000000", filter_object=1, manager_interface=2, team=3,
                knowledge_context=4, rows=[{"id": "x", "address": "0x1", "expected": True}],
                sample_count=1, chunk_size=1, thread_id=1,
            )

    def test_decode_requires_complete_sample_checked_subset(self):
        rows, _ = filter_order(RECORDS, {1, 2, 3})
        decoded = decode_filter_capture(rows, {
            "evaluatedCount": len(rows), "sampleChecked": True,
            "includedPlayerIds": ["10", "12"],
        })

        self.assertFalse(decoded[1])
        self.assertTrue(decoded[10])
        self.assertFalse(decoded[11])
        with self.assertRaises(DiscoverabilityError):
            decode_filter_capture(rows, {"evaluatedCount": 1, "sampleChecked": True, "includedPlayerIds": []})
        with self.assertRaises(DiscoverabilityError):
            decode_filter_capture(rows, {"evaluatedCount": len(rows), "sampleChecked": True, "includedPlayerIds": ["999"]})

    def test_extract_records_builder_and_filter_evidence_then_detaches(self):
        device = FakeDevice([
            {"kind": "ready"},
            {"kind": "thread", "thread": 42, "sample": {"42": 5000}},
            {"kind": "builder-result", "returnValue": "1"},
            {"kind": "progress", "done": 6, "total": 6},
            {"kind": "filter-result", "includedPlayerIds": ["10"], "evaluatedCount": 6, "sampleChecked": True},
            {"kind": "finished"},
        ])

        result = extract(device, 99, "source", script_name="test", timeout_seconds=1)

        self.assertTrue(result["attached"])
        self.assertTrue(result["agentReady"])
        self.assertEqual(result["builderReturnValue"], "1")
        self.assertEqual(result["includedPlayerIds"], ["10"])
        self.assertEqual(result["progress"], [{"done": 6, "total": 6}])
        self.assertEqual(result["agentErrors"], [])
        self.assertTrue(result["scriptUnloaded"])
        self.assertTrue(result["detached"])


if __name__ == "__main__":
    unittest.main()
