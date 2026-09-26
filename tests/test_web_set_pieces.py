import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "src/fm_analytics/fixtures/sample-game.json"


def _complete_fixture(directory: Path) -> Path:
    game, squad = load_fixture(FIXTURE)
    original = squad.players[0]
    required = required_role_attributes()
    players = tuple(
        replace(
            original,
            id=f"player-{index}",
            name=f"Player {index}",
            positions=(slot.position,),
            attributes={
                name: AttributeObservation(Visibility.KNOWN, value=10)
                for name in required
            },
        )
        for index, slot in enumerate(
            MVP_CATALOGUE.tactics["balanced_442"].slots, start=1
        )
    )
    path = directory / "complete.json"
    path.write_text(
        json.dumps({"game": game.to_dict(), "squad": replace(squad, players=players).to_dict()}),
        encoding="utf-8",
    )
    return path


class SetPiecePageTests(unittest.TestCase):
    def _serve(self, fixture_path: Path) -> int:
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(fixture_path),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server.server_address[1]

    def _get(self, port: int, path: str) -> tuple[int, str]:
        connection = HTTPConnection("127.0.0.1", port)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, body

    def test_partial_data_builds_a_squad_wide_plan(self) -> None:
        status, body = self._get(self._serve(FIXTURE), "/set-pieces")

        self.assertEqual(status, 200)
        self.assertIn("Left-side Corners (prefer Right foot)", body)
        self.assertIn("Free Kick Taking is not captured", body)
        self.assertIn("Long throws", body)
        self.assertIn("Attacking corners", body)
        self.assertIn("Attacking wide free kicks", body)
        self.assertIn("Defensive routines", body)
        self.assertIn("Squad-wide template", body)

    def test_complete_data_uses_the_selected_match_xi_and_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            port = self._serve(_complete_fixture(Path(directory)))
            status, body = self._get(
                port,
                "/set-pieces?tactic=balanced_442&delivery=outswinging&risk=secure",
            )

        self.assertEqual(status, 200)
        self.assertIn("Balanced 4-4-2 match XI", body)
        self.assertIn("Optimized against the selected tactic&#x27;s exact XI", body)
        self.assertIn("Secure template", body)
        self.assertIn("3 held back", body)
        self.assertIn("Attack near post", body)
        self.assertIn("Stay back", body)


if __name__ == "__main__":
    unittest.main()
