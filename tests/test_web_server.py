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
from fm_analytics.web.rendering import ScoutingPoolNotBuilt
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
    def _serve(self, fixture_path: Path, scouting_provider=None, scouting_refresh=None):
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(fixture_path),
            scouting_provider=scouting_provider,
            scouting_refresh=scouting_refresh,
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

    def _post(self, port: int, path: str, body: str = "") -> tuple[int, str | None, str]:
        connection = HTTPConnection("127.0.0.1", port)
        connection.request(
            "POST", path, body,
            {"Content-Type": "application/x-www-form-urlencoded"} if body else {},
        )
        response = connection.getresponse()
        location = response.getheader("Location")
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, location, body

    def test_every_page_renders_for_a_complete_squad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            for path in ("/", "/squad", "/roles", "/tactics", "/set-pieces", "/depth", "/scouting", "/data"):
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

    def test_tactics_page_has_a_matchday_substitution_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/tactics")

            self.assertEqual(status, 200)
            self.assertIn("Matchday substitutions", body)
            self.assertIn("Bring on (best first)", body)

    def test_set_pieces_page_suggests_assignments_and_names_known_limitations(self) -> None:
        # This page only needs its own inputs, so it works before the wider
        # role-scoring extraction is complete.
        port = self._serve(FIXTURE)

        status, body = self._get(port, "/set-pieces")

        self.assertEqual(status, 200)
        self.assertIn("Suggested assignments", body)
        self.assertIn("Left-side Corners (prefer Right foot)", body)
        self.assertIn("Direct free kicks", body)
        self.assertIn("Free Kick Taking is not captured", body)
        self.assertIn("Long throws", body)
        self.assertIn("Outswingers", body)

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

    def test_scouting_page_has_a_name_box_and_a_live_results_container(self) -> None:
        """The as-you-type behaviour depends on this exact id and input name."""
        port = self._serve(FIXTURE)
        status, body = self._get(port, "/scouting")

        self.assertEqual(status, 200)
        self.assertIn("name='name'", body)
        self.assertIn("id='scouting-results'", body)
        self.assertIn("fetch(", body)

    def test_scouting_results_fragment_matches_the_full_page_for_the_same_filters(self) -> None:
        """The live-filter endpoint must compute the same thing the full page does."""
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Ashley Wells", positions=(), raw_positions=("DR",),
                    attributes={}, age=19, club="Example FC", footedness="Right",
                ),
                ScoutingCandidate(
                    id="external-2", name="Someone Else", positions=(), raw_positions=("DR",),
                    attributes={}, age=19, club="Example FC", footedness="Right",
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        full_status, full_body = self._get(
            port, "/scouting?position=DR&includeRawPositions=1&name=Wells"
        )
        fragment_status, fragment_body = self._get(
            port, "/scouting/results?position=DR&includeRawPositions=1&name=Wells"
        )

        self.assertEqual(full_status, 200)
        self.assertEqual(fragment_status, 200)
        self.assertIn("Ashley Wells", full_body)
        self.assertNotIn("Someone Else", full_body)
        self.assertIn("Ashley Wells", fragment_body)
        self.assertNotIn("Someone Else", fragment_body)
        # The fragment is only the results half -- no filter form, no page shell.
        self.assertNotIn("Find a target", fragment_body)
        self.assertNotIn("<!doctype html>", fragment_body)

    def test_scouting_results_fragment_reports_errors_without_the_page_shell(self) -> None:
        def scouting_provider():
            raise OSError("scouting capture is unreadable")

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting/results")

        self.assertEqual(status, 503)
        self.assertIn("scouting capture is unreadable", body)

    def test_a_position_with_no_role_is_ranked_with_min_median_and_max(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Ranked Defender", positions=("DC",),
                    attributes={}, age=20, club="Example FC", scouting_knowledge=9,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting?view=scouted&position=DC")

        self.assertEqual(status, 200)
        self.assertIn("Ranked for DC (1)", body)
        self.assertIn("data-sort='median'", body)
        self.assertIn("Sorted by <b>Median (best guess)</b>", body)
        self.assertIn("Ranked Defender", body)

    def test_the_scouted_tab_ranks_everyone_without_choosing_a_position_first(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="a", name="Scouted One", positions=(), attributes={},
                    age=20, scouting_knowledge=9,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, body = self._get(port, "/scouting?view=scouted")

        self.assertIn("Ranked, all positions (1)", body)
        self.assertIn("data-sort='median'", body)
        self.assertIn("data-sort='minimum'", body)
        self.assertIn("data-sort='ceiling'", body)

    def test_column_headings_sort_on_the_server_and_show_the_direction(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(id="a", name="Older", positions=(), attributes={}, age=30, scouting_knowledge=9),
                ScoutingCandidate(id="b", name="Younger", positions=(), attributes={}, age=18, scouting_knowledge=9),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, ascending = self._get(port, "/scouting?view=scouted&sort=age")
        _status, descending = self._get(port, "/scouting?view=scouted&sort=age&dir=desc")

        self.assertIn("data-sort='age' data-default='asc'>Age ▲", ascending)
        self.assertLess(ascending.index("Younger"), ascending.index("Older"))
        self.assertIn("Age ▼", descending)
        self.assertLess(descending.index("Older"), descending.index("Younger"))
        self.assertIn("name='dir' value='desc'", descending)

    def test_the_role_table_shows_the_median_too(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(id="a", name="Role Player", positions=("ST",), attributes={}, age=20),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, body = self._get(port, "/scouting?role=af_attack&position=ST")

        self.assertIn("<th>Median</th>", body)

    def test_familiarity_columns_appear_only_when_the_raw_positions_box_is_ticked(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="a", name="Rated Defender", positions=("DC",), attributes={},
                    age=22, scouting_knowledge=12, raw_position_familiarity={"DC": 17, "DR": 4},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _s, off = self._get(port, "/scouting?view=scouted&position=DC")
        _s, ticked = self._get(port, "/scouting?view=scouted&position=DC&includeRawPositions=1")

        self.assertIn("Rated Defender", off)
        self.assertNotIn("data-sort='adjusted'", off)   # the sort *button*, not the dropdown label
        self.assertNotIn("17/20", off)
        self.assertIn("data-sort='adjusted'", ticked)
        self.assertIn("17/20", ticked)
        self.assertIn("(×0.92)", ticked)

    def test_the_scouting_page_offers_a_rank_by_control(self) -> None:
        port = self._serve(FIXTURE)
        _status, body = self._get(port, "/scouting")

        self.assertIn("name='sort'", body)
        self.assertIn("Ceiling (best case)", body)

    def test_the_browse_table_shows_each_players_attributes(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-1", name="Sheet Player", positions=("ST",),
                    attributes={"pace": AttributeObservation(Visibility.RANGE, minimum=9, maximum=15)},
                    age=19, scouting_knowledge=12,
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, body = self._get(port, "/scouting?view=scouted")

        self.assertIn("<th>Attributes</th>", body)
        self.assertIn("9-15", body)

    def test_a_scouted_player_links_to_an_exhaustive_scouting_report(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="report player/1", name="Report Player", positions=("ST",),
                    attributes={
                        "pace": AttributeObservation(Visibility.KNOWN, value=16),
                        "finishing": AttributeObservation(Visibility.RANGE, minimum=12, maximum=16),
                    },
                    age=21, scouting_knowledge=82,
                    raw_position_familiarity={"ST": 18, "AMR": 7},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        _status, listing = self._get(port, "/scouting?view=scouted")
        status, report = self._get(port, "/scouting/player/report%20player%2F1")

        self.assertIn("href='/scouting/player/report%20player%2F1'", listing)
        self.assertEqual(status, 200)
        self.assertIn("All captured attributes", report)
        self.assertIn("Pace", report)
        self.assertIn("16", report)
        self.assertIn("12-16", report)
        self.assertIn("Position familiarity", report)
        self.assertIn("18/20", report)
        self.assertIn("AMR", report)
        self.assertIn("All position and role scores", report)
        self.assertIn("Advanced Forward (Attack)", report)
        self.assertIn("Attribute score inputs", report)

    def test_a_missing_scouting_report_player_returns_not_found(self) -> None:
        port = self._serve(FIXTURE)

        status, body = self._get(port, "/scouting/player/missing")

        self.assertEqual(status, 404)
        self.assertIn("not in the current scouting capture", body)

    def test_scouting_refresh_button_runs_the_configured_capture(self) -> None:
        calls = []

        def refresh(*, allow_rebuild=False):
            calls.append(allow_rebuild)
            return "Captured scouting data"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        status, location, _body = self._post(port, "/scouting/refresh")
        refreshed_status, refreshed_body = self._get(port, "/scouting?refreshed=1")

        self.assertEqual(status, 303)
        self.assertEqual(location, "/scouting?refreshed=1")
        self.assertEqual(calls, [False])
        self.assertEqual(refreshed_status, 200)
        self.assertIn("Refresh scouting data", refreshed_body)
        self.assertIn("Scouting data refreshed", refreshed_body)

    def test_refresh_defaults_to_no_rebuild_and_says_nothing_was_written(self) -> None:
        """The plain button must never carry consent to run FM's code."""
        def refresh(*, allow_rebuild=False):
            self.assertFalse(allow_rebuild)
            return "Captured scouting data"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        _status, location, _body = self._post(port, "/scouting/refresh")
        _refreshed_status, refreshed_body = self._get(port, location)

        self.assertIn("Nothing was written to FM", refreshed_body)

    def test_unbuilt_pool_offers_a_choice_instead_of_rebuilding(self) -> None:
        def refresh(*, allow_rebuild=False):
            self.assertFalse(allow_rebuild)
            raise ScoutingPoolNotBuilt("FM has not built this manager's pool yet.")

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        status, _location, body = self._post(port, "/scouting/refresh")

        self.assertEqual(status, 409)
        self.assertIn("Player Search", body)
        self.assertIn("Nothing has been sent to FM", body)
        self.assertIn("allow_rebuild", body)

    def test_rebuild_happens_only_when_the_form_carries_consent(self) -> None:
        calls = []

        def refresh(*, allow_rebuild=False):
            calls.append(allow_rebuild)
            return "Captured scouting data"

        port = self._serve(FIXTURE, scouting_refresh=refresh)
        status, location, _body = self._post(
            port, "/scouting/refresh", "allow_rebuild=1"
        )
        _refreshed_status, refreshed_body = self._get(port, location)

        self.assertEqual(status, 303)
        self.assertEqual(calls, [True])
        self.assertEqual(location, "/scouting?refreshed=rebuilt")
        self.assertIn("inside the running game", refreshed_body)

    def test_scouting_page_requires_opt_in_for_raw_external_positions(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-raw",
                    name="Raw Position Striker",
                    positions=(),
                    raw_positions=("ST",),
                    attributes={},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        hidden_status, hidden_body = self._get(port, "/scouting?position=ST")
        shown_status, shown_body = self._get(
            port,
            "/scouting?position=ST&includeRawPositions=1",
        )

        self.assertEqual(hidden_status, 200)
        self.assertNotIn("Raw Position Striker", hidden_body)
        self.assertEqual(shown_status, 200)
        self.assertIn("Raw Position Striker", shown_body)
        self.assertIn("Raw external positions enabled", shown_body)
        self.assertIn("raw external data", shown_body)
        self.assertIn("Ranked for ST", shown_body)

    def test_scouting_page_explains_when_an_old_capture_has_no_raw_positions(self) -> None:
        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="external-no-raw",
                    name="No Raw Position",
                    positions=(),
                    attributes={},
                ),
            )

        port = self._serve(FIXTURE, scouting_provider)
        status, body = self._get(port, "/scouting?includeRawPositions=1")

        self.assertEqual(status, 200)
        self.assertIn("Raw external positions enabled, but unavailable", body)

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

    def test_tactics_page_explains_play_now_and_positional_training(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        self.assertIn("Cover risk", body)
        self.assertIn("Team balance", body)
        self.assertIn("Game-plan support", body)
        self.assertIn("After positional training", body)
        self.assertIn("does not project attribute growth", body)
        self.assertIn("<ul class='legend'>", body)
        # Owned players' attributes are exact, so scores collapse to one number.
        self.assertNotIn(" / ", body.split("What can this squad play now?")[1].split("</table>")[0])

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
