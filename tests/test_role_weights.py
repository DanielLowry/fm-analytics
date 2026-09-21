"""Role attribute weights: a plain `{attribute: weight}` map per role, 0 to 10."""

import unittest

from fm_analytics.analytics.catalogue import MVP_CATALOGUE
from fm_analytics.analytics.role_scoring import RoleAttribute, RoleDefinition, score_role
from fm_analytics.analytics.role_weights import MAX_EFFECTIVE_WEIGHT, parse_attribute_weights
from fm_analytics.domain import AttributeObservation, Visibility


class WeightValidationTests(unittest.TestCase):
    def test_the_scale_runs_zero_to_ten(self) -> None:
        self.assertEqual(MAX_EFFECTIVE_WEIGHT, 10)
        for weight in (0, 1, 7, 10):
            self.assertEqual(parse_attribute_weights("r", {"pace": weight}), {"pace": weight})

    def test_out_of_range_weights_are_refused(self) -> None:
        for weight in (-1, 11):
            with self.assertRaisesRegex(ValueError, "between 0 and 10"):
                parse_attribute_weights("r", {"pace": weight})

    def test_a_weight_must_be_a_whole_number(self) -> None:
        for weight in (7.5, "7", True, None):
            with self.assertRaisesRegex(ValueError, "whole number"):
                parse_attribute_weights("r", {"pace": weight})

    def test_the_old_object_form_is_refused_with_a_message_that_says_why(self) -> None:
        with self.assertRaisesRegex(ValueError, "whole number"):
            parse_attribute_weights("r", {"pace": {"effectiveWeight": 7}})

    def test_a_role_needs_at_least_one_attribute(self) -> None:
        for empty in ({}, None, []):
            with self.assertRaisesRegex(ValueError, "non-empty"):
                parse_attribute_weights("r", empty)

    def test_file_order_is_preserved(self) -> None:
        self.assertEqual(
            list(parse_attribute_weights("r", {"b": 1, "a": 2, "c": 3})), ["b", "a", "c"]
        )


class ScaleInvarianceTests(unittest.TestCase):
    """Scoring uses each weight's share of the total, so the scale cannot matter."""

    def test_doubling_every_weight_changes_no_score(self) -> None:
        observations = {
            "finishing": AttributeObservation(visibility=Visibility.KNOWN, value=16),
            "pace": AttributeObservation(visibility=Visibility.KNOWN, value=8),
            "composure": AttributeObservation(visibility=Visibility.UNKNOWN),
        }

        def role(factor: float) -> RoleDefinition:
            return RoleDefinition(
                key="t", name="T", eligible_positions=("ST",), catalogue_version="test",
                attributes=(
                    RoleAttribute("finishing", 4 * factor),
                    RoleAttribute("pace", 2 * factor),
                    RoleAttribute("composure", 1 * factor),
                ),
            )

        base, doubled = score_role(role(1), observations), score_role(role(2), observations)
        self.assertAlmostEqual(base.score.lower, doubled.score.lower, places=6)
        self.assertAlmostEqual(base.score.central, doubled.score.central, places=6)
        self.assertAlmostEqual(base.score.upper, doubled.score.upper, places=6)
        self.assertAlmostEqual(base.median, doubled.median, places=6)


class ShippedRoleTests(unittest.TestCase):
    def test_every_shipped_role_has_weighted_attributes_in_range(self) -> None:
        for key, role in MVP_CATALOGUE.roles.items():
            self.assertTrue(role.attributes, key)
            for attribute in role.attributes:
                self.assertTrue(0 < attribute.weight <= MAX_EFFECTIVE_WEIGHT, f"{key}: {attribute}")

    def test_no_shipped_role_looks_like_a_flat_guess(self) -> None:
        # A flat 2.0 / 1.0 weighting scores plausibly while being badly wrong.
        for key, role in MVP_CATALOGUE.roles.items():
            distinct = {attribute.weight for attribute in role.attributes}
            self.assertNotEqual(distinct, {1.0, 2.0}, f"{key} looks like a flat fallback")

    def test_every_tactic_slot_names_a_role_eligible_at_its_position(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            for slot in tactic.slots:
                for key in (slot.role_key, *slot.alternate_role_keys):
                    self.assertIn(
                        slot.position, MVP_CATALOGUE.roles[key].eligible_positions,
                        f"{tactic.key}/{slot.key} at {slot.position} names {key}",
                    )


if __name__ == "__main__":
    unittest.main()
