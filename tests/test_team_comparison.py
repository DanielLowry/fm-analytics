import unittest
from dataclasses import replace
from itertools import product
from math import sqrt
from pathlib import Path

from fm_analytics.analytics import (
    RoleAttribute,
    SelectionObjective,
    TacticSlot,
    evaluate_tactic,
    recommend_tactic,
    score_player_for_slot,
)
from fm_analytics.analytics.team_comparison import TeamComparisonStatus, compare_team_xi
from fm_analytics.analytics.attribute_taper import AttributeTaper
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.cli import load_fixture
from fm_analytics.reporting import RecommendationPolicy, build_team_xi_comparison
from tests.test_xi_selection import CATALOGUE, NO_FAMILIARITY_DISCOUNT, TACTIC, legal_squad, player


class TeamComparisonTests(unittest.TestCase):
    def compare(self, players=None, catalogue=CATALOGUE, **kwargs):
        defaults = dict(roster_complete=True, positions_complete=True,
                        familiarity_policy=NO_FAMILIARITY_DISCOUNT)
        defaults.update(kwargs)
        return compare_team_xi(legal_squad() if players is None else players, catalogue, **defaults)

    def test_exact_roster_preserves_existing_recommendation_and_collapses_band(self):
        players = legal_squad()
        result = self.compare(players)
        existing = recommend_tactic(players, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)
        self.assertEqual(result.central, existing)
        self.assertEqual(result.lower, existing)
        self.assertEqual(result.upper, existing)
        self.assertEqual(result.score, existing.selected.score)
        self.assertEqual(result.score.lower, result.score.upper)

    def test_unknown_reserve_is_only_selected_at_the_ceiling_and_retains_evidence(self):
        players = legal_squad()
        reserve = replace(player(99, "ST", 20), attributes={
            "quality": AttributeObservation(Visibility.UNKNOWN),
        })
        result = self.compare([*players, reserve])
        for scenario in (result.lower, result.central):
            self.assertNotIn(reserve.id, {item.player_id for item in scenario.selected.assignments})
        ceiling = result.upper.selected
        self.assertIn(reserve.id, {item.player_id for item in ceiling.assignments})
        assignment = next(item for item in ceiling.assignments if item.player_id == reserve.id)
        self.assertEqual(assignment.intrinsic_role_score.contributions[0].observation.visibility,
                         Visibility.UNKNOWN)
        self.assertGreater(result.score.upper, result.central.selected.score.upper)
        self.assertEqual(len({item.player_id for item in ceiling.assignments}), 11)

    def test_role_and_tactic_choice_changes_between_endpoints(self):
        alternative = replace(CATALOGUE.roles["generic"], key="other", name="Other",
                              attributes=(RoleAttribute("other", 1),))
        other_tactic = replace(TACTIC, key="other_tactic", name="Other tactic",
                              slots=tuple(replace(slot, role_key="other") for slot in TACTIC.slots))
        flexible_tactic = replace(TACTIC, key="flexible", name="Flexible",
                                 slots=tuple(replace(slot, alternate_role_keys=("other",))
                                             for slot in TACTIC.slots))
        catalogue = replace(CATALOGUE, roles={**CATALOGUE.roles, "other": alternative},
                            tactics={TACTIC.key: TACTIC, other_tactic.key: other_tactic})
        players = [replace(p, attributes={**p.attributes, "other": AttributeObservation(
            Visibility.RANGE, minimum=1, maximum=20)}) for p in legal_squad()]
        result = self.compare(players, catalogue)
        self.assertEqual(result.lower.selected.tactic.key, TACTIC.key)
        self.assertEqual(result.upper.selected.tactic.key, other_tactic.key)
        flexible_catalogue = replace(catalogue, tactics={flexible_tactic.key: flexible_tactic})
        flexible = self.compare(players, flexible_catalogue)
        self.assertEqual({a.intrinsic_role_score.role_key for a in flexible.lower.selected.assignments},
                         {"generic"})
        self.assertEqual({a.intrinsic_role_score.role_key for a in flexible.upper.selected.assignments},
                         {"other"})

    def test_missing_roster_or_positions_never_yields_comparable_score_even_with_eleven(self):
        for kwargs, status in (
            ({"roster_complete": False}, TeamComparisonStatus.ROSTER_INCOMPLETE),
            ({"positions_complete": False}, TeamComparisonStatus.POSITIONS_INCOMPLETE),
        ):
            with self.subTest(status=status):
                result = self.compare(**kwargs)
                self.assertTrue(result.central.selected.has_legal_xi)
                self.assertEqual(result.status, status)
                self.assertIsNone(result.score)
        unknown_position = replace(player(99, "ST", 12), positions=())
        self.assertEqual(self.compare([*legal_squad(), unknown_position]).status,
                         TeamComparisonStatus.POSITIONS_INCOMPLETE)

    def test_partial_and_empty_rosters_are_explainable_but_unscored_in_every_scenario(self):
        for players in (legal_squad()[:3], []):
            result = self.compare(players)
            self.assertEqual(result.status, TeamComparisonStatus.NO_LEGAL_XI)
            self.assertIsNone(result.score)
            for scenario in (result.lower, result.central, result.upper):
                self.assertFalse(scenario.selected.has_legal_xi)

    def test_wholly_unknown_and_uncaptured_attributes_keep_legal_zero_floor_xi(self):
        for attributes in ({}, {"quality": AttributeObservation(Visibility.UNKNOWN)}):
            players = [replace(p, attributes=attributes) for p in legal_squad()]
            result = self.compare(players)
            self.assertEqual(result.status, TeamComparisonStatus.READY)
            self.assertEqual(result.score.lower, 0)
            self.assertEqual(result.score.central, 0)
            self.assertGreater(result.score.upper, 0)

    def test_tactic_scope_is_explicit_and_invalid_keys_are_rejected(self):
        result = self.compare(tactic_keys=[TACTIC.key])
        self.assertEqual(result.tactic_keys, (TACTIC.key,))
        for keys in ([], [TACTIC.key, TACTIC.key], ["does_not_exist"]):
            with self.assertRaises(ValueError):
                self.compare(tactic_keys=keys)
        with self.assertRaises(ValueError):
            self.compare(roster_complete="yes")
        with self.assertRaises(ValueError):
            evaluate_tactic(TACTIC, legal_squad(), CATALOGUE, objective="median")

    def test_tightening_attributes_narrows_band_for_unchanged_eligibility(self):
        players = [replace(p, attributes={"quality": AttributeObservation(
            Visibility.RANGE, minimum=5, maximum=18)}) for p in legal_squad()]
        wide = self.compare(players).score
        narrower = self.compare([replace(p, attributes={"quality": AttributeObservation(
            Visibility.RANGE, minimum=10, maximum=14)}) for p in players]).score
        exact = self.compare().score
        self.assertLessEqual(wide.lower, narrower.lower)
        self.assertGreaterEqual(wide.upper, narrower.upper)
        self.assertLessEqual(narrower.lower, exact.central)
        self.assertGreaterEqual(narrower.upper, exact.central)

    def test_tapered_unknown_inputs_bound_every_exact_completion(self):
        tapered = replace(TACTIC, attribute_taper=(AttributeTaper("quality", below=13),))
        catalogue = replace(CATALOGUE, tactics={tapered.key: tapered})
        players = [replace(p, attributes={"quality": AttributeObservation(Visibility.RANGE,
                    minimum=8, maximum=16)}) for p in legal_squad()]
        bounds = self.compare(players, catalogue).score
        for value in range(8, 17):
            exact_players = [replace(p, attributes={"quality": AttributeObservation(
                Visibility.KNOWN, value=value)}) for p in players]
            exact = self.compare(exact_players, catalogue).score.central
            self.assertLessEqual(bounds.lower, exact)
            self.assertGreaterEqual(bounds.upper, exact)

    def test_reporting_uses_existing_policies_and_does_not_limit_search_to_our_pins(self):
        original = replace(TACTIC, key="pinned", name="Pinned")
        better = replace(TACTIC, key="best", name="Best")
        catalogue = replace(CATALOGUE, tactics={original.key: original, better.key: better})
        _, squad = load_fixture(Path(__file__).resolve().parents[1] /
                                "src/fm_analytics/fixtures/sample-game.json")
        players = tuple(replace(squad.players[0], id=p.id, name=p.name, positions=p.positions,
                               attributes=p.attributes, availability="available", injured=False,
                               suspended=False, condition_percent=100, match_fitness_percent=100)
                        for p in legal_squad())
        squad = replace(squad, players=players)
        policy = RecommendationPolicy(pinned_tactics=(original.key,),
                                      familiarity=NO_FAMILIARITY_DISCOUNT)
        result = build_team_xi_comparison(squad, roster_complete=True, positions_complete=True,
                                         catalogue=catalogue, policy=policy)
        self.assertEqual(set(result.tactic_keys), {original.key, better.key})
        self.assertEqual(result.central.selected.tactic.key, better.key)
        restricted = build_team_xi_comparison(squad, roster_complete=True, positions_complete=True,
                                             catalogue=catalogue, policy=policy,
                                             tactic_keys=policy.pinned_tactics)
        self.assertEqual(restricted.central.selected.tactic.key, original.key)

    def test_shared_position_assignment_matches_exhaustive_oracle_at_each_endpoint(self):
        positions = ("GK", "DL", "DC", "DC", "DR", "DM", "MC", "AMC", "AML", "AMR", "ST")
        role = replace(CATALOGUE.roles["generic"], eligible_positions=tuple(set(positions)))
        tactic = replace(TACTIC, slots=tuple(TacticSlot(str(i), position, role.key)
                                            for i, position in enumerate(positions)))
        catalogue = replace(CATALOGUE, roles={role.key: role}, tactics={tactic.key: tactic})
        players = [player(i, position, 12) for i, position in enumerate(positions)
                   if position not in {"MC", "AMC"}]
        players.extend(replace(player(i + 20, "MC", 12), positions=("MC", "AMC"),
                               attributes={"quality": observation})
                       for i, observation in enumerate((
                           AttributeObservation(Visibility.KNOWN, value=12),
                           AttributeObservation(Visibility.RANGE, minimum=4, maximum=20),
                           AttributeObservation(Visibility.RANGE, minimum=10, maximum=14),
                           AttributeObservation(Visibility.UNKNOWN),
                       )))
        choices = [tuple(assignment for p in players if (assignment := score_player_for_slot(
            p, slot, catalogue, familiarity_policy=NO_FAMILIARITY_DISCOUNT)) is not None)
                   for slot in tactic.slots]
        legal = [assignments for assignments in product(*choices)
                 if len({a.player_id for a in assignments}) == 11]
        self.assertGreater(len(legal), 1)
        for objective in SelectionObjective:
            result = evaluate_tactic(tactic, players, catalogue, objective=objective,
                                     familiarity_policy=NO_FAMILIARITY_DISCOUNT)
            maximum = max(round((sum(sqrt(getattr(a.selection_score, objective)) for a in assignments)
                                 / 11) ** 2 * result.tactic_balance_multiplier, 6)
                          for assignments in legal)
            self.assertAlmostEqual(getattr(result.score, objective), maximum, places=5)


if __name__ == "__main__":
    unittest.main()
