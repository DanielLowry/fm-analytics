import unittest

from fm_analytics.analytics import (
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    TacticSystemRequirements,
    evaluate_tactic,
)
from fm_analytics.analytics.tactical_system import assess_coherence
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "joint-role-system-test-v1"
POSITIONS = ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST")


def observation(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


GENERIC = RoleDefinition(
    key="generic",
    name="Generic",
    eligible_positions=tuple(sorted(set(POSITIONS))),
    attributes=(RoleAttribute("quality", 1),),
    catalogue_version=VERSION,
)
CREATOR = RoleDefinition(
    key="creator",
    name="Creator",
    eligible_positions=("ST",),
    attributes=(RoleAttribute("creator", 1),),
    catalogue_version=VERSION,
    system_traits={"creativity": 2.0},
)
RUNNER = RoleDefinition(
    key="runner",
    name="Runner",
    eligible_positions=("ST",),
    attributes=(RoleAttribute("runner", 1),),
    catalogue_version=VERSION,
    system_traits={"runners": 1.0, "penetration": 1.0},
)


def tactic(*, dynamic: bool) -> TacticDefinition:
    slots = tuple(
        TacticSlot(key=f"slot-{index}", position=position, role_key="generic")
        for index, position in enumerate(POSITIONS[:10])
    ) + (
        TacticSlot(
            key="slot-10",
            position="ST",
            role_key="creator",
            alternate_role_keys=("runner",) if dynamic else (),
        ),
    )
    return TacticDefinition(
        key="dynamic" if dynamic else "fixed",
        name="Dynamic" if dynamic else "Fixed",
        formation="test",
        mentality="Balanced",
        instructions=(),
        slots=slots,
        catalogue_version=VERSION,
        system_requirements=TacticSystemRequirements(minimums={"runners": 1.0}),
    )


def players() -> list[PlayerSelectionInput]:
    result = []
    for index, position in enumerate(POSITIONS[:10], 1):
        result.append(
            PlayerSelectionInput(
                id=str(index), name=f"Player {index}", positions=(position,),
                attributes={"quality": observation(20)}, availability="available",
                injured=False, suspended=False, condition_percent=100,
                match_fitness_percent=100,
            )
        )
    result.append(
        PlayerSelectionInput(
            id="11", name="Forward", positions=("ST",),
            attributes={"creator": observation(20), "runner": observation(8)},
            availability="available", injured=False, suspended=False,
            condition_percent=100, match_fitness_percent=100,
        )
    )
    return result


class JointRoleSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalogue = FootballCatalogue(
            version=VERSION,
            roles={role.key: role for role in (GENERIC, CREATOR, RUNNER)},
            tactics={item.key: item for item in (tactic(dynamic=False), tactic(dynamic=True))},
        )

    def test_advisory_structure_does_not_override_the_better_player_fit(self) -> None:
        fixed = evaluate_tactic(tactic(dynamic=False), players(), self.catalogue)
        dynamic = evaluate_tactic(tactic(dynamic=True), players(), self.catalogue)

        selected_forward = next(item for item in dynamic.assignments if item.slot.key == "slot-10")
        self.assertEqual(selected_forward.intrinsic_role_score.role_key, "creator")
        self.assertEqual(dynamic.score, dynamic.xi_score)
        self.assertEqual(dynamic.score, fixed.score)
        self.assertTrue(dynamic.coherence.shortfalls)

    def test_every_permitted_role_version_is_considered_before_players_are_assigned(self) -> None:
        slots = tuple(
            TacticSlot(key=f"slot-{index}", position=position, role_key="generic")
            for index, position in enumerate(POSITIONS[:9])
        ) + (
            TacticSlot("slot-9", "ST", "creator", alternate_role_keys=("runner",)),
            TacticSlot("slot-10", "ST", "creator", alternate_role_keys=("runner",)),
        )
        shaped = TacticDefinition(
            key="two-role-choices", name="Two role choices", formation="test",
            mentality="Balanced", instructions=(), slots=slots,
            catalogue_version=VERSION,
            system_requirements=TacticSystemRequirements(minimums={"runners": 2.0}),
        )
        forwards = [
            PlayerSelectionInput(
                id=str(index), name=f"Forward {index}", positions=("ST",),
                attributes={"creator": observation(20), "runner": observation(8)},
                availability="available", injured=False, suspended=False,
                condition_percent=100, match_fitness_percent=100,
            )
            for index in (10, 11)
        ]
        catalogue = FootballCatalogue(
            version=VERSION,
            roles={role.key: role for role in (GENERIC, CREATOR, RUNNER)},
            tactics={shaped.key: shaped},
        )
        result = evaluate_tactic(shaped, players()[:9] + forwards, catalogue)

        selected_roles = tuple(
            assignment.intrinsic_role_score.role_key
            for assignment in result.assignments
            if assignment.slot.position == "ST"
        )
        self.assertEqual(selected_roles, ("creator", "creator"))
        self.assertEqual(result.score, result.xi_score)
        self.assertTrue(result.coherence.shortfalls)

    def test_creator_redundancy_is_an_explicit_coherence_penalty(self) -> None:
        requirements = TacticSystemRequirements(maximum_creators=1)
        shaped = TacticDefinition(
            key="redundant", name="Redundant", formation="test", mentality="Balanced",
            instructions=(), slots=tactic(dynamic=True).slots,
            catalogue_version=VERSION, system_requirements=requirements,
        )

        result = assess_coherence(shaped, (CREATOR, CREATOR))

        self.assertLess(result.score, 100)
        self.assertIn("creators 2/1", result.shortfalls)


if __name__ == "__main__":
    unittest.main()
