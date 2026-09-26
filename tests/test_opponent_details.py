"""Detailed position and attribute observations in opponent profiles."""

import unittest
from urllib.parse import parse_qs

from fm_analytics.analytics.catalogue import MVP_CATALOGUE
from fm_analytics.analytics.opponent import OpponentProfile, attribute_emphasis
from fm_analytics.analytics.opponent_details import (
    ATTRIBUTE_DEFINITIONS,
    ATTRIBUTES_BY_KEY,
    POSITION_DEFINITIONS,
)
from fm_analytics.reporting import required_role_attributes
from fm_analytics.web.opponent_controls import (
    opponent_controls,
    opponent_from_query,
    opponent_query,
    opponent_summary_items,
)


class DetailedProfileTests(unittest.TestCase):
    def test_sparse_details_are_canonical_hashable_and_ignore_neutral_values(self) -> None:
        profile = OpponentProfile(
            attribute_levels={"leadership": -1, "dribbling": 2, "finishing": 0},
            position_levels={"DL": 1, "GK": 2, "DR": 0},
        )

        self.assertEqual(
            profile.attribute_levels, (("dribbling", 2), ("leadership", -1))
        )
        self.assertEqual(profile.position_levels, (("GK", 2), ("DL", 1)))
        self.assertIsInstance(hash(profile), int)
        self.assertFalse(profile.is_neutral)

    def test_invalid_detail_names_and_levels_are_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown opponent attribute"):
            OpponentProfile(attribute_levels={"cornersButMore": 1})
        with self.assertRaisesRegex(ValueError, "unknown opponent position"):
            OpponentProfile(position_levels={"SW": 1})
        for bad in (-3, 3, 1.5, "1", True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                OpponentProfile(attribute_levels={"flair": bad})

    def test_every_detail_has_a_response_on_both_sides(self) -> None:
        known_attributes = required_role_attributes()
        fielded_positions = {
            slot.position
            for tactic in MVP_CATALOGUE.tactics.values()
            for slot in tactic.slots
        }
        for detail in (*ATTRIBUTE_DEFINITIONS, *POSITION_DEFINITIONS):
            self.assertTrue(detail.strong, detail.key)
            self.assertTrue(detail.weak, detail.key)
            for rule in (*detail.strong, *detail.weak):
                self.assertLessEqual(set(rule.attributes), known_attributes, detail.key)
                self.assertLessEqual(set(rule.positions), fielded_positions, detail.key)

    def test_exact_detail_replaces_equivalent_broad_slider(self) -> None:
        detailed = OpponentProfile(attribute_levels={"dribbling": -1})
        combined = OpponentProfile(
            dribbling_quality=2, attribute_levels={"dribbling": -1}
        )

        self.assertEqual(attribute_emphasis(combined), attribute_emphasis(detailed))

    def test_different_evidence_still_combines_with_a_broad_slider(self) -> None:
        detailed = OpponentProfile(attribute_levels={"passing": 1})
        combined = OpponentProfile(
            chance_creation=2, attribute_levels={"passing": 1}
        )

        self.assertGreater(
            len(attribute_emphasis(combined)), len(attribute_emphasis(detailed))
        )

    def test_examples_from_a_scout_report_all_have_effects(self) -> None:
        profile = OpponentProfile(
            attribute_levels={
                "tackling": 1, "dribbling": 1, "offTheBall": 1,
                "longShots": -1, "oneOnOnes": -1, "flair": -1,
                "leadership": -1,
            },
            position_levels={"DR": 1, "DL": 1, "GK": 1},
        )

        self.assertEqual(len(attribute_emphasis(profile)), 10)


class DetailedWebControlTests(unittest.TestCase):
    def test_details_round_trip_through_the_bookmarkable_query(self) -> None:
        original = OpponentProfile(
            formation="442",
            chance_creation=2,
            attribute_levels={"dribbling": 1, "leadership": -2},
            position_levels={"DR": 2, "GK": 1},
        )

        query = opponent_query(original)
        restored = opponent_from_query(parse_qs(query))

        self.assertEqual(restored, original)
        self.assertIn("opp_attr_leadership=-2", query)
        self.assertIn("opp_pos_DR=2", query)

    def test_controls_include_every_declared_position_and_attribute(self) -> None:
        body = opponent_controls(OpponentProfile.neutral())

        self.assertIn("Detailed strengths and weaknesses", body)
        for item in POSITION_DEFINITIONS:
            self.assertIn(f"name='opp_pos_{item.key}'", body)
        for item in ATTRIBUTE_DEFINITIONS:
            self.assertIn(f"name='opp_attr_{item.query_key}'", body)

    def test_active_details_are_summarised_and_panel_opens(self) -> None:
        profile = OpponentProfile(
            attribute_levels={"tackling": 1, "longShots": -1},
            position_levels={"DR": 1, "GK": -1},
        )

        summary = opponent_summary_items(profile)
        body = opponent_controls(profile)

        self.assertIn("Strong positions: Right-back", summary)
        self.assertIn("Position weaknesses: Goalkeeper", summary)
        self.assertIn("Attribute strengths: Tackling", summary)
        self.assertIn("Attribute weaknesses: Long Shots", summary)
        self.assertIn("class='opponent-details' open", body)

    def test_bad_detail_query_is_reported_as_a_validation_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Leadership must be a whole number"):
            opponent_from_query({"opp_attr_leadership": ["strong"]})


if __name__ == "__main__":
    unittest.main()
