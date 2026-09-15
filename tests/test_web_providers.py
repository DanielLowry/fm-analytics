import tempfile
import unittest
from pathlib import Path

from fm_analytics.api import BridgeError
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.cli import load_fixture
from fm_analytics.persistence import SnapshotStore
from fm_analytics.web.providers import (
    fixture_provider,
    html_overlay_provider,
    live_provider,
    snapshot_provider,
)


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "src/fm_analytics/fixtures/sample-game.json"

SQUAD_HTML = """
<table>
  <tr><th>UID</th><th>Name</th><th>Position</th><th>Pas</th></tr>
  <tr><td>player-1</td><td>Sam Keeper</td><td>GK</td><td>10</td></tr>
  <tr><td>player-2</td><td>Chris Centreback</td><td>D (C), DM</td><td>10</td></tr>
  <tr><td>player-3</td><td>Morgan Midfielder</td><td>M/AM (C)</td><td>10</td></tr>
</table>
"""


class FixtureProviderTests(unittest.TestCase):
    def test_reads_game_and_squad_from_a_json_file(self) -> None:
        provide = fixture_provider(FIXTURE)

        game, squad = provide()

        self.assertEqual(game.game_date.isoformat(), "2020-08-14")
        self.assertEqual(len(squad.players), 3)


class SnapshotProviderTests(unittest.TestCase):
    def test_reads_the_latest_capture_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "snapshot.sqlite3"
            game, squad = load_fixture(FIXTURE)
            capture = SnapshotStore(db_path).capture(game, squad, source="fixture")

            provide = snapshot_provider(db_path)
            loaded_game, loaded_squad = provide()

            self.assertEqual(loaded_game.game_date, game.game_date)
            self.assertEqual(len(loaded_squad.players), len(squad.players))
            self.assertGreaterEqual(capture.id, 1)

    def test_reads_a_specific_capture_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "snapshot.sqlite3"
            game, squad = load_fixture(FIXTURE)
            capture = SnapshotStore(db_path).capture(game, squad, source="fixture")

            provide = snapshot_provider(db_path, capture_id=capture.id)
            loaded_game, _loaded_squad = provide()

            self.assertEqual(loaded_game.game_date, game.game_date)

    def test_raises_when_no_capture_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "empty.sqlite3"
            provide = snapshot_provider(db_path)

            with self.assertRaises(BridgeSourceError):
                provide()


class HtmlOverlayProviderTests(unittest.TestCase):
    def test_overlays_positions_and_attributes_from_html_onto_the_base_squad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            html_path = Path(directory) / "squad.html"
            html_path.write_text(SQUAD_HTML, encoding="utf-8")

            provide = html_overlay_provider(fixture_provider(FIXTURE), (html_path,))
            game, squad = provide()

            self.assertEqual(len(squad.players), 3)
            keeper = next(p for p in squad.players if p.name == "Sam Keeper")
            self.assertIn("passing", keeper.attributes)

    def test_enforces_the_expected_player_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            html_path = Path(directory) / "squad.html"
            html_path.write_text(SQUAD_HTML, encoding="utf-8")

            provide = html_overlay_provider(
                fixture_provider(FIXTURE), (html_path,), expected_players=4
            )

            with self.assertRaises(ValueError):
                provide()


class LiveProviderTests(unittest.TestCase):
    def test_bridge_health_failure_surfaces_as_an_error(self) -> None:
        provide = live_provider(base_url="http://127.0.0.1:1")

        with self.assertRaises((BridgeError, OSError)):
            provide()


if __name__ == "__main__":
    unittest.main()
