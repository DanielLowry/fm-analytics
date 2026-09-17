import json
import tempfile
import unittest
from pathlib import Path

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
