import struct
import tempfile
import unittest

from tools.fm20_cold_visibility_call import resolve_cold_call_addresses
from tools.fm20_linux_probe import FM20_4_4_STEAM, ProbeError


MODULE_BASE = 0
CONTEXT_ROOT_ADDRESS = MODULE_BASE + 0x746A440
ROOT = 0x2000
VECTOR_START = 0x3000
CONTEXT = 0x4000
MANAGER_PERSON = 0x5000
MANAGER_INTERFACE = MANAGER_PERSON - 0x480
MANAGER_TABLE = 0x6000
PEOPLE_FIRST_POINTER = 0x7000
PEOPLE_COLLECTION = 0x8000
PEOPLE_VECTOR_START = 0x9000
PLAYER_PERSON = 0xB000
PLAYER_INTERFACE = PLAYER_PERSON - 0x1C8
PLAYER_TABLE = 0xC000
ACTIVE_MANAGER_ID = "42"
PLAYER_ID = 777

PEOPLE_ROOT_FIELD = (
    MODULE_BASE
    + FM20_4_4_STEAM.main_address_offset
    + FM20_4_4_STEAM.person_collection_offset
)


class FakeProcessMemory:
    """A sparse, seek-addressed stand-in for /proc/<pid>/mem."""

    def __init__(self) -> None:
        self.file = tempfile.TemporaryFile()

    def u64(self, address: int, value: int) -> None:
        self.file.seek(address)
        self.file.write(value.to_bytes(8, "little"))

    def i32(self, address: int, value: int) -> None:
        self.file.seek(address)
        self.file.write(struct.pack("<i", value))

    def __enter__(self) -> int:
        self.file.flush()
        return self.file.fileno()

    def __exit__(self, *args: object) -> None:
        self.file.close()


def _valid_memory() -> FakeProcessMemory:
    memory = FakeProcessMemory()
    memory.u64(CONTEXT_ROOT_ADDRESS, ROOT)
    memory.u64(ROOT + 0x18, VECTOR_START)
    memory.u64(ROOT + 0x20, VECTOR_START + 8)
    memory.u64(VECTOR_START, CONTEXT)
    memory.u64(CONTEXT + 0x18, MANAGER_PERSON)
    memory.u64(MANAGER_PERSON, MODULE_BASE + FM20_4_4_STEAM.human_manager_type_offset)
    memory.i32(MANAGER_PERSON + 0xC, int(ACTIVE_MANAGER_ID))
    memory.u64(MANAGER_INTERFACE + 8, MANAGER_TABLE)
    memory.i32(MANAGER_TABLE + 4, MANAGER_PERSON - (MANAGER_INTERFACE + 8))

    memory.u64(PEOPLE_ROOT_FIELD, PEOPLE_FIRST_POINTER)
    memory.u64(
        PEOPLE_FIRST_POINTER + FM20_4_4_STEAM.collection_indirection_offset,
        PEOPLE_COLLECTION,
    )
    memory.u64(PEOPLE_COLLECTION, PEOPLE_VECTOR_START)
    memory.u64(PEOPLE_COLLECTION + 8, PEOPLE_VECTOR_START + 8)
    memory.u64(PEOPLE_VECTOR_START, PLAYER_PERSON)
    memory.u64(PLAYER_PERSON, MODULE_BASE + FM20_4_4_STEAM.player_type_offset)
    memory.i32(PLAYER_PERSON + 0xC, PLAYER_ID)
    memory.u64(PLAYER_INTERFACE + 8, PLAYER_TABLE)
    memory.i32(PLAYER_TABLE + 4, PLAYER_PERSON - (PLAYER_INTERFACE + 8))
    return memory


class ResolveColdCallAddressesTests(unittest.TestCase):
    def test_resolves_a_fully_consistent_memory_graph(self) -> None:
        with _valid_memory() as fd:
            context, manager_interface, player_interface = resolve_cold_call_addresses(
                fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID
            )

        self.assertEqual(context, CONTEXT)
        self.assertEqual(manager_interface, MANAGER_INTERFACE)
        self.assertEqual(player_interface, PLAYER_INTERFACE)

    def test_fails_closed_when_context_root_is_missing(self) -> None:
        memory = _valid_memory()
        memory.u64(CONTEXT_ROOT_ADDRESS, 0)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "context root is missing"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID)

    def test_fails_closed_when_more_than_one_context_exists(self) -> None:
        memory = _valid_memory()
        memory.u64(ROOT + 0x20, VECTOR_START + 16)  # two contexts, not one
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "exactly one manager-knowledge context"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID)

    def test_fails_closed_when_context_pointer_is_null(self) -> None:
        memory = _valid_memory()
        memory.u64(VECTOR_START, 0)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "context is null"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID)

    def test_fails_closed_when_context_owner_is_not_a_human_manager(self) -> None:
        memory = _valid_memory()
        memory.u64(MANAGER_PERSON, 0xDEAD)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "not a human manager"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID)

    def test_fails_closed_when_context_owner_is_not_the_active_manager(self) -> None:
        with _valid_memory() as fd:
            with self.assertRaisesRegex(ProbeError, "not the active manager"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, "999")

    def test_fails_closed_when_manager_interface_adjustment_is_wrong(self) -> None:
        memory = _valid_memory()
        memory.i32(MANAGER_TABLE + 4, 0)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "manager interface adjustment"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID)

    def test_fails_closed_when_player_id_is_not_found(self) -> None:
        with _valid_memory() as fd:
            with self.assertRaisesRegex(ProbeError, "did not resolve uniquely"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID + 1, ACTIVE_MANAGER_ID)

    def test_fails_closed_when_player_id_matches_more_than_one_person(self) -> None:
        memory = _valid_memory()
        # A second loaded person with the same player type and ID.
        memory.u64(PEOPLE_COLLECTION + 8, PEOPLE_VECTOR_START + 16)
        second_player = 0xD000
        memory.u64(PEOPLE_VECTOR_START + 8, second_player)
        memory.u64(second_player, MODULE_BASE + FM20_4_4_STEAM.player_type_offset)
        memory.i32(second_player + 0xC, PLAYER_ID)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "did not resolve uniquely"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID)

    def test_fails_closed_when_player_interface_adjustment_is_wrong(self) -> None:
        memory = _valid_memory()
        memory.i32(PLAYER_TABLE + 4, 0)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "player interface adjustment"):
                resolve_cold_call_addresses(fd, MODULE_BASE, PLAYER_ID, ACTIVE_MANAGER_ID)


if __name__ == "__main__":
    unittest.main()
