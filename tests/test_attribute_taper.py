"""Attribute taper: fit falls away below a tactic's attribute level, it never cuts off.

The guiding property is in the name. Nobody is ruled out below a level; a player
short on one attribute but strong elsewhere can still be the best available.
"""

import unittest
from dataclasses import replace

from fm_analytics.analytics import MVP_CATALOGUE, PlayerSelectionInput, evaluate_tactic
from fm_analytics.analytics.attribute_taper import (
    AttributeTaperPolicy,
    assess_tapers,
    taper_role_score,
)
from fm_analytics.analytics.bench_selection import select_bench
from fm_analytics.analytics.catalogue import AttributeTaper, FootballCatalogue
from fm_analytics.analytics.role_scoring import score_role
from fm_analytics.analytics.weaknesses import assess_weaknesses
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes

TACTIC = "balanced_442"


def known(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


def ranged(low: int, high: int) -> AttributeObservation:
    return AttributeObservation(Visibility.RANGE, minimum=low, maximum=high)


def with_tapers(*tapers: AttributeTaper, tactic_key: str = TACTIC) -> FootballCatalogue:
    tactic = replace(MVP_CATALOGUE.tactics[tactic_key], attribute_taper=tuple(tapers))
    return replace(MVP_CATALOGUE, tactics={**MVP_CATALOGUE.tactics, tactic_key: tactic})


class CurveTests(unittest.TestCase):
    policy = AttributeTaperPolicy()

    def test_no_penalty_at_or_above_the_level(self) -> None:
        for value in (12, 13, 20):
            self.assertEqual(self.policy.factor(value, 12), 1.0)

    def test_the_penalty_grows_smoothly_with_the_shortfall(self) -> None:
        factors = [self.policy.factor(v, 12) for v in (12, 11, 10, 9, 8, 7, 6)]
        # No cliff: each point short costs the same, and never increases.
        steps = [round(a - b, 6) for a, b in zip(factors, factors[1:])]
        self.assertEqual(steps, [0.06] * 6)

    def test_a_single_shortfall_never_costs_more_than_the_floor(self) -> None:
        self.assertEqual(self.policy.factor(1, 12), 0.5)
        self.assertEqual(self.policy.factor(2, 12), 0.5)

    def test_it_matches_the_numbers_the_design_promised(self) -> None:
        self.assertEqual(
            {v: round(self.policy.factor(v, 12), 2) for v in (10, 8, 4)},
            {10: 0.88, 8: 0.76, 4: 0.52},
        )

    def test_policy_rejects_incoherent_floors(self) -> None:
        with self.assertRaises(ValueError):
            AttributeTaperPolicy(single_floor=0.3, combined_floor=0.5)
        with self.assertRaises(ValueError):
            AttributeTaperPolicy(penalty_per_point=0)


class AssessmentTests(unittest.TestCase):
    def test_no_tapers_means_no_penalty(self) -> None:
        result = assess_tapers((), {"passing": known(3)})
        self.assertEqual(result.multiplier.central, 1.0)
        self.assertFalse(result.applies)

    def test_a_player_above_the_level_is_untouched_and_unexplained(self) -> None:
        result = assess_tapers((AttributeTaper("passing", 12),), {"passing": known(14)})
        self.assertFalse(result.applies)
        self.assertEqual(result.notes, ())

    def test_a_shortfall_is_explained_in_plain_words(self) -> None:
        result = assess_tapers((AttributeTaper("firstTouch", 12),), {"firstTouch": known(8)})
        self.assertEqual(result.notes, ("first touch 8, below this tactic's 12 (fit ×0.76)",))

    def test_several_tapers_multiply(self) -> None:
        result = assess_tapers(
            (AttributeTaper("passing", 12), AttributeTaper("stamina", 12)),
            {"passing": known(10), "stamina": known(10)},
        )
        self.assertAlmostEqual(result.multiplier.central, 0.88 * 0.88, places=6)

    def test_the_combined_penalty_never_scores_a_player_to_nothing(self) -> None:
        tapers = tuple(AttributeTaper(a, 20) for a in ("passing", "stamina", "pace", "vision"))
        result = assess_tapers(tapers, {a.attribute: known(1) for a in tapers})
        self.assertEqual(result.multiplier.central, AttributeTaperPolicy().combined_floor)
        self.assertGreater(result.multiplier.central, 0)

    def test_a_scouted_range_is_penalised_at_its_low_end_only(self) -> None:
        result = assess_tapers((AttributeTaper("passing", 12),), {"passing": ranged(8, 14)})
        band = result.multiplier
        self.assertLess(band.lower, band.central)       # 8 is short
        self.assertEqual(band.upper, 1.0)               # 14 is not
        self.assertLessEqual(band.central, band.upper)

    def test_an_unknown_attribute_is_treated_as_the_scale_minimum_centrally(self) -> None:
        result = assess_tapers((AttributeTaper("passing", 12),), {})
        self.assertEqual(result.multiplier.central, 0.5)   # floor
        self.assertEqual(result.multiplier.upper, 1.0)     # could still be fine
        self.assertIn("not known", result.notes[0])


class TaperDefinitionTests(unittest.TestCase):
    def test_a_taper_level_must_be_a_whole_number_within_the_scale(self) -> None:
        for bad in (0, 1, 21, 12.5, "12", None, True):
            with self.assertRaisesRegex(ValueError, "taper level"):
                AttributeTaper("passing", bad)

    def test_positions_must_be_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            AttributeTaper("passing", 12, ("MC", "MC"))

    def test_an_unknown_attribute_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown attributes"):
            with_tapers(AttributeTaper("pasing", 12))

    def test_a_position_the_tactic_does_not_field_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not field"):
            with_tapers(AttributeTaper("passing", 12, ("WBL",)))

    def test_tapering_one_attribute_twice_for_a_position_is_refused(self) -> None:
        # It would quietly double the penalty.
        with self.assertRaisesRegex(ValueError, "more than once"):
            with_tapers(AttributeTaper("passing", 12), AttributeTaper("passing", 10, ("MC",)))

    def test_the_same_attribute_at_different_positions_is_fine(self) -> None:
        with_tapers(AttributeTaper("passing", 12, ("MC",)), AttributeTaper("passing", 10, ("DC",)))


class LoaderTests(unittest.TestCase):
    def test_entries_load_with_and_without_positions(self) -> None:
        from fm_analytics.analytics.catalogue import _taper_blocks

        tapers = _taper_blocks(
            [{"attribute": "passing", "taperBelow": 12, "positions": ["MC"]},
             {"attribute": "stamina", "taperBelow": 11}], "t")
        self.assertEqual(tapers[0], AttributeTaper("passing", 12, ("MC",)))
        self.assertEqual(tapers[1].positions, ())

    def test_the_word_minimum_is_not_accepted(self) -> None:
        # The name is the contract: this is a taper, not a hard minimum.
        from fm_analytics.analytics.catalogue import _taper_blocks

        with self.assertRaisesRegex(ValueError, "unknown key.*minimum"):
            _taper_blocks([{"attribute": "passing", "minimum": 12}], "t")

    def test_a_non_list_is_refused_with_a_message_that_says_what_to_write(self) -> None:
        from fm_analytics.analytics.catalogue import _taper_blocks

        with self.assertRaisesRegex(ValueError, "must be a list"):
            _taper_blocks({"passing": 12}, "t")


RIVALS = {
    # Great at the work, poor passer.
    "Grafter": {"passing": 5, "workRate": 19, "stamina": 19, "tackling": 19,
                "positioning": 19, "teamwork": 19},
    # A specialist passer, otherwise ordinary.
    "Passer": {"passing": 17, "vision": 16, "firstTouch": 16, "technique": 16},
    # Solid all round, including passing.
    "Steady": {"passing": 13, "workRate": 14, "stamina": 14, "tackling": 14,
               "positioning": 14, "teamwork": 14},
}


class SelectionTests(unittest.TestCase):
    """Behaviour in a real evaluation of balanced_442's two central-midfield slots."""

    def _players(self, rivals=None) -> tuple[PlayerSelectionInput, ...]:
        """Twelve all-rounders who cannot play MC, plus the named midfielders.

        Only the rivals are MC-eligible, so who takes the two MC slots isolates
        the effect of the taper.
        """
        attributes = sorted(required_role_attributes())
        players = [
            PlayerSelectionInput(
                id=f"base-{i}", name=f"Base {i}",
                positions=("GK", "DL", "DR", "DC", "ML", "MR", "ST"),
                attributes={a: known(12) for a in attributes}, availability="available",
                injured=False, suspended=False, condition_percent=100, match_fitness_percent=100,
            )
            for i in range(12)
        ]
        for name, strong in (RIVALS if rivals is None else rivals).items():
            values = {a: known(11) for a in attributes}
            values.update({a: known(v) for a, v in strong.items()})
            players.append(PlayerSelectionInput(
                id=name, name=name, positions=("MC",), attributes=values, availability="available",
                injured=False, suspended=False, condition_percent=100, match_fitness_percent=100,
            ))
        return tuple(players)

    def _evaluate(self, catalogue: FootballCatalogue, players=None):
        return evaluate_tactic(catalogue.tactics[TACTIC], players or self._players(), catalogue)

    def _mc(self, evaluation) -> dict:
        return {a.player_name: a for a in evaluation.assignments if a.slot.position == "MC"}

    def test_without_a_taper_the_poor_passer_wins_a_place_on_his_other_strengths(self) -> None:
        self.assertEqual(set(self._mc(self._evaluate(MVP_CATALOGUE))), {"Grafter", "Steady"})

    def test_a_taper_changes_who_is_picked(self) -> None:
        catalogue = with_tapers(AttributeTaper("passing", 12, ("MC",)))
        self.assertEqual(set(self._mc(self._evaluate(catalogue))), {"Passer", "Steady"})

    def test_a_shortfall_lowers_the_score_by_the_stated_factor(self) -> None:
        plain = self._mc(self._evaluate(MVP_CATALOGUE))["Grafter"]
        catalogue = with_tapers(AttributeTaper("passing", 12, ("MC",)))
        # Not selected under the taper, so read his score in his slot directly.
        from fm_analytics.analytics import score_player_for_slot

        player = next(p for p in self._players() if p.id == "Grafter")
        slot = next(s for s in catalogue.tactics[TACTIC].slots if s.position == "MC")
        tapered = score_player_for_slot(player, slot, catalogue.for_tactic(TACTIC))
        # Passing 5 against a level of 12 is 7 short: 1 - 0.06 * 7 = 0.58.
        self.assertAlmostEqual(tapered.taper_multiplier.central, 0.58, places=6)
        self.assertLess(tapered.selection_score.central, plain.selection_score.central)
        self.assertAlmostEqual(
            tapered.selection_score.central / plain.selection_score.central, 0.58, places=2
        )
        self.assertEqual(len(tapered.taper_notes), 1)

    def test_the_taper_is_a_penalty_not_a_bar(self) -> None:
        # Three points short (passing 9 against 12) costs 18%, which an
        # overwhelmingly better all-rounder more than makes up: he still plays,
        # visibly penalised.
        rivals = {
            "Grafter": {**RIVALS["Grafter"], "passing": 9, "decisions": 20, "anticipation": 20,
                        "concentration": 20, "composure": 20, "vision": 20, "firstTouch": 20},
            "Passer": RIVALS["Passer"], "Steady": RIVALS["Steady"],
        }
        catalogue = with_tapers(AttributeTaper("passing", 12, ("MC",)))
        picked = self._mc(self._evaluate(catalogue, self._players(rivals)))
        self.assertIn("Grafter", set(picked))
        self.assertTrue(picked["Grafter"].taper_notes)
        self.assertAlmostEqual(picked["Grafter"].taper_multiplier.central, 0.82, places=6)

    def test_the_taper_reaches_only_the_positions_it_names(self) -> None:
        catalogue = with_tapers(AttributeTaper("passing", 12, ("ML", "MR")))
        picked = self._mc(self._evaluate(catalogue))
        self.assertEqual(set(picked), {"Grafter", "Steady"})        # unchanged
        self.assertTrue(all(a.taper_multiplier.central == 1.0 for a in picked.values()))

    def test_a_whole_team_taper_reaches_every_slot(self) -> None:
        catalogue = with_tapers(AttributeTaper("passing", 20))
        evaluation = self._evaluate(catalogue)
        self.assertTrue(all(a.taper_multiplier.central < 1.0 for a in evaluation.assignments))

    def test_the_taper_is_not_booked_as_a_readiness_cost(self) -> None:
        catalogue = with_tapers(AttributeTaper("passing", 12, ("MC",)))
        evaluation = self._evaluate(catalogue)
        for a in evaluation.assignments:
            self.assertAlmostEqual(
                a.tapered_score.central,
                a.in_position_score.central * a.taper_multiplier.central, places=5,
            )
            # Fully fit, so nothing separates the tapered score from today's:
            # whatever the taper removed is not left over to be called readiness.
            self.assertAlmostEqual(a.selection_score.central, a.tapered_score.central, places=4)

    def test_a_tactic_with_no_taper_scores_exactly_as_before(self) -> None:
        for a in self._evaluate(MVP_CATALOGUE).assignments:
            self.assertEqual(a.taper_multiplier.central, 1.0)
            self.assertEqual(a.taper_notes, ())
            self.assertEqual(a.tapered_score, a.in_position_score)


class ConsistencyTests(unittest.TestCase):
    """A starter and the cover for his slot must be judged the same way."""

    def test_starter_and_cover_are_both_tapered_in_the_depth_report(self) -> None:
        players = SelectionTests()._players()
        catalogue = with_tapers(AttributeTaper("passing", 12, ("MC",)))
        evaluation = evaluate_tactic(catalogue.tactics[TACTIC], players, catalogue)
        report = assess_weaknesses(evaluation, players, catalogue)
        mc = next(d for d in report.depth if d.slot.position == "MC")
        starter = next(a for a in evaluation.assignments if a.slot.key == mc.slot.key)
        # A backup's depth score is the same tapered figure a starter would get.
        for candidate in mc.available_backups:
            player = next(p for p in players if p.id == candidate.player_id)
            raw = score_role(
                catalogue.for_tactic(TACTIC).role_for_slot(mc.slot, starter.intrinsic_role_score.role_key),
                player.attributes,
            ).score.central
            self.assertLessEqual(candidate.role_score.score.central, raw + 1e-9)

    def test_bench_scores_carry_the_taper(self) -> None:
        players = SelectionTests()._players()
        catalogue = with_tapers(AttributeTaper("passing", 20))
        evaluation = evaluate_tactic(catalogue.tactics[TACTIC], players, catalogue)
        bench = select_bench(evaluation, players, catalogue, bench_size=3)
        for entry in bench.entries:
            self.assertLess(entry.primary_assignment.taper_multiplier.central, 1.0)


class RoleScoreTests(unittest.TestCase):
    def test_taper_role_score_leaves_an_unaffected_score_alone(self) -> None:
        role = MVP_CATALOGUE.roles["cm_support"]
        attributes = {a: known(14) for a in required_role_attributes()}
        base = score_role(role, attributes)
        self.assertIs(taper_role_score(base, assess_tapers((), attributes)), base)



class PresentationTests(unittest.TestCase):
    """Wording matters: this is a taper, and nothing should call it a minimum."""

    def _tactic(self):
        return replace(
            MVP_CATALOGUE.tactics[TACTIC],
            attribute_taper=(
                AttributeTaper("passing", 12, ("MC",)), AttributeTaper("stamina", 11),
            ),
        )

    def test_the_tactic_page_says_it_is_a_taper_and_names_where_it_applies(self) -> None:
        import re
        from fm_analytics.web.rendering import _tactic_notes

        text = re.sub(r"<[^>]+>", "", _tactic_notes(self._tactic()))
        self.assertIn("Expects at least: passing 12 (MC); stamina 11 (whole team)", text)
        self.assertIn("a taper, not a cut-off", text)
        self.assertNotIn("minimum", text.lower())

    def test_the_index_lists_the_levels(self) -> None:
        from tools.tactic_index import taper_detail

        self.assertEqual(taper_detail(self._tactic()), "passing 12 (MC); stamina 11 (whole team)")

    def test_no_shipped_tactic_uses_the_word_minimum_for_a_taper(self) -> None:
        # The loader refuses the key; this names the intent.
        import json
        from pathlib import Path

        data = Path(__file__).resolve().parents[1] / "src/fm_analytics/analytics/data/tactics"
        for path in data.glob("*.json"):
            self.assertNotIn("attributeMinimum", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
