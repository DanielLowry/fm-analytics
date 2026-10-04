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

    def test_team_corners_recorded_under_the_archive_readers_old_name_read_as_corners(self) -> None:
        document = self.match.to_document()
        document["detail"]["home"]["corners_taken"] = document["detail"]["home"].pop("corners")
        again = MatchRecord.from_document(document)
        self.assertEqual(again.detail.home["corners"], 3)
        self.assertNotIn("corners_taken", again.detail.home)
        self.assertEqual(again.content_hash(), self.match.content_hash())

    def test_incidents_round_trip_and_an_empty_list_keeps_the_old_content_hash(self) -> None:
        document = self.match.to_document()
        self.assertNotIn("incidents", document)
        document["incidents"] = [
            {"minute": 90, "addedTime": 4, "side": "home", "kind": "penalty", "playerShortId": 7, "player": "Home 11"},
            {"minute": 18, "side": "away", "kind": "sent_off", "playerShortId": 9},
        ]
        record = MatchRecord.from_document(document)
        self.assertEqual([incident.clock for incident in record.incidents], ["90+4", "18"])
        self.assertEqual([incident.is_goal for incident in record.incidents], [True, False])
        self.assertEqual(MatchRecord.from_document(record.to_document()), record)
        self.assertNotEqual(record.content_hash(), self.match.content_hash())
        document["incidents"] = []
        self.assertEqual(MatchRecord.from_document(document).content_hash(), self.match.content_hash())

    def test_extra_time_and_a_shootout_round_trip_and_are_absent_otherwise(self) -> None:
        self.assertFalse(self.match.after_extra_time)
        self.assertNotIn("scoreAt90", self.match.to_document())
        document = self.match.to_document()
        document.update({"scoreAt90": [1, 1], "penalties": [5, 4]})
        record = MatchRecord.from_document(document)
        self.assertTrue(record.after_extra_time)
        self.assertEqual((record.score_at_90, record.penalties), ((1, 1), (5, 4)))
        self.assertEqual(MatchRecord.from_document(record.to_document()), record)
        document["penalties"] = [5]
        with self.assertRaisesRegex(ValueError, "penalties"):
            MatchRecord.from_document(document)

    def test_positions_round_trip_and_their_absence_keeps_the_old_content_hash(self) -> None:
        document = self.match.to_document()
        self.assertNotIn("position", document["detail"]["players"][0])
        self.assertIsNone(self.match.detail.players[0].position)
        striker = document["detail"]["players"][10]
        striker.update({"position": "ST", "startPosition": "ST", "startCentreSide": "left"})
        substitute = document["detail"]["players"][0]
        substitute.update({"position": "DL", "startPosition": None, "startCentreSide": None})
        record = MatchRecord.from_document(document)
        line = record.detail.players[10]
        self.assertEqual((line.position, line.start_position, line.start_centre_side), ("ST", "ST", "left"))
        self.assertNotIn("startPosition", record.to_document()["detail"]["players"][0])
        self.assertEqual(MatchRecord.from_document(record.to_document()), record)
        self.assertNotEqual(record.content_hash(), self.match.content_hash())
        for line in document["detail"]["players"]:
            line.update({"position": None, "startPosition": None, "startCentreSide": None})
        self.assertEqual(MatchRecord.from_document(document).content_hash(), self.match.content_hash())

    def test_a_saved_tactic_round_trips_and_its_absence_keeps_the_old_content_hash(self) -> None:
        document = self.match.to_document()
        self.assertNotIn("savedTactics", document["detail"])
        document["detail"]["savedTactics"] = {"home": {"name": "Vertical 4-4-2", "slots": [
            {"position": "MC", "centreSide": "right", "roleCode": 0x20, "dutyCode": 0x400000},
            {"position": "DC", "centreSide": "left", "roleCode": 0x2, "dutyCode": 0x4000000},
        ]}}
        record = MatchRecord.from_document(document)
        tactic = record.detail.saved_tactics["home"]
        self.assertEqual(tactic.slot_at("MC", "right").duty, "support")
        self.assertIsNone(tactic.slot_at("DC", "left").duty)  # Cover is only a lead so far
        self.assertIsNone(tactic.slot_at("MC", "left"))
        self.assertEqual(MatchRecord.from_document(record.to_document()), record)
        self.assertNotEqual(record.content_hash(), self.match.content_hash())
        del document["detail"]["savedTactics"]
        self.assertEqual(MatchRecord.from_document(document).content_hash(), self.match.content_hash())

    def test_a_position_or_centre_side_fm_does_not_have_is_refused(self) -> None:
        for key, value in (("position", "STC"), ("startPosition", "CB"), ("startCentreSide", "middle")):
            document = self.match.to_document()
            document["detail"]["players"][10][key] = value
            with self.assertRaisesRegex(ValueError, key):
                MatchRecord.from_document(document)

    def test_an_incident_of_an_unknown_kind_is_refused(self) -> None:
        document = self.match.to_document()
        document["incidents"] = [{"minute": 5, "side": "home", "kind": "missed_penalty", "playerShortId": 1}]
        with self.assertRaisesRegex(ValueError, "kind"):
            MatchRecord.from_document(document)

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
