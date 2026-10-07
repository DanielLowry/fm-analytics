import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from fm_analytics.analytics.match_interventions import InterventionProposal, InterventionSnapshot
from fm_analytics.domain.matches import MatchCapture
from fm_analytics.persistence.match_history import (
    MIGRATIONS,
    MatchHistoryError,
    MatchHistoryStore,
    MatchTimelineError,
)

from tests.match_support import LEAGUE_RESULTS, US, capture_document, season

KEY = "club:100"
DETAILED = "2019-09-01:100:201"


def intervention() -> InterventionProposal:
    return InterventionProposal(
        finding_key="finishing_recent",
        problem_class="finishing",
        title="Test finishing selection",
        hypothesis="Conversion may be the issue.",
        controlled_intervention="Change one forward only.",
        expected_benefit="More goals from the same chances.",
        success_condition="Conversion improves.",
        stop_condition="Chance supply falls.",
        target_matches=5,
        started_after_date=date(2019, 9, 1),
        started_after_match_key=DETAILED,
        baseline=InterventionSnapshot(
            matches=5, points_per_game=1.0, conversion_pct=8.0,
            shots_for=10.0, clear_cut_chances_for=1.5,
            shots_against=9.0, clear_cut_chances_against=0.8,
            adjusted_shots_for=0.0, adjusted_clear_cut_chances_for=0.0,
            adjusted_clear_cut_chances_against=0.0,
        ),
        manager_note="Try Appau",
    )


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

    def test_usual_roles_are_per_save_and_the_latest_per_slot_wins(self) -> None:
        self.store.set_usual_role(KEY, "vertical_442", "DCL", "cd_cover")
        self.store.set_usual_role(KEY, "vertical_442", "DCL", "cd_defend")
        self.store.set_usual_role(KEY, "vertical_442", "DCR", "cd_defend")
        self.assertEqual(self.store.load_history(KEY).usual_roles, {
            ("vertical_442", "DCL"): "cd_defend", ("vertical_442", "DCR"): "cd_defend",
        })
        with self.assertRaises(ValueError):
            self.store.set_usual_role("club:999", "vertical_442", "DCL", "cd_defend")  # no such save
        with self.assertRaises(ValueError):
            self.store.set_usual_role(KEY, "vertical_442", " ", "cd_defend")

    def test_one_intervention_is_active_until_an_append_only_outcome_closes_it(self) -> None:
        started = self.store.start_intervention(KEY, intervention())
        self.assertTrue(started.active)
        history = self.store.load_history(KEY)
        self.assertEqual(history.interventions[0].proposal.manager_note, "Try Appau")
        with self.assertRaisesRegex(ValueError, "active intervention"):
            self.store.start_intervention(KEY, intervention())

        self.store.finish_intervention(
            KEY, started.id, outcome="not_supported", note="No improvement"
        )
        closed = self.store.load_history(KEY).interventions[0]
        self.assertFalse(closed.active)
        self.assertEqual((closed.outcome, closed.outcome_note), ("not_supported", "No improvement"))
        # Closing is an event, not a mutation of the frozen starting record.
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM interventions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM intervention_events").fetchone()[0], 1)
        self.assertTrue(self.store.start_intervention(KEY, intervention()).active)

    def test_intervention_input_and_outcomes_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "500"):
            self.store.start_intervention(
                KEY, InterventionProposal(**{**intervention().__dict__, "manager_note": "x" * 501})
            )
        started = self.store.start_intervention(KEY, intervention())
        with self.assertRaisesRegex(ValueError, "outcome"):
            self.store.finish_intervention(KEY, started.id, outcome="maybe")


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

    def write_v1_history(self) -> None:
        """A v1 file as the program of the time wrote it: one capture's matches and league results."""
        MatchHistoryStore(self.path, migrations=MIGRATIONS[:1]).initialize()
        recorded = capture()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO saves VALUES (1, ?, ?, ?, '2026-09-29T10:00:00+00:00')",
                               (KEY, US["id"], US["name"]))
            connection.execute("INSERT INTO captures VALUES (1, 1, ?, ?, ?, 'v1', ?, ?, ?)",
                               (recorded.captured_at, recorded.game_date.isoformat(), recorded.captured_at,
                                len(recorded.matches), len(recorded.matches), len(LEAGUE_RESULTS)))
            for match in recorded.matches:
                connection.execute(
                    "INSERT INTO match_versions (save_id, match_key, match_date, has_detail, content_hash, "
                    "document, capture_id) VALUES (1, ?, ?, ?, ?, ?, 1)",
                    (match.key, match.date.isoformat(), int(match.detail is not None), match.content_hash(),
                     json.dumps(match.to_document(), sort_keys=True)),
                )
            for competition, rows in recorded.league_results:
                for row in rows:
                    connection.execute(
                        "INSERT INTO league_results VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                        (competition.id, competition.name, competition.short_name, row.date.isoformat(),
                         row.home.id, row.home.name, row.away.id, row.away.name, row.home_goals, row.away_goals),
                    )

    def test_a_real_v1_history_is_upgraded_to_the_latest_schema(self) -> None:
        self.write_v1_history()
        self.assertEqual(self.user_version(), 1)
        history = self.store.load_history(KEY)
        self.assertEqual((len(history.matches), history.interventions, history.usual_roles), (6, (), {}))
        ((_league, results),) = history.league_results
        self.assertEqual(len(results), len(LEAGUE_RESULTS))
        self.assertEqual({result.season for result in results}, {None})  # unknown until a capture says
        self.assertEqual(self.user_version(), len(MIGRATIONS))
        self.assertEqual(self.user_version(self.path.with_name(self.path.name + ".bak-v1")), 1)

    def test_a_later_capture_fills_in_only_the_seasons_that_were_unknown(self) -> None:
        self.write_v1_history()
        tagged = [dict(row, season=2019) for row in LEAGUE_RESULTS]
        self.store.record(capture(league_results=tagged, game_date="2019-09-06"), save_key=KEY)
        before = self.store.load_history(KEY).league_results[0][1]
        self.assertEqual({result.season for result in before}, {2019})
        # A season once known stays as recorded, like the rest of the result.
        retagged = [dict(row, season=2020, homeGoals=9) for row in LEAGUE_RESULTS]
        self.store.record(capture(league_results=retagged, game_date="2019-09-07"), save_key=KEY)
        self.assertEqual(self.store.load_history(KEY).league_results[0][1], before)

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
