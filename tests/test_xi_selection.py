import unittest

from fm_analytics.analytics import (
    AttributePriority,
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    evaluate_tactic,
    recommend_tactic,
)
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "selection-test-v1"
ROLE = RoleDefinition(
    key="generic",
    name="Generic",
    eligible_positions=("GK", "SW", "DC", "MC", "ST"),
    attributes=(RoleAttribute("quality", 1, AttributePriority.REQUIRED),),
    catalogue_version=VERSION,
)


def tactic(key: str, role_key: str = "generic") -> TacticDefinition:
    positions = (
        "GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST"
    )
    return TacticDefinition(
        key=key,
        name=key,
        formation="test shape",
        mentality="Balanced",
        instructions=(),
        slots=tuple(
            TacticSlot(key=f"slot-{index}", position=position, role_key=role_key)
            for index, position in enumerate(positions)
        ),
        catalogue_version=VERSION,
    )


TACTIC = tactic("test")
CATALOGUE = FootballCatalogue(
    version=VERSION,
    roles={ROLE.key: ROLE},
    tactics={TACTIC.key: TACTIC},
)


def player(
    number: int,
    position: str,
    quality: int,
    *,
    availability: str = "available",
    condition: int | None = 100,
    match_fitness: int | None = 100,
) -> PlayerSelectionInput:
    return PlayerSelectionInput(
        id=str(number),
        name=f"Player {number:02}",
        positions=(position,),
        attributes={
            "quality": AttributeObservation(Visibility.KNOWN, value=quality)
        },
        availability=availability,
        injured=False,
        suspended=False,
        condition_percent=condition,
        match_fitness_percent=match_fitness,
    )


def legal_squad() -> list[PlayerSelectionInput]:
    positions = (
        "GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST"
    )
    return [
        player(index, position, 12)
        for index, position in enumerate(positions, 1)
    ]


class XiSelectionTests(unittest.TestCase):
    def test_builds_legal_xi_with_unique_eligible_players(self) -> None:
        squad = legal_squad()
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        self.assertTrue(evaluation.has_legal_xi)
        self.assertEqual(len(evaluation.assignments), 11)
        self.assertEqual(len({item.player_id for item in evaluation.assignments}), 11)
        positions = {candidate.id: candidate.positions for candidate in squad}
        self.assertTrue(
            all(
                item.slot.position in positions[item.player_id]
                for item in evaluation.assignments
            )
        )

    def test_readiness_can_change_selection_without_changing_intrinsic_score(self) -> None:
        squad = legal_squad()
        squad.extend(
            (
                player(20, "ST", 20, condition=65, match_fitness=50),
                player(21, "ST", 19, condition=100, match_fitness=100),
                player(22, "ST", 18, condition=100, match_fitness=100),
            )
        )

        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        selected_ids = {item.player_id for item in evaluation.assignments}
        self.assertIn("21", selected_ids)
        self.assertNotIn("20", selected_ids)
        fit = next(item for item in evaluation.assignments if item.player_id == "21")
        self.assertEqual(fit.readiness_penalty, 0)
        self.assertEqual(
            fit.intrinsic_role_score.score.central,
            fit.selection_score.central,
        )

    def test_unavailable_and_low_condition_players_are_excluded(self) -> None:
        squad = legal_squad()
        squad[0] = player(1, "GK", 20, availability="suspended")
        squad.append(player(30, "GK", 15, condition=64))

        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        self.assertFalse(evaluation.has_legal_xi)
        self.assertEqual([slot.position for slot in evaluation.unfilled_slots], ["GK"])

    def test_unknown_readiness_is_penalized_and_explained(self) -> None:
        squad = legal_squad()
        squad.append(player(20, "ST", 20, condition=None, match_fitness=None))

        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)

        assignment = next(item for item in evaluation.assignments if item.player_id == "20")
        self.assertEqual(
            assignment.readiness_warnings,
            ("condition unknown", "match fitness unknown"),
        )
        self.assertGreater(assignment.readiness_penalty, 0)

    def test_recommendation_prefers_legal_shape_before_score(self) -> None:
        impossible_base = tactic("impossible")
        impossible_slots = list(impossible_base.slots)
        impossible_slots[-1] = TacticSlot("slot-10", "SW", "generic")
        impossible = TacticDefinition(
            key=impossible_base.key,
            name=impossible_base.name,
            formation=impossible_base.formation,
            mentality=impossible_base.mentality,
            instructions=impossible_base.instructions,
            slots=tuple(impossible_slots),
            catalogue_version=VERSION,
        )
        catalogue = FootballCatalogue(
            version=VERSION,
            roles={ROLE.key: ROLE},
            tactics={impossible.key: impossible, TACTIC.key: TACTIC},
        )

        recommendation = recommend_tactic(legal_squad(), catalogue)

        self.assertEqual(recommendation.selected.tactic.key, "test")
        self.assertTrue(recommendation.selected.has_legal_xi)

    def test_rejects_duplicate_player_ids(self) -> None:
        squad = legal_squad()
        squad.append(player(1, "ST", 20))

        with self.assertRaisesRegex(ValueError, "unique"):
            evaluate_tactic(TACTIC, squad, CATALOGUE)


if __name__ == "__main__":
    unittest.main()
