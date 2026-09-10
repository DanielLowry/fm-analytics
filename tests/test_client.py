import json
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from fm_analytics.api import BridgeClient, BridgeContractError, BridgeError


ROOT = Path(__file__).resolve().parent.parent
GOLDEN = json.loads(
    (ROOT / "src/fm_analytics/fixtures/sample-game.json").read_text(encoding="utf-8")
)
GAME = GOLDEN["game"]
SQUAD = GOLDEN["squad"]


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

        self.assertEqual(game.controlled_club.name, "North London FC")
        self.assertEqual(squad.players[0].name, "Sam Keeper")
        self.assertEqual(squad.players[0].condition_percent, 96)
        self.assertEqual(squad.players[0].contract.end_date.isoformat(), "2022-06-30")
        self.assertEqual(squad.players[1].attributes["passing"].minimum, 11)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[0], "http://bridge.test/v1/game")
        self.assertEqual(request.call_args_list[1].args[0], "http://bridge.test/v1/squad")

    def test_reads_unavailable_health_document(self) -> None:
        body = BytesIO(json.dumps(GOLDEN["errors"]["healthUnavailable"]).encode())
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

    def test_reports_missing_required_game_field_with_resource_context(self) -> None:
        client = BridgeClient("http://bridge.test")

        with patch(
            "fm_analytics.api.client.urlopen",
            return_value=BytesIO(
                json.dumps(GOLDEN["breakingExamples"]["gameDateRenamed"]).encode()
            ),
        ):
            with self.assertRaisesRegex(
                BridgeContractError,
                "invalid v1 game response: missing required field 'gameDate'",
            ):
                client.get_game()

    def test_reports_invalid_nested_squad_observation_with_context(self) -> None:
        invalid_squad = deepcopy(SQUAD)
        invalid_squad["players"][1]["attributes"]["passing"] = {
            "visibility": "range",
            "minimum": 15,
            "maximum": 10,
        }
        client = BridgeClient("http://bridge.test")

        with patch(
            "fm_analytics.api.client.urlopen",
            return_value=BytesIO(json.dumps(invalid_squad).encode()),
        ):
            with self.assertRaisesRegex(
                BridgeContractError,
                "invalid v1 squad response: attribute minimum cannot exceed maximum",
            ):
                client.get_squad()

    def test_accepts_nullable_fields_and_open_availability_value(self) -> None:
        squad_payload = deepcopy(SQUAD)
        player = squad_payload["players"][0]
        for name in (
            "dateOfBirth",
            "age",
            "conditionPercent",
            "matchFitnessPercent",
            "injured",
            "suspended",
            "contract",
        ):
            player[name] = None
        player["availability"] = "future_visible_status"
        client = BridgeClient("http://bridge.test")

        with patch(
            "fm_analytics.api.client.urlopen",
            return_value=BytesIO(json.dumps(squad_payload).encode()),
        ):
            squad = client.get_squad()

        self.assertIsNone(squad.players[0].condition_percent)
        self.assertEqual(squad.players[0].availability, "future_visible_status")

    def test_rejects_unknown_closed_visibility_value(self) -> None:
        squad_payload = deepcopy(SQUAD)
        squad_payload["players"][0]["attributes"]["reflexes"] = {
            "visibility": "estimated",
            "value": 16,
        }
        client = BridgeClient("http://bridge.test")

        with patch(
            "fm_analytics.api.client.urlopen",
            return_value=BytesIO(json.dumps(squad_payload).encode()),
        ):
            with self.assertRaisesRegex(
                BridgeContractError,
                "invalid v1 squad response: 'estimated' is not a valid Visibility",
            ):
                client.get_squad()

    def test_surfaces_unsupported_contract_version(self) -> None:
        body = BytesIO(
            json.dumps(GOLDEN["errors"]["unsupportedContractVersion"]).encode()
        )
        error = HTTPError(
            "http://bridge.test/v2/game",
            404,
            "Not Found",
            {},
            body,
        )
        client = BridgeClient("http://bridge.test")

        with patch("fm_analytics.api.client.urlopen", side_effect=error):
            with self.assertRaisesRegex(
                BridgeError,
                "unsupported_contract_version",
            ):
                client.get_game()


if __name__ == "__main__":
    unittest.main()
