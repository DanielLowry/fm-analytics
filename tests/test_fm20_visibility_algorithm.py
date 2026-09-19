import unittest

from fm_analytics.bridge.fm20_visibility_algorithm import (
    PositionFamily,
    RangeWidths,
    VisibilityThresholds,
    build_ranged_observation,
    build_visible_observation,
    calculate_effective_knowledge,
    calculate_range_widths,
    classify_visibility,
    select_position_family,
    thresholds_for_attribute,
)
from fm_analytics.domain.models import Visibility


class Fm20VisibilityAlgorithmTests(unittest.TestCase):
    def test_combines_all_effective_knowledge_sources(self) -> None:
        self.assertEqual(
            calculate_effective_knowledge(
                explicit_knowledge=40,
                baseline_knowledge=22,
                report_knowledge=52,
            ),
            52,
        )
        self.assertEqual(
            calculate_effective_knowledge(
                explicit_knowledge=0,
                baseline_knowledge=12,
                report_knowledge=None,
            ),
            12,
        )
        with self.assertRaisesRegex(ValueError, "report knowledge"):
            calculate_effective_knowledge(
                explicit_knowledge=0,
                baseline_knowledge=12,
                report_knowledge=101,
            )

    def test_builds_public_observation_without_leaking_unknown_value(self) -> None:
        common = {
            "attribute": "acceleration",
            "exact_value": 14,
            "player_row_id": 100,
            "display_attribute_id": 0x27,
            "position_ratings": [1] * 15,
            "age": 22,
            "report_quality_sum": None,
        }

        unknown = build_visible_observation(effective_knowledge=17, **common)
        ranged = build_visible_observation(effective_knowledge=18, **common)
        known = build_visible_observation(effective_knowledge=56, **common)

        self.assertEqual(unknown.visibility, Visibility.UNKNOWN)
        self.assertIsNone(unknown.value)
        self.assertIsNone(unknown.minimum)
        self.assertIsNone(unknown.maximum)
        self.assertEqual(ranged.visibility, Visibility.RANGE)
        self.assertEqual((ranged.minimum, ranged.maximum), (12, 17))
        self.assertEqual(known.visibility, Visibility.KNOWN)
        self.assertEqual(known.value, 14)

    def test_selects_position_family_using_fm_priority_and_threshold(self) -> None:
        ratings = [1] * 15
        ratings[0] = 18
        ratings[12] = 20
        self.assertEqual(
            select_position_family(ratings), PositionFamily.GOALKEEPER
        )

        ratings = [1] * 15
        ratings[3] = 20
        ratings[10] = 18
        self.assertEqual(select_position_family(ratings), PositionFamily.ATTACKER)

        ratings = [1] * 15
        ratings[4] = 18
        self.assertEqual(select_position_family(ratings), PositionFamily.DEFENDER)

        ratings = [1] * 15
        ratings[5] = 20
        ratings[7] = 18
        self.assertEqual(select_position_family(ratings), PositionFamily.MIDFIELDER)

    def test_position_family_does_not_guess_from_ui_position_threshold(self) -> None:
        ratings = [1] * 15
        ratings[2] = 17
        ratings[13] = 20

        self.assertEqual(select_position_family(ratings), PositionFamily.MIDFIELDER)

    def test_position_family_rejects_malformed_ratings(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 15"):
            select_position_family([1] * 14)
        with self.assertRaisesRegex(ValueError, "position rating"):
            select_position_family([1] * 14 + [21])

    def test_exposes_all_captured_physical_threshold_profiles(self) -> None:
        expected = {
            PositionFamily.GOALKEEPER: (26, 13, 20, 27, 33, 25, 28, 35),
            PositionFamily.DEFENDER: (12, 28, 27, 13, 20, 10, 5, 24),
            PositionFamily.MIDFIELDER: (18, 28, 26, 19, 12, 5, 14, 22),
            PositionFamily.ATTACKER: (5, 29, 27, 6, 18, 8, 4, 26),
        }
        attributes = (
            "acceleration",
            "agility",
            "balance",
            "pace",
            "stamina",
            "strength",
            "jumpingReach",
            "naturalFitness",
        )

        for family, range_thresholds in expected.items():
            with self.subTest(family=family):
                actual = tuple(
                    thresholds_for_attribute(family, attribute)
                    for attribute in attributes
                )
                self.assertEqual(
                    actual,
                    tuple(
                        VisibilityThresholds(value, value + 38)
                        for value in range_thresholds
                    ),
                )

    def test_exposes_static_outfield_attribute_profiles(self) -> None:
        self.assertEqual(
            thresholds_for_attribute(PositionFamily.DEFENDER, "marking"),
            VisibilityThresholds(range=6, exact=44),
        )
        self.assertEqual(
            thresholds_for_attribute(PositionFamily.MIDFIELDER, "passing"),
            VisibilityThresholds(range=6, exact=44),
        )
        self.assertEqual(
            thresholds_for_attribute(PositionFamily.ATTACKER, "finishing"),
            VisibilityThresholds(range=10, exact=48),
        )

    def test_threshold_lookup_fails_closed_for_unsupported_combinations(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported for goalkeeper"):
            thresholds_for_attribute(PositionFamily.GOALKEEPER, "finishing")
        with self.assertRaisesRegex(ValueError, "unsupported for defender"):
            thresholds_for_attribute(PositionFamily.DEFENDER, "reflexes")
        with self.assertRaisesRegex(TypeError, "PositionFamily"):
            thresholds_for_attribute("defender", "marking")  # type: ignore[arg-type]

    def test_classifies_against_both_thresholds(self) -> None:
        self.assertEqual(classify_visibility(11, 12, 50), Visibility.UNKNOWN)
        self.assertEqual(classify_visibility(12, 12, 50), Visibility.RANGE)
        self.assertEqual(classify_visibility(50, 12, 50), Visibility.KNOWN)

    def test_a_bracket_needs_both_quality_and_knowledge_within_its_limits(self) -> None:
        # Poor knowledge AND poor quality: the widest bracket.
        self.assertEqual(
            calculate_range_widths(age=27, effective_knowledge=15, report_quality_sum=8),
            RangeWidths(wide=6, medium=3, narrow=2),
        )
        # Either one being better is enough to leave it (the old code needed both).
        self.assertEqual(
            calculate_range_widths(age=27, effective_knowledge=15, report_quality_sum=16),
            RangeWidths(wide=5, medium=3, narrow=2),
        )
        self.assertEqual(
            calculate_range_widths(age=27, effective_knowledge=25, report_quality_sum=5),
            RangeWidths(wide=5, medium=3, narrow=2),
        )

    def test_reproduces_real_players_from_fms_own_exports(self) -> None:
        """Each case reproduced every attribute FM exported for that player."""
        # Rogan McGeorge / Jack Farmer: knowledge 15, scout quality in 12-19.
        self.assertEqual(
            calculate_range_widths(age=27, effective_knowledge=15, report_quality_sum=16),
            RangeWidths(wide=5, medium=3, narrow=2),
        )
        # Shuai Li: age 16, knowledge 20, a better scout (quality 20-24).
        self.assertEqual(
            calculate_range_widths(age=16, effective_knowledge=20, report_quality_sum=22),
            RangeWidths(wide=6, medium=3, narrow=2),
        )
        # Jordan Richards: knowledge 27 is enough to leave the widest bracket.
        self.assertEqual(
            calculate_range_widths(age=21, effective_knowledge=27, report_quality_sum=17),
            RangeWidths(wide=5, medium=3, narrow=2),
        )

    def test_very_good_quality_and_knowledge_add_no_extra_width(self) -> None:
        self.assertEqual(
            calculate_range_widths(age=25, effective_knowledge=60, report_quality_sum=40),
            RangeWidths(wide=2, medium=1, narrow=1),
        )
        self.assertEqual(
            calculate_range_widths(age=25, effective_knowledge=51, report_quality_sum=29),
            RangeWidths(wide=2, medium=1, narrow=1),
        )

    def test_a_missing_report_lets_knowledge_alone_decide(self) -> None:
        # No report is a quality sum of zero: it can never be the reason to
        # stay wide, so knowledge picks the bracket (the old code always
        # forced the widest bracket here, whatever the knowledge).
        self.assertEqual(
            calculate_range_widths(age=25, effective_knowledge=60, report_quality_sum=None),
            RangeWidths(wide=2, medium=1, narrow=1),
        )
        self.assertEqual(
            calculate_range_widths(age=21, effective_knowledge=27, report_quality_sum=None),
            RangeWidths(wide=5, medium=3, narrow=2),
        )
        self.assertEqual(
            calculate_range_widths(age=27, effective_knowledge=15, report_quality_sum=None),
            RangeWidths(wide=6, medium=3, narrow=2),
        )

    def test_builds_all_seven_deterministic_bound_patterns(self) -> None:
        widths = RangeWidths(wide=6, medium=3, narrow=2)
        expected = (
            (4, 12),
            (8, 16),
            (4, 10),
            (10, 16),
            (7, 13),
            (7, 12),
            (8, 13),
        )
        for row_id, bounds in enumerate(expected):
            with self.subTest(row_id=row_id):
                observation = build_ranged_observation(
                    exact_value=10,
                    player_row_id=row_id,
                    display_attribute_id=0,
                    widths=widths,
                )
                self.assertEqual(
                    (observation.minimum, observation.maximum), bounds
                )

    def test_clamps_bounds_to_attribute_scale(self) -> None:
        observation = build_ranged_observation(
            exact_value=1,
            player_row_id=2,
            display_attribute_id=0,
            widths=RangeWidths(wide=8, medium=4, narrow=2),
        )

        self.assertEqual(observation.visibility, Visibility.KNOWN)
        self.assertEqual(observation.value, 1)

    def test_rejects_unverified_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "range threshold"):
            classify_visibility(20, 60, 50)
        with self.assertRaisesRegex(ValueError, "report quality"):
            calculate_range_widths(
                age=25, effective_knowledge=60, report_quality_sum=41
            )


if __name__ == "__main__":
    unittest.main()
