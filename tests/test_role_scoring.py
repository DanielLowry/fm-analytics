import unittest
import random
from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.role_scoring import score_role_summary

from fm_analytics.analytics import (
    RoleAttribute,
    RoleDefinition,
    ScoringPolicy,
    is_position_eligible,
    score_role,
)
from fm_analytics.domain.models import AttributeObservation, Visibility


def known(value: int) -> AttributeObservation:
    return AttributeObservation(visibility=Visibility.KNOWN, value=value)


def ranged(minimum: int, maximum: int) -> AttributeObservation:
    return AttributeObservation(
        visibility=Visibility.RANGE,
        minimum=minimum,
        maximum=maximum,
    )


def role() -> RoleDefinition:
    return RoleDefinition(
        key="central_midfielder_support",
        name="Central Midfielder (Support)",
        eligible_positions=("MC",),
        attributes=(
            RoleAttribute("passing", 2),
            RoleAttribute("vision", 1),
        ),
        catalogue_version="test-v1",
    )


class RoleScoringTests(unittest.TestCase):
    def test_compact_scores_match_explanations_for_every_role_and_policy(self):
        rng = random.Random(41)
        for policy in (ScoringPolicy(), ScoringPolicy(unknown_central=10),
                       ScoringPolicy(scale_minimum=0, scale_maximum=25, unknown_central=3)):
            for definition in MVP_CATALOGUE.roles.values():
                observations = {}
                for weighted in definition.attributes:
                    choices = [known(rng.randint(1, 20)), ranged(4, 17), AttributeObservation(Visibility.UNKNOWN), None]
                    chosen = rng.choice(choices)
                    if chosen is not None:
                        observations[weighted.name] = chosen
                full = score_role(definition, observations, policy=policy)
                compact = score_role_summary(definition, observations, policy=policy)
                self.assertEqual((compact.lower, compact.central, compact.upper, compact.median),
                                 (full.score.lower, full.score.central, full.score.upper, full.median))
                for visibility, count in ((Visibility.KNOWN, compact.known), (Visibility.RANGE, compact.ranged), (Visibility.UNKNOWN, compact.unknown)):
                    self.assertEqual(count, sum(c.observation.visibility is visibility for c in full.contributions))

    def test_compact_cache_distinguishes_weights_and_policy_and_rejects_bad_scale(self):
        from dataclasses import replace
        definition = role()
        observations = {"passing": known(20)}
        original = score_role_summary(definition, observations)
        changed = score_role_summary(replace(definition, attributes=(RoleAttribute("passing", 1), RoleAttribute("vision", 9))), observations)
        self.assertNotEqual(original, changed)
        self.assertNotEqual(original.central, score_role_summary(definition, observations, policy=ScoringPolicy(unknown_central=10)).central)
        with self.assertRaisesRegex(ValueError, "outside"):
            score_role_summary(definition, observations, policy=ScoringPolicy(scale_maximum=15))

    def test_exact_score_is_weighted_and_reproducible(self) -> None:
        result = score_role(role(), {"passing": known(20), "vision": known(1)})

        self.assertAlmostEqual(result.score.lower, 66.666667)
        self.assertEqual(result.score.lower, result.score.central)
        self.assertEqual(result.score.central, result.score.upper)
        self.assertEqual(result.scoring_version, "role-score-v1")
        self.assertEqual(result.catalogue_version, "test-v1")
        self.assertEqual(result.information_gaps, ())

    def test_range_preserves_lower_midpoint_and_upper_estimates(self) -> None:
        result = score_role(role(), {"passing": ranged(10, 14), "vision": known(10)})

        self.assertLess(result.score.lower, result.score.central)
        self.assertLess(result.score.central, result.score.upper)
        passing = result.contributions[0]
        self.assertEqual((passing.raw.lower, passing.raw.central, passing.raw.upper), (10, 12, 14))
        self.assertEqual(result.information_gaps, (passing,))

    def test_unknown_is_centrally_conservative_but_retains_upside(self) -> None:
        result = score_role(
            role(),
            {
                "passing": AttributeObservation(visibility=Visibility.UNKNOWN),
                "vision": known(10),
            },
        )

        passing = result.contributions[0]
        self.assertEqual((passing.raw.lower, passing.raw.central, passing.raw.upper), (1, 1, 20))
        self.assertEqual(result.score.lower, result.score.central)
        self.assertGreater(result.score.upper, result.score.central)

    def test_absent_input_is_an_explicit_information_gap(self) -> None:
        result = score_role(role(), {"passing": known(12)})

        vision = result.contributions[1]
        self.assertFalse(vision.supplied)
        self.assertEqual(vision.observation.visibility, Visibility.UNKNOWN)
        self.assertEqual(result.information_gaps, (vision,))

    def test_information_gaps_are_ordered_by_potential_score_effect(self) -> None:
        result = score_role(
            role(),
            {"passing": ranged(18, 20), "vision": ranged(1, 20)},
        )

        self.assertEqual(
            [gap.attribute for gap in result.information_gaps],
            ["vision", "passing"],
        )

    def test_rejects_visible_values_outside_policy_scale(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            score_role(role(), {"passing": known(21), "vision": known(10)})

    def test_unknown_policy_is_explicit_and_versioned(self) -> None:
        result = score_role(
            role(),
            {},
            policy=ScoringPolicy(version="optimistic-test", unknown_central=10),
        )

        self.assertEqual(result.scoring_version, "optimistic-test")
        self.assertGreater(result.score.central, result.score.lower)

    def test_position_eligibility_is_separate_from_role_quality(self) -> None:
        definition = role()

        self.assertTrue(is_position_eligible(definition, ("MC", "AMC")))
        self.assertFalse(is_position_eligible(definition, ("DC",)))

    def test_role_rejects_duplicate_attributes(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            RoleDefinition(
                key="duplicate",
                name="Duplicate",
                eligible_positions=("MC",),
                attributes=(
                    RoleAttribute("passing", 1),
                    RoleAttribute("passing", 2),
                ),
                catalogue_version="test-v1",
            )


if __name__ == "__main__":
    unittest.main()
