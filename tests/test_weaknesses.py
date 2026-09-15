import unittest
from dataclasses import replace

from fm_analytics.analytics import (
    WeaknessKind,
    WeaknessPolicy,
    assess_weaknesses,
    evaluate_tactic,
)
from tests.test_xi_selection import CATALOGUE, TACTIC, legal_squad, player


class WeaknessTests(unittest.TestCase):
    def test_reports_weak_starters_and_absent_backups_separately(self) -> None:
        squad = legal_squad()
        squad[0] = player(1, "GK", 6)
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        report = assess_weaknesses(evaluation, squad, CATALOGUE)

        kinds = [weakness.kind for weakness in report.weaknesses]
        weak = [w for w in report.weaknesses if w.kind is WeaknessKind.WEAK_STARTER]
        self.assertEqual([w.player_id for w in weak], ["1"])
        self.assertEqual(kinds.count(WeaknessKind.NO_BACKUP), 11)

    def test_an_evenly_matched_squad_has_no_weak_links(self) -> None:
        # Relative, not absolute: a uniformly modest XI has no weak starter.
        squad = legal_squad()
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        report = assess_weaknesses(evaluation, squad, CATALOGUE)

        self.assertNotIn(
            WeaknessKind.WEAK_STARTER, {weakness.kind for weakness in report.weaknesses}
        )

    def test_backup_is_weak_only_when_it_drops_off_sharply_from_the_starter(self) -> None:
        close = legal_squad() + [player(40, "GK", 11)]
        far = legal_squad() + [player(40, "GK", 4)]

        def gk_kinds(squad):
            report = assess_weaknesses(
                evaluate_tactic(TACTIC, squad, CATALOGUE), squad, CATALOGUE
            )
            return {w.kind for w in report.weaknesses if w.slot_keys == ("slot-0",)}

        self.assertNotIn(WeaknessKind.WEAK_BACKUP, gk_kinds(close))
        self.assertIn(WeaknessKind.WEAK_BACKUP, gk_kinds(far))

    def test_policy_rejects_out_of_range_ratios(self) -> None:
        with self.assertRaises(ValueError):
            WeaknessPolicy(starter_ratio=0)
        with self.assertRaises(ValueError):
            WeaknessPolicy(backup_ratio=1.5)

    def test_reports_shared_cover_for_simultaneous_slots(self) -> None:
        squad = legal_squad()
        squad.append(player(50, "DC", 10))
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        report = assess_weaknesses(evaluation, squad, CATALOGUE)

        shared = [
            weakness
            for weakness in report.weaknesses
            if weakness.kind is WeaknessKind.SHARED_COVER
        ]
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0].player_id, "50")
        self.assertEqual(len(shared[0].slot_keys), 4)

    def test_unfilled_slot_distinguishes_temporary_availability(self) -> None:
        squad = legal_squad()
        squad[0] = replace(squad[0], availability="suspended", suspended=True)
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        report = assess_weaknesses(evaluation, squad, CATALOGUE)

        gaps = [
            weakness
            for weakness in report.weaknesses
            if weakness.kind in {
                WeaknessKind.STRUCTURAL_GAP,
                WeaknessKind.TEMPORARY_GAP,
            }
        ]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].kind, WeaknessKind.TEMPORARY_GAP)
        self.assertEqual(gaps[0].slot_keys, ("slot-0",))

    def test_unfilled_slot_without_nominal_candidate_is_structural(self) -> None:
        squad = legal_squad()[1:]
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        report = assess_weaknesses(evaluation, squad, CATALOGUE)

        gap = next(
            weakness
            for weakness in report.weaknesses
            if weakness.kind is WeaknessKind.STRUCTURAL_GAP
        )
        self.assertEqual(gap.slot_keys, ("slot-0",))

    def test_unfilled_slot_caused_by_one_player_covering_two_is_simultaneous(self) -> None:
        squad = legal_squad()
        del squad[1]
        squad[4] = replace(squad[4], positions=("DC", "MC"))
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        report = assess_weaknesses(evaluation, squad, CATALOGUE)

        simultaneous = [
            weakness
            for weakness in report.weaknesses
            if weakness.kind is WeaknessKind.SIMULTANEOUS_GAP
        ]
        self.assertEqual(len(simultaneous), 1)


if __name__ == "__main__":
    unittest.main()
