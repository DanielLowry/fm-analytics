import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from fm_analytics.bridge import (
    BridgeServer,
    BridgeSourceError,
    FixtureDataSource,
    LinuxProtonDataSource,
)


ROOT = Path(__file__).resolve().parent.parent


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

    def request(self, path: str) -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", path)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_health_game_and_squad_endpoints(self) -> None:
        health_status, health = self.request("/health")
        game_status, game = self.request("/game")
        squad_status, squad = self.request("/squad")

        self.assertEqual((health_status, game_status, squad_status), (200, 200, 200))
        self.assertEqual(health["status"], "ready")
        self.assertEqual(game["gameDate"], "2020-08-14")
        self.assertEqual(squad["players"][1]["attributes"]["passing"]["visibility"], "range")

    def test_unknown_endpoint_returns_not_found(self) -> None:
        status, payload = self.request("/unknown")

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not found")


if __name__ == "__main__":
    unittest.main()
