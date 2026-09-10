import unittest
from datetime import date

from tools.fm20_linux_probe import (
    ProbeError,
    calculate_age,
    decode_fm_date,
    decode_positions,
    display_percent,
    parse_module_mapping,
    read_fm_string,
    read_optional_contract_date,
    read_pointer_collection,
    validate_executable,
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

    def test_rejects_an_executable_with_the_wrong_size(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile() as executable:
            with self.assertRaisesRegex(ProbeError, "unsupported executable size"):
                validate_executable(executable.name)

    def test_decode_date_masks_fm_flag_bits(self) -> None:
        self.assertEqual(decode_fm_date(bytes.fromhex("af 1a e3 07")), date(2019, 6, 24))

    def test_decode_date_rejects_invalid_value(self) -> None:
        with self.assertRaisesRegex(ProbeError, "invalid FM date"):
            decode_fm_date(bytes.fromhex("00 00 00 00"))

    def test_decodes_player_birth_date_before_the_game_era(self) -> None:
        self.assertEqual(
            decode_fm_date(bytes.fromhex("01 00 c3 07")),
            date(1987, 1, 1),
        )

    def test_calculates_age_on_either_side_of_birthday(self) -> None:
        born = date(2000, 6, 25)

        self.assertEqual(calculate_age(born, date(2019, 6, 24)), 18)
        self.assertEqual(calculate_age(born, date(2019, 6, 25)), 19)

    def test_display_percent_discards_hidden_precision(self) -> None:
        self.assertEqual(display_percent(9_775), 98)
        self.assertEqual(display_percent(6_250), 63)
        with self.assertRaisesRegex(ProbeError, "percentage"):
            display_percent(10_001)

    def test_contract_date_treats_fm_sentinel_as_missing(self) -> None:
        memory = bytearray(bytes.fromhex("02 00 6c 07"))

        with self.memory_file(memory) as memory_fd:
            result = read_optional_contract_date(memory_fd, 0)

        self.assertIsNone(result)

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

    def test_reads_direct_and_indirect_fm_strings(self) -> None:
        memory = bytearray(160)
        memory[8:16] = (40).to_bytes(8, "little")
        memory[40:44] = (4).to_bytes(4, "little")
        memory[44:48] = b"Club"
        memory[16:24] = (64).to_bytes(8, "little")
        memory[64:72] = (96).to_bytes(8, "little")
        memory[96:100] = (6).to_bytes(4, "little")
        memory[100:106] = b"Player"

        with self.memory_file(memory) as memory_fd:
            club = read_fm_string(memory_fd, 8, indirect=False)
            player = read_fm_string(memory_fd, 16)

        self.assertEqual(club, "Club")
        self.assertEqual(player, "Player")

    def test_positions_include_accomplished_or_natural_roles(self) -> None:
        ratings = bytes([1, 1, 14, 20, 16, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1])

        self.assertEqual(decode_positions(ratings), ("DC", "DR"))

    def test_positions_fall_back_to_the_strongest_role(self) -> None:
        ratings = bytes([1, 1, 12, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1])

        self.assertEqual(decode_positions(ratings), ("DL",))

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
