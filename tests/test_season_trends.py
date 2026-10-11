import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics.match_analysis import ReviewFilters
from fm_analytics.analytics.season_trends import season_trends
from fm_analytics.domain.mentality import MentalityPlan
from fm_analytics.match_ingest import format_trends, record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import (
    build_match_breakdowns,
    build_match_review,
    build_matches_export,
    build_season_trends,
)

from tests.match_support import ALPHA, BRAVO, CHARLIE, US, capture_document, detail, lineup, match, player, team_stats
from tests.test_match_breakdowns import STRIKER, THEIR_STRIKER, goal, shot
from tests.test_web_matches import MatchPagesCase



def _match(day, home, away, home_goals, away_goals, *, incidents, shots, subs=()) -> dict:
    """A match with full stats, its goals timed and its shots; `subs` are (side, minute) substitutions."""
    players = lineup("home") + lineup("away")
    for index, (side, minute) in enumerate(subs):
        players.append(player(side, 11 + index, 0x80, name=f"{side.title()} sub {index + 1}", came_on=minute))
        players[(9 if side == "home" else 20) - index]["wentOff"] = minute
    found = detail(home=team_stats(goals=home_goals), away=team_stats(goals=away_goals), players=players)
    found["shots"] = list(shots)
    document = match(day, home, away, home_goals, away_goals, detail=found)
    document["incidents"] = list(incidents)
    return document


def led_and_drew() -> dict:
    """Us 1-1 Alpha: ahead from the 20th minute, level from the 80th. Our sub at 60′, theirs at 70′."""
    return _match(
        "2019-09-01", US, ALPHA, 1, 1,
        incidents=[goal(20, "home", STRIKER), goal(80, "away", THEIR_STRIKER)],
        shots=[shot("home", STRIKER, 19, 30), shot("away", THEIR_STRIKER, 30, 0), shot("away", THEIR_STRIKER, 50, 0),
               shot("away", THEIR_STRIKER, 79, 30)],
        subs=[("home", 60), ("away", 70)],
    )


def came_back() -> dict:
    """Bravo 1-2 us: behind from the 10th minute, level from the 50th, ahead from the 88th."""
    return _match(
        "2019-09-08", BRAVO, US, 1, 2,
        incidents=[goal(10, "home", 1010), goal(50, "away", 1510), goal(88, "away", 1510)],
        shots=[shot("home", 1010, 9, 0), shot("away", 1510, 49, 0), shot("away", 1510, 87, 30)],
    )


def won_with_a_red_card() -> dict:
    """Us 1-0 Charlie with one of theirs sent off: a lead held, but out of the chance figures."""
    return _match(
        "2019-09-15", US, CHARLIE, 1, 0,
        incidents=[goal(30, "home", STRIKER),
                   {"minute": 40, "addedTime": 0, "side": "away", "kind": "sent_off", "playerShortId": 1503}],
        shots=[shot("home", STRIKER, 29, 0)],
    )


class TrendsCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = MatchHistoryStore(Path(directory.name) / "history.sqlite3")
        self.capture = Path(directory.name) / "capture.json"

    def history(self, matches: list[dict]):
        self.capture.write_text(json.dumps(capture_document(matches, game_date="2019-10-01")), encoding="utf-8")
        record_capture_file(self.store, self.capture)
        return self.store.load_history("club:100")


class SeasonTrendTests(TrendsCase):
    def test_leads_not_won_their_chances_while_ahead_and_the_last_15_minutes_are_counted(self) -> None:
        history = self.history([led_and_drew(), came_back(), won_with_a_red_card()])
        review = build_match_review(history, filters=ReviewFilters(competitions="all"))
        trends = build_season_trends(review)
        (season,) = trends.windows  # three matches: no last 10 or last 5
        self.assertEqual((season.matches, season.timed, season.led, season.led_won, season.led_drawn), (3, 3, 3, 2, 1))
        self.assertEqual(season.dropped, 2)  # the draw after leading
        self.assertEqual([match.opponent for match in trends.dropped_matches], ["Alpha"])
        self.assertEqual(trends.dropped_matches[0].goals, (("20", 1, 0), ("80", 1, 1)))
        # They led once (Bravo) and lost: two of four leads were won, both sides counted.
        self.assertEqual(season.usual_hold, 0.5)
        # After 75′: conceded at 80 (a draw from 1-0, two lost); scored at 88 (a win from 1-1, two won).
        self.assertEqual((season.late_goals, season.late_won, season.late_lost), ((1, 1), 2, 2))
        # The red-card match counts in the results, not in the chances, as in the By the score panel.
        self.assertEqual((season.split_matches, dict(trends.left_out)), (2, {"a sending-off": 1}))
        ahead = season.by_state["ahead"]
        self.assertEqual(ahead.shots[1], 3)  # their three shots from 20′ to 80′, the equaliser's included
        breakdowns = build_match_breakdowns(history, review)
        self.assertEqual((ahead.minutes, ahead.shots), (breakdowns.by_state["ahead"].minutes, breakdowns.by_state["ahead"].shots))
        self.assertEqual(season.late.shots, breakdowns.by_period["76–90+"].shots)

    def test_each_change_is_set_against_the_15_minutes_before_it_by_the_score_then(self) -> None:
        history = self.history([led_and_drew()])
        trends = build_season_trends(build_match_review(history, filters=ReviewFilters(competitions="all")))
        ours, theirs = trends.changes
        self.assertEqual((ours.minute, ours.ours, ours.kind, ours.state, ours.score), (60, True, "substitution", "ahead", (1, 0)))
        self.assertEqual(ours.what, "On: Home sub 1; off: Home 10")
        self.assertEqual((ours.before.minutes, ours.before.shots, ours.after.minutes, ours.after.shots),
                         (15, [0, 1], 15, [0, 0]))
        # Theirs at 70′: the 15 minutes after hold their 79:30 equaliser.
        self.assertEqual((theirs.minute, theirs.ours, theirs.after.shots, theirs.after.goals), (70, False, [0, 1], [0, 1]))
        self.assertEqual([group.key for group in trends.change_groups], ["substitutions", "substitutions_ahead", "theirs"])

    def test_a_recorded_mentality_change_counts_and_shares_a_minute_with_a_substitution(self) -> None:
        history = self.history([led_and_drew()])
        (row,) = build_match_review(history, filters=ReviewFilters(competitions="all")).matches
        row = replace(row, mentality=MentalityPlan.parse("Balanced, 60 Cautious, 85 Positive"))
        trends = season_trends([row])
        ours = [change for change in trends.changes if change.ours]
        self.assertEqual([(change.minute, change.kind) for change in ours], [(60, "both"), (85, "mentality")])
        self.assertEqual(ours[0].what, "On: Home sub 1; off: Home 10; Balanced to Cautious")
        # The window after 60′ stops at the next change, at 85′, which is "before" it.
        self.assertEqual((ours[0].after.minutes, ours[1].before.minutes), (15, 15))
        self.assertEqual((trends.group("substitutions").changes, trends.group("mentality").changes), (1, 2))
        self.assertEqual(ours[1].state, "level")  # 1-1 from the 80th

    def test_the_last_10_and_last_5_appear_once_there_are_more_matches_than_that(self) -> None:
        results = [match(f"2019-08-{day:02d}", US, ALPHA if day % 2 else BRAVO, 1, 0) for day in range(1, 8)]
        for document in results:
            document["incidents"] = [goal(85, "home", STRIKER)]
        trends = build_season_trends(build_match_review(self.history(results), filters=ReviewFilters(competitions="all")))
        self.assertEqual([window.key for window in trends.windows], ["season", "last5"])
        self.assertEqual((trends.window("season").late_won, trends.window("last5").late_won), (14, 10))
        self.assertEqual([match.late_so_far for match in trends.matches], [2, 4, 6, 8, 10, 12, 14])
        self.assertEqual(trends.window("season").split_matches, 0)  # results only: no chance figures
        self.assertEqual(trends.change_groups, ())


class SharedTrendTests(MatchPagesCase):
    def setUp(self) -> None:
        MatchPagesCase.setUp(self)
        self.capture.write_text(json.dumps(capture_document(
            [led_and_drew(), came_back(), won_with_a_red_card()], game_date="2019-10-01")), encoding="utf-8")

    def test_the_page_the_command_line_and_the_export_show_the_same_trends(self) -> None:
        self.record()
        history = self.store.load_history("club:100")
        filters = ReviewFilters(competitions="all")
        trends = build_season_trends(build_match_review(history, filters=filters))
        _status, body = self._get(self.serve(), "/matches?competitions=all")
        self.assertIn("<h2>Season trends</h2>", body)
        self.assertIn("The 1 match you led and did not win", body)
        self.assertIn("Their substitutions, for comparison", body)
        self.assertIn("1–0 <span class='muted'>20′</span> · 1–1 <span class='muted'>80′</span>", body)
        text = format_trends(trends)
        self.assertIn("dropped from winning positions: 2 points (led in 3: won 2, drew 1, lost 0, usually 50%", text)
        self.assertIn("after 75′: goals 1–1, clear-cut chances 0–0, points +2 / −2", text)
        exported = build_matches_export(history, filters=filters)["season_trends"]
        (window,) = exported["windows"]
        self.assertEqual((window["points_dropped_from_winning_positions"], window["after_75"]),
                         (2, {"goals": [1, 1], "points_won": 2, "points_lost": 2}))
        self.assertEqual(exported["left_out_of_chance_figures"], {"a sending-off": 1})
        self.assertEqual([change["by"] for change in exported["each_change"]], ["us", "them"])


if __name__ == "__main__":
    unittest.main()
