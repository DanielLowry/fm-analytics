import json
import tempfile
import unittest
from pathlib import Path

import contextlib
from types import SimpleNamespace
from unittest import mock

from tools import fm20_scouting_feed as feed
from tools.fm20_scouting_feed import ScoutingFeedError, feed_document, load_prior_visibility


class ScoutingFeedTests(unittest.TestCase):
    def test_builds_an_identity_only_feed_without_claiming_unread_fields(self) -> None:
        document = feed_document(
            [30, 10], {10: "One Player", 30: "Two Player"},
            game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=22,
            excluded_own_ids=[1, 2],
        )

        self.assertEqual([player["id"] for player in document["players"]], ["10", "30"])
        self.assertEqual(document["players"][0]["positions"], [])
        self.assertEqual(document["players"][0]["attributes"], {})
        self.assertEqual(document["source"]["excludedOwnContractedCount"], 2)
        self.assertIn("not yet", document["source"]["fieldCoverage"]["attributes"])

    def test_refuses_to_publish_an_unlabelled_discovered_player(self) -> None:
        with self.assertRaisesRegex(ScoutingFeedError, "identity lookup failed"):
            feed_document(
                [10], {}, game_date="2020-08-14",
                managed_club={"id": "club-1", "name": "Hungerford Town"},
                source_count=1, excluded_own_ids=[],
            )

    def test_includes_only_verified_visible_attributes_for_hydrated_players(self) -> None:
        document = feed_document(
            [10, 30], {10: "One Player", 30: "Two Player"},
            game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=22,
            excluded_own_ids=[],
            attributes_by_id={
                10: {"finishing": {"visibility": "range", "minimum": 8, "maximum": 14}}
            },
            footedness_by_id={10: "Right"},
        )

        self.assertEqual(document["players"][0]["attributes"]["finishing"]["maximum"], 14)
        self.assertEqual(document["players"][1]["attributes"], {})
        self.assertEqual(document["players"][0]["footedness"], "Right")
        self.assertNotIn("footedness", document["players"][1])
        self.assertIn("1/2", document["source"]["fieldCoverage"]["attributes"])

    def test_marks_raw_external_positions_as_the_accepted_visibility_gap(self) -> None:
        document = feed_document(
            [10], {10: "One Player"},
            game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=22,
            excluded_own_ids=[],
            raw_positions_by_id={10: ("ST", "AMC")},
        )

        self.assertEqual(document["players"][0]["positions"], [])
        self.assertEqual(document["players"][0]["rawPositions"], ["ST", "AMC"])
        self.assertIn("accepted", document["source"]["fieldCoverage"]["positions"])

    def test_loads_only_existing_visible_fields_from_a_prior_same_date_feed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps({
                "gameDate": "2020-08-14",
                "players": [{
                    "id": "10", "attributes": {"pace": {"visibility": "unknown"}},
                    "footedness": "Right",
                }],
            }), encoding="utf-8")

            game_date, attributes, footedness, raw_positions = load_prior_visibility(path)

        self.assertEqual(game_date, "2020-08-14")
        self.assertEqual(attributes[10]["pace"]["visibility"], "unknown")
        self.assertEqual(footedness, {10: "Right"})
        self.assertEqual(raw_positions, {})


if __name__ == "__main__":
    unittest.main()


class CapturePoolSafetyGateTests(unittest.TestCase):
    """The pool must be read, not rebuilt, unless rebuilding is explicitly allowed."""

    def _patch(self, pool_ids):
        state = SimpleNamespace(module_base="0x140000000", game_date="2019-06-24")
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        return (
            mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), pool_ids)),
            mock.patch.object(feed, "_active_manager", return_value=manager),
            mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}),
            mock.patch.object(feed, "connect_to_fm", side_effect=AssertionError("must not attach to FM")),
        )

    def test_unbuilt_pool_refuses_rather_than_calling_into_fm(self) -> None:
        with contextlib.ExitStack() as stack:
            for patch in self._patch([]):
                stack.enter_context(patch)
            with self.assertRaises(feed.PoolNotBuiltError) as caught:
                feed.capture_pool(1234, remote_address="127.0.0.1:27042")
        self.assertIn("Open Player Search in FM", str(caught.exception))

    def test_rebuild_still_needs_a_frida_address(self) -> None:
        """Consent alone is not enough; an unreachable server must fail closed."""
        with contextlib.ExitStack() as stack:
            for patch in self._patch([]):
                stack.enter_context(patch)
            with self.assertRaises(ScoutingFeedError) as caught:
                feed.capture_pool(1234, remote_address=None, allow_rebuild=True)
        self.assertIn("Frida server address is required", str(caught.exception))

    def test_pool_not_built_is_a_scouting_feed_error(self) -> None:
        """Existing callers that catch the base class keep failing closed."""
        self.assertTrue(issubclass(feed.PoolNotBuiltError, ScoutingFeedError))


class FeedProvenanceTests(unittest.TestCase):
    def test_document_records_whether_fm_was_asked_to_rebuild(self) -> None:
        read_only = feed.feed_document(
            [1], {1: "A Player"}, game_date="2019-06-24",
            managed_club={"id": "c1", "name": "Example FC"},
            source_count=1, excluded_own_ids=[],
        )
        rebuilt = feed.feed_document(
            [1], {1: "A Player"}, game_date="2019-06-24",
            managed_club={"id": "c1", "name": "Example FC"},
            source_count=1, excluded_own_ids=[], rebuilt=True,
        )

        self.assertFalse(read_only["source"]["poolRebuiltByCapture"])
        self.assertEqual(read_only["source"]["transport"], "read-only-process-memory")
        self.assertTrue(rebuilt["source"]["poolRebuiltByCapture"])
        self.assertEqual(rebuilt["source"]["transport"], "windows-frida-server")
