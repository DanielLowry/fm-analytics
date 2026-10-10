import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from fm_analytics.analytics.match_analysis import ReviewFilters
from fm_analytics.match_ingest import record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_match_export, build_match_report, build_match_review

from tests.match_support import capture_document, season, two_seasons
from tests.test_penalty_record import with_penalty_against_us
from tests.test_match_chances import SNATCHED, UNLUCKY, chance_match
from tests.test_match_chances import baseline as chance_baseline
from tests.test_match_diagnostics import diagnostic_season, one_match_target, varied_season
from tests.web_support import FIXTURE, WebServerHelpers, write_complete_fixture

DETAILED = "2019-09-01:100:201"
DETAILED_URL = "/matches/" + quote(DETAILED, safe="")


class MatchPagesCase(WebServerHelpers, unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.store = MatchHistoryStore(self.directory / "history.sqlite3")
        self.capture = self.directory / "capture.json"
        self.capture.write_text(json.dumps(capture_document(season())), encoding="utf-8")
        self.captures = 0

    def record(self) -> None:
        record_capture_file(self.store, self.capture)

    def fake_capture(self) -> str:
        self.captures += 1
        return f"{record_capture_file(self.store, self.capture).summary()}"

    def serve(self, fixture=FIXTURE, **kwargs) -> int:
        return self._serve(fixture, match_store=self.store, match_capture=self.fake_capture, **kwargs)


class ReviewPageTests(MatchPagesCase):
    def test_with_no_history_the_page_says_how_to_start(self) -> None:
        status, body = self._get(self.serve(), "/matches")
        self.assertEqual(status, 200)
        self.assertIn("No matches recorded yet", body)
        self.assertIn("Read matches from FM", body)
        self.assertIn('href="/matches" class="active"', body)

    def test_the_review_shows_every_section_and_the_shared_numbers(self) -> None:
        self.record()
        status, body = self._get(self.serve(), "/matches")
        self.assertEqual(status, 200)
        for heading in ("Against different opposition", "Your tactics against each kind of opponent",
                        "Home and away", "Where goals come from", "Who creates and shoots",
                        "Worth testing", "Working: leave alone"):
            self.assertIn(heading, body)
        self.assertIn("matches usable", body)
        self.assertIn("W2 D2 L1", body)  # the same record `fm-matches review` prints
        self.assertIn("Early season", body)
        self.assertIn("too few to read", body)
        self.assertIn("Advanced Forward (Attack)", body)
        self.assertIn(DETAILED_URL, body)

    def test_filters_change_the_selection_and_bad_ones_are_refused(self) -> None:
        self.record()
        port = self.serve()
        _status, body = self._get(port, "/matches?group=relative&competitions=league")
        self.assertIn("Above us", body)
        self.assertNotIn("Cup Rovers", body)
        status, _body = self._get(port, "/matches?group=bogus")
        self.assertEqual(status, 400)


    def test_a_season_can_be_picked_and_a_bad_one_is_refused(self) -> None:
        matches, results = two_seasons()
        self.capture.write_text(json.dumps(
            capture_document(matches, game_date="2020-08-09", league_results=results)
        ), encoding="utf-8")
        self.record()
        port = self.serve()
        last_season = "/matches/" + quote("2019-09-01:100:201", safe="")
        this_season = "/matches/" + quote("2020-08-08:100:204", safe="")
        _status, body = self._get(port, "/matches")
        self.assertIn("<option value='' selected>All seasons</option>", body)
        self.assertIn("<option value='2020'>2020/21</option><option value='2019'>2019/20</option>", body)
        self.assertIn(last_season, body)
        self.assertIn(this_season, body)
        _status, body = self._get(port, "/matches?season=2019")
        self.assertIn("2019/20 season review", body)
        self.assertIn("<option value='2019' selected>2019/20</option>", body)
        self.assertIn(last_season, body)
        self.assertNotIn(this_season, body)
        status, _body = self._get(port, "/matches?season=last")
        self.assertEqual(status, 400)

    def test_the_copy_button_fetches_the_selected_matches(self) -> None:
        self.record()
        port = self.serve()
        _status, body = self._get(port, "/matches?competitions=league&venue=home")
        self.assertIn("data-fetch-copy data-copy-url='/api/matches-export?group=table&amp;competitions=league"
                      "&amp;venue=home'", body)
        self.assertIn("data-copy-success='2 matches copied as JSON!'", body)
        self.assertIn(">Copy all match data</button>", body)
        _status, body = self._get(port, "/matches?tactic=wing_play_442")
        self.assertNotIn("data-fetch-copy", body)  # nothing selected, nothing to copy


class MatchPageTests(MatchPagesCase):
    def test_a_match_with_stats_shows_the_panel_players_and_notes_form(self) -> None:
        self.record()
        status, body = self._get(self.serve(), DETAILED_URL)
        self.assertEqual(status, 200)
        self.assertIn("Hungerford Town 2–1 Alpha", body)
        self.assertIn("1 of 4", body)
        self.assertIn("Home 11", body)
        self.assertIn("Pressing Forward", body)  # no positions here, so no duty is claimed
        self.assertIn("From the roles in the line-up this looks like", body)
        self.assertIn("Minutes", body)
        self.assertIn("action='/matches/note'", body)

    def test_a_match_page_shows_the_named_timeline_every_shot_and_their_formation(self) -> None:
        matches = season()
        found = matches[-1]["detail"]
        found["events"] = [
            {"minute": 12, "side": "home", "kind": "goal", "code": 1, "playerShortId": 1010},
            {"minute": 12, "side": "home", "kind": "assist", "code": 0x24, "playerShortId": 1005},
            {"minute": 50, "side": "away", "kind": "goal", "code": 1, "playerShortId": 1510},
            {"minute": 70, "side": "away", "kind": "yellow_card", "code": 0x26, "playerShortId": 1503},
            {"minute": 90, "addedTime": 3, "side": "home", "kind": "goal", "code": 1, "playerShortId": 1009},
        ]
        found["shots"] = [
            {"side": "home", "playerShortId": 1010, "minute": 11, "second": 4, "across": 1.0, "up": 0.5},
            {"side": "away", "playerShortId": 1510, "minute": 49, "second": 30, "across": -1.0, "up": 0.2},
            {"side": "home", "playerShortId": 1009, "minute": 60, "second": 0, "across": 0.0, "up": 4.0},
            {"side": "home", "playerShortId": 1009, "minute": 92, "second": 10, "across": 2.0, "up": 1.0},
        ]
        found["formations"] = {"away": "4-1-4-1 DM Wide"}
        self.capture.write_text(json.dumps(capture_document(matches)), encoding="utf-8")
        self.record()
        _status, body = self._get(self.serve(), DETAILED_URL)
        self.assertIn("They lined up <strong>4-1-4-1 DM Wide</strong>", body)
        self.assertIn("12′</span> You – Goal: Home 11 <span class='muted'>(assist Home 6)</span>", body)
        self.assertIn("70′</span> Alpha – Booked: Away 4", body)
        self.assertIn("90+3′</span> You – Goal: Home 10", body)
        self.assertIn("<h2>Shots</h2>", body)
        self.assertIn("<tr><td>You</td><td>3</td><td>2</td><td>0</td><td>1</td><td>1</td><td>2</td></tr>", body)
        self.assertIn("<td>Home 10</td><td>Over</td>", body)
        self.assertIn("90+3′</td><td>You</td><td>Home 10</td><td>Goal</td>", body)
        exported = build_match_export(self.store.load_history("club:100"),
                                      build_match_report(self.store.load_history("club:100"), DETAILED))["match"]
        self.assertEqual(exported["opponent_formation"], "4-1-4-1 DM Wide")
        self.assertEqual(exported["timeline"][0], {"minute": 12, "team": "us", "event": "goal", "player": "Home 11",
                                                   "assist": "Home 6"})
        self.assertEqual(exported["shots"][-1], {"minute": "90+3", "team": "us", "player": "Home 10", "outcome": "goal"})
        self.assertEqual(exported["shot_directions"]["them"]["on_goal"], 1)

    def test_the_copy_button_holds_the_shared_match_document(self) -> None:
        self.record()
        _status, body = self._get(self.serve(), DETAILED_URL)
        self.assertIn("Copy match to clipboard", body)
        source = body.split("<script type='application/json' data-player-copy-text>")[1].split("</script>")[0]
        copied = json.loads(json.loads(source))  # the embedded value is the JSON text itself
        history = self.store.load_history("club:100")
        expected = build_match_export(history, build_match_report(history, DETAILED))
        copied["meta"].pop("generated_at")
        expected["meta"].pop("generated_at")
        self.assertEqual(copied, expected)

    def test_a_result_only_match_explains_how_to_add_its_stats(self) -> None:
        self.record()
        status, body = self._get(self.serve(), "/matches/" + quote("2019-08-10:202:100", safe=""))
        self.assertEqual(status, 200)
        self.assertIn("Only the result was found", body)
        self.assertIn("Copy match to clipboard", body)  # the result and its context are still worth copying

    def test_a_match_page_sets_the_match_against_your_usual_range(self) -> None:
        target = one_match_target()
        self.capture.write_text(
            json.dumps(capture_document(varied_season() + [target], game_date="2019-10-20")), encoding="utf-8"
        )
        self.record()
        status, body = self._get(self.serve(), "/matches/" + quote("2019-10-01:100:201", safe=""))
        self.assertEqual(status, 200)
        self.assertIn("<h2>Diagnosis</h2>", body)
        self.assertIn("Created more than usual; allowed about the usual.", body)
        self.assertIn("vs <b>12</b> matches", body)
        self.assertIn("▲ Above", body)
        self.assertIn("Led 1–0 from 10′ but drew", body)
        self.assertIn("usually 6.80", body)
        self.assertLess(body.index("<h2>Diagnosis</h2>"), body.index("<h2>Match stats</h2>"))

    def test_a_match_page_judges_the_result_against_the_chances(self) -> None:
        target = chance_match("2019-10-01", UNLUCKY, SNATCHED)
        self.capture.write_text(
            json.dumps(capture_document(chance_baseline() + [target], game_date="2019-10-20")), encoding="utf-8"
        )
        self.record()
        status, body = self._get(self.serve(), "/matches/" + quote("2019-10-01:100:201", safe=""))
        self.assertEqual(status, 200)
        self.assertIn("<h2>Result vs chances</h2>", body)
        self.assertIn("tone-unlucky'>Unlucky defeat</span>", body)
        self.assertIn("You had the better chances, worth 3.0 goals to their 0.5.", body)
        self.assertIn("fm-chances-odds-L actual", body)
        self.assertIn("Clear-cut chances you missed", body)
        self.assertIn("Against your usual for", body)
        self.assertIn("How this is worked out", body)
        self.assertLess(body.index("<h2>Result vs chances</h2>"), body.index("<h2>Diagnosis</h2>"))

    def test_a_match_without_enough_history_says_why_it_is_not_compared(self) -> None:
        self.record()
        _status, body = self._get(self.serve(), DETAILED_URL)
        self.assertIn("<h2>Diagnosis</h2>", body)
        self.assertIn("Your usual range needs 10 other usable matches; there are 0.", body)
        self.assertIn("From 76′: 1 scored, 0 conceded", body)

    def test_an_unknown_match_is_not_found(self) -> None:
        self.record()
        status, _body = self._get(self.serve(), "/matches/" + quote("2019-01-01:1:2", safe=""))
        self.assertEqual(status, 404)


class MatchPostTests(MatchPagesCase):
    def test_saving_notes_stores_them_and_returns_to_the_match(self) -> None:
        self.record()
        port = self.serve()
        status, location, _body = self._post(
            port, "/matches/note", f"match={quote(DETAILED)}&tactic=wing_play_442&rating=-1&note=Sat+deep"
        )
        self.assertEqual((status, location), (303, DETAILED_URL))
        note = self.store.load_history("club:100").notes[DETAILED]
        self.assertEqual((note.tactic_key, note.opponent_rating, note.note), ("wing_play_442", -1, "Sat deep"))
        _status, body = self._get(port, DETAILED_URL)
        self.assertIn("value='wing_play_442' selected", body)

    def test_who_gave_a_penalty_away_is_saved_from_the_match_page_and_tallied_on_the_matches_page(self) -> None:
        self.capture.write_text(json.dumps(with_penalty_against_us()), encoding="utf-8")
        self.record()
        port = self.serve()
        _status, body = self._get(port, DETAILED_URL)
        self.assertIn("<h3>Penalties you gave away</h3>", body)
        self.assertIn("50′, scored by Away 11: who gave it away?", body)
        self.assertNotIn("Late Sub</option>", body)  # not on the pitch yet
        status, location, _body = self._post(port, "/matches/penalty", f"match={quote(DETAILED)}&minute=50&added=0&player=1003")
        self.assertEqual((status, location), (303, DETAILED_URL))
        _status, body = self._get(port, DETAILED_URL)
        self.assertIn("<option value='1003' selected>Home 4</option>", body)
        self.assertIn("given away by Home 4, your record", body)
        _status, body = self._get(port, "/matches")
        self.assertIn("<h2>Penalties you gave away</h2>", body)
        self.assertIn("<li><strong>Home 4</strong>: 1</li>", body)
        status, _location, _body = self._post(port, "/matches/penalty", f"match={quote(DETAILED)}&minute=50&added=0&player=1503")
        self.assertEqual(status, 400)  # one of theirs

    def test_bad_notes_are_refused_and_nothing_is_stored(self) -> None:
        self.record()
        port = self.serve()
        for form in (f"match={quote(DETAILED)}&rating=9", f"match={quote(DETAILED)}&tactic=nope"):
            status, _location, _body = self._post(port, "/matches/note", form)
            self.assertEqual(status, 400)
        self.assertEqual(self.store.load_history("club:100").notes, {})

    def test_confirming_a_role_code_is_stored(self) -> None:
        self.record()
        status, location, _body = self._post(self.serve(), "/matches/role-code", "code=262144&role=af_attack")
        self.assertEqual((status, location), (303, "/matches"))
        self.assertEqual(self.store.load_history("club:100").role_codes, {262144: "af_attack"})

    def test_reading_from_fm_records_and_reports_the_outcome(self) -> None:
        port = self.serve()
        status, location, _body = self._post(port, "/matches/capture")
        self.assertEqual((status, location, self.captures), (303, "/matches", 1))
        _status, body = self._get(port, "/matches")
        self.assertIn("6 matches seen", body)
        self.assertIn("Against different opposition", body)

    def test_a_failed_read_is_shown_not_raised(self) -> None:
        def failing() -> str:
            raise RuntimeError("Matches could not be read from FM: FM20 is not running")

        port = self._serve(FIXTURE, match_store=self.store, match_capture=failing)
        self._post(port, "/matches/capture")
        status, body = self._get(port, "/matches")
        self.assertEqual(status, 200)
        self.assertIn("FM20 is not running", body)

    def test_a_controlled_test_can_start_but_a_second_cannot_until_it_is_closed(self) -> None:
        self.capture.write_text(
            json.dumps(capture_document(diagnostic_season(10), game_date="2019-09-20")),
            encoding="utf-8",
        )
        self.record()
        port = self.serve()
        _status, body = self._get(port, "/matches")
        self.assertIn("Start this test", body)

        status, location, _body = self._post(
            port,
            "/matches/intervention/start",
            "finding=role_output%3Ab2b_support&note=Test+Appau",
        )
        self.assertEqual((status, location), (303, "/matches"))
        active = self.store.load_history("club:100").interventions[0]
        self.assertTrue(active.active)
        _status, body = self._get(port, "/matches")
        self.assertIn("Active controlled test", body)
        self.assertIn("Test Appau", body)
        self.assertNotIn("Start this test", body)

        status, _location, body = self._post(
            port, "/matches/intervention/start", "finding=role_output%3Ab2b_support"
        )
        self.assertEqual(status, 400)
        self.assertIn("active intervention", body)

        status, _location, body = self._post(
            port,
            "/matches/intervention/finish",
            f"intervention={active.id}&outcome=adopted",
        )
        self.assertEqual(status, 400)
        self.assertIn("five eligible exposures", body)

        status, location, _body = self._post(
            port,
            "/matches/intervention/finish",
            f"intervention={active.id}&outcome=stopped&note=Changed+plan",
        )
        self.assertEqual((status, location), (303, "/matches"))
        closed = self.store.load_history("club:100").interventions[0]
        self.assertEqual((closed.active, closed.outcome), (False, "stopped"))


class TacticsPanelTests(MatchPagesCase):
    def test_the_tactics_page_shows_the_pinned_tactics_match_record(self) -> None:
        self.record()
        port = self.serve(write_complete_fixture(self.directory), pinned_tactics=("vertical_442",))
        status, body = self._get(port, "/tactics")
        self.assertEqual(status, 200)
        self.assertIn("Your match record", body)
        self.assertIn("Vertical 4-4-2: W1 D0 L0", body)

    def test_without_history_the_tactics_page_has_no_panel(self) -> None:
        port = self.serve(write_complete_fixture(self.directory))
        _status, body = self._get(port, "/tactics")
        self.assertNotIn("Your match record", body)
        _status, body = self._get(port, "/tactics/vertical_442")
        self.assertNotIn("How this tactic has played", body)
        self.assertNotIn("#tactic-history", body)

    def test_a_tactic_page_shows_how_that_tactic_has_played(self) -> None:
        self.record()
        port = self.serve(write_complete_fixture(self.directory))
        status, body = self._get(port, "/tactics/vertical_442")
        self.assertEqual(status, 200)
        self.assertIn("How this tactic has played", body)
        self.assertIn("href='#tactic-history'", body)
        self.assertIn("W1 D0 L0", body)  # the 2-1 over Alpha, inferred from its line-up
        self.assertIn("When goals came", body)
        self.assertIn("Penalties: 0 for, 0 against", body)
        self.assertIn(DETAILED_URL, body)
        self.assertIn("/matches?tactic=vertical_442", body)
        # The same record `fm-matches review --tactic vertical_442` computes.
        history = self.store.load_history("club:100")
        review = build_match_review(history, filters=ReviewFilters(tactic="vertical_442"))
        self.assertEqual((review.overall.wins, review.overall.draws, review.overall.losses), (1, 0, 0))

    def test_a_tactic_never_played_says_so(self) -> None:
        self.record()
        port = self.serve(write_complete_fixture(self.directory))
        _status, body = self._get(port, "/tactics/wing_play_442")
        self.assertIn("No league or cup match recorded with this tactic yet", body)


if __name__ == "__main__":
    unittest.main()
