import unittest

from fm_analytics.analytics import (
    AttributePriority,
    CandidateRoleScore,
    RoleAttribute,
    RoleDefinition,
    compare_role_scores,
    score_role,
)
from fm_analytics.domain import AttributeObservation, Visibility


ROLE = RoleDefinition(
    key="keeper_defend",
    name="Goalkeeper (Defend)",
    eligible_positions=("GK",),
    attributes=(
        RoleAttribute("reflexes", 2, AttributePriority.REQUIRED),
        RoleAttribute("aerialReach", 1, AttributePriority.DESIRABLE),
    ),
    catalogue_version="test-v1",
)


def exact_candidate(player_id: str, name: str, value: int) -> CandidateRoleScore:
    observation = AttributeObservation(visibility=Visibility.KNOWN, value=value)
    return CandidateRoleScore(
        player_id=player_id,
        player_name=name,
        role_score=score_role(
            ROLE,
            {"reflexes": observation, "aerialReach": observation},
        ),
    )


class RoleComparisonTests(unittest.TestCase):
    def test_clear_exact_winner_is_certain(self) -> None:
        result = compare_role_scores(
            [
                exact_candidate("2", "Backup", 10),
                exact_candidate("1", "Starter", 15),
            ]
        )

        self.assertEqual(result.selected.player_id, "1")
        self.assertTrue(result.decision_certain)
        self.assertEqual(result.scouting_priorities, ())

    def test_uncertain_contender_generates_targeted_scouting_priorities(self) -> None:
        unknown = AttributeObservation(visibility=Visibility.UNKNOWN)
        contender = CandidateRoleScore(
            player_id="2",
            player_name="Unknown Contender",
            role_score=score_role(
                ROLE,
                {"reflexes": unknown, "aerialReach": unknown},
            ),
        )

        result = compare_role_scores(
            [contender, exact_candidate("1", "Known Starter", 12)]
        )

        self.assertEqual(result.selected.player_id, "1")
        self.assertFalse(result.decision_certain)
        self.assertEqual(
            [priority.attribute for priority in result.scouting_priorities],
            ["reflexes", "aerialReach"],
        )
        self.assertTrue(
            all(
                priority.player_id == "2"
                for priority in result.scouting_priorities
            )
        )

    def test_clear_interval_winner_does_not_request_unnecessary_scouting(self) -> None:
        range_observation = AttributeObservation(
            visibility=Visibility.RANGE,
            minimum=18,
            maximum=20,
        )
        interval_winner = CandidateRoleScore(
            player_id="1",
            player_name="Interval Winner",
            role_score=score_role(
                ROLE,
                {
                    "reflexes": range_observation,
                    "aerialReach": range_observation,
                },
            ),
        )

        result = compare_role_scores(
            [interval_winner, exact_candidate("2", "Known Backup", 10)]
        )

        self.assertTrue(result.decision_certain)
        self.assertEqual(result.scouting_priorities, ())

    def test_missing_input_remains_distinguishable_from_explicit_unknown(self) -> None:
        missing = CandidateRoleScore(
            player_id="2",
            player_name="Incomplete",
            role_score=score_role(ROLE, {}),
        )

        result = compare_role_scores(
            [missing, exact_candidate("1", "Known Starter", 12)]
        )

        self.assertTrue(result.scouting_priorities)
        self.assertTrue(
            all(not priority.supplied for priority in result.scouting_priorities)
        )

    def test_exact_tie_is_not_falsely_called_certain(self) -> None:
        result = compare_role_scores(
            [
                exact_candidate("2", "Beta", 12),
                exact_candidate("1", "Alpha", 12),
            ]
        )

        self.assertEqual(result.selected.player_name, "Alpha")
        self.assertFalse(result.decision_certain)
        self.assertEqual(result.scouting_priorities, ())

    def test_rejects_mixed_role_versions(self) -> None:
        different_role = RoleDefinition(
            key="sweeper_keeper_support",
            name="Sweeper Keeper (Support)",
            eligible_positions=("GK",),
            attributes=ROLE.attributes,
            catalogue_version="test-v1",
        )
        mixed = CandidateRoleScore(
            player_id="2",
            player_name="Other Role",
            role_score=score_role(
                different_role,
                {"reflexes": AttributeObservation(Visibility.KNOWN, value=15)},
            ),
        )

        with self.assertRaisesRegex(ValueError, "same role"):
            compare_role_scores([exact_candidate("1", "Starter", 15), mixed])

    def test_rejects_duplicate_player_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            compare_role_scores(
                [
                    exact_candidate("1", "Starter", 15),
                    exact_candidate("1", "Same Player", 10),
                ]
            )


if __name__ == "__main__":
    unittest.main()
