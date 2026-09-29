import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fm_analytics.domain.matches import MatchCapture
from fm_analytics.persistence.match_history import (
    MIGRATIONS,
    MatchHistoryError,
    MatchHistoryStore,
    MatchTimelineError,
)

from tests.match_support import capture_document, season

KEY = "club:100"
DETAILED = "2019-09-01:100:201"


def capture(matches=None, **kwargs) -> MatchCapture:
    return MatchCapture.from_document(capture_document(season() if matches is None else matches, **kwargs))


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "match-history.sqlite3"
        self.store = MatchHistoryStore(self.path)


class RecordingTests(StoreCase):
    def test_a_capture_records_every_match_and_league_result(self) -> None:
        result = self.store.record(capture(), save_key=KEY)
        self.assertEqual((result.matches_seen, result.versions_added, result.league_results_added), (6, 6, 8))
        history = self.store.load_history(KEY)
        self.assertEqual(len(history.matches), 6)
        self.assertEqual(history.club.name, "Hungerford Town")
        self.assertEqual(len(history.league_results[0][1]), 8)

    def test_recording_the_same_capture_twice_adds_nothing(self) -> None:
        self.store.record(capture(), save_key=KEY)
        again = self.store.record(capture(), save_key=KEY)
        self.assertTrue(again.skipped)
        self.assertEqual(self.store.saves()[0].captures, 1)

    def test_a_later_capture_without_the_stats_never_hides_them(self) -> None:
        self.store.record(capture(), save_key=KEY)
        matches = season()
        matches[-1]["detail"] = None  # FM no longer holds this match's stats
        later = self.store.record(capture(matches, game_date="2019-09-12"), save_key=KEY)
        self.assertEqual(later.versions_added, 1)
        current = {match.key: match for match in self.store.load_history(KEY).matches}
        self.assertIsNotNone(current[DETAILED].detail)
        self.assertEqual(len(self.store.match_versions(KEY, DETAILED)), 2)

    def test_newer_stats_for_the_same_match_replace_older_ones_but_both_are_kept(self) -> None:
        self.store.record(capture(), save_key=KEY)
        matches = season()
        matches[-1]["detail"]["home"]["shots"] = 13
        self.store.record(capture(matches, game_date="2019-09-12"), save_key=KEY)
        current = {match.key: match for match in self.store.load_history(KEY).matches}
        self.assertEqual(current[DETAILED].detail.home["shots"], 13)
        self.assertEqual([m.detail.home["shots"] for m in self.store.match_versions(KEY, DETAILED)], [12, 13])

    def test_two_saves_never_share_matches(self) -> None:
        self.store.record(capture(), save_key=KEY)
        self.store.record(capture(season()[:2]), save_key="other-save")
        self.assertEqual(len(self.store.load_history(KEY).matches), 6)
        self.assertEqual(len(self.store.load_history("other-save").matches), 2)
        self.assertIsNone(self.store.load_history("never-recorded"))

    def test_a_capture_older_than_the_save_is_refused_unless_allowed(self) -> None:
        self.store.record(capture(game_date="2019-09-05"), save_key=KEY)
        older = capture(season()[:3], game_date="2019-08-20")
        with self.assertRaises(MatchTimelineError):
            self.store.record(older, save_key=KEY)
        self.assertEqual(self.store.saves()[0].captures, 1)
        self.store.record(older, save_key=KEY, allow_rewind=True)
        self.assertEqual(self.store.saves()[0].captures, 2)

    def test_the_latest_save_is_the_one_last_recorded(self) -> None:
        self.assertIsNone(self.store.latest_save_key())
        self.store.record(capture(), save_key=KEY)
        self.store.record(capture(season()[:2]), save_key="other-save")
        self.assertEqual(self.store.latest_save_key(), "other-save")


class NotesAndRoleCodeTests(StoreCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.record(capture(), save_key=KEY)

    def test_the_latest_note_wins_and_earlier_ones_stay(self) -> None:
        self.store.add_note(KEY, DETAILED, tactic_key="vertical_442", opponent_rating=1, note="first")
        self.store.add_note(KEY, DETAILED, tactic_key="wing_play_442", opponent_rating=None, note="  second  ")
        note = self.store.load_history(KEY).notes[DETAILED]
        self.assertEqual((note.tactic_key, note.opponent_rating, note.note), ("wing_play_442", None, "second"))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM match_notes").fetchone()[0], 2)

    def test_a_note_is_validated(self) -> None:
        for rating in (3, -3, True):
            with self.assertRaisesRegex(ValueError, "rating"):
                self.store.add_note(KEY, DETAILED, tactic_key=None, opponent_rating=rating)
        with self.assertRaisesRegex(ValueError, "1000"):
            self.store.add_note(KEY, DETAILED, tactic_key=None, opponent_rating=None, note="x" * 1001)
        with self.assertRaisesRegex(ValueError, "no match"):
            self.store.add_note(KEY, "2019-01-01:1:2", tactic_key=None, opponent_rating=0)

    def test_a_confirmed_role_code_is_kept_and_the_latest_wins(self) -> None:
        self.store.confirm_role_code(0x40000, "pf_attack")
        self.store.confirm_role_code(0x40000, "af_attack")
        self.assertEqual(self.store.load_history(KEY).role_codes, {0x40000: "af_attack"})
        with self.assertRaises(ValueError):
            self.store.confirm_role_code(0, "af_attack")


class MigrationTests(StoreCase):
    ADD_COLUMN = "ALTER TABLE match_notes ADD COLUMN mood TEXT;"

    def user_version(self, path: Path | None = None) -> int:
        with closing(sqlite3.connect(path or self.path)) as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def test_a_new_file_is_created_at_the_latest_version(self) -> None:
        self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS))

    def test_an_older_file_is_backed_up_then_upgraded_with_its_matches_intact(self) -> None:
        self.store.record(capture(), save_key=KEY)
        upgraded = MatchHistoryStore(self.path, migrations=(*MIGRATIONS, self.ADD_COLUMN))
        self.assertEqual(len(upgraded.load_history(KEY).matches), 6)
        self.assertEqual(self.user_version(), len(MIGRATIONS) + 1)
        backup = self.path.with_name(self.path.name + f".bak-v{len(MIGRATIONS)}")
        self.assertEqual(self.user_version(backup), len(MIGRATIONS))

    def test_a_file_from_a_newer_program_is_refused_not_touched(self) -> None:
        MatchHistoryStore(self.path, migrations=(*MIGRATIONS, self.ADD_COLUMN)).initialize()
        with self.assertRaisesRegex(MatchHistoryError, "newer than this program"):
            self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS) + 1)

    def test_a_sqlite_file_that_is_not_ours_is_refused(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TABLE something_else (x)")
        with self.assertRaisesRegex(MatchHistoryError, "not a match-history database"):
            self.store.initialize()


if __name__ == "__main__":
    unittest.main()
