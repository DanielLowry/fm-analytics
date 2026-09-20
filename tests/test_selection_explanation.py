import unittest
from dataclasses import replace

from fm_analytics.analytics import (
    FamiliarityPolicy,
    FootballCatalogue,
    RoleAttribute,
    RoleDefinition,
    TacticSlot,
    evaluate_tactic,
    evaluate_tactic_with_forced_assignment,
    explain_tactic_selection,
)
from fm_analytics.domain import AttributeObservation, Visibility
from tests.test_xi_selection import ROLE, TACTIC, VERSION, legal_squad, player


NO_FAMILIARITY_DISCOUNT = FamiliarityPolicy(floor_multiplier=1.0)


class SelectionExplanationTests(unittest.TestCase):
    def _balanced_assignment_case(self):
        role_a = RoleDefinition(
            key="role-a",
            name="Role A",
            eligible_positions=("ST",),
            attributes=(RoleAttribute("a", 1),),
            catalogue_version=VERSION,
        )
        role_b = RoleDefinition(
            key="role-b",
            name="Role B",
            eligible_positions=("ST",),
            attributes=(RoleAttribute("b", 1),),
            catalogue_version=VERSION,
        )
        shaped = replace(
            TACTIC,
            slots=TACTIC.slots[:-2]
            + (
                TacticSlot("slot-9", "ST", "role-a"),
                TacticSlot("slot-10", "ST", "role-b"),
            ),
        )
        catalogue = FootballCatalogue(
            version=VERSION,
            roles={role.key: role for role in (ROLE, role_a, role_b)},
            tactics={shaped.key: shaped},
        )
        squad = legal_squad()[:9] + [
            replace(
                player(10, "ST", 12),
                attributes={
                    "a": AttributeObservation(Visibility.KNOWN, value=20),
                    "b": AttributeObservation(Visibility.KNOWN, value=9),
                },
            ),
            replace(
                player(11, "ST", 12),
                attributes={
                    "a": AttributeObservation(Visibility.KNOWN, value=11),
                    "b": AttributeObservation(Visibility.KNOWN, value=3),
                },
            ),
        ]
        return shaped, catalogue, squad

    def test_forced_assignment_reoptimises_the_other_ten_slots(self) -> None:
        tactic, catalogue, squad = self._balanced_assignment_case()

        forced = evaluate_tactic_with_forced_assignment(
            tactic,
            squad,
            catalogue,
            slot_key="slot-9",
            player_id="10",
            role_key="role-a",
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )

        by_slot = {item.slot.key: item.player_id for item in forced.assignments}
        self.assertTrue(forced.has_legal_xi)
        self.assertEqual(by_slot["slot-9"], "10")
        self.assertEqual(by_slot["slot-10"], "11")

    def test_explanation_identifies_a_stronger_local_player_used_elsewhere(self) -> None:
        tactic, catalogue, squad = self._balanced_assignment_case()
        evaluation = evaluate_tactic(
            tactic,
            squad,
            catalogue,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )

        explanation = explain_tactic_selection(
            evaluation,
            squad,
            catalogue,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )
        slot = next(item for item in explanation.slots if item.starter.slot.key == "slot-9")
        alternative = next(item for item in slot.alternatives if item.player_id == "10")

        self.assertEqual(slot.starter.player_id, "11")
        self.assertGreater(
            alternative.assignment.selection_score.central,
            slot.starter.selection_score.central,
        )
        self.assertEqual(alternative.current_slot_key, "slot-10")
        self.assertLess(alternative.tactic_score_change, 0)


if __name__ == "__main__":
    unittest.main()
