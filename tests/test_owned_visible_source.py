import unittest
from dataclasses import dataclass

from tools.fm20_linux_probe import ProbeError
from tools.fm20_owned_visible_source import (
    build_parser,
    normalize_attribute_byte,
    select_players,
)


@dataclass(frozen=True)
class ExamplePlayer:
    id: str
    name: str


class OwnedVisibleSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.players = (
            ExamplePlayer("1", "Alex Smith"),
            ExamplePlayer("2", "Bob Jones"),
        )

    def test_normalizes_fm_signed_attribute_bytes(self) -> None:
        self.assertEqual(normalize_attribute_byte(3), 1)
        self.assertEqual(normalize_attribute_byte(48), 10)
        self.assertEqual(normalize_attribute_byte(98), 20)
        self.assertEqual(normalize_attribute_byte(-128), 1)
        self.assertEqual(normalize_attribute_byte(127), 20)

    def test_rejects_non_byte_input(self) -> None:
        with self.assertRaisesRegex(ProbeError, "out of range"):
            normalize_attribute_byte(128)

    def test_selects_a_managed_player_by_id(self) -> None:
        selected = select_players(self.players, player_id=2, player_name=None)

        self.assertEqual(selected, (self.players[1],))

    def test_selects_a_managed_player_by_case_insensitive_name(self) -> None:
        selected = select_players(
            self.players,
            player_id=None,
            player_name=" alex smith ",
        )

        self.assertEqual(selected, (self.players[0],))

    def test_defaults_to_the_full_managed_squad(self) -> None:
        selected = select_players(self.players, player_id=None, player_name=None)

        self.assertEqual(selected, self.players)

    def test_rejects_a_player_outside_the_managed_squad(self) -> None:
        with self.assertRaisesRegex(ProbeError, "not in"):
            select_players(self.players, player_id=999, player_name=None)

    def test_requires_an_id_for_duplicate_names(self) -> None:
        players = self.players + (ExamplePlayer("3", "Alex Smith"),)

        with self.assertRaisesRegex(ProbeError, "ambiguous"):
            select_players(players, player_id=None, player_name="Alex Smith")

    def test_cli_defaults_to_in_game_visibility(self) -> None:
        args = build_parser().parse_args([])

        self.assertEqual(args.visibility, "in-game")
        self.assertFalse(args.acknowledge_hidden_data)

    def test_cli_accepts_explicit_full_visibility_flags(self) -> None:
        args = build_parser().parse_args(
            [
                "--visibility",
                "full",
                "--acknowledge-hidden-data",
                "--team-id",
                "608",
            ]
        )

        self.assertEqual(args.visibility, "full")
        self.assertTrue(args.acknowledge_hidden_data)
        self.assertEqual(args.team_id, "608")


if __name__ == "__main__":
    unittest.main()
