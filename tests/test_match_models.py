import unittest
from datetime import date

from fm_analytics.domain.matches import MatchCapture, MatchRecord

from tests.match_support import US, capture_document, season


class MatchCaptureTests(unittest.TestCase):
    def test_a_capture_parses_every_match_and_league_result(self) -> None:
        capture = MatchCapture.from_document(capture_document(season()))
        self.assertEqual(capture.game_date, date(2019, 9, 5))
        self.assertEqual(capture.managed_club.id, US["id"])
        self.assertEqual(len(capture.matches), 6)
        (league, results), = capture.league_results
        self.assertEqual(league.name, "Test League South")
        self.assertEqual(len(results), 8)

    def test_a_document_that_is_not_a_match_capture_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a match capture"):
            MatchCapture.from_document({"format": "something-else"})
        document = capture_document(season())
        document["formatVersion"] = 2
        with self.assertRaisesRegex(ValueError, "version 1"):
            MatchCapture.from_document(document)

    def test_negative_or_non_numeric_counts_are_refused(self) -> None:
        document = capture_document(season())
        document["matches"][1]["homeGoals"] = -1
        with self.assertRaisesRegex(ValueError, "homeGoals"):
            MatchCapture.from_document(document)
        document = capture_document(season())
        document["matches"][-1]["detail"]["home"]["shots"] = "twelve"
        with self.assertRaisesRegex(ValueError, "shots"):
            MatchCapture.from_document(document)


class MatchRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.match = MatchCapture.from_document(capture_document(season())).matches[-1]

    def test_the_key_is_date_and_both_clubs(self) -> None:
        self.assertEqual(self.match.key, "2019-09-01:100:201")

    def test_a_record_round_trips_through_its_document(self) -> None:
        again = MatchRecord.from_document(self.match.to_document())
        self.assertEqual(again, self.match)
        self.assertEqual(again.content_hash(), self.match.content_hash())

    def test_possession_is_each_sides_share_of_possession_time(self) -> None:
        self.assertEqual(self.match.detail.possession_percent("home"), 40)
        self.assertEqual(self.match.detail.possession_percent("away"), 60)

    def test_sides_follow_the_club(self) -> None:
        self.assertEqual(self.match.side_of("100"), "home")
        self.assertEqual(self.match.side_of("201"), "away")
        with self.assertRaises(ValueError):
            self.match.side_of("999")
        self.assertEqual(len(self.match.detail.players_for("home")), 11)

    def test_minutes_count_a_full_match_as_ninety(self) -> None:
        document = capture_document(season())
        players = document["matches"][-1]["detail"]["players"]
        players[5]["wentOff"] = 63
        players[6]["cameOn"] = 63
        match = MatchCapture.from_document(document).matches[-1]
        home = match.detail.players_for("home")
        self.assertEqual([home[0].minutes, home[5].minutes, home[6].minutes], [90, 63, 27])
        self.assertEqual(MatchRecord.from_document(match.to_document()), match)

    def test_off_target_counts_blocked_shots_as_neither(self) -> None:
        from fm_analytics.analytics.match_analysis import side_metrics

        document = capture_document(season())
        document["matches"][-1]["detail"]["players"][9]["stats"]["shots_blocked"] = 2
        match = MatchCapture.from_document(document).matches[-1]
        self.assertEqual(side_metrics(match, "home")["off_target"], 12 - 6 - 2)

    def test_a_result_only_match_has_no_detail(self) -> None:
        first = MatchCapture.from_document(capture_document(season())).matches[1]
        self.assertIsNone(first.detail)


if __name__ == "__main__":
    unittest.main()
