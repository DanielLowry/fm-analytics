"""The opponent profile actually reaching scoring, not just declaring effects.

Three things this guards, each a way the wiring could be wrong without
`test_opponent.py` (which only checks the declared data) catching it:

* a neutral profile is invisible everywhere it is threaded through -- the
  tactic evaluation, its component scores, the bench, the substitution board
  and the weakness/depth report are all byte-identical to calling with no
  opponent at all;
* a non-neutral profile actually changes who is picked, not just a number;
* the `for_tactic`/`for_context` split does not double-apply a tactic's own
  emphasis when one entry point's derived catalogue is handed to another
  (the counterfactual scores `explain_tactic_selection` computes via
  `evaluate_tactic_with_forced_assignment`).
"""

import unittest

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    OpponentProfile,
    PlayerSelectionInput,
    assess_squad_depth,
    assess_weaknesses,
    build_substitution_board,
    evaluate_tactic,
    evaluate_tactic_with_forced_assignment,
    explain_tactic_selection,
    recommend_tactic,
    select_bench,
)
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes

TACTIC = "balanced_442"
ATTRIBUTES = sorted(required_role_attributes())


def _flat_player(player_id: str, positions: tuple[str, ...], **overrides: int) -> PlayerSelectionInput:
    values = {name: 12 for name in ATTRIBUTES}
    values.update(overrides)
    return PlayerSelectionInput(
        id=player_id,
        name=player_id,
        positions=positions,
        attributes={
            name: AttributeObservation(Visibility.KNOWN, value=value)
            for name, value in values.items()
        },
        availability="available",
        injured=False,
        suspended=False,
        condition_percent=100,
        match_fitness_percent=100,
    )


def _squad_with_two_goalkeepers() -> tuple[PlayerSelectionInput, ...]:
    """One outfielder per other slot, plus two GK-only rivals who differ.

    Commander is built for the air (aerialReach/commandOfArea); Shotstopper
    for shot-stopping (reflexes/handling). Values are tuned so Shotstopper
    starts ahead and a +2 aerial threat is enough to flip the pick -- proving
    the opponent changed a selection, not just a score.
    """
    outfield = tuple(
        _flat_player(f"outfield-{i}", ("DL", "DR", "DC", "MC", "ML", "MR", "AML", "AMR", "ST"))
        for i in range(12)
    )
    commander = _flat_player("Commander", ("GK",), aerialReach=17, commandOfArea=17)
    shotstopper = _flat_player("Shotstopper", ("GK",), reflexes=17, handling=17)
    return outfield + (commander, shotstopper)


def _picked(evaluation, slot_key: str) -> str:
    return next(a.player_name for a in evaluation.assignments if a.slot.key == slot_key)


class NeutralOpponentChangesNothingTests(unittest.TestCase):
    """The default opponent must leave every existing surface untouched."""

    def setUp(self) -> None:
        self.tactic = MVP_CATALOGUE.tactics[TACTIC]
        self.players = _squad_with_two_goalkeepers()
        self.neutral = OpponentProfile.neutral()

    def test_evaluate_tactic_is_identical_with_and_without_an_explicit_neutral_profile(self) -> None:
        without = evaluate_tactic(self.tactic, self.players, MVP_CATALOGUE)
        with_neutral = evaluate_tactic(self.tactic, self.players, MVP_CATALOGUE, opponent=self.neutral)
        self.assertEqual(without, with_neutral)

    def test_opponent_fit_is_inactive_and_perfect_under_neutral(self) -> None:
        evaluation = evaluate_tactic(self.tactic, self.players, MVP_CATALOGUE, opponent=self.neutral)
        self.assertFalse(evaluation.opponent_fit.active)
        self.assertEqual(evaluation.opponent_fit.score, 100.0)

    def test_recommend_tactic_ranking_is_unaffected_by_an_explicit_neutral_profile(self) -> None:
        without = recommend_tactic(self.players, MVP_CATALOGUE)
        with_neutral = recommend_tactic(self.players, MVP_CATALOGUE, opponent=self.neutral)
        self.assertEqual(
            [e.tactic.key for e in without.evaluations],
            [e.tactic.key for e in with_neutral.evaluations],
        )
        self.assertEqual(without.selected.score, with_neutral.selected.score)

    def test_bench_and_substitution_board_are_unaffected(self) -> None:
        evaluation = evaluate_tactic(self.tactic, self.players, MVP_CATALOGUE)
        without_bench = select_bench(evaluation, self.players, MVP_CATALOGUE)
        with_bench = select_bench(evaluation, self.players, MVP_CATALOGUE, opponent=self.neutral)
        self.assertEqual(without_bench, with_bench)
        without_board = build_substitution_board(evaluation, without_bench, self.players, MVP_CATALOGUE)
        with_board = build_substitution_board(
            evaluation, with_bench, self.players, MVP_CATALOGUE, opponent=self.neutral
        )
        self.assertEqual(without_board, with_board)

    def test_weakness_and_depth_reports_are_unaffected(self) -> None:
        evaluation = evaluate_tactic(self.tactic, self.players, MVP_CATALOGUE)
        without = assess_weaknesses(evaluation, self.players, MVP_CATALOGUE)
        with_neutral = assess_weaknesses(evaluation, self.players, MVP_CATALOGUE, opponent=self.neutral)
        self.assertEqual(without, with_neutral)
        recommendation = recommend_tactic(self.players, MVP_CATALOGUE)
        depth_without = assess_squad_depth(recommendation.evaluations, self.players, MVP_CATALOGUE)
        depth_with = assess_squad_depth(
            recommendation.evaluations, self.players, MVP_CATALOGUE, opponent=self.neutral
        )
        self.assertEqual(depth_without, depth_with)

    def test_selection_explanation_is_unaffected(self) -> None:
        evaluation = evaluate_tactic(self.tactic, self.players, MVP_CATALOGUE)
        without = explain_tactic_selection(evaluation, self.players, MVP_CATALOGUE)
        with_neutral = explain_tactic_selection(evaluation, self.players, MVP_CATALOGUE, opponent=self.neutral)
        self.assertEqual(without, with_neutral)


class OpponentChangesSelectionTests(unittest.TestCase):
    """A non-neutral profile must change who is picked, not just a score."""

    def test_aerial_threat_flips_a_close_goalkeeper_pick(self) -> None:
        tactic = MVP_CATALOGUE.tactics[TACTIC]
        players = _squad_with_two_goalkeepers()
        neutral = evaluate_tactic(tactic, players, MVP_CATALOGUE, opponent=OpponentProfile.neutral())
        self.assertEqual(_picked(neutral, "GK"), "Shotstopper")
        aerial = evaluate_tactic(tactic, players, MVP_CATALOGUE, opponent=OpponentProfile(aerial_threat=2))
        self.assertEqual(_picked(aerial, "GK"), "Commander")

    def test_a_demanding_opponent_makes_the_new_component_active_with_a_real_shortfall(self) -> None:
        # attacking_433 cannot reach the defensiveCover/restDefence floor a very
        # fast opponent asks for (see test_opponent.ReachabilityTests), so the
        # new component must be active and short of 100 once it is wired all
        # the way through `evaluate_tactic`, not just in `assess_opponent_fit`
        # directly (already covered in test_opponent.py).
        players = _squad_with_two_goalkeepers()
        tactic = MVP_CATALOGUE.tactics["attacking_433"]
        neutral = evaluate_tactic(tactic, players, MVP_CATALOGUE, opponent=OpponentProfile.neutral())
        fast = evaluate_tactic(tactic, players, MVP_CATALOGUE, opponent=OpponentProfile(pace_in_behind=2))
        self.assertFalse(neutral.opponent_fit.active)
        self.assertTrue(fast.opponent_fit.active)
        self.assertLess(fast.opponent_fit.score, 100.0)
        self.assertTrue(fast.opponent_fit.shortfalls)

    def test_a_demanding_opponent_lowers_the_blended_score_for_a_strong_enough_squad(self) -> None:
        # The blended score only falls once the opponent-fit shortfall (~83
        # here) is actually the *worst* of the active components -- for a weak
        # synthetic squad, xi_score itself is well below that, and adding a
        # comparatively strong opponent-fit component can pull the blend *up*.
        # A near-maximal squad avoids that trap and isolates the intended effect.
        strong = tuple(
            _flat_player(f"strong-{i}", ("DL", "DR", "DC", "MC", "ML", "MR", "AML", "AMR", "ST"), **{
                a: 20 for a in ATTRIBUTES
            })
            for i in range(11)
        )
        strong_gk = _flat_player("strong-gk", ("GK",), **{a: 20 for a in ATTRIBUTES})
        players = strong + (strong_gk,)
        tactic = MVP_CATALOGUE.tactics["attacking_433"]
        neutral = evaluate_tactic(tactic, players, MVP_CATALOGUE, opponent=OpponentProfile.neutral())
        fast = evaluate_tactic(tactic, players, MVP_CATALOGUE, opponent=OpponentProfile(pace_in_behind=2))
        self.assertLess(fast.score.central, neutral.score.central)


class NoDoubleApplicationRegressionTests(unittest.TestCase):
    """`explain_tactic_selection`'s counterfactuals must apply emphasis once.

    `explain_tactic_selection` derives its own tactic view for scoring
    alternatives, then hands the *original* (plain) catalogue on to
    `evaluate_tactic_with_forced_assignment`, which derives its own view in
    turn. Passing the already-derived view into it instead would apply the
    tactic's emphasis a second time.
    """

    def test_a_counterfactual_score_matches_a_direct_single_application(self) -> None:
        tactic = MVP_CATALOGUE.tactics[TACTIC]
        self.assertTrue(tactic.attribute_emphasis, "test needs a tactic with real emphasis")
        players = _squad_with_two_goalkeepers()
        evaluation = evaluate_tactic(tactic, players, MVP_CATALOGUE)
        gk_role_key = next(
            a for a in evaluation.assignments if a.slot.key == "GK"
        ).intrinsic_role_score.role_key
        explanation = explain_tactic_selection(evaluation, players, MVP_CATALOGUE, alternative_limit=1)
        gk_slot = next(slot for slot in explanation.slots if slot.starter.slot.key == "GK")
        self.assertTrue(gk_slot.alternatives)
        alternative = gk_slot.alternatives[0]
        # A direct, single-application evaluation with that same player forced
        # into the same slot and role must give the identical score -- if the
        # emphasis were applied twice inside `explain_tactic_selection`, this
        # would disagree.
        forced = evaluate_tactic_with_forced_assignment(
            tactic,
            players,
            MVP_CATALOGUE,
            slot_key="GK",
            player_id=alternative.player_id,
            role_key=gk_role_key,
        )
        self.assertEqual(forced.score, alternative.counterfactual_score)


if __name__ == "__main__":
    unittest.main()
