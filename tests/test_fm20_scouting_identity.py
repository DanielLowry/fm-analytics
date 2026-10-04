"""The per-person memory readers behind the scouting capture (``tools.fm20_scouting_identity``)."""

import os
import struct
import unittest
from unittest import mock

from tools import fm20_linux_probe as probe
from tools import fm20_scouting_identity as identity
from tools.fm20_linux_probe import FM20_4_4_STEAM, POSITION_CODES, STAFF_ROLE_PLAYER_TYPE_RVA

ORDINARY = FM20_4_4_STEAM.player_type_offset


class PositionRatingReaderTests(unittest.TestCase):
    BASE = 0x140000000

    def read_players(self, reader, players: dict[int, tuple[int, int, bytes]]):
        """Run ``reader`` over fake memory: player ID -> (person, type RVA, bytes at a rating offset)."""
        memory: dict[int, bytes] = {}
        for person, type_rva, ratings in players.values():
            memory[person] = struct.pack("<Q", self.BASE + type_rva)
            # Ordinary layout's ratings at person - 0x5C; staff-role layout's at person - 0x134.
            memory[person - (0x5C if type_rva == ORDINARY else 0x134)] = ratings

        def read(_fd, address, size):
            if address not in memory:
                return bytes(size)
            return memory[address][:size]

        with mock.patch.object(identity, "read_exact", side_effect=read), \
                mock.patch.object(probe, "read_exact", side_effect=read):
            return reader(os.getpid(), self.BASE, {pid: person for pid, (person, _t, _r) in players.items()})

    def test_the_reader_keeps_all_fifteen_ratings_and_refuses_a_non_rating_array(self) -> None:
        good = bytes(range(len(POSITION_CODES)))
        noise = bytes([200] + [0] * (len(POSITION_CODES) - 1))
        ratings = self.read_players(
            identity.read_raw_position_familiarity, {1: (0x10000, ORDINARY, good), 2: (0x20000, ORDINARY, noise)}
        )

        self.assertEqual(ratings, {1: dict(zip(POSITION_CODES, good))})

    def test_a_player_coach_is_read_from_his_own_layout(self) -> None:
        # FM keeps a player who also holds a staff role in a bigger object, his
        # person 0xD8 further in. Read at the ordinary offset, 625 of one
        # capture's players had all-zero or nonsense ratings.
        right_back = bytes([1, 1, 15, 1, 20, 1, 1, 1, 1, 1, 1, 1, 1, 1, 13])
        striker = bytes([1] * 12 + [20, 1, 1])
        players = {
            1: (0x10000, STAFF_ROLE_PLAYER_TYPE_RVA, right_back),
            2: (0x20000, ORDINARY, striker),
        }

        ratings = self.read_players(identity.read_raw_position_familiarity, players)
        positions = self.read_players(identity.read_raw_external_positions, players)

        self.assertEqual(ratings[1], dict(zip(POSITION_CODES, right_back)))
        self.assertEqual(positions, {1: ("DL", "DR", "WBR"), 2: ("ST",)})

    def test_noise_and_unknown_kinds_of_person_get_no_positions(self) -> None:
        noise = bytes([0] * 12 + [64, 248, 49])  # what one player-coach's wrong offset held
        positions = self.read_players(identity.read_raw_external_positions, {
            1: (0x10000, ORDINARY, noise),
            2: (0x20000, 0x1234, bytes([20] * 15)),
        })

        self.assertEqual(positions, {})


if __name__ == "__main__":
    unittest.main()
