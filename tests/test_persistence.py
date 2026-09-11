import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fm_analytics.domain import GameState, Squad
from fm_analytics.persistence import SnapshotStore


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


if __name__ == "__main__":
    unittest.main()
