import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from fm_analytics.api import BridgeClient


GAME = {
    "gameDate": "2020-08-14",
    "humanManager": {"id": "m1", "name": "Manager"},
    "controlledClub": {"id": "c1", "name": "Club"},
}
SQUAD = {
    "club": {"id": "c1", "name": "Club"},
    "asOfDate": "2020-08-14",
    "players": [
        {
            "id": "p1",
            "name": "Player",
            "age": 22,
            "positions": ["MC"],
            "clubId": "c1",
            "dateOfBirth": "1998-04-03",
            "conditionPercent": 97,
            "matchFitnessPercent": 84,
            "availability": "available",
            "injured": False,
            "suspended": False,
            "contract": {
                "contractType": "full_time",
                "startDate": "2019-07-01",
                "endDate": "2022-06-30",
                "joinedDate": "2019-07-01",
                "squadStatus": "first_team_regular",
                "transferStatus": "not_set",
                "contractedClub": {"id": "c1", "name": "Club"},
            },
            "attributes": {
                "passing": {"visibility": "known", "value": 14}
            },
        }
    ],
}


class BridgeClientTests(unittest.TestCase):
    def test_decodes_game_and_squad(self) -> None:
        responses = [
            BytesIO(json.dumps(GAME).encode()),
            BytesIO(json.dumps(SQUAD).encode()),
        ]
        client = BridgeClient("http://bridge.test")

        with patch("fm_analytics.api.client.urlopen", side_effect=responses) as request:
            game = client.get_game()
            squad = client.get_squad()

        self.assertEqual(game.controlled_club.name, "Club")
        self.assertEqual(squad.players[0].name, "Player")
        self.assertEqual(squad.players[0].condition_percent, 97)
        self.assertEqual(squad.players[0].contract.end_date.isoformat(), "2022-06-30")
        self.assertEqual(squad.players[0].attributes["passing"].value, 14)
        self.assertEqual(request.call_count, 2)

    def test_reads_unavailable_health_document(self) -> None:
        body = BytesIO(
            json.dumps(
                {
                    "status": "save_not_loaded",
                    "source": "linux-proton",
                    "detail": "No save is loaded.",
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
        client = BridgeClient("http://bridge.test")

        with patch("fm_analytics.api.client.urlopen", side_effect=error):
            health = client.get_health()

        self.assertFalse(health.is_ready)
        self.assertEqual(health.status, "save_not_loaded")


if __name__ == "__main__":
    unittest.main()
