"""Goals and chances conceded: who delivered, from where, near or back post, and who of ours was around."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fm_analytics.analytics.conceded import conceded_moments, review_conceded
from fm_analytics.conceded_export import conceded_json
from fm_analytics.domain.matches import MatchRecord
from fm_analytics.match_ingest import main, record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_conceded_review, build_match_export, build_match_report

from tests.match_support import ALPHA, LEAGUE, US, capture_document, season, team_stats
from tests.test_opponent_report import (
    DCL, DCR, DL, DR, FREE_KICK, HEADER_FROM_CROSS, MCL, ML, MR, SHOT_IN_AREA, STL, STR, goal, players, short_id,
)
from tests.web_support import FIXTURE, WebServerHelpers

OUTSIDE = "0000000000000000"  # a shot from outside the area


def match(*events, ours=None, theirs=None, shots=(), incidents=None, day="2020-08-15") -> MatchRecord:
    """Us at home to Alpha; `events` in match order."""
    events = [event for group in events for event in group]
    home = sum(1 for e in events if e["side"] == "home" and e["kind"] in ("goal", "penalty")) + sum(
        1 for e in events if e["side"] == "away" and e["kind"] == "own_goal")
    away = sum(1 for e in events if e["side"] == "away" and e["kind"] in ("goal", "penalty")) + sum(
        1 for e in events if e["side"] == "home" and e["kind"] == "own_goal")
    detail = {
        "home": team_stats(goals=home), "away": team_stats(goals=away),
        "players": (ours or players(US, "home")) + (theirs or players(ALPHA, "away")),
        "events": events, "shots": list(shots),
    }
    document = {"date": day, "competition": LEAGUE, "home": US, "away": ALPHA, "homeGoals": home,
                "awayGoals": away, "attendance": 400, "detail": detail, "season": 2020}
    if incidents is not None:
        document["incidents"] = incidents
        detail["events"] = []
    return MatchRecord.from_document(document)


def ours_name(order: int) -> str:
    position, centre = {DL: ("DL", None), DR: ("DR", None), DCL: ("DC", None), DCR: ("DC", None),
                        ML: ("ML", None), MR: ("MR", None)}.get(order, ("?", None))
    return f"Hungerford Town {position}{order} ({position})"


def chance(minute: int, order: int) -> list[dict]:
    return [{"minute": minute, "side": "away", "kind": "clear_cut_chance", "code": 0x2F,
             "playerShortId": short_id(ALPHA, order)}]


class OneGoalTests(unittest.TestCase):
    def test_a_cross_from_their_right_met_by_their_left_striker_is_down_our_left_at_the_back_post(self) -> None:
        (moment,) = conceded_moments(match(goal(30, "away", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS)), US["id"])
        self.assertEqual((moment.delivered_by, moment.delivery_position, moment.delivery_flank), ("Alpha MR5", "MR", "left"))
        self.assertEqual((moment.taker, moment.taker_position, moment.taker_side, moment.post),
                         ("Alpha ST10", "ST", "right", "back"))
        self.assertEqual([player.label for player in moment.facing_delivery], [ours_name(DL), ours_name(ML)])
        # The back post is our right: our right-back and the right of our pair.
        self.assertEqual([player.label for player in moment.in_zone],
                         ["Hungerford Town DR1 (DR)", "Hungerford Town DC2 (DC)"])
        self.assertEqual((moment.how_key, moment.score_before, moment.outcome), ("header_from_cross", (0, 0), "Goal"))

    def test_the_striker_on_the_crossers_side_meets_it_at_the_near_post(self) -> None:
        (moment,) = conceded_moments(match(goal(30, "away", ALPHA, STR, assist=MR, descriptor=HEADER_FROM_CROSS)), US["id"])
        self.assertEqual((moment.taker_side, moment.post), ("left", "near"))
        self.assertEqual([player.label for player in moment.in_zone],
                         ["Hungerford Town DL4 (DL)", "Hungerford Town DC3 (DC)"])

    def test_a_shot_from_outside_the_area_brings_in_our_holding_and_central_midfielders(self) -> None:
        (moment,) = conceded_moments(match(goal(30, "away", ALPHA, MCL, descriptor=OUTSIDE)), US["id"])
        self.assertEqual((moment.delivery_flank, moment.post, moment.area_key), (None, None, "outside"))
        self.assertIn("Hungerford Town MC6 (MC)", [player.label for player in moment.in_zone])

    def test_who_was_on_the_pitch_allows_for_substitutions_and_sendings_off(self) -> None:
        ours = players(US, "home")
        ours[DL]["wentOff"] = 20
        substitute = dict(ours[DL], order=11, started=False, shortId=short_id(US, 11), name="Sub DL",
                          cameOn=20, wentOff=None, startPosition=None)
        events = [{"minute": 25, "side": "home", "kind": "sent_off", "code": 5, "playerShortId": short_id(US, ML)}]
        found = conceded_moments(match(events, goal(30, "away", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS),
                                       ours=ours + [substitute]), US["id"])
        self.assertEqual([player.label for player in found[0].facing_delivery], ["Sub DL (DL)"])

    def test_set_pieces_are_fms_or_the_corner_guess_and_never_get_a_post_or_zone(self) -> None:
        penalty = [{"minute": 10, "side": "away", "kind": "penalty", "code": 3, "playerShortId": short_id(ALPHA, STL)}]
        theirs = players(ALPHA, "away", stats={MR: {"corners_taken": 2}})
        found = conceded_moments(match(
            penalty, goal(40, "away", ALPHA, MCL, descriptor=FREE_KICK),
            goal(60, "away", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS), theirs=theirs,
        ), US["id"], given_away={(f"2020-08-15:{US['id']}:{ALPHA['id']}", 10, 0): short_id(US, DCL)})
        self.assertEqual([moment.how_key for moment in found], ["penalty", "direct_free_kick", "possibly_corner"])
        self.assertTrue(all(not moment.around and moment.post is None for moment in found))
        self.assertEqual(found[0].given_away_by, "Hungerford Town DC3")
        self.assertEqual([moment.score_before for moment in found], [(0, 0), (0, 1), (0, 2)])

    def test_a_chance_has_its_shot_and_zone_and_one_that_became_a_goal_is_told_once(self) -> None:
        shot = {"side": "away", "playerShortId": short_id(ALPHA, STR), "minute": 49, "second": 3, "across": 6.0, "up": 1.0}
        found = conceded_moments(match(
            chance(50, STR), chance(70, STL), goal(70, "away", ALPHA, STL, descriptor=SHOT_IN_AREA), shots=[shot],
        ), US["id"])
        self.assertEqual([(moment.kind, moment.outcome) for moment in found], [("chance", "Wide"), ("goal", "Goal")])
        self.assertEqual((found[0].taker_side, found[0].delivered_by), ("left", None))
        self.assertEqual([player.label for player in found[0].in_zone],
                         ["Hungerford Town DL4 (DL)", "Hungerford Town DC3 (DC)"])
        self.assertTrue(found[1].from_clear_cut_chance)

    def test_without_a_timeline_each_goal_still_comes_from_fms_result(self) -> None:
        incidents = [{"minute": 12, "addedTime": 0, "side": "away", "kind": "goal", "playerShortId": 9, "player": "Their 9"}]
        (moment,) = conceded_moments(match(goal(12, "away", ALPHA, STL), incidents=incidents), US["id"])
        self.assertEqual((moment.taker, moment.how, moment.around), ("Their 9", None, ()))


class ReviewTests(unittest.TestCase):
    def test_the_breakdowns_count_every_goal_and_chance_and_who_of_ours_was_around(self) -> None:
        review = review_conceded([
            match(goal(30, "away", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS), chance(80, STR)),
            match(goal(10, "away", ALPHA, STR, assist=ML, descriptor=HEADER_FROM_CROSS), day="2020-08-22"),
        ], US["id"])
        self.assertEqual((review.matches, review.goals, review.chances), (2, 2, 1))
        self.assertEqual({row.key: row.goals for row in review.flanks}, {"left": 1, "right": 1})
        self.assertEqual({row.key: row.goals for row in review.posts}, {"back": 2})
        self.assertEqual({row.key: (row.goals, row.chances) for row in review.takers}, {"ST": (2, 1)})
        right_back = next(record for record in review.zone if record.name == "Hungerford Town DR1")
        self.assertEqual((right_back.goals, right_back.chances, right_back.minutes), (2, 0, 180))
        self.assertEqual([moment.date.isoformat() for moment in review.moments],
                         ["2020-08-22", "2020-08-15", "2020-08-15"])

    def test_the_export_holds_every_moment_and_names_the_guesses(self) -> None:
        document = json.loads(json.dumps(conceded_json(review_conceded(
            [match(goal(30, "away", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS))], US["id"]))))
        (moment,) = document["moments"]
        self.assertEqual((moment["post_guess"], moment["delivered_down"]), ("back", "left"))
        self.assertEqual(set(document["guesses"]), {"post", "zone", "possibly_from_corners"})


def capture_with_conceded() -> dict:
    document = capture_document(season())
    document["matches"].append(match(goal(30, "away", ALPHA, STL, assist=MR, descriptor=HEADER_FROM_CROSS),
                                     day="2019-09-14").to_document())
    return document


class SurfaceTests(WebServerHelpers, unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.db = self.directory / "history.sqlite3"
        self.store = MatchHistoryStore(self.db)
        capture = self.directory / "capture.json"
        capture.write_text(json.dumps(capture_with_conceded()), encoding="utf-8")
        record_capture_file(self.store, capture)
        self.history = self.store.load_history(self.store.latest_save_key())
        self.key = f"2019-09-14:{US['id']}:{ALPHA['id']}"

    def test_the_page_shows_every_goal_and_chance_with_the_shared_figures(self) -> None:
        port = self._serve(FIXTURE, match_store=self.store)
        status, body = self._get(port, "/conceded")
        self.assertEqual(status, 200)
        for heading in ("How we concede", "Where they come from", "Our players around", "Every goal and chance"):
            self.assertIn(heading, body)
        self.assertIn("href=\"/conceded\" class=\"active\"", body)
        self.assertNotIn("Group opponents by", body)
        self.assertIn("Hungerford Town DR1 (DR)", body)
        self.assertEqual(self._get(port, "/conceded?group=bogus")[0], 400)
        status, page = self._get(port, "/matches/" + self.key.replace(":", "%3A"))
        self.assertIn("Goals and chances conceded", page)
        self.assertIn("Back post", page)

    def test_the_match_copy_and_the_command_carry_the_same_figures(self) -> None:
        report = build_match_report(self.history, self.key)
        export = build_match_export(self.history, report)
        self.assertEqual(export["conceded"]["moments"][0]["post_guess"], "back")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--db", str(self.db), "conceded", "--json"]), 0)
        expected = conceded_json(build_conceded_review(
            self.history, [m for m in self.history.matches if not m.competition.is_friendly]))
        self.assertEqual(json.loads(output.getvalue()), json.loads(json.dumps(expected)))
        output = io.StringIO()
        with redirect_stdout(output):
            main(["--db", str(self.db), "conceded"])
        self.assertIn("back post (guess)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
