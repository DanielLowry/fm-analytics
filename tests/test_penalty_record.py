import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.domain.matches import MatchCapture
from fm_analytics.match_ingest import main as fm_matches
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_match_report, build_match_review, build_penalty_record, build_season_export

from tests.match_support import capture_document, player, season

KEY = "club:100"
DETAILED = "2019-09-01:100:201"


def with_penalty_against_us(*, game_date: str = "2019-09-05") -> dict:
    """`season()`, its detailed match now 2-1 with Alpha's goal a 50th-minute penalty, and a substitute who
    came on after it."""
    matches = season()
    found = matches[-1]
    found["incidents"] = [
        {"minute": 12, "addedTime": 0, "side": "home", "kind": "goal", "playerShortId": 1010, "player": "Home 11"},
        {"minute": 50, "addedTime": 0, "side": "away", "kind": "penalty", "playerShortId": 1510, "player": "Away 11"},
        {"minute": 90, "addedTime": 3, "side": "home", "kind": "goal", "playerShortId": 1009, "player": "Home 10"},
    ]
    found["detail"]["players"].append(player("home", 11, 0x80, name="Late Sub", came_on=70))
    found["detail"]["events"][1] = {"minute": 50, "side": "away", "kind": "penalty", "code": 3, "playerShortId": 1510}
    return capture_document(matches, game_date=game_date)


class PenaltyRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "history.sqlite3"
        self.store = MatchHistoryStore(self.database)
        self.store.record(MatchCapture.from_document(with_penalty_against_us()), save_key=KEY)

    def report(self):
        return build_match_report(self.store.load_history(KEY), DETAILED)

    def test_a_penalty_against_us_offers_who_was_on_the_pitch_then(self) -> None:
        (penalty,) = self.report().penalties
        self.assertEqual((penalty.clock, penalty.taker, penalty.opponent), ("50", "Away 11", "Alpha"))
        names = [name for _short_id, name in penalty.on_pitch]
        self.assertEqual(len(names), 11)
        self.assertNotIn("Late Sub", names)  # on at 70′, after the penalty
        self.assertIsNone(penalty.given_away_by)

    def test_who_gave_it_away_is_recorded_shown_tallied_and_can_be_cleared(self) -> None:
        self.store.record_penalty_foul(KEY, DETAILED, 50, 0, 1003)
        report = self.report()
        self.assertEqual(report.penalties[0].given_away_by, "Home 4")
        entry = next(entry for entry in report.timeline.entries if entry.kind == "penalty")
        self.assertEqual((entry.player, entry.given_away_by, entry.ours), ("Away 11", "Home 4", False))
        history = self.store.load_history(KEY)
        record = build_penalty_record(history, build_match_review(history))
        self.assertEqual((record.by_player, len(record.unrecorded)), ((("Home 4", 1),), 0))
        self.store.record_penalty_foul(KEY, DETAILED, 50, 0, 1004)  # the latest wins
        self.assertEqual(self.report().penalties[0].given_away_by, "Home 5")
        self.store.record_penalty_foul(KEY, DETAILED, 50, 0, None)
        self.assertIsNone(self.report().penalties[0].given_away_by)

    def test_reading_matches_from_fm_again_never_loses_the_record(self) -> None:
        self.store.record_penalty_foul(KEY, DETAILED, 50, 0, 1003)
        # A later read of FM sees the match again (with something changed, so it is stored again).
        later = with_penalty_against_us(game_date="2019-09-12")
        later["matches"][-1]["attendance"] = 612
        self.assertEqual(self.store.record(MatchCapture.from_document(later), save_key=KEY).versions_added, 1)
        self.assertEqual(self.report().penalties[0].given_away_by, "Home 4")
        exported = build_season_export(self.store.load_history(KEY), detail="basic", bundle=None, squad_note="none")
        goals = next(match for match in exported["matches"] if match["key"] == DETAILED)["goals"]
        self.assertEqual(goals[1]["given_away_by"], "Home 4")

    def test_only_a_penalty_fm_shows_against_us_and_a_player_on_the_pitch_can_be_recorded(self) -> None:
        for minute, player_id, message in ((51, 1003, "no penalty"), (50, 1011, "not one of yours"),
                                           (50, 1503, "not one of yours")):
            with self.assertRaisesRegex(ValueError, message):
                self.store.record_penalty_foul(KEY, DETAILED, minute, 0, player_id)
        with self.assertRaisesRegex(ValueError, "no match"):
            self.store.record_penalty_foul(KEY, "2019-09-02:100:201", 50, 0, 1003)

    def test_the_command_line_records_by_name_and_refuses_an_unclear_one(self) -> None:
        def run(*args: str) -> str:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                fm_matches(["--db", str(self.database), "--save", KEY, *args])
            return out.getvalue()

        self.assertIn("Recorded: Home 4 gave away the 50′ penalty.", run("penalty", DETAILED, "50", "--player", "home 4"))
        self.assertIn("does not pick out one", run("penalty", DETAILED, "50", "--player", "Home"))
        self.assertIn("Home 4", run("review"))
        self.assertIn("Cleared.", run("penalty", DETAILED, "50", "--clear"))
        self.assertIn("not recorded: 2019-09-01 v Alpha 50′", run("review"))


if __name__ == "__main__":
    unittest.main()
