import unittest

from tools.fm20_discoverability_cold_query import (
    own_contracted_ids,
    select_expected_exclusions,
    summarize,
)
from tools.fm20_linux_probe import ProbeError


class ColdDiscoverabilityQueryTests(unittest.TestCase):
    def test_own_contracted_ids_skip_loaned_in_and_unknown_contracts(self) -> None:
        squad = [(1, "10"), (2, "10"), (3, "99"), (4, None)]

        self.assertEqual(own_contracted_ids(squad, "10"), {1, 2})

    def test_expected_exclusions_are_own_players_present_in_source(self) -> None:
        self.assertEqual(
            select_expected_exclusions({1, 2, 3, 5, 6, 7}, {1, 2, 3, 4}), {1, 2, 3}
        )

    def test_expected_exclusions_fail_closed_without_three_own_players(self) -> None:
        with self.assertRaises(ProbeError):
            select_expected_exclusions({1, 2, 5, 6, 7}, {1, 2, 4})

    def test_expected_exclusions_fail_closed_without_three_other_players(self) -> None:
        with self.assertRaises(ProbeError):
            select_expected_exclusions({1, 2, 3, 5}, {1, 2, 3})

    def test_summary_subtracts_native_exclusions(self) -> None:
        summary = summarize(
            [1, 2, 3, 10, 11, 12],
            {1: False, 2: False, 3: False, 10: True, 11: False, 12: True},
            True,
            {1, 2, 3},
        )

        self.assertEqual(summary["discoverablePlayerIds"], [10, 12])
        self.assertEqual(summary["discoverableCount"], 2)
        self.assertTrue(summary["allOwnFirstTeamExcluded"])
        self.assertEqual(summary["excludedNotOwnFirstTeam"], [11])

    def test_summary_flags_own_player_that_was_not_excluded(self) -> None:
        summary = summarize([1, 2, 10], {1: False, 2: True, 10: True}, True, {1, 2})

        self.assertFalse(summary["allOwnFirstTeamExcluded"])

    def test_incomplete_batch_publishes_no_ids(self) -> None:
        summary = summarize([1, 2, 3, 10], {1: False}, False, {1, 2, 3})

        self.assertIsNone(summary["discoverablePlayerIds"])
        self.assertIsNone(summary["discoverableCount"])


if __name__ == "__main__":
    unittest.main()
