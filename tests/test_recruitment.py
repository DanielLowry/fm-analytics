import unittest

from fm_analytics.analytics import (
    WeaknessPolicy,
    assess_weaknesses,
    build_recruitment_briefs,
    evaluate_tactic,
)
from tests.test_xi_selection import CATALOGUE, TACTIC, legal_squad, player


class RecruitmentTests(unittest.TestCase):
    def test_briefs_carry_the_squad_relative_bar_that_created_each_weakness(self) -> None:
        squad = legal_squad()
        squad[0] = player(1, "GK", 6)
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)
        policy = WeaknessPolicy(version="custom-ratios", starter_ratio=0.9, backup_ratio=0.75)
        report = assess_weaknesses(evaluation, squad, CATALOGUE, policy=policy)

        briefs = build_recruitment_briefs(report, CATALOGUE)

        starter_briefs = [brief for brief in briefs if brief.need == "starter"]
        self.assertEqual([brief.slot_keys for brief in starter_briefs], [("slot-0",)])
        self.assertEqual(
            starter_briefs[0].minimum_role_score,
            round(report.reference_score * 0.9, 6),
        )
        keeper = next(a for a in evaluation.assignments if a.slot.key == "slot-0")
        gk_depth = next(
            brief for brief in briefs if brief.need == "depth" and brief.slot_keys == ("slot-0",)
        )
        self.assertEqual(
            gk_depth.minimum_role_score,
            round(keeper.intrinsic_role_score.score.central * 0.75, 6),
        )

if __name__ == "__main__":
    unittest.main()
