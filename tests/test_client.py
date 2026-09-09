import json
import unittest
from io import BytesIO
from unittest.mock import patch

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
        self.assertEqual(squad.players[0].attributes["passing"].value, 14)
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
