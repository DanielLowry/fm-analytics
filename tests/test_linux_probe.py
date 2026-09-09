import unittest
from datetime import date

from tools.fm20_linux_probe import ProbeError, decode_fm_date, parse_module_mapping


class LinuxFm20ProbeTests(unittest.TestCase):
    def test_parses_proton_module_base(self) -> None:
        mapping = (
            "140000000-140001000 r--p 00000000 103:03 42 "
            "/games/SteamLibrary/steamapps/common/Football Manager 2020/fm.exe\n"
        )

        base, executable = parse_module_mapping([mapping])

        self.assertEqual(base, 0x140000000)
        self.assertTrue(executable.endswith("Football Manager 2020/fm.exe"))

    def test_decode_date_masks_fm_flag_bits(self) -> None:
        self.assertEqual(decode_fm_date(bytes.fromhex("af 1a e3 07")), date(2019, 6, 24))

    def test_decode_date_rejects_invalid_value(self) -> None:
        with self.assertRaisesRegex(ProbeError, "invalid FM date"):
            decode_fm_date(bytes.fromhex("00 00 00 00"))


if __name__ == "__main__":
    unittest.main()

