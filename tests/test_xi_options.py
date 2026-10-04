"""Ignoring condition changes selection without discarding other availability facts."""
import unittest
from dataclasses import replace

from fm_analytics.analytics import ReadinessPolicy, score_player_for_slot
from tests.test_xi_selection import CATALOGUE, TACTIC, player


class IgnoreConditionTests(unittest.TestCase):
    def test_ignoring_condition_removes_cutoff_penalty_and_unknown_warning(self):
        policy = ReadinessPolicy(ignore_condition=True)
        for condition in (0, 60, None):
            with self.subTest(condition=condition):
                candidate = replace(player(1, "ST", 14, match_fitness=70), condition_percent=condition)
                score = score_player_for_slot(candidate, TACTIC.slots[-1], CATALOGUE, readiness_policy=policy)
                self.assertIsNotNone(score)
                self.assertEqual(score.readiness_penalty, 3.0)
                self.assertNotIn("condition unknown", score.readiness_warnings)
        self.assertIsNone(score_player_for_slot(
            player(1, "ST", 14, condition=60, match_fitness=70), TACTIC.slots[-1], CATALOGUE,
        ))

    def test_ignoring_condition_keeps_injury_suspension_and_match_fitness_checks(self):
        candidate = player(1, "ST", 14, condition=60, match_fitness=100)
        for changes in ({"injured": True}, {"suspended": True}, {"match_fitness_percent": 20},
                        {"availability": "unavailable"}):
            with self.subTest(changes=changes):
                self.assertIsNone(score_player_for_slot(
                    replace(candidate, **changes), TACTIC.slots[-1], CATALOGUE,
                    readiness_policy=ReadinessPolicy(ignore_condition=True),
                ))


if __name__ == "__main__":
    unittest.main()
