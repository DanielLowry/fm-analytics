import unittest
from dataclasses import replace

from fm_analytics.analytics import (
    build_substitution_board,
    evaluate_tactic,
    select_bench,
)
from tests.test_xi_selection import CATALOGUE, TACTIC, legal_squad, player


class SubstitutionBoardTests(unittest.TestCase):
    def test_lists_named_bench_options_for_the_exact_starter_slot(self) -> None:
        squad = legal_squad()
        versatile = replace(player(20, "GK", 10), positions=("GK", "DC"), name="Versatile")
        squad.append(versatile)
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)
        bench = select_bench(evaluation, squad, CATALOGUE, bench_size=1)

        board = build_substitution_board(evaluation, bench, squad, CATALOGUE)
        gk_target = next(target for target in board.targets if target.starter.slot.key == "slot-0")

        self.assertEqual([option.player_name for option in gk_target.options], ["Versatile"])
        self.assertEqual(gk_target.options[0].assignment.slot.key, "slot-0")
        self.assertEqual(
            gk_target.options[0].sole_cover_slot_keys,
            ("slot-1", "slot-2", "slot-3", "slot-4"),
        )

    def test_rejects_a_bench_player_missing_from_the_selection(self) -> None:
        squad = legal_squad()
        squad.append(player(20, "ST", 10))
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)
        bench = select_bench(evaluation, squad, CATALOGUE)
        missing_bench = replace(
            bench,
            entries=(replace(bench.entries[0], player_id="missing"),),
        )

        with self.assertRaisesRegex(ValueError, "bench players"):
            build_substitution_board(evaluation, missing_bench, squad, CATALOGUE)


if __name__ == "__main__":
    unittest.main()
