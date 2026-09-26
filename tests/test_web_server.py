import html
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from fm_analytics.analytics import AXIS_DEFINITIONS, MVP_CATALOGUE, OpponentProfile
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes
from fm_analytics.persistence import SnapshotStore
from fm_analytics.analytics import ScoutingCandidate
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.rendering import ScoutingPoolNotBuilt, _slot_reasoning
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

            for path in ("/", "/squad", "/roles", "/tactics", "/tactic-checks", "/set-pieces", "/depth", "/scouting", "/data"):
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

    def test_squad_can_compare_every_player_captured_for_a_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
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
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/squad?position=DR&role=fb_support")

            self.assertEqual(status, 200)
            self.assertIn("Role: Full-Back (Support)", body)

    def test_squad_player_links_to_a_full_player_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            _status, squad = self._get(port, "/squad")
            status, report = self._get(port, "/squad/player/player-1")

            self.assertIn("href='/squad/player/player-1'", squad)
            self.assertIn("Attribute-based role score", squad)
            self.assertIn("In-position role score (best role)", squad)
            self.assertIn("Today’s selection score (best role)", squad)
            self.assertIn("unknown (assumed 10/20)", squad)
            self.assertEqual(status, 200)
            self.assertIn("All captured attributes", report)
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
            fixture_path = _write_complete_fixture(Path(directory))
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

    def test_tactic_detail_has_a_matchday_bench_and_complete_coverage_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/tactics/balanced_442")

            self.assertEqual(status, 200)
            self.assertIn("Matchday bench", body)
            self.assertIn("Substitution coverage", body)
            coverage = body.split("Substitution coverage", 1)[1].split("</details>", 1)[0]
            self.assertEqual(coverage.count("coverage-card"), 11)

    def test_matchday_bench_is_numbered_with_reserve_goalkeeper_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
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
            self.assertIn("Take players from the top", body)
            self.assertIn("<th>Priority</th>", body)
            self.assertIn("<td><b>1</b></td>", body)
            self.assertIn("Backup Goalkeeper", body)
            self.assertIn("Reserve goalkeeper", body)
            self.assertNotIn("No eligible reserve goalkeeper", body)

    def test_unknown_tactic_detail_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path)

            status, body = self._get(port, "/tactics/not-a-tactic")

            self.assertEqual(status, 404)
            self.assertIn("not in the current catalogue", body)

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
        self.assertIn("name='tactic'", body)
        self.assertIn("Generic position / role ranking", body)
        self.assertIn("id='scouting-results'", body)
        self.assertIn("fetch(", body)

    def test_scouting_can_rank_targets_by_gain_for_a_selected_tactic(self) -> None:
        required = required_role_attributes()

        def scouting_provider():
            return (
                ScoutingCandidate(
                    id="strong-target",
                    name="Strong Target",
                    positions=("ST",),
                    attributes={
                        name: AttributeObservation(Visibility.KNOWN, value=20)
                        for name in required
                    },
                    age=22,
                    scouting_knowledge=100,
                ),
            )

        with tempfile.TemporaryDirectory() as directory:
            fixture_path = _write_complete_fixture(Path(directory))
            port = self._serve(fixture_path, scouting_provider)

            status, body = self._get(port, "/scouting?tactic=balanced_442")
            player_status, player_body = self._get(
                port,
                "/scouting/player/strong-target?tactic=balanced_442",
            )

        self.assertEqual(status, 200)
        self.assertIn("Impact on Balanced 4-4-2", body)
        self.assertIn("Strong Target", body)
        self.assertIn("Current score:", body)
        self.assertIn("XI gain", body)
        self.assertIn("Starts", body)
        self.assertIn("Sorted by <b>XI gain (estimate)</b>", body)
        self.assertEqual(player_status, 200)
        self.assertIn("Tactic impact", player_body)
        self.assertIn("name='tactic'", player_body)
        self.assertIn("Impact on Balanced 4-4-2", player_body)
        self.assertIn("Projected tactic score", player_body)
        self.assertIn("XI gain", player_body)
        self.assertIn("Starts", player_body)

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

        self.assertIn("<th>Median estimate</th>", body)

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
        self.assertIn("In-position role score", ticked)
        self.assertIn("attribute-based", ticked)
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
        self.assertIn("Tactic impact", report)
        self.assertIn("Analyse player", report)
        self.assertIn("Pace", report)
        self.assertIn("16", report)
        self.assertIn("12-16", report)
        self.assertIn("Position familiarity", report)
        self.assertIn("18/20", report)
        self.assertIn("AMR", report)
        self.assertIn("Position score summary", report)
        self.assertIn("Best role (by estimate)", report)
        self.assertIn("In-position estimate", report)
        self.assertIn("All attribute-based role scores by position", report)
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
        self.server = server
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

    def test_tactics_overview_is_compact_and_links_to_drill_down(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        self.assertIn("Recommended for today", body)
        self.assertIn("Key issue", body)
        self.assertIn("View tactic", body)
        self.assertNotIn("Starting XI", body)
        self.assertNotIn("Matchday bench", body)
        # Owned players' attributes are exact, so scores collapse to one number.
        self.assertNotIn(" / ", body.split("Compare tactics")[1].split("</table>")[0])

    def test_tactics_page_renders_every_opponent_slider(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        self.assertIn("Opponent profile", body)
        self.assertEqual(body.count("type='range'"), len(AXIS_DEFINITIONS))
        for axis in AXIS_DEFINITIONS:
            self.assertIn(f"name='opp_{axis.key}'", body)
            self.assertIn(html.escape(axis.label), body)
        self.assertIn("min='-2' max='2' step='1' value='0'", body)

    def test_opponent_profile_shows_neutral_deltas_and_survives_drill_down(self) -> None:
        query = "opp_quality=2&opp_pace_in_behind=2"
        status, body = self._get(f"/tactics?{query}")

        self.assertEqual(status, 200)
        self.assertIn("Active opponent assumptions", body)
        self.assertIn("Quality: Much stronger than us", body)
        self.assertIn("Pace in behind: Very fast", body)
        self.assertIn("Change vs neutral", body)
        self.assertIn("Opponent fit", body)
        self.assertIn("Recommended for this opponent", body)
        escaped_query = "opp_quality=2&amp;opp_pace_in_behind=2"
        self.assertIn(escaped_query, body)

        status, detail = self._get(f"/tactics/balanced_442?{query}")

        self.assertEqual(status, 200)
        self.assertIn("Opponent profile:", detail)
        self.assertIn("Opponent fit", detail)
        self.assertIn(f"href='/tactics?{escaped_query}'", detail)
        self.assertEqual(detail.count("type='range'"), len(AXIS_DEFINITIONS))
        self.assertIn("action='/tactics/balanced_442'", detail)
        self.assertIn(
            "href='/tactics/balanced_442'>Reset to neutral</a>", detail
        )

        status, aerial_only = self._get("/tactics?opp_aerial_threat=2")

        self.assertEqual(status, 200)
        self.assertIn("Player emphasis only; no system check", aerial_only)

    def test_invalid_opponent_slider_is_a_bad_request(self) -> None:
        status, body = self._get("/tactics?opp_quality=3")

        self.assertEqual(status, 400)
        self.assertIn("between -2 and 2", body)

    def test_tactic_detail_explains_each_selection_and_score_layer(self) -> None:
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        self.assertEqual(body.count("Why Player"), 11)
        self.assertIn("attribute-based", body)
        self.assertIn("in-position", body)
        self.assertIn("readiness", body)
        self.assertIn("other ten slots are", body)
        self.assertIn("Tactic score", body)
        self.assertIn("Player scores", body)
        self.assertIn("Score details", body)
        self.assertIn("if every player score rises by 2%", body)
        self.assertIn("tactic-balance factor", body)

    def test_tactic_checks_page_lists_player_independent_failures(self) -> None:
        status, body = self._get("/tactic-checks")

        self.assertEqual(status, 200)
        self.assertIn("Experimental, player-independent checks", body)
        self.assertIn("does affect tactic rankings", body)
        self.assertIn("Fluid Counter 4-1-4-1", body)
        self.assertIn("Failing combination", body)
        self.assertIn("Forward threat: roles provide 1.4; standard is 1.5", body)

    def test_tactic_detail_warns_when_its_selected_roles_fail_a_check(self) -> None:
        evaluation = next(
            item
            for item in self.server.bundle().recommendation.evaluations
            if item.coherence.shortfalls or item.instruction_suitability.shortfalls
        )

        status, body = self._get(f"/tactics/{evaluation.tactic.key}")

        self.assertEqual(status, 200)
        self.assertIn("Selected roles miss a structural check", body)
        self.assertIn("reduces the tactic-balance factor", body)
        self.assertIn(f"/tactic-checks#{evaluation.tactic.key}", body)

    def test_tactic_detail_justifies_the_shape_and_every_slot(self) -> None:
        tactic = MVP_CATALOGUE.tactics["balanced_442"]
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        self.assertIn("Why this shape:", body)
        self.assertIn("When to use it:", body)
        self.assertIn("When to avoid it:", body)
        self.assertIn("Why these instructions", body)
        self.assertEqual(body.count("Why this role here:"), 11)
        for slot in tactic.slots:
            self.assertIn(html.escape(slot.why), body)

    def test_tactic_detail_says_which_attributes_the_tactic_leans_on(self) -> None:
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        self.assertIn("Leans on:", body)
        # Rendered for a manager, not as the JSON key.
        self.assertIn("off the ball +2", body)
        self.assertNotIn("offTheBall", body)

    def test_tactic_detail_labels_an_introduced_role_requirement(self) -> None:
        status, body = self._get("/tactics/pressing_442")

        self.assertEqual(status, 200)
        self.assertIn("aggression +1", body)
        self.assertIn("new requirement", body)

    def test_tactics_overview_hints_when_each_tactic_suits(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertIn(html.escape(tactic.when_to_use), body)

    def test_an_alternate_role_choice_does_not_borrow_the_default_roles_reasoning(self) -> None:
        slot = MVP_CATALOGUE.tactics["balanced_442"].slots[-1]
        default = _slot_reasoning(slot, slot.role_key, "Advanced Forward (Attack)")
        alternate = _slot_reasoning(slot, slot.alternate_role_keys[0], "Poacher (Attack)")

        self.assertNotIn("suits", default)
        self.assertIn("Your squad suits Poacher (Attack)", alternate)
        self.assertIn(html.escape(slot.why), alternate)

    def test_xi_rows_follow_formation_order_from_goalkeeper_to_attack(self) -> None:
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        assignment_table = body.split("<h2>Starting XI</h2>", 1)[1].split(
            "<h2>Matchday bench</h2>", 1
        )[0]
        self.assertLess(
            assignment_table.index("<td>GK</td>"),
            assignment_table.index("<td>ST</td>"),
        )

    def test_depth_page_leads_with_conclusions_and_a_compact_table(self) -> None:
        status, body = self._get("/depth")

        self.assertEqual(status, 200)
        self.assertIn("Conclusions", body)
        self.assertIn("By position", body)
        # No per-weakness sentence dump: reasons are short kind codes.
        self.assertNotIn("is below the starter role-fit threshold", body)


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
            fixture_path = _write_complete_fixture(Path(directory))
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

    def test_source_flags_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--fixture", "a.json", "--direct-live"])


if __name__ == "__main__":
    unittest.main()
