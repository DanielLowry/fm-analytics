"""The opponent profile and the effects it declares.

The effects are football hypotheses, so these tests guard structure, not the
numbers: a neutral opponent changes nothing, every name the table uses exists,
a higher setting never asks for less, and the floors stay on a scale the
catalogue can actually supply.
"""

import unittest
from dataclasses import fields
from itertools import product

from fm_analytics.analytics.catalogue import MVP_CATALOGUE
from fm_analytics.analytics.opponent import (
    AXES,
    AXIS_DEFINITIONS,
    EmphasisRule,
    FloorRule,
    OpponentAxis,
    OpponentProfile,
    assess_opponent_fit,
    attribute_emphasis,
    system_floors,
)
from fm_analytics.analytics.tactical_system import SYSTEM_DIMENSIONS, role_traits
from fm_analytics.reporting import required_role_attributes

SETTINGS = (-2, -1, 0, 1, 2)
FIELDED_POSITIONS = {slot.position for t in MVP_CATALOGUE.tactics.values() for slot in t.slots}


def one_axis(axis: str, value: int) -> OpponentProfile:
    return OpponentProfile(**{axis: value})


def best_achievable(tactic) -> dict[str, float]:
    """The largest total of each dimension over every legal role version."""
    best: dict[str, float] = {}
    options = [MVP_CATALOGUE.role_keys_for_slot(slot) for slot in tactic.slots]
    for combo in product(*options):
        if not MVP_CATALOGUE.role_version_is_legal(tactic, combo):
            continue
        totals: dict[str, float] = {}
        for role_key in combo:
            for dimension, value in role_traits(MVP_CATALOGUE.roles[role_key]).items():
                totals[dimension] = totals.get(dimension, 0.0) + value
        for dimension, value in totals.items():
            best[dimension] = max(best.get(dimension, 0.0), value)
    return best


class ProfileTests(unittest.TestCase):
    def test_default_is_neutral_on_every_axis(self) -> None:
        profile = OpponentProfile.neutral()
        self.assertTrue(profile.is_neutral)
        self.assertEqual([getattr(profile, axis) for axis in AXES], [0] * len(AXES))
        self.assertEqual(profile, OpponentProfile())

    def test_there_are_six_axes(self) -> None:
        self.assertEqual(len(AXES), 6)

    def test_any_nonzero_axis_is_not_neutral(self) -> None:
        for axis in AXES:
            self.assertFalse(one_axis(axis, 1).is_neutral, axis)

    def test_out_of_range_and_non_integers_are_refused(self) -> None:
        for bad in (3, -3, 1.5, "1", True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                OpponentProfile(quality=bad)


class NeutralChangesNothingTests(unittest.TestCase):
    def test_neutral_has_no_emphasis_and_no_floors(self) -> None:
        self.assertEqual(attribute_emphasis(OpponentProfile.neutral()), ())
        self.assertEqual(system_floors(OpponentProfile.neutral()), {})

    def test_neutral_fit_is_inactive_so_it_cannot_dilute_a_blend(self) -> None:
        tactic = MVP_CATALOGUE.tactics["balanced_442"]
        roles = tuple(MVP_CATALOGUE.roles[slot.role_key] for slot in tactic.slots)
        fit = assess_opponent_fit(roles, OpponentProfile.neutral())
        self.assertFalse(fit.active)
        self.assertEqual(fit.score, 100.0)

    def test_quality_alone_moves_no_attribute(self) -> None:
        # Quality is only about how solid or open a system must be.
        for value in SETTINGS:
            self.assertEqual(attribute_emphasis(one_axis("quality", value)), ())

    def test_aerial_alone_asks_for_no_system_floor(self) -> None:
        # The system model has no aerial-defence dimension; aerial threat acts
        # through who is picked, not through team balance.
        for value in SETTINGS:
            self.assertEqual(system_floors(one_axis("aerial_threat", value)), {})


class ExtensibilityTests(unittest.TestCase):
    """The guardrail that makes adding a slider a self-contained change."""

    def test_every_profile_field_has_exactly_one_axis_definition(self) -> None:
        profile_fields = {field.name for field in fields(OpponentProfile)}
        axis_keys = [axis.key for axis in AXIS_DEFINITIONS]
        self.assertEqual(profile_fields, set(axis_keys))
        self.assertEqual(len(axis_keys), len(set(axis_keys)), "duplicate axis key")

    def test_a_field_with_no_axis_definition_is_refused_at_import(self) -> None:
        # Exercise the same check the module runs on import, so a change to
        # its logic that stops it catching this is itself caught here.
        from fm_analytics.analytics import opponent as opponent_module

        broken = tuple(a for a in AXIS_DEFINITIONS if a.key != "quality")
        original = opponent_module.AXIS_DEFINITIONS
        opponent_module.AXIS_DEFINITIONS = broken
        try:
            with self.assertRaises(AssertionError):
                opponent_module._check_profile_matches_axes()
        finally:
            opponent_module.AXIS_DEFINITIONS = original

    def test_axis_definitions_carry_usable_labels(self) -> None:
        for axis in AXIS_DEFINITIONS:
            self.assertTrue(axis.label)
            self.assertTrue(axis.low)
            self.assertTrue(axis.high)
            self.assertNotEqual(axis.low, axis.high, axis.key)

    def test_an_axis_needs_no_effects_to_be_valid(self) -> None:
        # aerial_threat has emphasis but no floors -- exercising that an axis
        # may declare only one kind of effect.
        aerial = next(a for a in AXIS_DEFINITIONS if a.key == "aerial_threat")
        self.assertTrue(aerial.emphasis)
        self.assertEqual(aerial.floors, ())


class DeclaredDataTests(unittest.TestCase):
    def test_every_emphasised_attribute_is_one_a_role_can_weight(self) -> None:
        known = required_role_attributes()
        for axis in AXIS_DEFINITIONS:
            for rule in axis.emphasis:
                self.assertLessEqual(set(rule.attributes) - known, set(), (axis.key, rule))

    def test_every_emphasised_position_is_one_a_tactic_can_field(self) -> None:
        for axis in AXIS_DEFINITIONS:
            for rule in axis.emphasis:
                self.assertLessEqual(set(rule.positions) - FIELDED_POSITIONS, set(), (axis.key, rule))

    def test_every_floor_dimension_is_a_known_system_dimension(self) -> None:
        for axis in AXIS_DEFINITIONS:
            for rule in axis.floors:
                for floors in rule.floors:
                    self.assertLessEqual(set(floors), set(SYSTEM_DIMENSIONS), axis.key)

    def test_a_rule_with_no_reason_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            EmphasisRule(+1, ("pace",), ("DC",), why="")
        with self.assertRaises(ValueError):
            FloorRule(+1, ({"pressing": 1.0}, {"pressing": 2.0}), why="")

    def test_an_axis_missing_a_label_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            OpponentAxis(key="x", label="", low="a", high="b")

    def test_emphasis_blocks_are_valid_blocks(self) -> None:
        # Building them runs AttributeEmphasis's own validation (integer, in range).
        for axis, value in product(AXES, SETTINGS):
            attribute_emphasis(one_axis(axis, value))


class MonotonicTests(unittest.TestCase):
    """Turning an axis further from neutral never asks for less."""

    def test_floors_never_fall_as_a_side_gets_stronger(self) -> None:
        for axis in AXES:
            for direction in (1, -1):
                previous: dict[str, float] = {}
                for steps in (1, 2):
                    floors = system_floors(one_axis(axis, direction * steps))
                    for dimension, floor in previous.items():
                        self.assertGreaterEqual(floors.get(dimension, 0.0), floor, (axis, direction))
                    previous = floors

    def test_emphasis_never_shrinks_in_magnitude_as_a_side_gets_stronger(self) -> None:
        def totals(profile: OpponentProfile) -> dict[tuple[str, str], int]:
            out: dict[tuple[str, str], int] = {}
            for block in attribute_emphasis(profile):
                for attribute, delta in block.attributes.items():
                    for position in block.positions:
                        out[(position, attribute)] = out.get((position, attribute), 0) + delta
            return out

        for axis in AXES:
            for direction in (1, -1):
                one = totals(one_axis(axis, direction))
                two = totals(one_axis(axis, 2 * direction))
                for key, delta in one.items():
                    self.assertGreaterEqual(abs(two[key]), abs(delta), (axis, direction, key))

    def test_the_two_sides_of_an_axis_do_not_overlap(self) -> None:
        # One value of an axis is on one side only, so each side's blocks and
        # floors are the whole story for it.
        for axis in AXES:
            self.assertEqual(
                attribute_emphasis(one_axis(axis, 1)) == attribute_emphasis(one_axis(axis, -1)),
                not attribute_emphasis(one_axis(axis, 1)),
            )


class ReachabilityTests(unittest.TestCase):
    """The failure the earlier calibration work fixed: demands nothing can meet."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.best = {key: best_achievable(t) for key, t in MVP_CATALOGUE.tactics.items()}

    def unable(self, profile: OpponentProfile) -> set[str]:
        floors = system_floors(profile)
        return {
            key
            for key, best in self.best.items()
            if any(best.get(dimension, 0.0) < floor for dimension, floor in floors.items())
        }

    def test_no_single_setting_is_out_of_reach_for_most_of_the_catalogue(self) -> None:
        # The first draft of the attacking floors was on the wrong scale and
        # 40 of 42 tactics could not meet them. Keep every setting a real test.
        limit = 0.6 * len(MVP_CATALOGUE.tactics)
        for axis, value in product(AXES, SETTINGS):
            self.assertLessEqual(len(self.unable(one_axis(axis, value))), limit, (axis, value))

    def test_one_step_of_defensive_demand_is_within_reach_of_every_tactic(self) -> None:
        for axis in ("quality", "pace_in_behind", "attacking_width"):
            self.assertEqual(self.unable(one_axis(axis, 1)), set(), axis)

    def test_a_strong_fast_opponent_separates_attacking_shapes_from_solid_ones(self) -> None:
        unable = self.unable(one_axis("pace_in_behind", 2))
        self.assertIn("attacking_433", unable)
        self.assertNotIn("defensive_532", unable)


class OpponentFitTests(unittest.TestCase):
    def roles_for(self, key: str):
        return tuple(MVP_CATALOGUE.roles[slot.role_key] for slot in MVP_CATALOGUE.tactics[key].slots)

    def test_a_demanding_opponent_makes_the_fit_active_and_scores_a_shortfall(self) -> None:
        fit = assess_opponent_fit(self.roles_for("attacking_433"), one_axis("pace_in_behind", 2))
        self.assertTrue(fit.active)
        self.assertLess(fit.score, 100.0)
        self.assertTrue(fit.shortfalls)

    def test_a_tactic_that_meets_every_floor_scores_100(self) -> None:
        fit = assess_opponent_fit(self.roles_for("defensive_532"), one_axis("pace_in_behind", 1))
        self.assertTrue(fit.active)
        self.assertEqual(fit.score, 100.0)

    def test_a_harder_opponent_never_scores_a_tactic_higher(self) -> None:
        for key in MVP_CATALOGUE.tactics:
            roles = self.roles_for(key)
            for axis in AXES:
                for direction in (1, -1):
                    scores = [
                        assess_opponent_fit(roles, one_axis(axis, direction * steps)).score
                        for steps in (1, 2)
                    ]
                    self.assertGreaterEqual(scores[0], scores[1], (key, axis, direction))


if __name__ == "__main__":
    unittest.main()
