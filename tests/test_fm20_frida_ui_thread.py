import json
import shutil
import subprocess
import unittest

from tools.fm20_frida_ui_thread import (
    UI_THREAD_CHOICE_SOURCE,
    probe_agent_source,
    thread_selection_config,
)


NODE = shutil.which("node")


def choose(qpc_sample: dict, pump_sample: dict):
    """Run the agent's own thread decision, unchanged, outside Frida."""
    script = (
        UI_THREAD_CHOICE_SOURCE
        + f"\nprocess.stdout.write(JSON.stringify(chooseUiThread("
        f"{json.dumps(qpc_sample)}, {json.dumps(pump_sample)})));\n"
    )
    result = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(result.stdout)


class FridaUiThreadTests(unittest.TestCase):
    def test_passive_probe_prefers_a_unique_message_pump_thread(self) -> None:
        source = probe_agent_source("0x140000000")

        self.assertIn("unique-message-pump-thread", source)
        self.assertIn("no unambiguous FM UI thread was found", source)
        self.assertIn("pumpSample", source)
        self.assertNotIn("__CONFIG__", source)
        self.assertNotIn("__UI_THREAD_SELECTOR__", source)
        self.assertNotIn("new NativeFunction", source)

    def test_no_selection_can_run_a_call_inside_a_timing_call(self) -> None:
        """The fallback implicated in the save corruption must stay gone."""
        source = probe_agent_source("0x140000000")

        self.assertNotIn("dominant-qpc-fallback", source)
        self.assertNotIn("address: timing", source)
        self.assertIn("restingPoint: true", source)

    def test_shared_config_samples_every_supported_message_pump(self) -> None:
        config = thread_selection_config()

        self.assertEqual(config["threadSampleExport"], "QueryPerformanceCounter")
        self.assertEqual(
            config["restingPointExports"],
            ["GetMessageW", "GetMessageA", "PeekMessageW", "PeekMessageA"],
        )


@unittest.skipIf(NODE is None, "node is needed to run the agent's thread decision")
class ChooseUiThreadTests(unittest.TestCase):
    def test_one_pump_thread_is_chosen_at_its_busiest_pump(self) -> None:
        self.assertEqual(
            choose({"7": 10}, {"7": {"PeekMessageW": 40, "GetMessageW": 2}}),
            {"thread": 7, "pump": "PeekMessageW", "selection": "unique-message-pump-thread"},
        )

    def test_several_pump_threads_need_a_dominant_timing_caller_among_them(self) -> None:
        pumps = {"7": {"PeekMessageW": 40}, "9": {"PeekMessageW": 3}}

        self.assertEqual(
            choose({"7": 600, "9": 20}, pumps),
            {"thread": 7, "pump": "PeekMessageW", "selection": "dominant-qpc-message-pump-thread"},
        )
        self.assertIsNone(choose({"7": 600, "9": 300}, pumps))
        self.assertIsNone(choose({"11": 600, "9": 20}, pumps))

    def test_no_pump_call_refuses_even_with_a_dominant_timing_caller(self) -> None:
        self.assertIsNone(choose({"7": 6000, "9": 20}, {}))
        self.assertIsNone(choose({}, {}))


if __name__ == "__main__":
    unittest.main()
