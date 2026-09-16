import io
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tools.fm20_pe_symbols import (
    Fm20Image,
    SymbolError,
    main,
    readable_class_name,
)


IMAGE_BASE = 0x140000000
TEXT_RVA = 0x1000
DATA_RVA = 0x2000


def synthetic_image() -> bytes:
    """A minimal PE32+ with an exception table, RTTI, and one vtable.

    Layout, mirroring the shapes the real FM executable uses:
      code    RVA 0x1000, file 0x200
      data    RVA 0x2000, file 0x400
      a parent function 0x1000-0x1100 and a cold chunk 0x1200-0x1240 chained to it
      a vtable at RVA 0x2100 owned by db::PLAYER, slot 0x10 holding 0x1000
      the property key 'tofP' inside the code section
    """
    data = bytearray(0xA00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 2)  # machine, section count
    struct.pack_into("<H", data, 0x94, 0xF0)  # optional header size
    struct.pack_into("<H", data, 0x98, 0x20B)  # PE32+
    struct.pack_into("<Q", data, 0x98 + 24, IMAGE_BASE)
    # Exception directory (index 3) describing two runtime functions.
    struct.pack_into("<II", data, 0x98 + 112 + 3 * 8, 0x2200, 24)

    section = 0x188
    data[section:section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x300, TEXT_RVA, 0x300, 0x200)
    struct.pack_into("<I", data, section + 36, 0x60000020)
    section += 40
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x400, DATA_RVA, 0x400, 0x500)
    struct.pack_into("<I", data, section + 36, 0x40000040)

    def data_offset(rva: int) -> int:
        return 0x500 + rva - DATA_RVA

    # Runtime functions: parent, then a cold chunk whose unwind info chains back.
    struct.pack_into("<III", data, data_offset(0x2200), 0x1000, 0x1100, 0x2300)
    struct.pack_into("<III", data, data_offset(0x2200) + 12, 0x1200, 0x1240, 0x2310)
    struct.pack_into("<BBBB", data, data_offset(0x2300), 1, 0, 0, 0)  # plain unwind info
    struct.pack_into("<BBBB", data, data_offset(0x2310), 1 | (0x4 << 3), 0, 0, 0)  # chained
    struct.pack_into("<III", data, data_offset(0x2310) + 4, 0x1000, 0x1100, 0x2300)

    # RTTI: type descriptor, complete object locator, vtable with the locator in front.
    descriptor_rva = 0x2020
    locator_rva = 0x2060
    data[data_offset(descriptor_rva) + 16:data_offset(descriptor_rva) + 16 + 16] = b".?AVPLAYER@db@@\0"
    struct.pack_into("<IIIIII", data, data_offset(locator_rva), 1, 0x10, 0, descriptor_rva, 0, locator_rva)
    vtable_rva = 0x2100
    struct.pack_into("<Q", data, data_offset(vtable_rva - 8), IMAGE_BASE + locator_rva)
    struct.pack_into("<Q", data, data_offset(vtable_rva), IMAGE_BASE + 0x1080)  # slot 0x0
    struct.pack_into("<Q", data, data_offset(vtable_rva + 8), IMAGE_BASE + 0x1090)  # slot 0x8
    struct.pack_into("<Q", data, data_offset(vtable_rva + 0x10), IMAGE_BASE + 0x1000)  # slot 0x10

    data[0x260:0x264] = b"tofP"
    return bytes(data)


class PeSymbolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = Fm20Image(synthetic_image())

    def test_readable_class_name_reverses_msvc_scopes(self) -> None:
        self.assertEqual(readable_class_name(".?AVACTUAL_PLAYER@db@@"), "db::ACTUAL_PLAYER")
        self.assertEqual(readable_class_name(".?AVGAME_SCOUTED_PERSON@@"), "GAME_SCOUTED_PERSON")
        self.assertEqual(readable_class_name("unmangled"), "unmangled")

    def test_function_lookup_uses_the_exception_table(self) -> None:
        found = self.image.function_at(0x1040)

        self.assertEqual(self.image.function_count, 2)
        self.assertEqual((found.start_rva, found.end_rva), (0x1000, 0x1100))
        self.assertIsNone(self.image.function_at(0x1500))

    def test_cold_chunk_resolves_to_its_parent_function(self) -> None:
        found = self.image.function_at(0x1220)

        self.assertEqual((found.start_rva, found.end_rva), (0x1000, 0x1100))
        self.assertEqual((found.chunk_start_rva, found.chunk_end_rva), (0x1200, 0x1240))

    def test_slot_owner_names_the_class_and_slot(self) -> None:
        owners = self.image.slot_owners(0x1000)

        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0].vtable_rva, 0x2100)
        self.assertEqual(owners[0].slot_offset, 0x10)
        self.assertEqual(owners[0].owner.name, "db::PLAYER")
        self.assertEqual(owners[0].owner.object_offset, 0x10)

    def test_vtable_without_locator_is_reported_as_unknown(self) -> None:
        self.assertIsNone(self.image.class_at_vtable(0x2400))

    def test_property_key_search_is_restricted_to_code(self) -> None:
        self.assertEqual(self.image.find_property_key("tofP"), [0x1060])
        self.assertEqual(self.image.find_property_key("zzzz"), [])
        with self.assertRaises(SymbolError):
            self.image.find_property_key("too-long")

    def test_cli_reports_function_owner_and_key_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fm.exe"
            executable.write_bytes(synthetic_image())
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    "--executable", str(executable), "--no-validate", "--json", "owner", "0x1000",
                ])
            payload = json.loads(output.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(payload["0x1000"][0]["class"], "db::PLAYER")
        self.assertEqual(payload["0x1000"][0]["slot"], "0x10")

    def test_cli_reports_unreadable_executable_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fm.exe"
            executable.write_bytes(b"not a PE")
            errors = io.StringIO()
            with redirect_stdout(io.StringIO()):
                import contextlib
                with contextlib.redirect_stderr(errors):
                    status = main(["--executable", str(executable), "--no-validate", "function", "0x1000"])

        self.assertEqual(status, 1)
        self.assertIn("error:", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
