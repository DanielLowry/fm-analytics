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


if __name__ == "__main__":
    unittest.main()
