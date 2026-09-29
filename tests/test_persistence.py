import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fm_analytics.domain import GameState, Squad
from fm_analytics.persistence import SnapshotStore, SnapshotStoreError
from fm_analytics.persistence.store import BASELINE_VERSION


ROOT = Path(__file__).resolve().parent.parent
GOLDEN = json.loads(
    (ROOT / "src/fm_analytics/fixtures/sample-game.json").read_text(encoding="utf-8")
)


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "snapshots.sqlite3"
        self.store = SnapshotStore(self.path)
        self.game = GameState.from_dict(GOLDEN["game"])
        self.squad = Squad.from_dict(GOLDEN["squad"])
        self.observed_at = datetime(2026, 9, 11, 8, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_round_trips_complete_squad_observation(self) -> None:
        capture = self.store.capture(
            self.game,
            self.squad,
            source="fixture",
            captured_at=self.observed_at,
        )

        game, squad = self.store.load(capture.id)

        self.assertTrue(capture.created)
        self.assertEqual(game.to_dict(), self.game.to_dict())
        self.assertEqual(squad.to_dict(), self.squad.to_dict())
        self.assertEqual(self.store.latest_capture_id(), capture.id)

    def test_round_trips_other_teams_alongside_the_first_team(self) -> None:
        raw = self.squad.to_dict()
        raw["otherTeams"] = [
            {
                "marker": 9,
                "players": [
                    {**raw["players"][0], "id": "youth-1", "name": "Youth One"},
                    {**raw["players"][0], "id": "youth-2", "name": "Youth Two"},
                ],
            },
            {"marker": 12, "players": [{**raw["players"][0], "id": "youth-3", "name": "Youth Three"}]},
        ]
        squad = Squad.from_dict(raw)

        capture = self.store.capture(
            self.game, squad, source="fixture", captured_at=self.observed_at
        )
        _, loaded = self.store.load(capture.id)

        self.assertEqual(loaded.to_dict(), squad.to_dict())
        self.assertEqual([team.marker for team in loaded.other_teams], [9, 12])
        self.assertEqual(
            [player.id for player in loaded.other_teams[0].players], ["youth-1", "youth-2"]
        )
        self.assertEqual(len(loaded.all_players()), len(squad.all_players()))

    def test_rejects_duplicate_player_id_across_first_team_and_other_teams(self) -> None:
        raw = self.squad.to_dict()
        duplicate_id = raw["players"][0]["id"]
        raw["otherTeams"] = [
            {"marker": 9, "players": [{**raw["players"][0], "id": duplicate_id}]},
        ]

        with self.assertRaisesRegex(ValueError, "unique player IDs"):
            self.store.capture(self.game, Squad.from_dict(raw), source="fixture")

    def test_repeated_identical_observation_is_idempotent(self) -> None:
        first = self.store.capture(self.game, self.squad, source="fixture")
        second = self.store.capture(self.game, self.squad, source="fixture")

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(second.id, first.id)
        with sqlite3.connect(self.path) as connection:
            count = connection.execute("SELECT count(*) FROM captures").fetchone()[0]
        self.assertEqual(count, 1)

    def test_changed_visible_observation_creates_new_capture(self) -> None:
        first = self.store.capture(self.game, self.squad, source="fixture")
        changed = self.squad.to_dict()
        changed["players"][0]["conditionPercent"] = 87

        second = self.store.capture(
            self.game,
            Squad.from_dict(changed),
            source="fixture",
        )

        self.assertNotEqual(second.id, first.id)
        self.assertTrue(second.created)

    def test_rejects_incoherent_game_and_squad_dates(self) -> None:
        changed = self.squad.to_dict()
        changed["asOfDate"] = "2020-08-15"

        with self.assertRaisesRegex(ValueError, "must have the same date"):
            self.store.capture(
                self.game,
                Squad.from_dict(changed),
                source="fixture",
            )

        self.assertFalse(self.path.exists())

    def test_rejects_naive_capture_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            self.store.capture(
                self.game,
                self.squad,
                source="fixture",
                captured_at=datetime(2026, 9, 11, 8, 30),
            )


class SnapshotMigrationTests(unittest.TestCase):
    ADD_NOTE = "ALTER TABLE captures ADD COLUMN note TEXT;"

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "snapshots.sqlite3"
        self.store = SnapshotStore(self.path)
        self.game = GameState.from_dict(GOLDEN["game"])
        self.squad = Squad.from_dict(GOLDEN["squad"])

    def tearDown(self) -> None:
        self.directory.cleanup()

    def user_version(self, path: Path | None = None) -> int:
        with closing(sqlite3.connect(path or self.path)) as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def test_a_fresh_file_is_created_at_the_baseline_version(self) -> None:
        self.store.initialize()

        self.assertEqual(self.user_version(), BASELINE_VERSION)

    def test_initialising_twice_changes_nothing(self) -> None:
        self.store.initialize()
        self.store.initialize()

        self.assertEqual(self.user_version(), BASELINE_VERSION)
        self.assertFalse(list(self.path.parent.glob("*.bak-*")))

    def test_an_existing_baseline_file_keeps_opening_unchanged(self) -> None:
        capture = self.store.capture(self.game, self.squad, source="fixture")

        reopened = SnapshotStore(self.path)
        game, squad = reopened.load(capture.id)

        self.assertEqual(self.user_version(), BASELINE_VERSION)
        self.assertEqual(game.to_dict(), self.game.to_dict())
        self.assertEqual(squad.to_dict(), self.squad.to_dict())
        self.assertFalse(list(self.path.parent.glob("*.bak-*")))

    def test_an_injected_step_upgrades_a_baseline_file_after_a_backup(self) -> None:
        capture = self.store.capture(self.game, self.squad, source="fixture")
        upgraded = SnapshotStore(self.path, migrations=(self.ADD_NOTE,))

        upgraded.initialize()

        self.assertEqual(self.user_version(), BASELINE_VERSION + 1)
        backup = self.path.with_name(self.path.name + f".bak-v{BASELINE_VERSION}")
        self.assertTrue(backup.exists())
        self.assertEqual(self.user_version(backup), BASELINE_VERSION)
        game, squad = upgraded.load(capture.id)
        self.assertEqual(squad.to_dict(), self.squad.to_dict())
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("SELECT note FROM captures")  # the new column exists

    def test_a_failing_migration_is_rolled_back_and_the_data_left_usable(self) -> None:
        self.store.capture(self.game, self.squad, source="fixture")
        broken = SnapshotStore(self.path, migrations=("CREATE TABLE half_done (x); NOT SQL;",))

        with self.assertRaisesRegex(SnapshotStoreError, "rolled back"):
            broken.initialize()

        self.assertEqual(self.user_version(), BASELINE_VERSION)
        with closing(sqlite3.connect(self.path)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        self.assertNotIn("half_done", tables)
        self.assertEqual(self.store.latest_capture_id(), 1)

    def test_a_file_from_a_newer_program_is_refused_not_touched(self) -> None:
        SnapshotStore(self.path, migrations=(self.ADD_NOTE,)).initialize()

        with self.assertRaisesRegex(SnapshotStoreError, "newer than this program"):
            self.store.initialize()

        self.assertEqual(self.user_version(), BASELINE_VERSION + 1)

    def test_some_other_sqlite_file_is_refused(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TABLE unrelated (x)")

        with self.assertRaisesRegex(SnapshotStoreError, "not a squad-capture database"):
            self.store.initialize()

    def test_a_file_older_than_the_baseline_is_refused_with_a_recapture_message(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TABLE captures (id INTEGER PRIMARY KEY)")
            connection.execute(f"PRAGMA user_version = {BASELINE_VERSION - 1}")

        with self.assertRaisesRegex(SnapshotStoreError, "re-run the capture"):
            self.store.initialize()

        self.assertEqual(self.user_version(), BASELINE_VERSION - 1)
        self.assertFalse(list(self.path.parent.glob("*.bak-*")))


if __name__ == "__main__":
    unittest.main()
