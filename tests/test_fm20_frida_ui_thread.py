import unittest

from tools.fm20_frida_ui_thread import probe_agent_source, thread_selection_config


class FridaUiThreadTests(unittest.TestCase):
    def test_passive_probe_prefers_a_unique_message_pump_thread(self) -> None:
        source = probe_agent_source("0x140000000")

        self.assertIn("unique-message-pump-thread", source)
        self.assertIn("dominant-qpc-fallback", source)
        self.assertIn("no unambiguous FM UI thread was found", source)
        self.assertIn("pumpSample", source)
        self.assertNotIn("__CONFIG__", source)
        self.assertNotIn("__UI_THREAD_SELECTOR__", source)
        self.assertNotIn("new NativeFunction", source)

    def test_shared_config_samples_every_supported_message_pump(self) -> None:
        config = thread_selection_config()

        self.assertEqual(config["threadSampleExport"], "QueryPerformanceCounter")
        self.assertEqual(
            config["restingPointExports"],
            ["GetMessageW", "GetMessageA", "PeekMessageW", "PeekMessageA"],
        )


if __name__ == "__main__":
    unittest.main()
