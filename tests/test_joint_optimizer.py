import random
import unittest

from fm_analytics.analytics import (
    FamiliarityPolicy,
    MVP_CATALOGUE,
    OpponentProfile,
    PlayerSelectionInput,
    evaluate_tactic,
)
from fm_analytics.analytics.joint_optimizer import optimise_tactic_jointly
from fm_analytics.domain import AttributeObservation, Visibility


def synthetic_players() -> tuple[PlayerSelectionInput, ...]:
    rng = random.Random(7)
    positions = tuple(sorted({
        position
        for role in MVP_CATALOGUE.roles.values()
        for position in role.eligible_positions
    }))
    attributes = tuple(sorted({
        attribute.name
        for role in MVP_CATALOGUE.roles.values()
        for attribute in role.attributes
    }))
    return tuple(
        PlayerSelectionInput(
            id=str(index),
            name=f"Synthetic Player {index:02}",
            positions=tuple(rng.sample(positions, rng.randint(2, 4))),
            attributes={
                name: AttributeObservation(
                    Visibility.KNOWN, value=rng.randint(6, 18)
                )
                for name in attributes
            },
            availability="available",
            injured=False,
            suspended=False,
            condition_percent=100,
            match_fitness_percent=100,
            position_familiarity={position: 20 for position in positions},
        )
        for index in range(1, 31)
    )


class JointOptimizerPrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.players = synthetic_players()
        cls.familiarity = FamiliarityPolicy(floor_multiplier=1.0)

    def test_matches_production_objective_for_representative_tactics(self) -> None:
        # vertical_442 has 18 legal role versions; gegenpress_4231 includes the
        # one alternate pair whose system traits intentionally differ; the
        # front-foot shape has pinned roles.
        for tactic_key in ("vertical_442", "gegenpress_4231", "front_foot_442"):
            with self.subTest(tactic=tactic_key):
                tactic = MVP_CATALOGUE.tactics[tactic_key]
                production = evaluate_tactic(
                    tactic,
                    self.players,
                    MVP_CATALOGUE,
                    familiarity_policy=self.familiarity,
                )
                joint = optimise_tactic_jointly(
                    tactic,
                    self.players,
                    MVP_CATALOGUE,
                    familiarity_policy=self.familiarity,
                )
                self.assertTrue(production.has_legal_xi)
                self.assertIsNotNone(joint)
                assert joint is not None
                self.assertAlmostEqual(production.score.central, joint.objective, places=5)
                self.assertEqual(len(joint.assignments), 11)
                self.assertEqual(len({item.player_id for item in joint.assignments}), 11)

    def test_joint_model_enforces_the_cover_exclusion_group(self) -> None:
        tactic = MVP_CATALOGUE.tactics["vertical_442"]
        joint = optimise_tactic_jointly(
            tactic,
            self.players,
            MVP_CATALOGUE,
            familiarity_policy=self.familiarity,
        )
        self.assertIsNotNone(joint)
        assert joint is not None
        cover_centre_backs = [
            assignment
            for assignment in joint.assignments
            if assignment.slot.position == "DC"
            and assignment.intrinsic_role_score.role_key == "cd_cover"
        ]
        self.assertLessEqual(len(cover_centre_backs), 1)

    def test_matches_production_with_opponent_emphasis_and_system_floors(self) -> None:
        tactic = MVP_CATALOGUE.tactics["vertical_442"]
        opponent = OpponentProfile(quality=2, aerial_threat=1)
        production = evaluate_tactic(
            tactic,
            self.players,
            MVP_CATALOGUE,
            familiarity_policy=self.familiarity,
            opponent=opponent,
        )
        joint = optimise_tactic_jointly(
            tactic,
            self.players,
            MVP_CATALOGUE,
            familiarity_policy=self.familiarity,
            opponent=opponent,
        )
        self.assertIsNotNone(joint)
        assert joint is not None
        self.assertAlmostEqual(production.score.central, joint.objective, places=5)


if __name__ == "__main__":
    unittest.main()
