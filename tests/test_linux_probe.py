import unittest
from datetime import date

from tools.fm20_linux_probe import (
    ProbeError,
    decode_fm_date,
    parse_module_mapping,
    read_pointer_collection,
)


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

    def test_reads_valid_pointer_collection(self) -> None:
        memory = bytearray(160)
        # root + collection offset -> first pointer -> collection -> [start, end]
        memory[16:24] = (40).to_bytes(8, "little")
        memory[48:56] = (80).to_bytes(8, "little")
        memory[80:88] = (120).to_bytes(8, "little")
        memory[88:96] = (136).to_bytes(8, "little")
        memory[120:128] = (0xAAA).to_bytes(8, "little")
        memory[128:136] = (0xBBB).to_bytes(8, "little")

        with self.memory_file(memory) as memory_fd:
            pointers = read_pointer_collection(memory_fd, 0, 0, 16, 8)

        self.assertEqual(pointers, (0xAAA, 0xBBB))

    class memory_file:
        def __init__(self, data: bytearray):
            import tempfile

            self.file = tempfile.TemporaryFile()
            self.file.write(data)
            self.file.flush()

        def __enter__(self) -> int:
            return self.file.fileno()

        def __exit__(self, *args: object) -> None:
            self.file.close()


if __name__ == "__main__":
    unittest.main()
