import unittest

from tools.fm20_linux_probe import ProbeError
from tools.fm20_visibility_trace import display_attribute_id, raw_attribute_address


class VisibilityTraceTests(unittest.TestCase):
    def test_resolves_known_attribute_address_without_reading_value(self) -> None:
        self.assertEqual(raw_attribute_address(0x1000, "passing"), 0x117A)
        self.assertEqual(raw_attribute_address(0x1000, "acceleration"), 0x1195)

    def test_rejects_unknown_attribute(self) -> None:
        with self.assertRaisesRegex(ProbeError, "unsupported trace attribute"):
            raw_attribute_address(0x1000, "hiddenThing")

    def test_maps_attribute_to_executable_display_identifier(self) -> None:
        self.assertEqual(display_attribute_id("acceleration"), 0x27)
        self.assertEqual(display_attribute_id("agility"), 0x28)


if __name__ == "__main__":
    unittest.main()
