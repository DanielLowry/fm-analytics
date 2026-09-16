import unittest

from fm_analytics.analytics import (
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    build_role_matrix,
)
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "role-matrix-test-v1"
STRIKER = RoleDefinition(
    key="striker",
    name="Striker",
    eligible_positions=("ST",),
    attributes=(RoleAttribute("finishing", 2),),
    catalogue_version=VERSION,
)
KEEPER = RoleDefinition(
    key="keeper",
    name="Keeper",
    eligible_positions=("GK",),
    attributes=(RoleAttribute("reflexes", 2),),
    catalogue_version=VERSION,
)
DEFENDER = RoleDefinition(
    key="defender",
    name="Defender",
    eligible_positions=("DC",),
    attributes=(RoleAttribute("marking", 2),),
    catalogue_version=VERSION,
)
# FootballCatalogue requires at least one complete tactic even though this
# module never reads tactics; a trivial all-striker shape satisfies that
# structural invariant without implying anything about role_matrix behaviour.
_UNUSED_TACTIC = TacticDefinition(
    key="unused",
    name="Unused",
    formation="unused",
    mentality="Balanced",
    instructions=(),
    slots=tuple(TacticSlot(key=f"slot-{i}", position="ST", role_key="striker") for i in range(11)),
    catalogue_version=VERSION,
)
CATALOGUE = FootballCatalogue(
    version=VERSION,
    roles={role.key: role for role in (STRIKER, KEEPER, DEFENDER)},
    tactics={_UNUSED_TACTIC.key: _UNUSED_TACTIC},
)


def player(number: int, position: str, **attribute_values: int) -> PlayerSelectionInput:
    return PlayerSelectionInput(
        id=str(number),
        name=f"Player {number:02}",
        positions=(position,),
        attributes={
            name: AttributeObservation(Visibility.KNOWN, value=value)
            for name, value in attribute_values.items()
        },
        availability="available",
        injured=False,
        suspended=False,
        condition_percent=100,
        match_fitness_percent=100,
    )


class RoleMatrixTests(unittest.TestCase):
    def test_rejects_duplicate_player_ids(self) -> None:
        squad = [player(1, "ST", finishing=15), player(1, "ST", finishing=10)]

        with self.assertRaisesRegex(ValueError, "unique"):
            build_role_matrix(squad, CATALOGUE)

    def test_best_for_role_picks_the_highest_scoring_eligible_player(self) -> None:
        squad = [
            player(1, "ST", finishing=10),
            player(2, "ST", finishing=18),
            player(3, "GK", reflexes=12),
        ]

        matrix = build_role_matrix(squad, CATALOGUE)

        best = matrix.best_for_role("striker")
        self.assertEqual(best.player_id, "2")
        # The goalkeeper never entered the striker comparison at all.
        self.assertNotIn(
            "3", [candidate.player_id for candidate in matrix.role_rankings["striker"].candidates]
        )

    def test_uncovered_roles_are_reported_when_nobody_is_eligible(self) -> None:
        squad = [player(1, "ST", finishing=15)]

        matrix = build_role_matrix(squad, CATALOGUE)

        self.assertIn("keeper", matrix.uncovered_roles)
        self.assertIn("defender", matrix.uncovered_roles)
        self.assertIsNone(matrix.best_for_role("keeper"))
        self.assertNotIn("striker", matrix.uncovered_roles)

    def test_best_role_for_player_ranks_every_eligible_role(self) -> None:
        # A multi-position player eligible for two roles at once.
        multi = PlayerSelectionInput(
            id="9",
            name="Utility Player",
            positions=("ST", "DC"),
            attributes={
                "finishing": AttributeObservation(Visibility.KNOWN, value=18),
                "marking": AttributeObservation(Visibility.KNOWN, value=8),
            },
            availability="available",
            injured=False,
            suspended=False,
            condition_percent=100,
            match_fitness_percent=100,
        )
        squad = [multi]

        matrix = build_role_matrix(squad, CATALOGUE)
        profile = matrix.player_profiles["9"]

        self.assertEqual(len(profile.fits), 2)
        self.assertEqual(profile.best.role_key, "striker")
        self.assertEqual(matrix.best_role_for_player("9").role_key, "striker")

    def test_player_with_no_eligible_role_has_an_empty_profile(self) -> None:
        squad = [player(1, "AMC", passing=15)]

        matrix = build_role_matrix(squad, CATALOGUE)

        self.assertEqual(matrix.player_profiles["1"].fits, ())
        self.assertIsNone(matrix.best_role_for_player("1"))

    def test_missing_player_id_returns_none_rather_than_raising(self) -> None:
        matrix = build_role_matrix([player(1, "ST", finishing=15)], CATALOGUE)

        self.assertIsNone(matrix.best_role_for_player("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
