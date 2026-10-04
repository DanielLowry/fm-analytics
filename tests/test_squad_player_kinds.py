"""Player-coaches are squad members too; FM's virtual placeholders are not.

A first-team vector holds ordinary players, players who also hold a staff role
(FM's ACTUAL_PLAYER_AND_NON_PLAYER, e.g. Hungerford Town's Graeme Montgomery)
and virtual placeholders. FM's squad screen shows the first two. The second
kind's person part sits at interface + 0x2A0 instead of + 0x1C8; the player
record (ratings, attributes, condition) is at interface + 8 for both.
"""
import unittest
from datetime import date
from unittest.mock import patch

from tests.test_fm20_cold_query_cache import (
    DUAL_PLAYER_ID,
    DUAL_PLAYER_INTERFACE,
    DUAL_PLAYER_PERSON,
    FakeProcessMemory,
    PLAYER_ID,
    PLAYER_INTERFACE,
    PLAYER_PERSON,
    _add_valid_dual_role_player,
    _valid_player,
)
from tools import fm20_linux_probe as probe
from tools.fm20_owned_visible_source import _resolve_player_addresses

VIRTUAL_INTERFACE = 0x1F000
VECTOR = 0x20000


def squad_memory() -> FakeProcessMemory:
    memory = FakeProcessMemory()
    _valid_player(memory)
    _add_valid_dual_role_player(memory)
    for index, interface in enumerate((PLAYER_INTERFACE, DUAL_PLAYER_INTERFACE, VIRTUAL_INTERFACE)):
        memory.u64(VECTOR + 8 * index, interface)
    # A placeholder: neither kind's class table where a person would be.
    memory.u64(VIRTUAL_INTERFACE + 0x1C8, 0x1234)
    memory.u64(VIRTUAL_INTERFACE + 0x2A0, 0x5678)
    return memory


class SquadEntryTests(unittest.TestCase):
    def test_each_kind_of_entry(self):
        with squad_memory() as fd:
            self.assertEqual(probe.squad_entry_person(fd, 0, PLAYER_INTERFACE), PLAYER_PERSON)
            self.assertEqual(probe.squad_entry_person(fd, 0, DUAL_PLAYER_INTERFACE), DUAL_PLAYER_PERSON)
            self.assertIsNone(probe.squad_entry_person(fd, 0, VIRTUAL_INTERFACE))
            self.assertIsNone(probe.squad_entry_person(fd, 0, 0x7FFF_FFFF_0000))  # unreadable

    def test_squad_ids_include_player_coaches_and_skip_placeholders(self):
        with squad_memory() as fd:
            ids = probe.read_team_player_ids(fd, 0, VECTOR, VECTOR + 24, squad_label="first team")
        self.assertEqual(ids, {str(PLAYER_ID), str(DUAL_PLAYER_ID)})

    def test_a_player_coach_is_read_from_his_own_person_and_player_records(self):
        names = {PLAYER_PERSON + 0x28 + 0x30: "Ordinary", PLAYER_PERSON + 0x28 + 0x38: "Player",
                 DUAL_PLAYER_PERSON + 0x28 + 0x30: "Graeme", DUAL_PLAYER_PERSON + 0x28 + 0x38: "Montgomery"}
        memory = squad_memory()
        ratings = bytes([1] * 6 + [20, 14, 15] + [1] * 6)  # ML 20, MC 14, MR 15
        memory.file.seek(DUAL_PLAYER_INTERFACE + 8 + 0x164)
        memory.file.write(ratings)
        memory.file.seek(DUAL_PLAYER_INTERFACE + 8 + 0x14C)
        memory.file.write((3500).to_bytes(2, "little") + bytes(2) + (9082).to_bytes(2, "little"))
        with (
            memory as fd,
            patch.object(probe, "read_fm_string", side_effect=lambda _fd, address, indirect=True: names.get(address, "")),
            patch.object(probe, "read_player_contract", return_value=None),
        ):
            players = probe._read_team_squad_players(fd, 0, VECTOR, VECTOR + 24, date(2020, 5, 30),
                                                     squad_label="first team")
        coach = next(player for player in players if player.id == str(DUAL_PLAYER_ID))
        self.assertEqual(len(players), 2)
        self.assertEqual(coach.name, "Graeme Montgomery")
        self.assertEqual(coach.positions, ("ML", "MC", "MR"))
        self.assertEqual((coach.condition_percent, coach.match_fitness_percent),
                         (probe.display_percent(9082), probe.display_percent(3500)))

    def test_owned_attributes_are_found_for_both_kinds(self):
        with squad_memory() as fd:
            addresses = _resolve_player_addresses(fd, 0, {PLAYER_ID, DUAL_PLAYER_ID})
        self.assertEqual(addresses[PLAYER_ID], (PLAYER_INTERFACE + 8, PLAYER_PERSON))
        self.assertEqual(addresses[DUAL_PLAYER_ID], (DUAL_PLAYER_INTERFACE + 8, DUAL_PLAYER_PERSON))


if __name__ == "__main__":
    unittest.main()
