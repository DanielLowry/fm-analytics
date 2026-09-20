import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.role_scoring import RoleDefinition, RoleAttribute, score_role
from fm_analytics.analytics.role_weights import (
    MAX_EFFECTIVE_WEIGHT,
    AttributeWeightConfig,
    load_role_weights,
)
from fm_analytics.domain import AttributeObservation, Visibility


def config(weight: int, tier: str = "primary") -> AttributeWeightConfig:
    return AttributeWeightConfig(
        effective_weight=weight, duty_modifier=0, weight_tier=tier, core_soft_floor_applies=False,
    )


class WeightRangeTests(unittest.TestCase):
    def test_the_scale_runs_zero_to_ten(self) -> None:
        self.assertEqual(MAX_EFFECTIVE_WEIGHT, 10)
        for weight in (0, 1, 7, 10):
            config(weight)

    def test_out_of_range_weights_are_rejected(self) -> None:
        for weight in (-1, 11):
            with self.assertRaises(ValueError):
                config(weight)

    def test_a_tier_label_is_free_text_but_not_blank(self) -> None:
        config(8, "decisive at this position")
        with self.assertRaises(ValueError):
            config(8, "  ")


class LoadingTests(unittest.TestCase):
    def document(self, weight: int, tier: str) -> dict:
        return {
            "version": "role_weights_v3.0",
            "roles": {
                "x_role": {
                    "positionGroup": "ST", "csvRole": "X", "duty": "Attack",
                    "attributes": {"finishing": {
                        "effectiveWeight": weight, "dutyModifier": 0,
                        "weightTier": tier, "coreSoftFloorApplies": False,
                    }},
                }
            },
        }

    def load(self, document: dict):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weights.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return load_role_weights(path)

    def test_a_ten_point_file_loads(self) -> None:
        catalogue = self.load(self.document(10, "core"))
        self.assertEqual(catalogue.roles["x_role"].attributes["finishing"].effective_weight, 10)

    def test_the_shipped_file_still_loads(self) -> None:
        self.assertGreater(len(load_role_weights().roles), 0)

    def test_an_eleven_is_refused_at_load_time(self) -> None:
        with self.assertRaises(ValueError):
            self.load(self.document(11, "core"))


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


if __name__ == "__main__":
    unittest.main()


class CatalogueAgreementTests(unittest.TestCase):
    """The catalogue and the weights file must name the same roles.

    A role missing from the weights file used to fall back to a flat 2.0 on
    required/desirable attributes, which scores plausibly enough to pass
    unnoticed while being badly wrong. That is how splitting roles by position
    (wb_support -> wb_dl_dr_support / wb_wbl_wbr_support) silently degraded 7
    roles used by 60 slots across every tactic.
    """

    def test_every_catalogue_role_has_real_weights(self) -> None:
        from fm_analytics.analytics.catalogue import MVP_CATALOGUE

        weights = load_role_weights()
        missing = sorted(set(MVP_CATALOGUE.roles) - set(weights.roles))
        self.assertEqual(missing, [], f"catalogue roles with no weights: {missing}")

    def test_no_catalogue_role_uses_the_flat_fallback(self) -> None:
        from fm_analytics.analytics.catalogue import MVP_CATALOGUE

        for key, role in MVP_CATALOGUE.roles.items():
            distinct = {attribute.weight for attribute in role.attributes}
            self.assertNotEqual(
                distinct, {1.0, 2.0}, f"{key} looks like the required/desirable fallback"
            )

    def test_a_missing_role_raises_rather_than_falling_back(self) -> None:
        from fm_analytics.analytics.catalogue import _attributes_from_weights

        with self.assertRaisesRegex(ValueError, "no entry in role weights"):
            _attributes_from_weights(
                catalogue_key="not_a_role", required=("pace",), desirable=(),
                weight_catalogue=load_role_weights(),
            )

    def test_every_tactic_slot_names_a_role_eligible_at_its_position(self) -> None:
        from fm_analytics.analytics.catalogue import MVP_CATALOGUE

        for tactic in MVP_CATALOGUE.tactics.values():
            for slot in tactic.slots:
                for key in (slot.role_key, *slot.alternate_role_keys):
                    role = MVP_CATALOGUE.roles[key]
                    self.assertIn(
                        slot.position, role.eligible_positions,
                        f"{tactic.key}/{slot.key} at {slot.position} names {key}",
                    )
