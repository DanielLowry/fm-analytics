"""The Scouting pages over the feed merged with the save's knowledge history."""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fm_analytics.analytics import ScoutingCandidate
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence import KnowledgeCapture, PlayerKnowledge, PlayerKnowledgeStore
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer
from tests.web_support import FIXTURE, WebServerHelpers


class ScoutingHistoryPoolTests(WebServerHelpers, unittest.TestCase):
    """The scouting pages read the feed merged with the save's knowledge history."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = PlayerKnowledgeStore(Path(directory.name) / "knowledge.sqlite3")
        self.store.record(KnowledgeCapture("club:1", "2019-03-01", "t0", (
            PlayerKnowledge(
                "gone", "Gone Striker",
                {"positions": ("ST",), "club": "Old FC", "has_contract": False,
                 "transfer_status": "transfer_listed", "scouting_knowledge": 60, "age": 24},
                {"finishing": AttributeObservation(Visibility.KNOWN, value=15)},
            ),
            PlayerKnowledge(
                "otto", "Otto Striker", {"positions": ("ST",)},
                {"pace": AttributeObservation(Visibility.KNOWN, value=14)},
            ),
        )))
        self.current = (
            ScoutingCandidate(
                id="otto", name="Otto Striker", positions=("ST",),
                attributes={"pace": AttributeObservation(Visibility.UNKNOWN)},
                club="Example FC", scouting_knowledge=40, captured_game_date="2019-10-01",
            ),
        )

    def _serve_pool(self, **server_kwargs):
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(FIXTURE),
            scouting_provider=lambda: self.current,
            knowledge_store=self.store, knowledge_save_key="club:1", **server_kwargs,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server, server.server_address[1]

    def test_a_history_only_player_is_listed_only_under_everyone_ever_scouted(self) -> None:
        _server, port = self._serve_pool()
        _status, default = self._get(port, "/scouting")
        _status, everyone = self._get(port, "/scouting?everScouted=1")

        self.assertIn("Otto Striker", default)
        self.assertNotIn("Gone Striker", default)
        self.assertIn("Gone Striker", everyone)
        self.assertIn("Not currently realistic", everyone)
        self.assertIn("Last seen at Old FC, 2019-03-01", everyone)

    def test_an_old_free_agent_fact_never_passes_a_market_filter(self) -> None:
        _server, port = self._serve_pool()
        _status, body = self._get(port, "/scouting?everScouted=1&market=free")
        self.assertNotIn("Gone Striker", body)

    def test_the_report_of_a_history_only_player_says_so_and_dates_his_facts(self) -> None:
        _server, port = self._serve_pool()
        status, body = self._get(port, "/scouting/player/gone")

        self.assertEqual(status, 200)
        self.assertIn("Not in the current scouting feed", body)
        self.assertIn("Last seen at Old FC, 2019-03-01", body)
        self.assertIn("transfer_listed (as of 2019-03-01)", body)
        self.assertIn("Historical, last seen 2019-03-01", body)
        self.assertIn("out of date", body)
        # A verdict made on his report is dated today, not when he was last seen.
        self.assertIn("name='decidedOn' value='2019-10-01'", body)

    def test_a_filled_attribute_is_marked_historical_in_list_and_report(self) -> None:
        _server, port = self._serve_pool()
        _status, listing = self._get(port, "/scouting")
        _status, report = self._get(port, "/scouting/player/otto")

        self.assertIn("1 from history", listing)
        self.assertIn("Out of date: oldest seen 2019-03-01", listing)
        self.assertIn("attr-historical", listing)
        self.assertIn("Historical, last seen 2019-03-01", report)
        self.assertIn("Example FC", report)

    def test_the_pool_is_built_once_and_rebuilt_after_a_recording(self) -> None:
        def recorder():
            return self.store.record(KnowledgeCapture("club:1", "2019-09-20", "t1", (
                PlayerKnowledge(
                    "otto", "Otto Striker", {"positions": ("ST",)},
                    {"pace": AttributeObservation(Visibility.KNOWN, value=16)},
                ),
            )))

        server, port = self._serve_pool(knowledge_recorder=recorder)
        with patch.object(
            self.store, "best_known_profiles", wraps=self.store.best_known_profiles
        ) as reads:
            first = server.scouting()
            self._get(port, "/scouting")
            self._get(port, "/scouting/player/gone")
            self.assertIs(server.scouting(), first)
            self.assertEqual(reads.call_count, 1)
            reads.assert_called_with("club:1", "2019-10-01")

            server.record_knowledge()
            rebuilt = server.scouting()
            self.assertIsNot(rebuilt, first)
            self.assertEqual(reads.call_count, 2)
            self.assertEqual(rebuilt[0].attributes["pace"].value, 16)
            self.assertEqual(rebuilt[0].historical_reading("pace").last_seen_on, "2019-09-20")

    def test_an_unreadable_history_leaves_the_current_feed(self) -> None:
        server, port = self._serve_pool()
        with patch.object(self.store, "best_known_profiles", side_effect=sqlite3.OperationalError("locked")):
            self.assertIs(server.scouting(), self.current)
            status, body = self._get(port, "/scouting?everScouted=1")
        self.assertEqual(status, 200)
        self.assertIn("Otto Striker", body)
        self.assertNotIn("Gone Striker", body)

    def test_without_a_save_key_the_pool_is_the_feed(self) -> None:
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(FIXTURE),
            scouting_provider=lambda: self.current, knowledge_store=self.store,
        )
        self.addCleanup(server.server_close)
        self.assertIs(server.scouting(), self.current)


if __name__ == "__main__":
    unittest.main()
