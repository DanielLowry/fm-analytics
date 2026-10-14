"""Real-XI and structural evidence for choosing defensive free-kick plans."""

import json
import random
import shutil
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from fm_analytics.analytics import recommend_set_pieces
from fm_analytics.analytics.set_piece_config import DATA_DIR, DefensiveApproach, SET_PIECE_WEIGHTS, load_set_piece_weights
from fm_analytics.analytics.set_piece_plan_selection import comparison_score, select_defensive_plan
from fm_analytics.analytics.set_piece_routines import defensive_roles
from fm_analytics.analytics.set_pieces import _optimise_routine
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility


CAPTURE = Path(__file__).parent / "fixtures/hungerford-control-433dm-2020-10-20.json"
CURRENT_CAPTURE = Path(__file__).parent / "fixtures/hungerford-control-433dm-2020-11-01.json"
KINDS = ("indirect_wide", "indirect_deep")
GROUP_INSTRUCTIONS = {"wall": "Wall", "back": "Go back", "mark": "Man mark", "edge": "Edge of area", "forward": "Stay forward"}


def known(value):
    return AttributeObservation(Visibility.KNOWN, value=value)


class CapturedXITests(unittest.TestCase):
    capture = CAPTURE

    @classmethod
    def setUpClass(cls):
        _, cls.squad = load_fixture(cls.capture)
        cls.positions = json.loads(cls.capture.read_text())["lineupPositions"]

    def routines(self, squad=None, approach="balanced"):
        return tuple(r for r in recommend_set_pieces(
            squad or self.squad, selected_player_ids=tuple(self.positions),
            lineup_positions=self.positions, attacking_risk=approach,
        ).routines if r.selection)

    def solve(self, kind, template, squad=None):
        return _optimise_routine(
            key="test", name="Test plan", phase="defending", side=None,
            objective="Test template comparison", roles=defensive_roles(kind, template),
            players=(squad or self.squad).players, recommendations=(),
            lineup_positions=self.positions, notes=(),
        )


class TemplateSelectionTests(CapturedXITests):
    def test_earlier_control_xi_uses_one_wide_outlet_and_two_deep_outlets(self):
        wide, deep = self.routines()
        self.assertEqual(wide.selection.template_key, "two_player_wall_marking")
        self.assertEqual(deep.selection.template_key, "two_outlets_second_balls")
        expected_deep = {
            "Jonathan De Bie": "Defend area", "Ejiro Okosieme": "Go back",
            "Jamie Bradley-Green": "Go back", "Nathan Collier": "Go back", "Josh Neufville": "Go back",
            "David Lynch": "Man mark", "Ben Jefford": "Man mark",
            "Tom Sharpe": "Edge of area", "Lucas Odunston": "Edge of area",
            "Ross Holden": "Stay forward", "Abdul Sankoh": "Stay forward",
        }
        self.assertEqual({a.player.name: a.role.instruction for a in deep.assignments}, expected_deep)
        self.assertEqual(sum(a.role.instruction == "Wall" for a in wide.assignments), 2)
        self.assertEqual(sum(a.role.instruction == "Wall" for a in deep.assignments), 0)
        self.assertEqual(wide.players_held_back, 1)
        self.assertEqual(deep.players_held_back, 2)
        for routine in (wide, deep):
            self.assertFalse(routine.unfilled_roles)
            self.assertEqual(len(routine.assignments), 11)
            self.assertEqual(len({a.player.id for a in routine.assignments}), 11)
            self.assertGreaterEqual(routine.players_in_box, 6)
            self.assertEqual(next(a.player.name for a in routine.assignments if a.role.goalkeeper), "Jonathan De Bie")
            self.assertEqual(next(a.role.instruction for a in routine.assignments if a.player.name == "Ejiro Okosieme"), "Go back")

    def test_dropdown_changes_coverage_without_allowing_unbalanced_templates(self):
        for approach in ("secure", "balanced", "aggressive"):
            for routine in self.routines(approach=approach):
                with self.subTest(approach=approach, routine=routine.key):
                    self.assertEqual(routine.selection.approach, approach)
                    self.assertGreaterEqual(len(routine.selection.comparisons), 2)
                    for candidate in routine.selection.comparisons:
                        self.assertGreaterEqual(candidate.box_defenders, 7 if approach == "secure" else 6)
                        if approach != "balanced":
                            self.assertEqual(candidate.outlets, 1 if approach == "secure" else 2)

    def test_selected_assignment_beats_every_other_eligible_complete_plan(self):
        for approach in ("secure", "balanced", "aggressive"):
            for kind, routine in zip(KINDS, self.routines(approach=approach)):
                winner = comparison_score(routine)
                policy = SET_PIECE_WEIGHTS.defensive_approaches[approach]
                for template in SET_PIECE_WEIGHTS.defensive_templates[kind]:
                    if policy.accepts(template):
                        self.assertGreaterEqual(winner.central, comparison_score(self.solve(kind, template)).central)
                self.assertEqual(routine.selection.comparisons[0].key, routine.selection.template_key)
                self.assertEqual(routine.selection.comparisons[0].score, winner)
                self.assertEqual(winner, routine.score)

    def test_responsibility_budgets_stay_constant_when_job_counts_change(self):
        for kind in KINDS:
            expected = SET_PIECE_WEIGHTS.routine("defending_free_kicks", kind)
            totals = []
            for template in SET_PIECE_WEIGHTS.defensive_templates[kind]:
                roles = defensive_roles(kind, template)
                self.assertEqual(len(roles), 11)
                self.assertEqual(len({r.key for r in roles}), 11)
                for group, instruction in GROUP_INSTRUCTIONS.items():
                    jobs = [r for r in roles if r.instruction == instruction]
                    self.assertEqual(len(jobs), template.jobs[group])
                    if jobs:
                        self.assertAlmostEqual(sum(r.importance for r in jobs), expected[group].importance)
                totals.append(sum(r.importance for r in roles))
            self.assertAlmostEqual(min(totals), max(totals))

    def test_equal_player_suitability_does_not_reward_repeating_easier_jobs(self):
        # Every attribute has the same known rating. A change of role counts
        # must not raise plan fit by giving extra influence to one group.
        equal = replace(self.squad, players=tuple(
            replace(p, attributes={key: known(14) for key in p.attributes}) for p in self.squad.players
        ))
        for routine in self.routines(equal):
            self.assertEqual(len({candidate.score for candidate in routine.selection.comparisons}), 1)
            self.assertEqual(routine.selection.template_key, "delivery_cover")
            self.assertEqual(routine.players_held_back, 1)

    def test_stronger_defensive_wingers_can_select_a_different_template(self):
        defensive = {"heading", "jumpingReach", "bravery", "strength", "marking", "positioning", "anticipation", "concentration", "tackling"}
        revised = replace(self.squad, players=tuple(
            replace(p, attributes={key: known(16) if key in defensive else observation for key, observation in p.attributes.items()})
            if p.name in {"Ross Holden", "Abdul Sankoh"} else p for p in self.squad.players
        ))
        changed = self.routines(revised)
        self.assertTrue(any(r.selection.template_key != original.selection.template_key for r, original in zip(changed, self.routines())))

    def test_a_team_with_one_exceptional_outlet_can_choose_one_forward(self):
        outlet_inputs = {"pace", "acceleration", "firstTouch", "offTheBall", "strength", "dribbling", "passing"}
        revised = replace(self.squad, players=tuple(replace(p, attributes={
            key: known(20 if p.name == "Josh Neufville" and key in outlet_inputs else 14)
            for key in p.attributes
        }) for p in self.squad.players))
        for routine in self.routines(revised):
            self.assertEqual(routine.players_held_back, 1)
            self.assertEqual(next(a.player.name for a in routine.assignments if a.role.instruction == "Stay forward"), "Josh Neufville")

    def test_aerial_responsibility_follows_attributes_when_identities_are_exchanged(self):
        players = {p.name: p for p in self.squad.players}
        revised = replace(self.squad, players=tuple(
            replace(p, attributes=players["Ross Holden"].attributes) if p.name == "Ejiro Okosieme"
            else replace(p, attributes=players["Ejiro Okosieme"].attributes) if p.name == "Ross Holden"
            else p for p in self.squad.players
        ))
        for routine in self.routines(revised):
            self.assertEqual(next(a.role.instruction for a in routine.assignments if a.player.name == "Ross Holden"), "Go back")

    def test_player_and_template_order_do_not_change_the_selected_plan(self):
        shuffled = list(self.squad.players)
        random.Random(77).shuffle(shuffled)
        self.assertEqual([asdict(r) for r in self.routines()], [asdict(r) for r in self.routines(replace(self.squad, players=tuple(shuffled)))])
        for kind in KINDS:
            templates = SET_PIECE_WEIGHTS.defensive_templates[kind]
            policy = SET_PIECE_WEIGHTS.defensive_approaches["balanced"]
            original = select_defensive_plan(templates, policy, "balanced", lambda t: self.solve(kind, t))
            reversed_plan = select_defensive_plan(tuple(reversed(templates)), policy, "balanced", lambda t: self.solve(kind, t))
            self.assertEqual(original, reversed_plan)

    def test_unavailable_players_are_excluded_and_missing_coverage_reduces_plan_fit(self):
        revised = replace(self.squad, players=tuple(replace(p, injured=True) if p.name == "Ejiro Okosieme" else p for p in self.squad.players))
        for routine in self.routines(revised):
            self.assertNotIn("Ejiro Okosieme", {a.player.name for a in routine.assignments})
            self.assertTrue(routine.unfilled_roles)
            self.assertTrue(all(candidate.unfilled_jobs > 0 for candidate in routine.selection.comparisons))
            self.assertLess(comparison_score(routine).central, routine.score.central)

    def test_ranged_and_unknown_attributes_retain_score_uncertainty(self):
        revised = replace(self.squad, players=tuple(replace(p, attributes={
            **p.attributes, "jumpingReach": AttributeObservation(Visibility.RANGE, minimum=5, maximum=15),
            "marking": AttributeObservation(Visibility.UNKNOWN),
        }) for p in self.squad.players))
        for routine in self.routines(revised):
            for candidate in routine.selection.comparisons:
                self.assertLess(candidate.score.lower, candidate.score.central)
                self.assertLess(candidate.score.central, candidate.score.upper)
            self.assertLess(routine.evidence_coverage, 1)

    def test_stricter_coverage_policy_can_restrict_future_context_choices(self):
        for kind in KINDS:
            policy = DefensiveApproach(7, 1, 2)
            plan = select_defensive_plan(SET_PIECE_WEIGHTS.defensive_templates[kind], policy, "balanced", lambda t: self.solve(kind, t))
            self.assertTrue(all(candidate.box_defenders >= 7 for candidate in plan.selection.comparisons))
            with self.assertRaisesRegex(ValueError, "No defensive free-kick template"):
                select_defensive_plan(SET_PIECE_WEIGHTS.defensive_templates[kind], DefensiveApproach(10, 1, 2), "balanced", lambda t: self.solve(kind, t))


class UpdatedControlXITests(CapturedXITests):
    capture = CURRENT_CAPTURE

    def test_current_xi_selects_reviewed_wide_and_deep_assignments(self):
        common = {
            "Jonathan De Bie": "Defend area", "Ejiro Okosieme": "Go back",
            "Harrison Ashby": "Go back", "Jamie Bradley-Green": "Go back",
            "David Lynch": "Man mark", "Ben Jefford": "Man mark", "Tom Sharpe": "Edge of area",
        }
        expected = (
            ("two_player_wall_marking", {
                **common, "Nathan Collier": "Man mark", "Ross Holden": "Wall",
                "Abdul Sankoh": "Wall", "Victor Fundi": "Stay forward",
            }),
            ("two_outlets_marking", {
                **common, "Nathan Collier": "Go back", "Victor Fundi": "Man mark",
                "Ross Holden": "Stay forward", "Abdul Sankoh": "Stay forward",
            }),
        )
        for routine, (key, assignments) in zip(self.routines(), expected):
            with self.subTest(routine=routine.key):
                self.assertEqual(routine.selection.template_key, key)
                self.assertEqual({a.player.name: a.role.instruction for a in routine.assignments}, assignments)
                self.assertEqual(len({a.player.id for a in routine.assignments}), 11)
                self.assertFalse(routine.unfilled_roles)

    def test_new_structures_beat_the_previous_catalogue_for_current_xi(self):
        expected = (
            ("two_player_wall_marking", "two_outlets_marking", 49.268941, 49.589936),
            ("two_outlets_marking", "two_outlets_second_balls", 48.588466, 48.810750),
        )
        policy = SET_PIECE_WEIGHTS.defensive_approaches["balanced"]
        for kind, routine, (added, old_key, old_score, new_score) in zip(KINDS, self.routines(), expected):
            with self.subTest(kind=kind):
                previous = select_defensive_plan(
                    tuple(t for t in SET_PIECE_WEIGHTS.defensive_templates[kind] if t.key != added),
                    policy, "balanced", lambda t: self.solve(kind, t),
                )
                self.assertEqual(previous.selection.template_key, old_key)
                self.assertAlmostEqual(previous.score.central, old_score, places=5)
                self.assertAlmostEqual(routine.score.central, new_score, places=5)
                self.assertGreater(routine.score.central, previous.score.central)
                self.assertTrue(all(routine.score.central >= candidate.score.central for candidate in routine.selection.comparisons))

    def test_approach_filters_preserve_defensive_balance_with_new_choices(self):
        expected = {
            "secure": (("runner_cover", 2, 1, 7), ("runner_cover", 3, 1, 8)),
            "balanced": (("two_player_wall_marking", 6, 1, 6), ("two_outlets_marking", 6, 2, 7)),
            "aggressive": (("two_outlets_marking", 2, 2, 6), ("two_outlets_marking", 3, 2, 7)),
        }
        for approach, outcomes in expected.items():
            for routine, (key, candidates, outlets, box) in zip(self.routines(approach=approach), outcomes):
                with self.subTest(approach=approach, routine=routine.key):
                    self.assertEqual(routine.selection.template_key, key)
                    self.assertEqual(len(routine.selection.comparisons), candidates)
                    self.assertEqual(routine.players_held_back, outlets)
                    self.assertEqual(routine.players_in_box, box)
                    for candidate in routine.selection.comparisons:
                        self.assertGreaterEqual(candidate.box_defenders, 7 if approach == "secure" else 6)
                        if approach != "balanced":
                            self.assertEqual(candidate.outlets, outlets)


class TemplateCatalogueValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "weights"
        shutil.copytree(DATA_DIR, self.directory)

    def reject(self, mutate, message):
        shutil.copytree(DATA_DIR, self.directory, dirs_exist_ok=True)
        path = self.directory / "defending_free_kicks.json"
        document = json.loads(path.read_text())
        mutate(document)
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, message):
            load_set_piece_weights(self.directory)

    def test_missing_unknown_and_empty_catalogues_fail_clearly(self):
        for mutate, message in (
            (lambda d: d.pop("templates"), "missing keys.*templates"),
            (lambda d: d["templates"].pop("indirect_deep"), "missing keys.*indirect_deep"),
            (lambda d: d["templates"].update(direct_free_kick=[]), "unexpected keys.*direct_free_kick"),
            (lambda d: d["templates"].update(indirect_wide=[]), "non-empty template array"),
            (lambda d: d["templates"].update(indirect_wide={}), "non-empty template array"),
        ):
            with self.subTest(message=message):
                self.reject(mutate, message)

    def test_unknown_template_fields_missing_jobs_and_invalid_identity_are_rejected(self):
        for mutate, message in (
            (lambda d: d["templates"]["indirect_wide"][0].update(oppositionStrength=1), "unexpected keys.*oppositionStrength"),
            (lambda d: d["templates"]["indirect_wide"][0]["jobs"].pop("edge"), "missing keys.*edge"),
            (lambda d: d["templates"]["indirect_wide"][0].update(key=""), "non-empty string"),
            (lambda d: d["templates"]["indirect_wide"][0].update(description=None), "non-empty string"),
        ):
            self.reject(mutate, message)

    def test_job_counts_must_be_integers_and_assign_ten_outfield_players(self):
        for value in (-1, True, 1.5, "2", None):
            self.reject(lambda d: d["templates"]["indirect_wide"][0]["jobs"].update(wall=value), "non-negative integers")
        self.reject(lambda d: d["templates"]["indirect_wide"][0]["jobs"].update(back=6), "ten outfield players")

    def test_every_catalogue_entry_requires_sensible_defensive_balance(self):
        invalid = (
            dict(wall=0, mark=2, back=6, edge=1, forward=1),
            dict(wall=2, mark=2, back=3, edge=1, forward=2),
            dict(wall=1, mark=1, back=6, edge=1, forward=1),
            dict(wall=1, mark=2, back=6, edge=0, forward=1),
            dict(wall=1, mark=2, back=6, edge=1, forward=0),
            dict(wall=1, mark=2, back=3, edge=1, forward=3),
        )
        for jobs in invalid:
            with self.subTest(jobs=jobs):
                self.reject(lambda d: d["templates"]["indirect_wide"][0].update(jobs=jobs), "inadequate balance")
        self.reject(lambda d: d["templates"]["indirect_deep"][0].update(jobs=dict(wall=1, mark=2, back=5, edge=1, forward=1)), "inadequate balance")

    def test_duplicate_ids_and_duplicate_structures_are_rejected(self):
        self.reject(lambda d: d["templates"]["indirect_wide"][1].update(key=d["templates"]["indirect_wide"][0]["key"]), "duplicate template")
        self.reject(lambda d: d["templates"]["indirect_wide"][1].update(jobs=d["templates"]["indirect_wide"][0]["jobs"]), "duplicate template")

    def test_approaches_cannot_relax_minimum_defensive_balance_or_have_no_choices(self):
        for mutate, message in (
            (lambda d: d["approaches"].pop("secure"), "missing keys.*secure"),
            (lambda d: d["approaches"]["balanced"].update(minimumBoxDefenders=5), "approach must retain"),
            (lambda d: d["approaches"]["secure"].update(maximumOutlets=2), "approach must retain"),
            (lambda d: d["approaches"]["aggressive"].update(minimumOutlets=1), "approach must retain"),
            (lambda d: d["approaches"]["balanced"].update(minimumBoxDefenders=True), "requirements must be integers"),
            (lambda d: d["approaches"]["secure"].update(minimumBoxDefenders=8), "no eligible indirect_wide"),
        ):
            self.reject(mutate, message)

    def test_unscoreable_responsibility_budget_is_rejected(self):
        self.reject(lambda d: d["variants"]["indirect_wide"]["back"].update(importance=1e308), "budget is too large")


if __name__ == "__main__":
    unittest.main()
