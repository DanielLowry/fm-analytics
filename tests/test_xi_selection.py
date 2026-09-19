import unittest
from dataclasses import replace

from fm_analytics.analytics import (
    FamiliarityPolicy,
    FootballCatalogue,
    MVP_CATALOGUE,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticFitPolicy,
    TacticSlot,
    evaluate_tactic,
    best_position_adjusted_role,
    recommend_tactic,
    recommend_tactic_effective_and_potential,
    score_player_for_slot,
)
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "selection-test-v1"
# Most tests below exercise readiness/fit behaviour and were written before
# position familiarity existed; pin its penalty to zero so they keep testing
# exactly what they intended. Familiarity has its own tests further down.
NO_FAMILIARITY_DISCOUNT = FamiliarityPolicy(floor_multiplier=1.0)
ROLE = RoleDefinition(
    key="generic",
    name="Generic",
    eligible_positions=("GK", "SW", "DC", "MC", "ST"),
    attributes=(RoleAttribute("quality", 1),),
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
    position_familiarity: dict[str, int] | None = None,
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
        position_familiarity=position_familiarity or {},
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
    def test_best_position_adjusted_role_uses_the_tactics_familiarity_multiplier(self) -> None:
        fit = best_position_adjusted_role(
            player(1, "ST", 20, position_familiarity={"ST": 10}), CATALOGUE
        )

        self.assertIsNotNone(fit)
        assert fit is not None
        self.assertEqual(fit.position, "ST")
        self.assertEqual(fit.familiarity_rating, 10)
        self.assertTrue(fit.familiarity_known)
        self.assertEqual(fit.familiarity_multiplier, FamiliarityPolicy().multiplier(10))
        self.assertLess(
            fit.position_adjusted_score.central, fit.intrinsic_role_score.score.central
        )

    def test_one_weak_slot_outweighs_a_better_average(self) -> None:
        uneven = legal_squad()
        uneven[0] = player(1, "GK", 1)
        steady = [
            replace(
                item,
                attributes={"quality": AttributeObservation(Visibility.KNOWN, value=10)},
            )
            for item in legal_squad()
        ]

        uneven_result = evaluate_tactic(TACTIC, uneven, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)
        steady_result = evaluate_tactic(TACTIC, steady, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

        self.assertGreater(
            uneven_result.mean_score.central,
            steady_result.mean_score.central,
        )
        self.assertLess(uneven_result.score.central, steady_result.score.central)
        self.assertEqual(uneven_result.weakest_slot_keys, ("slot-0",))
        self.assertEqual(
            steady_result.weakest_score.central,
            steady_result.mean_score.central,
        )

    def test_tactic_ranking_prefers_steady_shape_over_higher_mean_weak_shape(self) -> None:
        weak_role = RoleDefinition(
            key="weak",
            name="Weak",
            eligible_positions=("GK",),
            attributes=(RoleAttribute("weak", 1),),
            catalogue_version=VERSION,
        )
        steady_role = RoleDefinition(
            key="steady",
            name="Steady",
            eligible_positions=ROLE.eligible_positions,
            attributes=(RoleAttribute("steady", 1),),
            catalogue_version=VERSION,
        )
        uneven_tactic = replace(
            TACTIC,
            key="uneven",
            slots=(TacticSlot("slot-0", "GK", "weak"),) + TACTIC.slots[1:],
        )
        steady_tactic = replace(
            TACTIC,
            key="steady",
            slots=tuple(replace(slot, role_key="steady") for slot in TACTIC.slots),
        )
        catalogue = FootballCatalogue(
            version=VERSION,
            roles={role.key: role for role in (ROLE, weak_role, steady_role)},
            tactics={item.key: item for item in (uneven_tactic, steady_tactic)},
        )
        squad = [
            replace(item, attributes={
                "quality": AttributeObservation(Visibility.KNOWN, value=12),
                "steady": AttributeObservation(Visibility.KNOWN, value=10),
                "weak": AttributeObservation(Visibility.KNOWN, value=1),
            })
            for item in legal_squad()
        ]

        recommendation = recommend_tactic(squad, catalogue, familiarity_policy=NO_FAMILIARITY_DISCOUNT)
        by_key = {item.tactic.key: item for item in recommendation.evaluations}

        self.assertEqual(recommendation.selected.tactic.key, "steady")
        self.assertGreater(
            by_key["uneven"].mean_score.central,
            by_key["steady"].mean_score.central,
        )
        self.assertLess(
            by_key["uneven"].score.central,
            by_key["steady"].score.central,
        )

    def test_fit_optimizer_can_prefer_a_balanced_xi_over_the_highest_mean(self) -> None:
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
            slots=TACTIC.slots[:-2] + (
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
            replace(player(10, "ST", 12), attributes={
                "a": AttributeObservation(Visibility.KNOWN, value=20),
                "b": AttributeObservation(Visibility.KNOWN, value=9),
            }),
            replace(player(11, "ST", 12), attributes={
                "a": AttributeObservation(Visibility.KNOWN, value=11),
                "b": AttributeObservation(Visibility.KNOWN, value=3),
            }),
        ]

        mean_best = evaluate_tactic(
            shaped, squad, catalogue, familiarity_policy=NO_FAMILIARITY_DISCOUNT,
            fit_policy=TacticFitPolicy(weakest_slot_weight=0),
        )
        balanced = evaluate_tactic(
            shaped, squad, catalogue, familiarity_policy=NO_FAMILIARITY_DISCOUNT
        )

        mean_ids = {item.slot.key: item.player_id for item in mean_best.assignments}
        balanced_ids = {item.slot.key: item.player_id for item in balanced.assignments}
        self.assertEqual((mean_ids["slot-9"], mean_ids["slot-10"]), ("10", "11"))
        self.assertEqual(
            (balanced_ids["slot-9"], balanced_ids["slot-10"]),
            ("11", "10"),
        )
        self.assertLess(balanced.mean_score.central, mean_best.mean_score.central)
        self.assertGreater(balanced.weakest_score.central, mean_best.weakest_score.central)
        self.assertEqual(balanced.fit_weakest_weight, 0.35)

    def test_missing_slot_has_zero_weakest_score(self) -> None:
        evaluation = evaluate_tactic(TACTIC, legal_squad()[:-1], CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

        self.assertFalse(evaluation.has_legal_xi)
        self.assertEqual(evaluation.weakest_score.central, 0)
        self.assertEqual(
            evaluation.weakest_slot_keys,
            tuple(slot.key for slot in evaluation.unfilled_slots),
        )
        self.assertEqual(len(evaluation.weakest_slot_keys), 1)
        self.assertEqual(
            evaluation.score.central,
            round(0.65 * evaluation.mean_score.central, 6),
        )

    def test_fit_policy_rejects_invalid_weight(self) -> None:
        for weight in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                TacticFitPolicy(weakest_slot_weight=weight)

    def test_narrow_squad_gets_legal_diamond_instead_of_partial_wide_xi(self) -> None:
        required = {
            attribute.name
            for role in MVP_CATALOGUE.roles.values()
            for attribute in role.attributes
        }
        positions = (
            "GK", "DL", "DC", "DC", "DR", "DM", "MC", "MC", "AMC", "ST", "ST", "MR"
        )
        squad = [
            PlayerSelectionInput(
                id=str(index),
                name=f"Player {index:02}",
                positions=(position,),
                attributes={
                    name: AttributeObservation(Visibility.KNOWN, value=10)
                    for name in required
                },
                availability="available",
                injured=False,
                suspended=False,
                condition_percent=100,
                match_fitness_percent=100,
            )
            for index, position in enumerate(positions, 1)
        ]

        recommendation = recommend_tactic(squad, MVP_CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

        self.assertEqual(recommendation.selected.tactic.key, "balanced_41212_diamond")
        self.assertTrue(recommendation.selected.has_legal_xi)
        self.assertEqual(len({item.player_id for item in recommendation.selected.assignments}), 11)

    def test_builds_legal_xi_with_unique_eligible_players(self) -> None:
        squad = legal_squad()
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

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

        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

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

        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

        self.assertFalse(evaluation.has_legal_xi)
        self.assertEqual([slot.position for slot in evaluation.unfilled_slots], ["GK"])

    def test_unknown_readiness_is_penalized_and_explained(self) -> None:
        squad = legal_squad()
        squad.append(player(20, "ST", 20, condition=None, match_fitness=None))

        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

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

        recommendation = recommend_tactic(legal_squad(), catalogue, familiarity_policy=NO_FAMILIARITY_DISCOUNT)

        self.assertEqual(recommendation.selected.tactic.key, "test")
        self.assertTrue(recommendation.selected.has_legal_xi)

    def test_rejects_duplicate_player_ids(self) -> None:
        squad = legal_squad()
        squad.append(player(1, "ST", 20))

        with self.assertRaisesRegex(ValueError, "unique"):
            evaluate_tactic(TACTIC, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)


class FamiliarityTests(unittest.TestCase):
    def test_known_rating_scales_role_score_by_a_multiplier(self) -> None:
        policy = FamiliarityPolicy(floor_multiplier=0.0)
        natural = player(1, "ST", 20, position_familiarity={"ST": 20})
        unconvincing = player(2, "ST", 20, position_familiarity={"ST": 9})

        natural_fit = score_player_for_slot(
            natural, TACTIC.slots[9], CATALOGUE, familiarity_policy=policy
        )
        unconvincing_fit = score_player_for_slot(
            unconvincing, TACTIC.slots[9], CATALOGUE, familiarity_policy=policy
        )

        self.assertEqual(natural_fit.familiarity_multiplier, 1.0)
        self.assertEqual(unconvincing_fit.familiarity_multiplier, policy.multiplier(9))
        self.assertEqual(natural_fit.familiarity_warnings, ())
        self.assertEqual(unconvincing_fit.familiarity_warnings, ())
        self.assertEqual(
            unconvincing_fit.selection_score.central,
            round(
                unconvincing_fit.intrinsic_role_score.score.central * policy.multiplier(9), 6
            ),
        )
        self.assertLess(
            unconvincing_fit.selection_score.central, natural_fit.selection_score.central
        )

    def test_floor_multiplier_bounds_the_worst_case_discount(self) -> None:
        # At the worst rating (1), the multiplier is exactly floor_multiplier,
        # regardless of how harsh a floor the policy configures.
        policy = FamiliarityPolicy(floor_multiplier=0.3)

        self.assertEqual(policy.multiplier(1), 0.3)
        self.assertEqual(policy.multiplier(20), 1.0)

    def test_missing_reading_falls_back_to_the_eligibility_minimum_and_warns(self) -> None:
        policy = FamiliarityPolicy(floor_multiplier=0.0)
        unread = player(1, "ST", 20)

        fit = score_player_for_slot(unread, TACTIC.slots[9], CATALOGUE, familiarity_policy=policy)

        self.assertEqual(fit.familiarity_multiplier, policy.multiplier(policy.unknown_rating))
        self.assertEqual(fit.familiarity_warnings, ("ST familiarity unknown",))

    def test_potential_disables_the_discount(self) -> None:
        policy = FamiliarityPolicy(floor_multiplier=0.0)
        unconvincing = player(1, "ST", 20, position_familiarity={"ST": 9})

        effective = score_player_for_slot(
            unconvincing, TACTIC.slots[9], CATALOGUE, familiarity_policy=policy
        )
        potential = score_player_for_slot(
            unconvincing, TACTIC.slots[9], CATALOGUE, familiarity_policy=policy.potential()
        )

        self.assertLess(effective.familiarity_multiplier, 1.0)
        self.assertEqual(potential.familiarity_multiplier, 1.0)
        self.assertEqual(
            potential.selection_score.central, potential.intrinsic_role_score.score.central
        )

    def test_familiarity_policy_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "below maximum"):
            FamiliarityPolicy(scale_minimum=20, scale_maximum=1)
        with self.assertRaisesRegex(ValueError, "within the familiarity scale"):
            FamiliarityPolicy(unknown_rating=0)
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            FamiliarityPolicy(floor_multiplier=-0.1)
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            FamiliarityPolicy(floor_multiplier=1.1)

    def test_effective_and_potential_recommendation_shares_every_other_input(self) -> None:
        squad = [
            player(index, position, 15, position_familiarity={position: 9})
            for index, position in enumerate(
                ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST"), 1
            )
        ]
        policy = FamiliarityPolicy(floor_multiplier=0.0)

        result = recommend_tactic_effective_and_potential(
            squad, CATALOGUE, familiarity_policy=policy
        )

        effective = result.effective.by_tactic_key("test")
        potential = result.potential.by_tactic_key("test")
        self.assertLess(effective.score.central, potential.score.central)
        # Every player is Unconvincing (9) at their own listed position, so
        # readiness and intrinsic role quality are identical between runs;
        # only the familiarity multiplier differs, uniformly, by design.
        self.assertEqual(
            round(effective.score.central / potential.score.central, 6),
            policy.multiplier(9),
        )

    def test_training_targets_reports_tactics_with_a_material_potential_gap(self) -> None:
        squad = [
            player(index, position, 15, position_familiarity={position: 9})
            for index, position in enumerate(
                ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST"), 1
            )
        ]
        result = recommend_tactic_effective_and_potential(
            squad, CATALOGUE, familiarity_policy=FamiliarityPolicy(floor_multiplier=0.0)
        )

        targets = result.training_targets()

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].tactic_key, "test")
        self.assertGreater(targets[0].score_gap, 0)
        self.assertEqual(
            targets[0].score_gap,
            round(targets[0].potential_score.central - targets[0].effective_score.central, 6),
        )

    def test_training_targets_excludes_gaps_below_the_minimum(self) -> None:
        # Every player is already Natural (20) at their own listed position,
        # so the familiarity penalty -- and therefore the potential gap -- is
        # zero regardless of policy weight.
        squad = [
            player(index, position, 15, position_familiarity={position: 20})
            for index, position in enumerate(
                ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST"), 1
            )
        ]
        result = recommend_tactic_effective_and_potential(squad, CATALOGUE)

        self.assertEqual(result.training_targets(), ())

    def test_training_target_bar_is_relative_to_effective_fit(self) -> None:
        squad = [
            player(index, position, 15, position_familiarity={position: 17})
            for index, position in enumerate(
                ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST"), 1
            )
        ]
        policy = FamiliarityPolicy(floor_multiplier=0.5)
        result = recommend_tactic_effective_and_potential(
            squad, CATALOGUE, familiarity_policy=policy
        )
        target = result.effective.by_tactic_key("test")
        expected_ratio = round(1 - policy.multiplier(17), 6)

        # A bar just above the real ratio excludes it; just below admits it.
        self.assertEqual(
            result.training_targets(minimum_gap_ratio=expected_ratio + 0.01), ()
        )
        self.assertEqual(
            [t.tactic_key for t in result.training_targets(minimum_gap_ratio=expected_ratio - 0.01)],
            ["test"],
        )

    def test_a_tactic_with_a_zero_effective_baseline_treats_any_gap_as_material(self) -> None:
        # A zero floor at the worst rating means the only fillable slot (GK)
        # scores exactly zero effectively while still being "filled" (nine
        # other slots are genuinely unfilled either way) -- baseline is 0.0
        # by score, not merely because slots are missing, so the relative
        # ratio check would divide by zero if it were not guarded.
        squad = [player(1, "GK", 15, position_familiarity={"GK": 1})]
        result = recommend_tactic_effective_and_potential(
            squad, CATALOGUE, familiarity_policy=FamiliarityPolicy(floor_multiplier=0.0)
        )
        effective = result.effective.by_tactic_key("test")
        self.assertEqual(effective.score.central, 0)

        target = next(
            (t for t in result.training_targets(minimum_gap_ratio=0.5) if t.tactic_key == "test"),
            None,
        )

        self.assertIsNotNone(target)
        self.assertGreater(target.score_gap, 0)


if __name__ == "__main__":
    unittest.main()
