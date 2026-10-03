import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fm_analytics.analytics import OpponentProfile
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes
from fm_analytics.persistence import SnapshotStore
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer, _build_provider, build_parser
from tests.web_support import FIXTURE, WebServerHelpers, write_complete_fixture


class SquadWebServerTests(WebServerHelpers, unittest.TestCase):
    def test_every_page_renders_for_a_complete_squad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            for path in ("/", "/squad", "/roles", "/tactics", "/tactic-checks", "/set-pieces", "/depth", "/scouting", "/data"):
                with self.subTest(path=path):
                    status, body = self._get(port, path)
                    self.assertEqual(status, 200)
                    self.assertIn("<html>", body)

    def test_squad_page_names_a_best_eligible_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/squad")

            self.assertEqual(status, 200)
            self.assertIn("Goalkeeper", body)

    def test_squad_can_compare_every_player_captured_for_a_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/squad?position=DR")

            self.assertEqual(status, 200)
            self.assertIn("DR comparison", body)
            self.assertIn("Best role at this position", body)
            self.assertIn("players are captured as eligible for DR", body)
            self.assertIn("In-position estimate", body)
            self.assertIn("Today’s score", body)
            self.assertIn("Player 5", body)

    def test_squad_position_comparison_can_pin_a_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/squad?position=DR&role=fb_support")

            self.assertEqual(status, 200)
            self.assertIn("Role: Full-Back (Support)", body)

    def test_squad_player_links_to_a_full_player_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            _status, squad = self._get(port, "/squad")
            status, report = self._get(port, "/squad/player/player-1")

            self.assertIn("href='/squad/player/player-1'", squad)
            self.assertIn("Attribute-based role score", squad)
            self.assertIn("In-position role score (best role)", squad)
            self.assertIn("Today’s selection score (best role)", squad)
            self.assertIn("unknown (assumed 10/20)", squad)
            self.assertEqual(status, 200)
            self.assertIn("Current attributes", report)
            self.assertIn("Position score summary", report)
            self.assertIn("Position familiarity", report)
            self.assertIn("All attribute-based role scores by position", report)
            self.assertIn("Best-role scores", report)
            self.assertIn("Today’s selection score (best role)", report)
            self.assertIn("<table class='sortable'>", squad)
            self.assertIn("data-sort='", squad)
            # The player page's three scores are the roster row's three scores.
            roster_row = squad.split("href='/squad/player/player-1'")[1].split("</tr>")[0]
            headline = report.split("Best-role scores")[1].split("</table>")[0]
            for cell in roster_row.split("<td")[-3:]:
                self.assertIn(cell.replace("</td>", ""), headline)

    def test_scored_pages_use_consistent_score_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            _status, roles = self._get(port, "/roles")
            _status, tactics = self._get(port, "/tactics")
            _status, tactic = self._get(port, "/tactics/balanced_442")
            _status, set_pieces = self._get(port, "/set-pieces")

            self.assertIn("Attribute-based role score", roles)
            self.assertIn("in-position familiarity", tactic)
            self.assertIn("selection score", tactic)
            self.assertIn("Play-now tactic score", tactics)
            self.assertIn("Set-piece attribute score", set_pieces)

    def test_other_squads_show_scores_and_link_to_position_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
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
            self.assertIn("href='/squad/player/youth-1'", body)
            other_table = body.split("id='other-club-squads'", 1)[1]
            self.assertIn("<th>In-position</th>", other_table)
            self.assertIn("data-sort='", other_table)
            # Identical captured players must receive identical best-role scores
            # irrespective of the squad they belong to.
            first_row = body.split("href='/squad/player/player-1'", 1)[1].split("</tr>", 1)[0]
            other_row = body.split("href='/squad/player/youth-1'", 1)[1].split("</tr>", 1)[0]
            self.assertEqual(first_row.split("<td")[-3:], other_row.split("<td")[-3:])
            status, report = self._get(port, '/squad/player/youth-1')
            self.assertEqual(status, 200)
            self.assertIn('Position score summary', report)
            self.assertIn('In-position estimate', report)
            self.assertIn('FM team marker 9', report)
            self.assertIn("href='/squad#other-club-squads'", report)

    def test_position_comparison_can_select_another_squad_or_the_whole_club(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            document = json.loads(fixture_path.read_text(encoding='utf-8'))
            document['squad']['players'][0]['positionFamiliarity'] = {'GK': 10}
            document['squad']['otherTeams'] = [{
                'marker': 9,
                'players': [{**document['squad']['players'][0], 'id': 'youth-1', 'name': 'Yusuf Youth', 'positionFamiliarity': {'GK': 20}}],
            }]
            fixture_path.write_text(json.dumps(document), encoding='utf-8')
            port = self._serve(fixture_path)
            for scope, first, other in [('first', True, False), ('9', False, True), ('all', True, True)]:
                with self.subTest(scope=scope):
                    status, body = self._get(port, '/squad?position=GK&role=gk_defend&team=' + scope)
                    self.assertEqual(status, 200)
                    comparison = body.split('<h2>GK comparison</h2>', 1)[1].split('</table>', 1)[0]
                    self.assertEqual("href='/squad/player/player-1'" in comparison, first)
                    self.assertEqual('Yusuf Youth' in comparison, other)
                    self.assertIn(f"value='{scope}' selected", body)
                    if scope == 'all':
                        self.assertLess(comparison.index('Yusuf Youth'), comparison.index("href='/squad/player/player-1'"))
                        self.assertIn('<th>Squad</th>', comparison)
                        self.assertIn('47.4', comparison)
            # Displaying or comparing these players must not put them in the XI.
            status, tactic = self._get(port, '/tactics/balanced_442')
            self.assertEqual(status, 200)
            self.assertNotIn('Yusuf Youth', tactic)

    def test_other_squad_estimates_tolerate_missing_data_and_empty_squads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            document = json.loads(fixture_path.read_text(encoding='utf-8'))
            document['squad']['otherTeams'] = [
                {'marker': 9, 'players': [{
                    **document['squad']['players'][0], 'id': 'unobserved', 'name': '<Unknown> Player',
                    'attributes': {}, 'positionFamiliarity': {}, 'conditionPercent': None, 'matchFitnessPercent': None,
                }]},
                {'marker': 10, 'players': []},
            ]
            fixture_path.write_text(json.dumps(document), encoding='utf-8')
            port = self._serve(fixture_path)
            for path in ['/squad', '/squad?position=GK&team=9', '/squad?position=GK&team=10', '/squad/player/unobserved']:
                with self.subTest(path=path):
                    status, body = self._get(port, path)
                    self.assertEqual(status, 200)
                    self.assertNotIn('<Unknown>', body)
                    if path == '/squad':
                        self.assertIn('0.0 (0.0–100.0)', body)
                        self.assertIn('Familiarity unknown', body)
            status, body = self._get(port, '/squad/player/not-at-this-club')
            self.assertEqual(status, 404)
            self.assertIn('not in the current club squads', body)

    def test_data_page_reports_other_team_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
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
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/tactics")

            self.assertEqual(status, 200)
            self.assertIn("Balanced 4-4-2", body)

    def test_tactic_detail_has_a_matchday_bench_and_complete_coverage_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/tactics/balanced_442")

            self.assertEqual(status, 200)
            self.assertIn("Matchday bench", body)
            self.assertIn("Substitution coverage", body)
            coverage = body.split("Substitution coverage", 1)[1].split("</details>", 1)[0]
            self.assertEqual(coverage.count("coverage-card"), 11)

    def test_matchday_bench_is_numbered_with_reserve_goalkeeper_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            game, squad = load_fixture(fixture_path)
            backup = replace(
                squad.players[0],
                id="backup-goalkeeper",
                name="Backup Goalkeeper",
                attributes={
                    name: AttributeObservation(Visibility.KNOWN, value=9)
                    for name in required_role_attributes()
                },
            )
            document = {
                "game": game.to_dict(),
                "squad": replace(squad, players=squad.players + (backup,)).to_dict(),
            }
            fixture_path.write_text(json.dumps(document), encoding="utf-8")
            port = self._serve(fixture_path)
            status, body = self._get(port, "/tactics/balanced_442")
            self.assertEqual(status, 200)
            self.assertIn("The whole bench is planned together", body)
            self.assertIn("<th>Priority</th>", body)
            self.assertIn("<td><b>1</b></td>", body)
            self.assertIn("Backup Goalkeeper", body)
            self.assertIn("Reserve goalkeeper", body)
            self.assertIn("credible cover (at least 80% of the starter's score)", body)
            self.assertIn("<th>Credible cover</th><th>Can fill</th>", body)
            self.assertNotIn("No eligible reserve goalkeeper", body)

    def test_unknown_tactic_detail_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/tactics/not-a-tactic")

            self.assertEqual(status, 404)
            self.assertIn("not in the current catalogue", body)

    def test_unknown_path_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
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


class CachingTests(unittest.TestCase):
    def test_repeated_reads_reuse_the_captured_snapshot(self) -> None:
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

    def test_read_is_not_recomputed_when_the_legacy_ttl_elapses(self) -> None:
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

        # A tactic recommendation is an immutable observation. The interval is
        # now reserved for background health checks; only an explicit squad
        # refresh may capture a new game/squad snapshot.
        self.assertEqual(calls["count"], 1)

    def test_a_provider_error_is_retried_on_the_next_read(self) -> None:
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

        # There is no good snapshot to preserve after a first-read failure, so
        # keep trying rather than trapping the UI behind a timed error cache.
        self.assertEqual(calls["count"], 2)

    def test_recommendation_cache_is_keyed_by_opponent_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = write_complete_fixture(Path(directory))
            server = SquadWebServer(("127.0.0.1", 0), fixture_provider(fixture_path))
            self.addCleanup(server.server_close)
            neutral_result, aerial_result = object(), object()
            profiles = []

            def build(_game, _squad, *, policy, ranking_executor):
                profiles.append(policy.opponent)
                return neutral_result if policy.opponent.is_neutral else aerial_result

            with patch(
                "fm_analytics.web.server.build_recommendation_bundle",
                side_effect=build,
            ):
                neutral = server.bundle()
                aerial = server.bundle(OpponentProfile(aerial_threat=2))
                neutral_again = server.bundle()

            self.assertIs(neutral, neutral_result)
            self.assertIs(aerial, aerial_result)
            self.assertIs(neutral_again, neutral_result)
            self.assertEqual(
                profiles,
                [OpponentProfile.neutral(), OpponentProfile(aerial_threat=2)],
            )


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

    def test_an_unreadable_snapshot_db_is_refused_at_startup_not_first_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "old.sqlite3"
            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.execute("CREATE TABLE captures (id INTEGER PRIMARY KEY)")
                connection.execute("PRAGMA user_version = 2")

            args = build_parser().parse_args(["--snapshot-db", str(db_path)])
            with self.assertRaisesRegex(SystemExit, "re-run the capture"):
                _build_provider(args)

    def test_source_flags_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--fixture", "a.json", "--direct-live"])


if __name__ == "__main__":
    unittest.main()
