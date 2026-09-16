import unittest

from tools.fm20_scouting_feed import ScoutingFeedError, feed_document


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


if __name__ == "__main__":
    unittest.main()
