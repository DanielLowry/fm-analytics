import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from fm_analytics.domain.leagues import LeagueCapture
from fm_analytics.persistence.league_history import LeagueHistoryError, LeagueHistoryStore
from tests.league_support import league_capture


class LeagueCaptureTests(unittest.TestCase):
    def setUp(self):
        self.capture = league_capture()

    def test_round_trip_keeps_complete_membership_visible_bands_and_uncaptured_state(self):
        document = self.capture.to_document()
        attrs = document["teams"][1]["squad"]["players"][0]["attributes"]
        attrs["passing"] = {"visibility": "range", "minimum": 8, "maximum": 14}
        del attrs["pace"]
        again = LeagueCapture.from_document(document)
        self.assertEqual(again.to_document(), document)
        self.assertEqual(again.content_hash(), LeagueCapture.from_document(document).content_hash())
        self.assertNotIn("pace", again.teams[1].squad.players[0].attributes)

    def test_research_inventories_hidden_inputs_and_raw_familiarity_are_rejected(self):
        mutations = (
            lambda d: d.update(researchOnly=True),
            lambda d: d.update(format="fm-analytics/league-inventory"),
            lambda d: d["teams"][1]["squad"]["players"][0].update(rawPositions=["ST"]),
            lambda d: d["teams"][1]["squad"]["players"][0].update(positionFamiliarity={"ST": 20}),
            lambda d: d["teams"][1]["squad"]["players"][0]["attributes"].update(currentAbility={"visibility":"known","value":20}),
            lambda d: d["teams"][1]["squad"]["players"][0]["attributes"].update(passing={"visibility":"range","minimum":8,"maximum":14,"rawValue":12}),
        )
        for mutation in mutations:
            document = self.capture.to_document()
            mutation(document)
            with self.assertRaises((ValueError, TypeError)):
                LeagueCapture.from_document(document)

    def test_mixed_dates_duplicate_players_and_incomplete_membership_claims_are_rejected(self):
        mutations = (
            lambda d: d["teams"][1]["squad"].update(asOfDate="2019-01-01"),
            lambda d: d["teams"][1]["squad"]["players"][0].update(id=d["teams"][0]["squad"]["players"][0]["id"]),
            lambda d: d["teams"][1]["squad"]["players"][0].update(clubId="another-club"),
            lambda d: d["teams"].pop(0),
            lambda d: d.update(membershipComplete="yes"),
        )
        for mutation in mutations:
            document = self.capture.to_document()
            mutation(document)
            with self.assertRaises(ValueError):
                LeagueCapture.from_document(document)

    def test_position_gap_can_be_recorded_but_not_claimed_complete(self):
        document = self.capture.to_document()
        document["teams"][1]["squad"]["players"][0]["positions"] = []
        with self.assertRaises(ValueError):
            LeagueCapture.from_document(document)
        document["teams"][1]["positionsComplete"] = False
        self.assertFalse(LeagueCapture.from_document(document).teams[1].positions_complete)


class LeagueHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "league.sqlite3"
        self.store = LeagueHistoryStore(self.path)
        self.capture = league_capture()

    def test_idempotent_save_scoped_history_never_reads_future_captures(self):
        self.assertTrue(self.store.record(self.capture))
        self.assertFalse(self.store.record(self.capture))
        day = self.capture.game.game_date
        self.assertEqual(self.store.latest(self.capture.save_key, self.capture.competition.id, as_of=day), self.capture)
        self.assertIsNone(self.store.latest("other-save", self.capture.competition.id, as_of=day))
        self.assertIsNone(self.store.latest(self.capture.save_key, self.capture.competition.id, as_of=day-timedelta(days=1)))

    def test_same_date_transfer_creates_new_roster_observation_without_rewriting_history(self):
        self.store.record(self.capture)
        document = self.capture.to_document()
        transferred = document["teams"][0]["squad"]["players"].pop()
        transferred["clubId"] = document["teams"][1]["squad"]["club"]["id"]
        transferred["positionFamiliarity"] = {}
        document["teams"][1]["squad"]["players"].append(transferred)
        moved = LeagueCapture.from_document(document)
        self.assertTrue(self.store.record(moved))
        self.assertEqual(self.store.latest(moved.save_key, moved.competition.id, as_of=moved.game.game_date), moved)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM league_captures").fetchone()[0], 2)

    def test_reload_to_earlier_date_requires_an_explicit_save_branch(self):
        self.store.record(self.capture)
        earlier = self.capture.game.game_date-timedelta(days=1)
        capture = replace(self.capture, game=replace(self.capture.game, game_date=earlier),
                          teams=tuple(replace(team, squad=replace(team.squad, as_of_date=earlier)) for team in self.capture.teams))
        with self.assertRaises(ValueError):
            self.store.record(capture)
        self.assertTrue(self.store.record(replace(capture, save_key="branch")))

    def test_unrelated_or_newer_database_is_refused(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE other (id INTEGER)")
            connection.execute("PRAGMA user_version=1")
        with self.assertRaises(LeagueHistoryError):
            self.store.record(self.capture)
        self.path.unlink()
        self.store.record(self.capture)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(LeagueHistoryError, "newer"):
            self.store.record(self.capture)


if __name__ == "__main__":
    unittest.main()
