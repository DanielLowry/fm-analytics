import unittest
import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from tools.phase00_validate import ValidationError, capture, compare


class Phase00ValidationTests(unittest.TestCase):
    def test_capture_reports_structured_unavailable_detail(self) -> None:
        body = BytesIO(
            json.dumps(
                {
                    "status": "game_absent",
                    "source": "linux-proton",
                    "detail": "no running FM20 process was found",
                }
            ).encode()
        )
        error = HTTPError(
            "http://bridge.test/health",
            503,
            "Service Unavailable",
            {},
            body,
        )

        with patch("tools.phase00_validate.urlopen", side_effect=error):
            with self.assertRaisesRegex(
                ValidationError,
                "no running FM20 process was found",
            ):
                capture("http://bridge.test")

    def test_capture_uses_versioned_resources(self) -> None:
        responses = [
            BytesIO(
                json.dumps(
                    {"status": "ready", "source": "fixture", "detail": None}
                ).encode()
            ),
            BytesIO(
                json.dumps(
                    {
                        "gameDate": "2019-06-24",
                        "humanManager": {"id": "1", "name": "Manager"},
                        "controlledClub": {"id": "2", "name": "Club"},
                    }
                ).encode()
            ),
            BytesIO(
                json.dumps(
                    {
                        "club": {"id": "2", "name": "Club"},
                        "asOfDate": "2019-06-24",
                        "players": [],
                    }
                ).encode()
            ),
        ]

        with patch("tools.phase00_validate.urlopen", side_effect=responses) as request:
            observation = capture("http://bridge.test")

        self.assertEqual(observation["playerCount"], 0)
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            [
                "http://bridge.test/v1/health",
                "http://bridge.test/v1/game",
                "http://bridge.test/v1/squad",
            ],
        )

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

    def test_accepts_expected_stability(self) -> None:
        observation = {
            "gameDate": "2019-06-24",
            "managerId": "1",
            "clubId": "2",
            "playerIds": ["3", "4"],
        }

        failures = compare(
            observation,
            observation,
            expect_date_change=False,
            expect_squad_change=False,
            expect_date_stable=True,
            expect_squad_stable=True,
        )

        self.assertEqual(failures, [])

    def test_reports_unexpected_changes(self) -> None:
        before = {
            "gameDate": "2019-06-24",
            "managerId": "1",
            "clubId": "2",
            "playerIds": ["3"],
        }
        after = {**before, "gameDate": "2019-06-25", "playerIds": ["4"]}

        failures = compare(
            before,
            after,
            expect_date_change=False,
            expect_squad_change=False,
            expect_date_stable=True,
            expect_squad_stable=True,
        )

        self.assertEqual(
            failures,
            ["gameDate changed", "first-team membership changed"],
        )


if __name__ == "__main__":
    unittest.main()
