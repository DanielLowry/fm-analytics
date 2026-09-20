import unittest

from fm_analytics.analytics import (
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    compare_players_at_position,
)
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "position-comparison-test-v1"


def _catalogue() -> FootballCatalogue:
    roles = (
        RoleDefinition("attack", "Attack", ("DR",), (RoleAttribute("attack", 1),), VERSION),
        RoleDefinition("defend", "Defend", ("DR",), (RoleAttribute("defend", 1),), VERSION),
    )
    tactic = TacticDefinition(
        "test", "Test", "test", "Balanced", (),
        tuple(TacticSlot(f"slot-{number}", "DR", "attack") for number in range(11)), VERSION,
    )
    return FootballCatalogue(VERSION, {role.key: role for role in roles}, {tactic.key: tactic})


def _player(number: int, attack: int, defend: int, *, condition: int = 100) -> PlayerSelectionInput:
    return PlayerSelectionInput(
        id=str(number), name=f"Player {number}", positions=("DR",),
        attributes={
            "attack": AttributeObservation(Visibility.KNOWN, value=attack),
            "defend": AttributeObservation(Visibility.KNOWN, value=defend),
        },
        availability="available", injured=False, suspended=False,
        condition_percent=condition, match_fitness_percent=100,
        position_familiarity={"DR": 20},
    )


class PositionComparisonTests(unittest.TestCase):
    def test_unpinned_comparison_chooses_each_players_best_role_and_ranks_by_position_estimate(self) -> None:
        comparison = compare_players_at_position(
            (_player(1, 20, 10), _player(2, 8, 19)), "DR", _catalogue()
        )

        self.assertEqual([entry.player_id for entry in comparison.entries], ["1", "2"])
        self.assertEqual([entry.assignment.intrinsic_role_score.role_key for entry in comparison.entries], ["attack", "defend"])
        self.assertTrue(all(entry.selectable_today for entry in comparison.entries))

    def test_pinned_role_applies_to_every_player(self) -> None:
        comparison = compare_players_at_position(
            (_player(1, 20, 10), _player(2, 8, 19)), "DR", _catalogue(), role_key="defend"
        )

        self.assertEqual(comparison.requested_role_name, "Defend")
        self.assertEqual(
            {entry.assignment.intrinsic_role_score.role_key for entry in comparison.entries}, {"defend"}
        )

    def test_unselectable_player_remains_visible_with_the_cutoff_reason(self) -> None:
        comparison = compare_players_at_position(
            (_player(1, 20, 10, condition=63),), "DR", _catalogue()
        )

        entry = comparison.entries[0]
        self.assertFalse(entry.selectable_today)
        self.assertGreater(entry.assignment.in_position_score.central, 0)
        self.assertIn("condition 63% is below 65%", entry.unavailability_reasons)


if __name__ == "__main__":
    unittest.main()
