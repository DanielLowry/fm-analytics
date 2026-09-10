import unittest

from tools.phase00_validate import compare


class Phase00ValidationTests(unittest.TestCase):
    def test_accepts_stable_identity_and_expected_changes(self) -> None:
        before = {
            "gameDate": "2019-06-24",
            "managerId": "1",
            "clubId": "2",
            "playerIds": ["3", "4"],
        }
        after = {
            "gameDate": "2019-06-25",
            "managerId": "1",
            "clubId": "2",
            "playerIds": ["3", "5"],
        }

        failures = compare(
            before,
            after,
            expect_date_change=True,
            expect_squad_change=True,
        )

        self.assertEqual(failures, [])

    def test_reports_missing_expected_changes(self) -> None:
        observation = {
            "gameDate": "2019-06-24",
            "managerId": "1",
            "clubId": "2",
            "playerIds": ["3"],
        }

        failures = compare(
            observation,
            observation,
            expect_date_change=True,
            expect_squad_change=True,
        )

        self.assertEqual(
            failures,
            ["gameDate did not change", "first-team membership did not change"],
        )


if __name__ == "__main__":
    unittest.main()
