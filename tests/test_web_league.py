import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fm_analytics.domain.leagues import LeagueCapture
from fm_analytics.persistence.league_history import LeagueHistoryStore
from fm_analytics.web.league_state import LeagueState, league_json_provider
from tests.league_support import league_capture
from tests.web_support import WebServerHelpers


class LeagueCaptureCommandTests(unittest.TestCase):
    def run_tool(self, returncode, stdout="", stderr=""):
        from subprocess import CompletedProcess
        from fm_analytics.web.league_state import CAPTURE_TOOL, league_capture_command
        with patch("fm_analytics.web.league_state.subprocess.run",
                   return_value=CompletedProcess([], returncode, stdout, stderr)) as run:
            try:
                return league_capture_command("out/league.json")()
            finally:
                command = run.call_args.args[0]
                self.assertEqual(command[-3:], [str(CAPTURE_TOOL), "--output", "out/league.json"])
                self.assertIn("research", command)

    def test_success_is_summarised_in_plain_words(self):
        message = self.run_tool(0, json.dumps({"clubs": 22, "players": 442, "gameDate": "2020-05-28"}))
        self.assertEqual(message, "Read 22 clubs and 442 players from FM at game date 2020-05-28.")

    def test_failure_carries_the_tools_own_reason(self):
        with self.assertRaisesRegex(RuntimeError, "FM changed during the capture"):
            self.run_tool(1, stderr="League capture failed: FM changed during the capture; try again")

    def test_a_missing_file_is_nothing_read_yet_only_when_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"league.json"
            self.assertIsNone(league_json_provider(path, allow_missing=True)())
            with self.assertRaises(FileNotFoundError):
                league_json_provider(path)()


class FakeReport:
    """Stands in for a computed LeagueReport where only caching is under test."""

    def __init__(self, capture):
        self.capture = capture

    def summaries(self):
        return {}


class LeagueStateTests(unittest.TestCase):
    def setUp(self):
        self.capture = league_capture()
        self.state = LeagueState()
        self.state.read = lambda: (self.capture.game, self.capture.teams[0].squad)
        self.state.setup_league(lambda: self.capture)

    def test_cache_reuses_reports_and_recomputes_changed_knowledge_and_scope(self):
        with patch("fm_analytics.web.league_state.build_league_comparison",
                   side_effect=lambda capture, **_: FakeReport(capture)) as build:
            first = self.state.league_report("balanced_442")
            self.assertIs(self.state.league_report("balanced_442"), first)
            self.assertEqual(build.call_count, 1)
            self.state.league_report()
            self.assertEqual(build.call_count, 2)
            self.capture = replace(self.capture, membership_evidence="New participant observation")
            self.state.league_report("balanced_442")
            self.assertEqual(build.call_count, 3)
            self.assertEqual(len(self.state._league_reports), 2)

    def test_mismatched_context_and_same_day_owned_observations_are_refused(self):
        game, owned = self.state.read()
        for different in (replace(game, game_date=game.game_date+timedelta(days=1)),
                          replace(game, human_manager=replace(game.human_manager, id="another-manager")),
                          replace(game, controlled_club=replace(game.controlled_club, id="another-club"))):
            self.state.read = lambda: (different, owned)
            with self.assertRaisesRegex(ValueError, "different dates"):
                self.state.league_report()
        self.state.read = lambda: (game, replace(owned, players=owned.players[:-1]))
        with self.assertRaisesRegex(ValueError, "different observations"):
            self.state.league_report()

    def test_bad_file_replacement_does_not_silently_serve_an_old_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"league.json"
            path.write_text(json.dumps(self.capture.to_document()))
            provider = league_json_provider(path)
            self.assertEqual(provider(), self.capture)
            path.write_text('{"partial":')
            with self.assertRaises(ValueError):
                provider()
            path.write_text(json.dumps(self.capture.to_document()))
            self.assertEqual(provider(), self.capture)

    def test_background_view_returns_loading_and_joins_a_single_job(self):
        started, finish = threading.Event(), threading.Event()
        report = FakeReport(self.capture)
        def compute(*args, **kwargs):
            started.set()
            finish.wait(5)
            return report
        with patch("fm_analytics.web.league_state.build_league_comparison", side_effect=compute) as build:
            self.assertEqual(self.state.league_view().status, "loading")
            self.assertTrue(started.wait(2))
            self.assertEqual(self.state.league_view().status, "loading")
            thread = self.state._league_thread
            finish.set()
            thread.join(2)
            self.assertIs(self.state.league_view().report, report)
            self.assertEqual(build.call_count, 1)

    def test_failed_refresh_retains_only_same_save_and_scope_and_can_retry(self):
        report = FakeReport(self.capture)
        with patch("fm_analytics.web.league_state.build_league_comparison", return_value=report):
            self.state.league_report("balanced_442")
        self.capture = replace(self.capture, membership_evidence="New observation")
        with patch("fm_analytics.web.league_state.build_league_comparison", side_effect=RuntimeError("Read failed")):
            view = self.state.league_view("balanced_442")
            self.assertIs(view.report, report)
            thread = self.state._league_thread
            if thread is not None:
                thread.join(2)
            view = self.state.league_view("balanced_442")
            self.assertEqual(view.error, "Read failed")
            self.assertEqual(view.status, "error")
        with patch("fm_analytics.web.league_state.build_league_comparison", return_value=report):
            self.state.league_view("balanced_442", retry=True)
            thread = self.state._league_thread
            if thread is not None:
                thread.join(2)
            self.assertEqual(self.state.league_view("balanced_442").status, "ready")
        self.capture = replace(self.capture, save_key="different-save")
        with patch("fm_analytics.web.league_state.build_league_comparison", side_effect=RuntimeError("Read failed")):
            self.assertIsNone(self.state.league_view("balanced_442").report)
            thread = self.state._league_thread
            if thread is not None:
                thread.join(2)


class LeagueWebTests(WebServerHelpers, unittest.TestCase):
    def _get(self, port, path):
        deadline = time.monotonic()+8
        while True:
            status, body = super()._get(port, path)
            if (status != 202 and "data-league-pending" not in body) or time.monotonic() >= deadline:
                return status, body
            self.assertIn("Updating league comparison", body)
            time.sleep(.01)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.capture = league_capture()
        self.fixture = Path(self.directory.name)/"owned.json"
        self.fixture.write_text(json.dumps({"game": self.capture.game.to_dict(),
                                           "squad": self.capture.teams[0].squad.to_dict()}))
        self.store = LeagueHistoryStore(Path(self.directory.name)/"history.sqlite3")
        self.port = self._serve(self.fixture, league_provider=lambda: self.capture, league_store=self.store)

    def test_overview_has_all_clubs_ranges_own_marker_and_unscored_status(self):
        status, body = self._get(self.port, "/league?tactic=balanced_442")
        self.assertEqual(status, 200)
        for text in ("Strong club", "Unscouted club", "Partial club", "your club", "Roster incomplete",
                     "Example league data", "among 3 scored clubs", "role='img'", "uncaptured",
                     "Recent form is left out for every club"):
            self.assertIn(text, body)
        self.assertEqual(self.store.latest(self.capture.save_key, self.capture.competition.id,
                                          as_of=self.capture.game.game_date), self.capture)

    def test_team_has_all_scenarios_roster_filters_and_actionable_gaps(self):
        status, body = self._get(self.port, "/league/teams/rival-2?tactic=balanced_442&position=GK")
        self.assertEqual(status, 200)
        for text in ("Conservative best XI", "Floor XI", "Ceiling XI", "Rank the squad", "Scout more",
                     "Missing position familiarity", "fm-league-pitch"):
            self.assertIn(text, body)
        roster = body.split("<h2>Rank the squad</h2>")[1]
        self.assertIn("Unscouted club player 0", roster)
        self.assertNotIn("Unscouted club player 1</a>", roster)

    def test_profile_distinguishes_missing_observations_and_escapes_display_names(self):
        document = self.capture.to_document()
        player = document["teams"][2]["squad"]["players"][0]
        player["name"] = "<script>alert('x')</script>"
        del player["attributes"]["passing"]
        self.capture = LeagueCapture.from_document(document)
        status, body = self._get(self.port, f"/league/teams/rival-2/players/{player['id']}?tactic=balanced_442")
        self.assertEqual(status, 200)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>alert", body)
        self.assertIn("Uncaptured", body)
        self.assertIn("?</td>", body)
        for row in document["teams"][2]["squad"]["players"]:
            row["attributes"] = {}
        self.capture = LeagueCapture.from_document(document)
        status, body = self._get(self.port, "/league/teams/rival-2?tactic=balanced_442")
        self.assertEqual(status, 200)
        self.assertIn("Capture needed", body)

    def test_unknown_routes_controls_and_failed_capture_are_explicit(self):
        for path, expected in (("/league?tactic=invalid", 400), ("/league?sort=invalid", 400),
                               ("/league/teams/rival-1?role=invalid", 400),
                               ("/league/teams/absent", 404),
                               ("/league/teams/rival-1/players/absent", 404)):
            with self.subTest(path=path):
                self.assertEqual(self._get(self.port, path)[0], expected)
        self.capture = replace(self.capture, game=replace(self.capture.game, game_date=self.capture.game.game_date+timedelta(days=1)),
                               teams=tuple(replace(r, squad=replace(r.squad, as_of_date=r.squad.as_of_date+timedelta(days=1)))
                                           for r in self.capture.teams))
        status, body = self._get(self.port, "/league?tactic=balanced_442")
        self.assertEqual(status, 400)
        self.assertIn("different dates", body)

    def test_no_capture_has_a_useful_empty_state(self):
        port = self._serve(self.fixture)
        status, body = self._get(port, "/league")
        self.assertEqual(status, 200)
        self.assertIn("League data needed", body)

    def test_overview_names_what_to_scout_and_how_well_starters_are_known(self):
        status, body = self._get(self.port, "/league?tactic=balanced_442")
        self.assertEqual(status, 200)
        for text in ("What to scout next", "Unscouted club player", "points of their best case rest on him",
                     "Starters: 11 known · 0 partly known · 0 unknown", "squads read completely",
                     "not scored yet: Partial club (Roster incomplete)", "Since last read"):
            self.assertIn(text, body)

    def test_a_second_read_explains_what_changed(self):
        from fm_analytics.domain import AttributeObservation, Visibility
        self._get(self.port, "/league?tactic=balanced_442")
        rival = self.capture.teams[2]
        scouted = tuple(replace(player, attributes={key: AttributeObservation(Visibility.KNOWN, value=14)
                                                    for key in player.attributes}) for player in rival.squad.players)
        self.capture = replace(self.capture, membership_evidence="Scouted the unscouted club",
                               teams=self.capture.teams[:2] + (replace(rival, squad=replace(rival.squad, players=scouted)),)
                               + self.capture.teams[3:])
        status, body = self._get(self.port, "/league?tactic=balanced_442")
        self.assertEqual(status, 200)
        self.assertIn("range narrower", body)
        status, body = self._get(self.port, "/league/teams/rival-2?tactic=balanced_442")
        self.assertIn("Since the read at game date", body)
        self.assertIn("best XI range 0.0–", body)

    def test_team_and_player_pages_explain_xi_differences_and_gaps(self):
        status, body = self._get(self.port, "/league/teams/rival-2?tactic=balanced_442")
        self.assertEqual(status, 200)
        self.assertIn("conservative XI", body)
        self.assertIn("Role attributes", body)
        self.assertIn("What to learn next", body)
        player = self.capture.teams[2].squad.players[0].id
        status, body = self._get(self.port, f"/league/teams/rival-2/players/{player}?tactic=balanced_442")
        self.assertEqual(status, 200)
        self.assertIn("What would sharpen his score", body)
        self.assertIn("Scout more", body)

    def test_reading_the_league_from_fm_is_offered_and_reported(self):
        reads = []

        def capture():
            reads.append(1)
            if len(reads) == 2:
                raise RuntimeError("FM20 is not running")
            return "Read 3 clubs and 33 players from FM at game date 2019-09-04."

        port = self._serve(self.fixture, league_provider=lambda: None, league_capture=capture)
        status, body = self._get(port, "/league")
        self.assertIn("League data needed", body)
        self.assertIn("Read the league from FM", body)
        self.assertEqual(self._post(port, "/league/capture")[:2], (303, "/league"))
        self.assertIn("Read 3 clubs and 33 players", self._get(port, "/league")[1])
        self._post(port, "/league/capture")
        self.assertIn("The league could not be read from FM: FM20 is not running", self._get(port, "/league")[1])
        self.assertEqual(len(reads), 2)

    def test_a_league_read_on_an_earlier_date_asks_to_be_read_again(self):
        older = replace(self.capture, game=replace(self.capture.game, game_date=self.capture.game.game_date-timedelta(days=1)),
                        teams=tuple(replace(r, squad=replace(r.squad, as_of_date=r.squad.as_of_date-timedelta(days=1)))
                                    for r in self.capture.teams))
        port = self._serve(self.fixture, league_provider=lambda: older, league_capture=lambda: "read")
        status, body = self._get(port, "/league")
        self.assertEqual(status, 409)
        self.assertIn("League out of date", body)
        self.assertIn("Read it again", body)
        self.assertIn("action='/league/capture'", body)

    def test_without_fm_there_is_no_read_button(self):
        status, body = self._get(self.port, "/league?tactic=balanced_442")
        self.assertNotIn("/league/capture", body)

    def test_failed_background_job_exposes_a_retry_and_redirects_to_clean_query(self):
        from fm_analytics.web.league_state import build_league_comparison
        calls = 0
        def compute(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Source unavailable")
            return build_league_comparison(*args, **kwargs)
        with patch("fm_analytics.web.league_state.build_league_comparison", side_effect=compute):
            status, body = self._get(self.port, "/league?tactic=balanced_442")
            self.assertEqual(status, 503)
            self.assertIn("Retry comparison", body)
            self.assertIn("Source unavailable", body)
            status, body = self._get(self.port, "/league?tactic=balanced_442&retry=1")
            self.assertEqual(status, 303)
            self.assertEqual(self._get(self.port, "/league?tactic=balanced_442")[0], 200)
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
