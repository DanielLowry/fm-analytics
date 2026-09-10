import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from fm_analytics.bridge import (
    BridgeServer,
    BridgeSourceError,
    FixtureDataSource,
    LinuxProtonDataSource,
)


ROOT = Path(__file__).resolve().parent.parent
GOLDEN = json.loads(
    (ROOT / "src/fm_analytics/fixtures/sample-game.json").read_text(encoding="utf-8")
)


class BridgeSourceTests(unittest.TestCase):
    def test_fixture_source_maps_the_python_domain_contract(self) -> None:
        source = FixtureDataSource(ROOT / "src/fm_analytics/fixtures/sample-game.json")

        self.assertEqual(source.get_health().to_dict(), {
            "status": "ready", "source": "fixture", "detail": None
        })
        self.assertEqual(source.get_game().controlled_club.name, "North London FC")
        self.assertEqual(len(source.get_squad().players), 3)

    def test_linux_source_reports_missing_probe_as_misconfigured(self) -> None:
        source = LinuxProtonDataSource("/does/not/exist")

        health = source.get_health()

        self.assertEqual(health.status, "misconfigured")
        self.assertIn("probe was not found", health.detail)

    def test_linux_source_classifies_probe_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(
                "import sys; print('error: no running FM20 process was found', file=sys.stderr); sys.exit(1)",
                encoding="utf-8",
            )
            source = LinuxProtonDataSource(probe, timeout_seconds=1)

            with self.assertRaises(BridgeSourceError) as context:
                source.get_game()

        self.assertEqual(context.exception.status, "game_absent")
        self.assertEqual(str(context.exception), "no running FM20 process was found")

    def test_linux_source_refreshes_after_cache_expiry(self) -> None:
        source = LinuxProtonDataSource(__file__)
        before = self.probe_document("2019-06-24", ("player-1",))
        after = self.probe_document("2019-06-25", ("player-1", "player-2"))

        with (
            patch.object(source, "_run_probe", side_effect=[before, after]) as run,
            patch(
                "fm_analytics.bridge.linux_proton.time.monotonic",
                side_effect=[10.0, 10.0, 10.5, 11.1, 11.1],
            ),
        ):
            first_game = source.get_game()
            cached_squad = source.get_squad()
            refreshed_squad = source.get_squad()

        self.assertEqual(first_game.game_date.isoformat(), "2019-06-24")
        self.assertEqual(len(cached_squad.players), 1)
        self.assertEqual(refreshed_squad.as_of_date.isoformat(), "2019-06-25")
        self.assertEqual(len(refreshed_squad.players), 2)
        self.assertEqual(run.call_count, 2)

    def test_linux_source_does_not_cache_failure(self) -> None:
        source = LinuxProtonDataSource(__file__)
        recovered = self.probe_document("2019-06-24", ("player-1",))

        with (
            patch.object(
                source,
                "_run_probe",
                side_effect=[
                    BridgeSourceError("game_absent", "FM20 is not running."),
                    recovered,
                ],
            ) as run,
            patch(
                "fm_analytics.bridge.linux_proton.time.monotonic",
                side_effect=[10.0, 10.1, 10.1],
            ),
        ):
            health = source.get_health()
            game = source.get_game()

        self.assertEqual(health.status, "game_absent")
        self.assertEqual(game.game_date.isoformat(), "2019-06-24")
        self.assertEqual(run.call_count, 2)

    @staticmethod
    def probe_document(game_date: str, player_ids: tuple[str, ...]) -> dict:
        return {
            "game_date": game_date,
            "human_managers": [
                {
                    "id": "manager-1",
                    "name": "Manager",
                    "active": True,
                    "club": {"id": "club-1", "name": "Club"},
                }
            ],
            "first_team_squad": [
                {
                    "id": player_id,
                    "name": f"Player {player_id}",
                    "positions": ["MC"],
                    "condition_percent": 95,
                    "match_fitness_percent": 90,
                    "availability": "available",
                    "injured": False,
                    "suspended": False,
                }
                for player_id in player_ids
            ],
        }


class BridgeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = BridgeServer(("127.0.0.1", 0), FixtureDataSource())
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path: str) -> tuple[int, dict, dict[str, str]]:
        connection = HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", path)
        response = connection.getresponse()
        payload = json.loads(response.read())
        headers = dict(response.getheaders())
        connection.close()
        return response.status, payload, headers

    def test_versioned_health_game_and_squad_match_golden_contract(self) -> None:
        health_status, health, health_headers = self.request("/v1/health")
        game_status, game, _ = self.request("/v1/game")
        squad_status, squad, _ = self.request("/v1/squad")

        self.assertEqual((health_status, game_status, squad_status), (200, 200, 200))
        self.assertEqual(health, GOLDEN["health"])
        self.assertEqual(game, GOLDEN["game"])
        self.assertEqual(squad, GOLDEN["squad"])
        self.assertEqual(health_headers["X-FM-Analytics-Contract-Version"], "1")

    def test_unknown_endpoint_returns_not_found(self) -> None:
        status, payload, _ = self.request("/v1/unknown")

        self.assertEqual(status, 404)
        self.assertEqual(payload, GOLDEN["errors"]["notFound"])

    def test_unsupported_contract_version_is_explicit(self) -> None:
        status, payload, headers = self.request("/v2/game")

        self.assertEqual(status, 404)
        self.assertEqual(payload, GOLDEN["errors"]["unsupportedContractVersion"])
        self.assertEqual(headers["X-FM-Analytics-Contract-Version"], "1")

    def test_phase00_unversioned_alias_remains_available(self) -> None:
        status, payload, _ = self.request("/game")

        self.assertEqual(status, 200)
        self.assertEqual(payload, GOLDEN["game"])


if __name__ == "__main__":
    unittest.main()
