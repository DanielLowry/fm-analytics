"""Team-assignment regressions, including a manager-visible real FM20 XI."""

import itertools
import json
import random
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import recommend_set_pieces
from fm_analytics.analytics.role_scoring import RoleAttribute
from fm_analytics.analytics.set_piece_routines import defensive_roles
from fm_analytics.analytics.set_pieces import _optimise_routine
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility


CAPTURE = Path(__file__).parent / "fixtures/hungerford-vertical-442-2020-10-20.json"


def known(value):
    return AttributeObservation(Visibility.KNOWN, value=value)


def solve(players, roles):
    return _optimise_routine(
        key="test", name="Test routine", phase="attacking", side=None,
        objective="Test whole-team assignment", roles=tuple(roles),
        players=tuple(players), recommendations=(), lineup_positions={}, notes=(),
    )


def signature(routine):
    return {item.role.key: item.player.id for item in routine.assignments}


class CapturedStartingXIRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game, cls.squad = load_fixture(CAPTURE)
        cls.positions = json.loads(CAPTURE.read_text())["lineupPositions"]
        cls.players = {player.name: player for player in cls.squad.players}

    def report(self, squad=None, **options):
        return recommend_set_pieces(
            squad or self.squad, selected_player_ids=tuple(self.positions),
            lineup_positions=self.positions, **options,
        )

    def corners(self, squad=None):
        return next(r for r in self.report(squad).routines if r.key == "defending_corner")

    def test_scarce_aerial_strength_contests_deliveries_instead_of_guarding_posts(self):
        routine = self.corners()
        jobs = {item.role.instruction: item.player.name for item in routine.assignments}

        self.assertEqual(jobs["Mark tall player"], "Ejiro Okosieme")
        zonal_players = {
            item.player.name for item in routine.assignments
            if item.role.instruction.startswith("Zonally mark")
        }
        self.assertIn("Jamie Bradley-Green", zonal_players)
        self.assertNotIn("Lucas Odunston", zonal_players)
        self.assertNotIn("Terrance Saydee", zonal_players)
        post_players = {jobs["Mark near post"], jobs["Mark far post"]}
        self.assertTrue(post_players.isdisjoint({"Ejiro Okosieme", "Jamie Bradley-Green"}))
        self.assertEqual(jobs["Stay forward"], "Victor Fundi")

    def test_aerial_ability_and_tracking_a_runner_are_distinct_requirements(self):
        roles = tuple(r for r in defensive_roles("corner") if r.instruction in {"Man mark", "Mark tall player"})
        routine = solve((self.players["David Lynch"], self.players["Ejiro Okosieme"]), roles)
        jobs = {item.role.instruction: item.player.name for item in routine.assignments}

        # Lynch has Jumping Reach 3 but strong positioning and tracking inputs.
        self.assertEqual(jobs["Man mark"], "David Lynch")
        self.assertEqual(jobs["Mark tall player"], "Ejiro Okosieme")

    def test_assignment_follows_attributes_when_real_player_profiles_are_exchanged(self):
        aerial = self.players["Ejiro Okosieme"]
        winger = self.players["Terrance Saydee"]
        swapped = replace(self.squad, players=tuple(
            replace(p, attributes=winger.attributes) if p.id == aerial.id
            else replace(p, attributes=aerial.attributes) if p.id == winger.id
            else p for p in self.squad.players
        ))
        marker = next(a for a in self.corners(swapped).assignments if a.role.instruction == "Mark tall player")

        self.assertEqual(marker.player.id, winger.id)

    def test_original_assignments_are_strictly_worse_under_the_revised_objective(self):
        previous = {
            "Defend area": "Jonathan De Bie", "Mark near post": "Ejiro Okosieme",
            "Mark far post": "Jamie Bradley-Green",
            "Zonally mark 6 yard box centre": "Ben Jefford",
            "Mark tall player": "Challis Johnson",
            "Zonally mark 6 yard box near post": "Lucas Odunston",
            "Zonally mark 6 yard box far post": "Terrance Saydee",
            "Man mark": "David Lynch", "Go back": "Victor Fundi",
            "Edge of area": "Tom Sharpe", "Stay forward": "Ross Holden",
        }
        old_value = sum(
            r.importance * r.score(self.players[previous[r.instruction]]).score.central
            for r in defensive_roles("corner")
        )
        routine = self.corners()
        self.assertGreater(sum(a.assignment_value for a in routine.assignments), old_value)

        roles = {r.instruction: r for r in defensive_roles("corner")}
        near, tall = roles["Mark near post"], roles["Mark tall player"]
        aerial, forward = self.players["Ejiro Okosieme"], self.players["Challis Johnson"]
        self.assertGreater(
            tall.importance * tall.score(aerial).score.central + near.importance * near.score(forward).score.central,
            tall.importance * tall.score(forward).score.central + near.importance * near.score(aerial).score.central,
        )

    def test_roster_order_does_not_change_any_routine_including_genuine_ties(self):
        expected = {r.key: signature(r) for r in self.report().routines}
        rng = random.Random(42)
        players = list(self.squad.players)
        for attempt in range(4):
            rng.shuffle(players)
            actual = self.report(replace(self.squad, players=tuple(players)))
            self.assertEqual({r.key: signature(r) for r in actual.routines}, expected, attempt)

    def test_lineup_availability_and_goalkeeper_constraints_apply_to_all_routines(self):
        injured = self.players["Ross Holden"]
        suspended = self.players["Terrance Saydee"]
        bench = replace(
            self.players["Ejiro Okosieme"], id="bench-star", name="Bench star",
            attributes={key: known(20) for key in self.players["Ejiro Okosieme"].attributes},
        )
        squad = replace(self.squad, players=tuple(
            replace(p, injured=True) if p.id == injured.id
            else replace(p, suspended=True) if p.id == suspended.id else p
            for p in self.squad.players
        ) + (bench,))
        for routine in self.report(squad).routines:
            with self.subTest(routine=routine.key):
                ids = [a.player.id for a in routine.assignments]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertTrue(set(ids).issubset(self.positions))
                self.assertTrue(set(ids).isdisjoint({injured.id, suspended.id, bench.id}))
                self.assertTrue(routine.unfilled_roles)
                for assignment in routine.assignments:
                    self.assertEqual(assignment.role.goalkeeper, self.positions[assignment.player.id] == "GK")

    def test_a_weak_squad_still_gets_complete_routines_without_ability_cutoffs(self):
        squad = replace(self.squad, players=tuple(
            replace(p, attributes={key: known(4) for key in p.attributes})
            for p in self.squad.players
        ))
        for routine in self.report(squad).routines:
            with self.subTest(routine=routine.key):
                self.assertFalse(routine.unfilled_roles)
                self.assertAlmostEqual(routine.score.central, 100 * 3 / 19, places=5)

    def test_unknown_attributes_remain_unknown_for_the_weighted_routine(self):
        squad = replace(self.squad, players=tuple(replace(p, attributes={}) for p in self.squad.players))
        for routine in self.report(squad).routines:
            self.assertFalse(routine.unfilled_roles)
            self.assertEqual(routine.evidence_coverage, 0)
            self.assertEqual((routine.score.lower, routine.score.central, routine.score.upper), (0, 0, 100))

    def test_ranged_aerial_attributes_retain_uncertainty(self):
        aerial = self.players["Ejiro Okosieme"]
        attrs = {**aerial.attributes, "jumpingReach": AttributeObservation(Visibility.RANGE, minimum=16, maximum=20)}
        squad = replace(self.squad, players=tuple(
            replace(p, attributes=attrs) if p.id == aerial.id else p for p in self.squad.players
        ))
        routine = self.corners(squad)
        assignment = next(a for a in routine.assignments if a.player.id == aerial.id)
        self.assertLess(assignment.score.score.lower, assignment.score.score.central)
        self.assertLess(assignment.score.score.central, assignment.score.score.upper)
        self.assertLess(routine.score.lower, routine.score.central)
        self.assertLess(routine.score.central, routine.score.upper)

    def test_attacking_corners_preserve_the_aerial_specialist_for_first_contact(self):
        for risk in ("secure", "balanced", "aggressive"):
            for routine in self.report(attacking_risk=risk).routines:
                if not routine.key.startswith("attacking_corner_"):
                    continue
                with self.subTest(risk=risk, routine=routine.key):
                    assignment = next(a for a in routine.assignments if a.player.name == "Ejiro Okosieme")
                    self.assertIn(assignment.role.instruction, {"Attack near post", "Attack far post"})

    def test_indirect_free_kicks_keep_both_main_aerial_defenders_attacking_the_delivery(self):
        for routine in self.report().routines:
            if routine.key not in {"defending_indirect_wide", "defending_indirect_deep"}:
                continue
            aerial_players = {a.player.name for a in routine.assignments if a.role.instruction == "Go back"}
            self.assertTrue({"Ejiro Okosieme", "Jamie Bradley-Green"}.issubset(aerial_players))


class WholeRoutineObjectiveTests(unittest.TestCase):
    def setUp(self):
        _game, squad = load_fixture(CAPTURE)
        self.base = next(p for p in squad.players if "GK" not in p.positions)
        self.role = next(r for r in defensive_roles("corner") if r.instruction == "Go back")

    def player(self, player_id, **attributes):
        return replace(self.base, id=player_id, name=player_id, attributes={k: known(v) for k, v in attributes.items()})

    def role_for(self, key, attribute, importance, priority=50):
        return replace(self.role, key=key, attributes=(RoleAttribute(attribute, 100),), importance=importance, priority=priority)

    def test_team_optimum_can_use_the_second_best_player_for_a_job(self):
        versatile = self.player("versatile", heading=16, marking=20)
        specialist = self.player("specialist", heading=14, marking=1)
        aerial = self.role_for("aerial", "heading", 2, priority=99)
        marker = self.role_for("marker", "marking", 1)
        result = solve((versatile, specialist), (aerial, marker))

        # Greedy selection would consume versatile in the first job and leave
        # a player with Marking 1 tracking a runner. The global solver does not.
        self.assertEqual(signature(result), {"aerial": "specialist", "marker": "versatile"})

    def test_importance_affects_the_objective_independently_of_inclusion_priority(self):
        strong = self.player("strong", heading=20)
        weak = self.player("weak", heading=10)
        important = self.role_for("important", "heading", 2, priority=1)
        secondary = self.role_for("secondary", "heading", 0.5, priority=99)
        result = solve((weak, strong), (secondary, important))

        self.assertEqual(signature(result), {"important": "strong", "secondary": "weak"})
        self.assertAlmostEqual(result.score.central, (2 * 100 + 0.5 * 100 * 9 / 19) / 2.5, places=5)
        self.assertTrue(all(0 <= a.score.score.central <= 100 for a in result.assignments))

    def test_weighted_assignment_matches_exhaustive_search_on_small_squads(self):
        rng = random.Random(17)
        roles = (
            self.role_for("aerial", "heading", 1.5),
            self.role_for("marker", "marking", 1.1),
            self.role_for("cover", "anticipation", 0.7),
        )
        for attempt in range(30):
            players = tuple(self.player(str(i), heading=rng.randint(1, 20), marking=rng.randint(1, 20), anticipation=rng.randint(1, 20)) for i in range(3))
            optimum = max(sum(
                r.importance * (p.attributes[r.attributes[0].name].value - 1) * 100 / 19
                for r, p in zip(roles, permutation)
            ) for permutation in itertools.permutations(players))
            result = solve(players, roles)
            self.assertAlmostEqual(sum(a.assignment_value for a in result.assignments), optimum, places=5, msg=str(attempt))

    def test_role_order_does_not_change_tied_assignments(self):
        players = (self.player("a", heading=10), self.player("b", heading=10))
        roles = (self.role_for("first", "heading", 1), self.role_for("second", "heading", 1))
        self.assertEqual(signature(solve(players, roles)), signature(solve(reversed(players), reversed(roles))))

    def test_partial_corner_routine_keeps_aerial_jobs_before_post_cover(self):
        _game, squad = load_fixture(CAPTURE)
        players = tuple(p for p in squad.players if p.name in {"Jonathan De Bie", "Ejiro Okosieme", "Jamie Bradley-Green"})
        report = recommend_set_pieces(replace(squad, players=players))
        routine = next(r for r in report.routines if r.key == "defending_corner")
        jobs = {a.role.instruction for a in routine.assignments}
        self.assertEqual(jobs, {"Defend area", "Mark tall player", "Zonally mark 6 yard box near post"})

    def test_invalid_importance_is_rejected(self):
        for importance in (0, -1, float("inf"), float("nan")):
            with self.subTest(importance=importance), self.assertRaises(ValueError):
                replace(self.role, importance=importance)


if __name__ == "__main__":
    unittest.main()
