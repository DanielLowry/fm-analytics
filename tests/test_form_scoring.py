"""Recent form inside the recommendation: the exact job only, applied before players and roles are chosen."""

import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from fm_analytics.analytics import (
    FootballCatalogue,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    evaluate_tactic,
    explain_tactic_selection,
    score_player_for_slot,
)
from fm_analytics.analytics.player_form import FormLookup, FormPolicy, FormRating, JobForm
from fm_analytics.cli import load_fixture
from fm_analytics.domain.matches import TeamRef
from fm_analytics.persistence.match_history import MatchHistory
from fm_analytics.reporting import squad_form
from fm_analytics.web.form_render import form_chip

from tests.test_xi_selection import CATALOGUE, NO_FAMILIARITY_DISCOUNT, TACTIC, VERSION, legal_squad, player

FIXTURE = Path(__file__).resolve().parents[1] / "src" / "fm_analytics" / "fixtures" / "sample-game.json"
STRIKER_JOB = ("test", "ST", "generic")


def strikers_squad():
    """The legal eleven plus a third striker, all three strikers equal."""
    squad = legal_squad()
    squad.append(player(12, "ST", 12))
    return squad


def selected_ids(squad):
    evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)
    return {assignment.player_id for assignment in evaluation.assignments}


class FormScoringTests(unittest.TestCase):
    def test_without_form_every_evaluation_is_exactly_as_before(self) -> None:
        plain = evaluate_tactic(TACTIC, legal_squad(), CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)
        elsewhere = [replace(p, form={("another_tactic", "ST", "generic"): 0.98}) for p in legal_squad()]
        self.assertEqual(
            evaluate_tactic(TACTIC, elsewhere, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT), plain
        )

    def test_poor_form_loses_a_close_choice(self) -> None:
        for out_of_form in ("10", "11", "12"):
            squad = [
                replace(p, form={STRIKER_JOB: 0.99}) if p.id == out_of_form else p for p in strikers_squad()
            ]
            self.assertNotIn(out_of_form, selected_ids(squad))

    def test_form_counts_only_in_its_exact_job(self) -> None:
        striker = replace(player(1, "ST", 12), positions=("ST", "MC"), form={STRIKER_JOB: 1.02})
        st_slot, mc_slot = TACTIC.slots[-1], TACTIC.slots[5]
        plain = score_player_for_slot(striker, st_slot, CATALOGUE, role_key="generic")
        here = score_player_for_slot(striker, st_slot, CATALOGUE, role_key="generic", tactic_key="test")
        elsewhere = score_player_for_slot(striker, st_slot, CATALOGUE, role_key="generic", tactic_key="other")
        midfield = score_player_for_slot(striker, mc_slot, CATALOGUE, role_key="generic", tactic_key="test")
        self.assertAlmostEqual(here.selection_score.central, plain.selection_score.central * 1.02, places=5)
        self.assertAlmostEqual(here.form_change, here.selection_score.central - plain.selection_score.central)
        self.assertEqual((here.form_multiplier, plain.form_multiplier), (1.02, 1.0))
        self.assertEqual(elsewhere.selection_score, plain.selection_score)
        self.assertEqual(midfield.form_multiplier, 1.0)

    def test_form_is_applied_per_role_before_the_role_is_chosen(self) -> None:
        # Two roles score the same for him; form in the alternate role makes it his best.
        alternate = RoleDefinition(
            key="alternate", name="Alternate", eligible_positions=("ST",),
            attributes=(RoleAttribute("quality", 1),), catalogue_version=VERSION,
        )
        slot = TacticSlot(key="ST", position="ST", role_key="generic", alternate_role_keys=("alternate",))
        shape = replace(TACTIC, key="flex", slots=TACTIC.slots[:-1] + (slot,))
        catalogue = FootballCatalogue(
            version=VERSION, roles={**CATALOGUE.roles, "alternate": alternate}, tactics={"flex": shape}
        )
        striker = replace(player(1, "ST", 12), form={("flex", "ST", "alternate"): 1.01})
        best = score_player_for_slot(striker, slot, catalogue, tactic_key="flex")
        self.assertEqual(best.intrinsic_role_score.role_key, "alternate")

    def test_worker_processes_rank_with_the_same_form(self) -> None:
        from fm_analytics.analytics import TacticRankingExecutor, recommend_tactic_effective_and_potential

        squad = [replace(p, form={STRIKER_JOB: 0.99}) if p.id == "10" else p for p in strikers_squad()]
        expected = recommend_tactic_effective_and_potential(squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)
        executor = TacticRankingExecutor(workers=2)
        try:
            ranked = recommend_tactic_effective_and_potential(
                squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT, ranking_executor=executor
            )
        finally:
            executor.shutdown()
        self.assertEqual(ranked, expected)
        self.assertNotIn("10", {a.player_id for a in ranked.effective.selected.assignments})

    def test_a_score_never_goes_above_100(self) -> None:
        striker = replace(player(1, "ST", 20), form={STRIKER_JOB: 1.02})
        assignment = score_player_for_slot(striker, TACTIC.slots[-1], CATALOGUE, role_key="generic", tactic_key="test")
        self.assertLessEqual(assignment.selection_score.upper, 100.0)

    def test_the_explanation_keeps_fitness_and_form_apart(self) -> None:
        def readiness_costs(squad):
            evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT)
            explained = explain_tactic_selection(
                evaluation, squad, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT
            )
            return {item.starter.player_id: item.readiness_score_cost for item in explained.slots}

        tired = [replace(p, condition_percent=70) if p.id == "11" else p for p in legal_squad()]
        in_form = [replace(p, form={STRIKER_JOB: 1.02}) if p.id == "11" else p for p in tired]
        self.assertGreater(readiness_costs(tired)["11"], 0)
        self.assertEqual(readiness_costs(in_form), readiness_costs(tired))


class SquadFormTests(unittest.TestCase):
    def history(self, club_id):
        return MatchHistory("club", TeamRef(club_id, "Club"), (), (), {}, {}, None)

    def test_form_comes_only_from_this_clubs_own_history(self) -> None:
        game, squad = load_fixture(FIXTURE)
        self.assertIsInstance(squad_form(self.history(squad.club.id), game, squad), FormLookup)
        self.assertIsNone(squad_form(self.history("another-club"), game, squad))
        self.assertIsNone(squad_form(None, game, squad))


class FormChipTests(unittest.TestCase):
    def job(self):
        rating = FormRating("m", date(2020, 3, 28), "Braintree Town", 7.15, 90, 1.0)
        return JobForm("7", "Victor Fundi", "vertical_442", "ST", "af_attack", (rating,), 7.15, 0.25, 1.001)

    def test_the_chip_shows_the_points_form_moved_todays_score(self) -> None:
        striker = score_player_for_slot(
            replace(player(1, "ST", 12), form={STRIKER_JOB: 1.02}), TACTIC.slots[-1], CATALOGUE,
            role_key="generic", tactic_key="test",
        )
        self.assertAlmostEqual(striker.form_change, 0.85, places=2)  # 2% of his 42.7
        self.assertIn("▲ +0.9", form_chip(striker, self.job()))
        self.assertIn("form-up", form_chip(striker, self.job()))

    def test_a_change_that_rounds_to_nothing_reads_0_0_and_no_games_reads_a_dash(self) -> None:
        tiny = replace(score_player_for_slot(player(1, "ST", 12), TACTIC.slots[-1], CATALOGUE), form_change=-0.02)
        chip = form_chip(tiny, self.job())
        self.assertIn(">0.0</span>", chip)
        self.assertNotIn("-0.0", chip)
        self.assertIn(">–</span>", form_chip(tiny, None))


if __name__ == "__main__":
    unittest.main()
