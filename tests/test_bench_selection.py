import unittest
from dataclasses import replace

from fm_analytics.analytics import select_bench
from tests.test_xi_selection import CATALOGUE, TACTIC, legal_squad, player
from fm_analytics.analytics import evaluate_tactic


class BenchSelectionTests(unittest.TestCase):
    def test_prefers_collective_slot_coverage_then_quality(self) -> None:
        squad = legal_squad()
        squad.extend(
            (
                player(20, "GK", 11),
                player(21, "DC", 11),
            )
        )
        versatile = player(22, "GK", 10)
        versatile = replace(versatile, positions=("GK", "DC"), name="Versatile")
        squad.append(versatile)
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        bench = select_bench(evaluation, squad, CATALOGUE, bench_size=1)

        self.assertEqual([entry.player_id for entry in bench.entries], ["22"])
        self.assertEqual(
            bench.entries[0].newly_covered_slots,
            ("slot-0", "slot-1", "slot-2", "slot-3", "slot-4"),
        )

    def test_excludes_starters_unavailable_and_low_readiness_players(self) -> None:
        squad = legal_squad()
        squad.extend(
            (
                player(20, "ST", 20, availability="suspended"),
                player(21, "ST", 19, condition=64),
                player(22, "ST", 11),
            )
        )
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)
        starter_ids = {item.player_id for item in evaluation.assignments}

        bench = select_bench(evaluation, squad, CATALOGUE)

        bench_ids = {entry.player_id for entry in bench.entries}
        self.assertEqual(bench_ids, {"22"})
        self.assertTrue(starter_ids.isdisjoint(bench_ids))

    def test_reports_uncovered_slots_when_bench_has_no_replacement(self) -> None:
        squad = legal_squad()
        squad.append(player(20, "ST", 11))
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        bench = select_bench(evaluation, squad, CATALOGUE)

        self.assertEqual(bench.covered_slots, ("slot-9", "slot-10"))
        self.assertEqual(len(bench.uncovered_slots), 9)

    def test_rejects_negative_bench_size(self) -> None:
        squad = legal_squad()
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            select_bench(evaluation, squad, CATALOGUE, bench_size=-1)


if __name__ == "__main__":
    unittest.main()
