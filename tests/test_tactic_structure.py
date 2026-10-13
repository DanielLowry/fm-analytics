import unittest

from fm_analytics.analytics import MVP_CATALOGUE, check_tactic_structure


class TacticStructureTests(unittest.TestCase):
    def test_fluid_counter_reports_its_failing_role_combinations(self) -> None:
        tactic = MVP_CATALOGUE.tactics["fluid_counter_4141"]

        check = check_tactic_structure(tactic, MVP_CATALOGUE)

        # DCL: CD(D), CD(C) or BPD(D); DCR: Cover or Defend; one Cover at most; AF or Poacher.
        self.assertEqual(check.combination_count, 10)
        self.assertEqual(len(check.failures), 5)
        self.assertTrue(
            all(
                "penetration 1.4/1.5"
                in failure.balance.shortfalls + failure.instructions.shortfalls
                for failure in check.failures
            )
        )
        self.assertTrue(
            all("p_attack" in failure.role_keys for failure in check.failures)
        )


if __name__ == "__main__":
    unittest.main()
