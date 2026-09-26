import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence.player_knowledge import (
    MIGRATIONS,
    KnowledgeCapture,
    KnowledgeStoreError,
    PlayerKnowledge,
    PlayerKnowledgeStore,
    TimelineError,
)


def known(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


def spread(low: int, high: int) -> AttributeObservation:
    return AttributeObservation(Visibility.RANGE, minimum=low, maximum=high)


UNKNOWN = AttributeObservation(Visibility.UNKNOWN)


def player(player_id="1", name="Ada Winger", profile=None, attributes=None, **extra):
    return PlayerKnowledge(
        player_id, name, {"positions": ("AML",), **(profile or {})}, attributes or {}, **extra
    )


def capture(game_date, *players, key="club:1", captured_at="2026-09-26T10:00:00+00:00"):
    return KnowledgeCapture(
        key, game_date, captured_at, tuple(players), club_id="1", club_name="Hungerford Town"
    )


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "knowledge.sqlite3"
        self.store = PlayerKnowledgeStore(self.path)

    def count(self, table: str) -> int:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class RecordingTests(StoreCase):
    def test_first_recording_reports_what_it_added(self) -> None:
        result = self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(14), "passing": spread(9, 13)}))
        )
        self.assertFalse(result.skipped)
        self.assertEqual(
            (result.players_seen, result.new_players, result.profile_rows, result.attribute_rows),
            (1, 1, 1, 2),
        )

    def test_recording_the_same_capture_twice_adds_nothing(self) -> None:
        first = capture("2019-09-08", player(attributes={"pace": known(14)}))
        self.store.record(first)
        before = [self.count(t) for t in ("ingests", "profile_observations", "attribute_observations")]
        again = self.store.record(first)
        self.assertTrue(again.skipped)
        self.assertEqual(
            before,
            [self.count(t) for t in ("ingests", "profile_observations", "attribute_observations")],
        )

    def test_the_same_content_captured_at_another_moment_is_still_skipped(self) -> None:
        self.store.record(capture("2019-09-08", player(), captured_at="2026-09-26T10:00:00+00:00"))
        again = self.store.record(
            capture("2019-09-08", player(), captured_at="2026-09-26T18:30:00+00:00")
        )
        self.assertTrue(again.skipped)

    def test_only_attributes_that_changed_are_appended(self) -> None:
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": spread(10, 16), "passing": known(11)}))
        )
        result = self.store.record(
            capture("2019-09-15", player(attributes={"pace": spread(12, 15), "passing": known(11)}))
        )
        self.assertEqual(result.attribute_rows, 1)
        history = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual(
            [(item.observed_on, item.observation) for item in history],
            [("2019-09-08", spread(10, 16)), ("2019-09-15", spread(12, 15))],
        )
        self.assertEqual(len(self.store.attribute_history("club:1", "1", "passing")), 1)

    def test_an_attribute_fading_to_unknown_is_kept_alongside_what_was_known(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        self.store.record(capture("2019-10-01", player(attributes={"pace": UNKNOWN})))
        history = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual([item.observation for item in history], [known(14), UNKNOWN])

    def test_a_profile_change_adds_a_profile_row_and_no_attribute_row(self) -> None:
        self.store.record(
            capture("2019-09-08", player(profile={"transfer_status": "not_set"}, attributes={"pace": known(14)}))
        )
        result = self.store.record(
            capture("2019-09-15", player(profile={"transfer_status": "transfer_listed"}, attributes={"pace": known(14)}))
        )
        self.assertEqual((result.profile_rows, result.attribute_rows), (1, 0))
        history = self.store.profile_history("club:1", "1")
        self.assertEqual([row["transfer_status"] for row in history], ["not_set", "transfer_listed"])
        self.assertEqual(history[0]["positions"], ["AML"])

    def test_an_unchanged_profile_is_not_repeated_when_only_attributes_change(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        result = self.store.record(capture("2019-09-15", player(attributes={"pace": known(15)})))
        self.assertEqual((result.profile_rows, result.attribute_rows), (0, 1))

    def test_a_player_missing_from_a_later_capture_keeps_his_history(self) -> None:
        self.store.record(
            capture("2019-09-08", player("1", attributes={"pace": known(14)}), player("2", "Bob"))
        )
        self.store.record(capture("2019-09-15", player("2", "Bob")))
        self.assertEqual(len(self.store.attribute_history("club:1", "1")), 1)
        self.assertEqual(self.store.saves()[0].players, 2)

    def test_being_dropped_from_scout_reports_is_recorded_as_a_profile_fact(self) -> None:
        self.store.record(capture("2019-09-08", player(profile={"dropped_from_scout_reports": False})))
        self.store.record(capture("2019-10-01", player(profile={"dropped_from_scout_reports": True})))
        flags = [r["dropped_from_scout_reports"] for r in self.store.profile_history("club:1", "1")]
        self.assertEqual(flags, [False, True])

    def test_matching_the_realistic_search_is_dated(self) -> None:
        self.store.record(capture("2019-09-08", player(profile={"matched_active_search": False})))
        self.store.record(capture("2019-10-01", player(profile={"matched_active_search": True})))
        history = self.store.profile_history("club:1", "1")
        self.assertEqual(
            [(r["observed_on"], r["matched_active_search"]) for r in history],
            [("2019-09-08", False), ("2019-10-01", True)],
        )


class LastKnownAndBackdatingTests(StoreCase):
    def test_a_last_known_snapshot_is_recorded_at_the_date_it_was_seen(self) -> None:
        dropped = player(
            attributes={}, last_known_attributes={"pace": spread(8, 12)},
            last_known_observed_on="2019-07-21",
        )
        self.store.record(capture("2019-09-08", dropped))
        (record,) = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual((record.observed_on, record.source), ("2019-07-21", "last_known"))
        self.assertEqual(record.observation, spread(8, 12))

    def test_seeing_him_earlier_moves_first_seen_back_and_last_seen_forward(self) -> None:
        self.store.record(
            capture(
                "2019-09-08",
                player(last_known_attributes={"pace": known(9)}, last_known_observed_on="2019-07-21"),
            )
        )
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT first_seen_on, last_seen_on FROM players").fetchone()
        self.assertEqual(row, ("2019-07-21", "2019-09-08"))

    def test_a_backdated_reading_equal_to_what_was_already_known_is_skipped(self) -> None:
        self.store.record(capture("2019-06-24", player(attributes={"pace": spread(8, 12)})))
        result = self.store.record(
            capture(
                "2019-09-08",
                player(attributes={"pace": known(11)}, attributes_observed_on="2019-09-08",
                       last_known_attributes={"pace": spread(8, 12)}, last_known_observed_on="2019-06-24"),
            )
        )
        states = [item.observation for item in self.store.attribute_history("club:1", "1", "pace")]
        self.assertEqual(states, [spread(8, 12), known(11)])
        self.assertEqual(result.attribute_rows, 1)

    def test_a_carried_forward_reading_keeps_its_own_older_date(self) -> None:
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(14)}, attributes_observed_on="2019-08-01"))
        )
        (record,) = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual(record.observed_on, "2019-08-01")


class SaveIsolationAndTimelineTests(StoreCase):
    def test_two_saves_never_share_a_history(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)}), key="club:1"))
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(9)}), key="save-b"))
        self.assertEqual(
            self.store.attribute_history("club:1", "1")[0].observation, known(14)
        )
        self.assertEqual(
            self.store.attribute_history("save-b", "1")[0].observation, known(9)
        )
        self.assertEqual({save.key for save in self.store.saves()}, {"club:1", "save-b"})

    def test_a_capture_older_than_the_save_is_refused_and_leaves_nothing_behind(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        before = self.count("attribute_observations")
        with self.assertRaisesRegex(TimelineError, "2019-09-01.*2019-09-08"):
            self.store.record(capture("2019-09-01", player(attributes={"pace": known(3)})))
        self.assertEqual(self.count("attribute_observations"), before)
        self.assertEqual(self.count("ingests"), 1)

    def test_a_rewind_can_be_allowed_explicitly(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        result = self.store.record(
            capture("2019-09-01", player(attributes={"pace": known(13)})), allow_rewind=True
        )
        self.assertFalse(result.skipped)
        self.assertEqual(self.store.saves()[0].first_game_date, "2019-09-01")

    def test_the_same_day_may_be_recorded_again_with_new_information(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": spread(8, 14)})))
        result = self.store.record(capture("2019-09-08", player(attributes={"pace": spread(10, 12)})))
        self.assertEqual(result.attribute_rows, 1)


class AtomicityAndValidationTests(StoreCase):
    def test_a_failure_part_way_through_records_nothing(self) -> None:
        with patch.object(
            PlayerKnowledgeStore, "_record_attributes", side_effect=RuntimeError("disk full")
        ):
            with self.assertRaises(RuntimeError):
                self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        for table in ("saves", "ingests", "players", "profile_observations", "attribute_observations"):
            self.assertEqual(self.count(table), 0, table)

    def test_unknown_profile_fields_are_rejected_rather_than_dropped(self) -> None:
        with self.assertRaisesRegex(ValueError, "current_ability"):
            PlayerKnowledge("1", "A", {"current_ability": 150})

    def test_a_capture_cannot_list_a_player_twice(self) -> None:
        with self.assertRaisesRegex(ValueError, "twice"):
            capture("2019-09-08", player("1"), player("1"))

    def test_dates_must_be_iso(self) -> None:
        with self.assertRaisesRegex(ValueError, "ISO date"):
            capture("08/09/2019", player())
        with self.assertRaisesRegex(ValueError, "ISO date"):
            player(attributes_observed_on="yesterday")

    def test_last_known_attributes_need_a_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "date"):
            player(last_known_attributes={"pace": known(9)})

    def test_the_database_itself_rejects_an_inconsistent_attribute_row(self) -> None:
        self.store.record(capture("2019-09-08", player()))
        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO attribute_observations (save_id, player_id, attribute, "
                    "observed_on, ingest_id, source, visibility, value) "
                    "VALUES (1, '1', 'pace', '2019-09-08', 1, 'current', 'range', 5)"
                )


class MigrationTests(StoreCase):
    ADD_NOTE = "ALTER TABLE saves ADD COLUMN note TEXT;"

    def user_version(self, path: Path | None = None) -> int:
        with closing(sqlite3.connect(path or self.path)) as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def test_a_new_file_is_created_at_the_latest_version(self) -> None:
        self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS))

    def test_initialising_twice_changes_nothing(self) -> None:
        self.store.initialize()
        self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS))
        self.assertFalse(list(self.path.parent.glob("*.bak-*")))

    def test_an_older_file_is_backed_up_then_upgraded_with_its_data_intact(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        upgraded = PlayerKnowledgeStore(self.path, migrations=(*MIGRATIONS, self.ADD_NOTE))

        upgraded.initialize()

        self.assertEqual(self.user_version(), len(MIGRATIONS) + 1)
        backup = self.path.with_name(self.path.name + f".bak-v{len(MIGRATIONS)}")
        self.assertTrue(backup.exists())
        self.assertEqual(self.user_version(backup), len(MIGRATIONS))
        self.assertEqual(upgraded.attribute_history("club:1", "1")[0].observation, known(14))
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("SELECT note FROM saves")  # the new column exists

    def test_a_failing_migration_is_rolled_back_and_the_data_left_usable(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        broken = PlayerKnowledgeStore(
            self.path, migrations=(*MIGRATIONS, "CREATE TABLE half_done (x); THIS IS NOT SQL;")
        )
        with self.assertRaisesRegex(KnowledgeStoreError, "rolled back"):
            broken.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS))
        with closing(sqlite3.connect(self.path)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        self.assertNotIn("half_done", tables)
        self.assertEqual(self.store.attribute_history("club:1", "1")[0].observation, known(14))

    def test_a_file_from_a_newer_program_is_refused_not_touched(self) -> None:
        PlayerKnowledgeStore(self.path, migrations=(*MIGRATIONS, self.ADD_NOTE)).initialize()
        with self.assertRaisesRegex(KnowledgeStoreError, "newer than this program"):
            self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS) + 1)

    def test_some_other_sqlite_file_is_refused(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TABLE unrelated (x)")
        with self.assertRaisesRegex(KnowledgeStoreError, "not a player-knowledge database"):
            self.store.initialize()


if __name__ == "__main__":
    unittest.main()
