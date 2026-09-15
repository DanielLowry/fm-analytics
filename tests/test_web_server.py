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
from fm_analytics.persistence import SnapshotStore
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer, _build_provider, build_parser


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "src/fm_analytics/fixtures/sample-game.json"


def _write_complete_fixture(directory: Path) -> Path:
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
                name: AttributeObservation(Visibility.KNOWN, value=10) for name in required
            },
        )
        for index, slot in enumerate(MVP_CATALOGUE.tactics["balanced_442"].slots, start=1)
    )
    complete_squad = replace(squad, players=players)
    path = directory / "complete.json"
    path.write_text(
        json.dumps({"game": game.to_dict(), "squad": complete_squad.to_dict()}),
        encoding="utf-8",
    )
    return path


class SquadWebServerTests(unittest.TestCase):
    def _serve(self, fixture_path: Path):
        server = SquadWebServer(("127.0.0.1", 0), fixture_provider(fixture_path))
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

    def test_every_page_renders_for_a_complete_squad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            for path in ("/", "/squad", "/roles", "/tactics", "/depth", "/data"):
                with self.subTest(path=path):
                    status, body = self._get(port, path)
                    self.assertEqual(status, 200)
                    self.assertIn("<html>", body)

    def test_squad_page_names_a_best_eligible_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/squad")

            self.assertEqual(status, 200)
            self.assertIn("Goalkeeper", body)

    def test_tactics_page_names_the_selected_tactic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/tactics")

            self.assertEqual(status, 200)
            self.assertIn("Balanced 4-4-2", body)

    def test_unknown_path_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, _body = self._get(port, "/nonexistent")

            self.assertEqual(status, 404)

    def test_incomplete_squad_fails_closed_on_scored_pages_but_not_on_data(self) -> None:
        port = self._serve(FIXTURE)

        for path in ("/squad", "/roles", "/tactics", "/depth"):
            with self.subTest(path=path):
                status, body = self._get(port, path)
                self.assertEqual(status, 503)
                self.assertIn("error", body.lower())

        status, body = self._get(port, "/data")
        self.assertEqual(status, 200)
        self.assertIn("Attribute coverage", body)

        status, body = self._get(port, "/")
        self.assertEqual(status, 200)
        self.assertIn("incomplete", body.lower())


class BuildProviderTests(unittest.TestCase):
    def test_defaults_to_the_bundled_fixture(self) -> None:
        args = build_parser().parse_args([])

        provider = _build_provider(args)
        game, squad = provider()

        self.assertEqual(len(squad.players), 3)
        self.assertEqual(game.game_date.isoformat(), "2020-08-14")

    def test_serves_a_snapshot_db_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "snap.sqlite3"
            game, squad = load_fixture(FIXTURE)
            SnapshotStore(db_path).capture(game, squad, source="fixture")

            args = build_parser().parse_args(["--snapshot-db", str(db_path)])
            provider = _build_provider(args)
            loaded_game, loaded_squad = provider()

            self.assertEqual(loaded_game.game_date, game.game_date)
            self.assertEqual(len(loaded_squad.players), len(squad.players))

    def test_capture_id_without_snapshot_db_is_rejected(self) -> None:
        args = build_parser().parse_args(["--capture-id", "1"])

        with self.assertRaises(SystemExit):
            _build_provider(args)

    def test_source_flags_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--fixture", "a.json", "--direct-live"])


if __name__ == "__main__":
    unittest.main()
