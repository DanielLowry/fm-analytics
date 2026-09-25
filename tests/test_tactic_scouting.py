import unittest

from fm_analytics.analytics import (
    FamiliarityPolicy,
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    ScoutingCandidate,
    TacticDefinition,
    TacticSlot,
    evaluate_tactic,
    rank_candidates_for_tactic,
    sort_tactic_assessments,
)
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "tactic-scouting-test-v1"
NO_FAMILIARITY_DISCOUNT = FamiliarityPolicy(floor_multiplier=1.0)
ROLE = RoleDefinition(
    key="generic",
    name="Generic",
    eligible_positions=("GK", "DC", "MC", "ST"),
    attributes=(RoleAttribute("quality", 1),),
    catalogue_version=VERSION,
)
POSITIONS = ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST")
TACTIC = TacticDefinition(
    key="test",
    name="Test tactic",
    formation="test shape",
    mentality="Balanced",
    instructions=(),
    slots=tuple(
        TacticSlot(key=f"slot-{index}", position=position, role_key=ROLE.key)
        for index, position in enumerate(POSITIONS)
    ),
    catalogue_version=VERSION,
)
CATALOGUE = FootballCatalogue(
    version=VERSION,
    roles={ROLE.key: ROLE},
    tactics={TACTIC.key: TACTIC},
)


def owned_squad(quality: int = 10) -> tuple[PlayerSelectionInput, ...]:
    return tuple(
        PlayerSelectionInput(
            id=f"owned-{index}",
            name=f"Owned {index}",
            positions=(position,),
            attributes={
                "quality": AttributeObservation(Visibility.KNOWN, value=quality)
            },
            availability="available",
            injured=False,
            suspended=False,
            condition_percent=100,
            match_fitness_percent=100,
        )
        for index, position in enumerate(POSITIONS)
    )


def candidate(
    identifier: str,
    name: str,
    observation: AttributeObservation,
) -> ScoutingCandidate:
    return ScoutingCandidate(
        id=identifier,
        name=name,
        positions=("ST",),
        attributes={"quality": observation},
        age=22,
        scouting_knowledge=80,
    )


class TacticScoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.squad = owned_squad()
        self.baseline = evaluate_tactic(
            TACTIC,
            self.squad,
            CATALOGUE,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )

    def test_strong_target_matches_a_full_reoptimisation_and_weak_target_is_depth(self) -> None:
        strong = candidate(
            "strong",
            "Strong Target",
            AttributeObservation(Visibility.KNOWN, value=20),
        )
        weak = candidate(
            "weak",
            "Weak Target",
            AttributeObservation(Visibility.KNOWN, value=5),
        )

        assessments = rank_candidates_for_tactic(
            (strong, weak),
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )
        by_id = {item.candidate.id: item for item in assessments}
        augmented = evaluate_tactic(
            TACTIC,
            self.squad
            + (
                PlayerSelectionInput(
                    id="scouting:strong",
                    name="Strong Target",
                    positions=("ST",),
                    attributes=strong.attributes,
                    availability="available",
                    injured=False,
                    suspended=False,
                    condition_percent=100,
                    match_fitness_percent=100,
                ),
            ),
            CATALOGUE,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )

        self.assertTrue(by_id["strong"].starts_at_estimate)
        self.assertGreater(by_id["strong"].score_gain.estimate, 0)
        self.assertAlmostEqual(
            by_id["strong"].projected_score.estimate,
            augmented.score.central,
        )
        self.assertEqual(len(by_id["strong"].replaced_player_names), 1)
        self.assertFalse(by_id["weak"].starts_at_estimate)
        self.assertEqual(by_id["weak"].score_gain.estimate, 0)
        self.assertEqual(by_id["weak"].projected_score.estimate, self.baseline.score.central)

    def test_scouting_uncertainty_can_show_ceiling_upside_without_an_estimated_start(self) -> None:
        uncertain = candidate(
            "uncertain",
            "Uncertain Target",
            AttributeObservation(Visibility.RANGE, minimum=1, maximum=19),
        )

        assessment = rank_candidates_for_tactic(
            (uncertain,),
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )[0]

        self.assertFalse(assessment.starts_at_estimate)
        self.assertEqual(assessment.score_gain.floor, 0)
        self.assertEqual(assessment.score_gain.estimate, 0)
        self.assertGreater(assessment.score_gain.ceiling, 0)
        self.assertEqual(assessment.ranged_attributes, 1)

    def test_candidates_sort_by_their_effect_on_the_selected_tactic(self) -> None:
        candidates = (
            candidate("weak", "Weak", AttributeObservation(Visibility.KNOWN, value=5)),
            candidate("strong", "Strong", AttributeObservation(Visibility.KNOWN, value=20)),
        )
        assessments = rank_candidates_for_tactic(
            candidates,
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )

        ordered = sort_tactic_assessments(assessments, sort="tactic_gain")

        self.assertEqual([item.candidate.id for item in ordered], ["strong", "weak"])


if __name__ == "__main__":
    unittest.main()
