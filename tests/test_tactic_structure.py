import unittest

from fm_analytics.analytics import MVP_CATALOGUE, check_tactic_structure


class TacticStructureTests(unittest.TestCase):
    def test_fluid_counter_reports_its_failing_role_combinations(self) -> None:
        tactic = MVP_CATALOGUE.tactics["fluid_counter_4141"]

        check = check_tactic_structure(tactic, MVP_CATALOGUE)

        self.assertEqual(check.combination_count, 6)
        self.assertEqual(len(check.failures), 3)
        self.assertTrue(
            all("penetration 1.4/1.5" in failure.balance.shortfalls for failure in check.failures)
        )
        self.assertTrue(
            all("p_attack" in failure.role_keys for failure in check.failures)
        )


if __name__ == "__main__":
    unittest.main()
