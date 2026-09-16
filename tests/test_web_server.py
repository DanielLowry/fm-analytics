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
from fm_analytics.analytics import ScoutingCandidate
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
    def _serve(self, fixture_path: Path, scouting_provider=None):
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(fixture_path),
            scouting_provider=scouting_provider,
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

    def test_every_page_renders_for_a_complete_squad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            for path in ("/", "/squad", "/roles", "/tactics", "/depth", "/scouting", "/data"):
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

    def test_squad_page_lists_other_teams_without_scoring_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            document = json.loads(fixture_path.read_text(encoding="utf-8"))
            document["squad"]["otherTeams"] = [{
                "marker": 9,
                "players": [{
                    **document["squad"]["players"][0],
                    "id": "youth-1",
                    "name": "Yusuf Youth",
                }],
            }]
            fixture_path.write_text(json.dumps(document), encoding="utf-8")
            port = self._serve(fixture_path)

            status, body = self._get(port, "/squad")

            self.assertEqual(status, 200)
            self.assertIn("Yusuf Youth", body)
            self.assertIn("team marker 9", body)
            self.assertIn("not included in role or tactic selection", body)

    def test_data_page_reports_other_team_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            document = json.loads(fixture_path.read_text(encoding="utf-8"))
            document["squad"]["otherTeams"] = [{
                "marker": 9,
                "players": [{
                    **document["squad"]["players"][0],
                    "id": "youth-1",
                    "name": "Yusuf Youth",
                }],
            }]
            fixture_path.write_text(json.dumps(document), encoding="utf-8")
            port = self._serve(fixture_path)

            status, body = self._get(port, "/data")

            self.assertEqual(status, 200)
            self.assertIn("Other club squads: 1 player(s) across 1 team(s)", body)

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

    def test_scouting_page_makes_unknown_profiles_a_reason_to_scout(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Unknown Striker", positions=("ST",),
                    attributes={}, age=19, club="Example FC", footedness="Right",
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting?role=af_attack&position=ST")

        self.assertEqual(status, 200)
        self.assertIn("Unknown Striker", body)
        self.assertIn("Scout first", body)
        self.assertIn("floor / estimate / ceiling", body)

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


class TacticsAndDepthPageTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.fixture_path = _write_complete_fixture(Path(directory.name))
        server = SquadWebServer(("127.0.0.1", 0), fixture_provider(self.fixture_path))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.port = server.server_address[1]

    def _get(self, path: str) -> tuple[int, str]:
        connection = HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, body

    def test_tactics_page_shows_the_fit_legend_and_injury_risk_column(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        self.assertIn("Injury risk", body)
        self.assertIn("65%", body)
        self.assertIn("<ul class='legend'>", body)
        # Owned players' attributes are exact, so scores collapse to one number.
        self.assertNotIn(" / ", body.split("Tactic comparison")[1].split("</table>")[0])

    def test_tactics_page_lists_roles_for_every_tactic_not_just_the_selected_one(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        # There are twelve tactics in the current catalogue; each gets its
        # own collapsible role/fill breakdown, not just the winner's.
        self.assertGreaterEqual(body.count("<details>"), 12)

    def test_depth_page_leads_with_conclusions_and_a_compact_table(self) -> None:
        status, body = self._get("/depth")

        self.assertEqual(status, 200)
        self.assertIn("Conclusions", body)
        self.assertIn("By position", body)
        # No per-weakness sentence dump: reasons are short kind codes.
        self.assertNotIn("is below the starter role-fit threshold", body)


class CachingTests(unittest.TestCase):
    def test_repeated_reads_within_the_ttl_do_not_call_the_provider_again(self) -> None:
        calls = {"count": 0}

        def provider():
            calls["count"] += 1
            return load_fixture(FIXTURE)

        server = SquadWebServer(("127.0.0.1", 0), provider, cache_ttl_seconds=60)
        self.addCleanup(server.server_close)

        server.read()
        server.read()
        server.read()

        self.assertEqual(calls["count"], 1)

    def test_read_is_recomputed_once_the_ttl_elapses(self) -> None:
        calls = {"count": 0}

        def provider():
            calls["count"] += 1
            return load_fixture(FIXTURE)

        server = SquadWebServer(("127.0.0.1", 0), provider, cache_ttl_seconds=0.05)
        self.addCleanup(server.server_close)

        server.read()
        import time

        time.sleep(0.1)
        server.read()

        self.assertEqual(calls["count"], 2)

    def test_a_provider_error_is_also_cached_within_the_ttl(self) -> None:
        calls = {"count": 0}

        def provider():
            calls["count"] += 1
            raise ValueError("boom")

        server = SquadWebServer(("127.0.0.1", 0), provider, cache_ttl_seconds=60)
        self.addCleanup(server.server_close)

        with self.assertRaises(ValueError):
            server.read()
        with self.assertRaises(ValueError):
            server.read()

        self.assertEqual(calls["count"], 1)


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
