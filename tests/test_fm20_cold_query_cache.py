import struct
import tempfile
import unittest

from tools.fm20_cold_query_cache import (
    _PLAYER_INTERFACE_CACHE,
    _scan_player_interfaces,
    _valid_player_interface,
    resolve_context_and_manager,
    resolve_player_interfaces,
)
from tools.fm20_linux_probe import FM20_4_4_STEAM, ProbeError


MODULE_BASE = 0
CONTEXT_ROOT_ADDRESS = MODULE_BASE + 0x746A440
ROOT = 0x2000
VECTOR_START = 0x3000
CONTEXT = 0x4000
MANAGER_PERSON = 0x5000
MANAGER_INTERFACE = MANAGER_PERSON - 0x480
MANAGER_TABLE = 0x6000
ACTIVE_MANAGER_ID = 42
PLAYER_PERSON = 0xB000
PLAYER_INTERFACE = PLAYER_PERSON - 0x1C8
PLAYER_TABLE = 0xC000
PLAYER_ID = 777

PEOPLE_ROOT_FIELD = (
    MODULE_BASE + FM20_4_4_STEAM.main_address_offset + FM20_4_4_STEAM.person_collection_offset
)


class FakeProcessMemory:
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


def _valid_context() -> FakeProcessMemory:
    memory = FakeProcessMemory()
    memory.i32(MODULE_BASE + FM20_4_4_STEAM.active_object_offset, ACTIVE_MANAGER_ID)
    memory.u64(CONTEXT_ROOT_ADDRESS, ROOT)
    memory.u64(ROOT + 0x18, VECTOR_START)
    memory.u64(ROOT + 0x20, VECTOR_START + 8)
    memory.u64(VECTOR_START, CONTEXT)
    memory.u64(CONTEXT + 0x18, MANAGER_PERSON)
    memory.u64(MANAGER_PERSON, MODULE_BASE + FM20_4_4_STEAM.human_manager_type_offset)
    memory.i32(MANAGER_PERSON + 0xC, ACTIVE_MANAGER_ID)
    memory.u64(MANAGER_INTERFACE + 8, MANAGER_TABLE)
    memory.i32(MANAGER_TABLE + 4, MANAGER_PERSON - (MANAGER_INTERFACE + 8))
    return memory


def _valid_player(memory: FakeProcessMemory) -> None:
    memory.u64(PEOPLE_ROOT_FIELD, 0x7000)
    memory.u64(0x7000 + FM20_4_4_STEAM.collection_indirection_offset, 0x8000)
    memory.u64(0x8000, 0x9000)
    memory.u64(0x8000 + 8, 0x9008)
    memory.u64(0x9000, PLAYER_PERSON)
    memory.u64(PLAYER_PERSON, MODULE_BASE + FM20_4_4_STEAM.player_type_offset)
    memory.i32(PLAYER_PERSON + 0xC, PLAYER_ID)
    memory.u64(PLAYER_INTERFACE + 8, PLAYER_TABLE)
    memory.i32(PLAYER_TABLE + 4, PLAYER_PERSON - (PLAYER_INTERFACE + 8))


class ResolveContextAndManagerTests(unittest.TestCase):
    def test_resolves_context_and_manager_from_the_active_object_field(self) -> None:
        with _valid_context() as fd:
            context, manager_interface = resolve_context_and_manager(fd, MODULE_BASE)

        self.assertEqual(context, CONTEXT)
        self.assertEqual(manager_interface, MANAGER_INTERFACE)

    def test_fails_closed_when_active_object_does_not_own_the_context(self) -> None:
        memory = _valid_context()
        memory.i32(MODULE_BASE + FM20_4_4_STEAM.active_object_offset, 999)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "not the active manager"):
                resolve_context_and_manager(fd, MODULE_BASE)

    def test_resolves_via_fallback_scan_when_active_object_is_something_else(self) -> None:
        """The active-object field tracks UI selection, not just the manager.

        Regression test: with a live save, browsing a player (Player Search,
        a profile, ...) sets ActiveObject to that player, not the manager, and
        the old direct comparison raised even though the manager is easily and
        unambiguously resolvable. The fallback must still succeed here.
        """
        memory = _valid_context()
        # Something else is selected in the UI -- not the manager, not a
        # collection miss, just an ordinary browsing state.
        memory.i32(MODULE_BASE + FM20_4_4_STEAM.active_object_offset, 4321)
        # A minimal but valid person collection containing only the manager,
        # so the fallback scan can resolve them as the sole employed manager.
        # Offsets mirror read_human_manager_contexts exactly: contract at
        # person+0xC8, team at contract+0x10, club at team+0x18, club id at
        # club+0xC.
        memory.u64(PEOPLE_ROOT_FIELD, 0x7000)
        memory.u64(0x7000 + FM20_4_4_STEAM.collection_indirection_offset, 0x8000)
        memory.u64(0x8000, 0x9000)
        memory.u64(0x8000 + 8, 0x9008)
        memory.u64(0x9000, MANAGER_PERSON)
        memory.u64(MANAGER_PERSON + 0xC8, 0xA000)  # actual_person + 0xA0 contract
        memory.u64(0xA000 + 0x10, 0xA100)  # contract -> team
        memory.u64(0xA100 + 0x18, 0xA200)  # team -> club
        memory.i32(0xA200 + 0xC, 55)  # club id
        with memory as fd:
            context, manager_interface = resolve_context_and_manager(fd, MODULE_BASE)

        self.assertEqual(context, CONTEXT)
        self.assertEqual(manager_interface, MANAGER_INTERFACE)

    def test_fails_closed_when_context_root_is_missing(self) -> None:
        memory = _valid_context()
        memory.u64(CONTEXT_ROOT_ADDRESS, 0)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "context root is missing"):
                resolve_context_and_manager(fd, MODULE_BASE)

    def test_fails_closed_when_manager_interface_adjustment_is_wrong(self) -> None:
        memory = _valid_context()
        memory.i32(MANAGER_TABLE + 4, 0)
        with memory as fd:
            with self.assertRaisesRegex(ProbeError, "manager interface adjustment"):
                resolve_context_and_manager(fd, MODULE_BASE)


class PlayerInterfaceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        _PLAYER_INTERFACE_CACHE.clear()

    def test_scan_resolves_a_known_player(self) -> None:
        memory = FakeProcessMemory()
        _valid_player(memory)
        with memory as fd:
            found = _scan_player_interfaces(fd, MODULE_BASE, {PLAYER_ID})

        self.assertEqual(found, {PLAYER_ID: PLAYER_INTERFACE})

    def test_valid_player_interface_accepts_a_correct_address(self) -> None:
        memory = FakeProcessMemory()
        _valid_player(memory)
        with memory as fd:
            self.assertTrue(_valid_player_interface(fd, MODULE_BASE, PLAYER_INTERFACE, PLAYER_ID))

    def test_valid_player_interface_rejects_wrong_id_at_the_address(self) -> None:
        memory = FakeProcessMemory()
        _valid_player(memory)
        with memory as fd:
            self.assertFalse(_valid_player_interface(fd, MODULE_BASE, PLAYER_INTERFACE, PLAYER_ID + 1))

    def test_resolve_populates_cache_on_first_lookup(self) -> None:
        memory = FakeProcessMemory()
        _valid_player(memory)
        with memory as fd:
            resolved = resolve_player_interfaces(1234, fd, MODULE_BASE, [PLAYER_ID])

        self.assertEqual(resolved, {PLAYER_ID: PLAYER_INTERFACE})
        self.assertEqual(_PLAYER_INTERFACE_CACHE[1234], {PLAYER_ID: PLAYER_INTERFACE})

    def test_resolve_reuses_cache_without_rescanning(self) -> None:
        _PLAYER_INTERFACE_CACHE[1234] = {PLAYER_ID: PLAYER_INTERFACE}
        memory = FakeProcessMemory()
        _valid_player(memory)  # scan data present, but a hit should not need it
        with memory as fd:
            resolved = resolve_player_interfaces(1234, fd, MODULE_BASE, [PLAYER_ID])

        self.assertEqual(resolved, {PLAYER_ID: PLAYER_INTERFACE})

    def test_resolve_rescans_when_cached_address_fails_revalidation(self) -> None:
        _PLAYER_INTERFACE_CACHE[1234] = {PLAYER_ID: 0xDEAD}  # stale/wrong address
        memory = FakeProcessMemory()
        _valid_player(memory)
        with memory as fd:
            resolved = resolve_player_interfaces(1234, fd, MODULE_BASE, [PLAYER_ID])

        self.assertEqual(resolved, {PLAYER_ID: PLAYER_INTERFACE})
        self.assertEqual(_PLAYER_INTERFACE_CACHE[1234][PLAYER_ID], PLAYER_INTERFACE)

    def test_resolve_omits_players_that_cannot_be_found(self) -> None:
        memory = FakeProcessMemory()
        _valid_player(memory)
        with memory as fd:
            resolved = resolve_player_interfaces(1234, fd, MODULE_BASE, [PLAYER_ID, 999])

        self.assertEqual(resolved, {PLAYER_ID: PLAYER_INTERFACE})

    def test_cache_is_isolated_per_pid(self) -> None:
        _PLAYER_INTERFACE_CACHE[1234] = {PLAYER_ID: PLAYER_INTERFACE}
        memory = FakeProcessMemory()
        # A real, valid, but empty person collection: a different process
        # with no cache entry and no matching player, not a broken read.
        memory.u64(PEOPLE_ROOT_FIELD, 0x7000)
        memory.u64(0x7000 + FM20_4_4_STEAM.collection_indirection_offset, 0x8000)
        memory.u64(0x8000, 0x9000)
        memory.u64(0x8000 + 8, 0x9000)
        with memory as fd:
            resolved = resolve_player_interfaces(5678, fd, MODULE_BASE, [PLAYER_ID])

        self.assertEqual(resolved, {})


if __name__ == "__main__":
    unittest.main()
