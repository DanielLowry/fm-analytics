"""Game-plan labels: read from each tactic's own settings and roles, never scoring input."""

import unittest
from dataclasses import replace

from fm_analytics.analytics.catalogue import MVP_CATALOGUE
from fm_analytics.analytics.game_plan import GAME_PLANS, game_plan_keys, game_plans
from fm_analytics.analytics.in_transition import InTransitionSettings
from fm_analytics.analytics.out_of_possession import OutOfPossessionSettings


def keys(tactic_key: str) -> tuple[str, ...]:
    return game_plan_keys(MVP_CATALOGUE.tactics[tactic_key], MVP_CATALOGUE)


class ShippedLabelTests(unittest.TestCase):
    def test_every_shipped_tactic_follows_at_least_one_plan(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertTrue(game_plans(tactic, MVP_CATALOGUE), tactic.key)

    def test_every_label_says_which_settings_earned_it(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            for label in game_plans(tactic, MVP_CATALOGUE):
                self.assertTrue(label.reasons, f"{tactic.key}: {label.key}")

    def test_the_control_range_carries_the_plan_it_was_built_for(self) -> None:
        expected = {
            "control_433dm": ("chance",),
            "control_4231": ("chance",),
            "control_442": ("chance",),
            "control_352": ("chance",),
            "control_343": ("chance",),
            "rest_defence_433": ("chance",),
            "squeeze_433dm": ("territorial",),
            "territorial_352": ("territorial",),
            "siege_442": ("territorial", "direct"),
            "patient_possession_433": ("possession",),
            "regista_4231": ("possession",),
        }
        for key, plans in expected.items():
            self.assertEqual(keys(key), plans, key)

    def test_counter_and_low_block_tactics_are_labelled_as_such(self) -> None:
        self.assertEqual(keys("vertical_442"), ("counter",))
        self.assertEqual(keys("deep_counter_541"), ("counter", "low_block"))
        self.assertEqual(keys("defensive_451"), ("low_block",))

    def test_chance_control_is_never_combined_with_another_plan(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            plans = game_plan_keys(tactic, MVP_CATALOGUE)
            if "chance" in plans:
                self.assertEqual(plans, ("chance",), tactic.key)

    def test_labels_come_in_page_order(self) -> None:
        order = [plan.key for plan in GAME_PLANS]
        for tactic in MVP_CATALOGUE.tactics.values():
            plans = game_plan_keys(tactic, MVP_CATALOGUE)
            self.assertEqual(list(plans), sorted(plans, key=order.index), tactic.key)

    def test_every_control_range_tactic_says_what_to_do_when_leading(self) -> None:
        for key in (
            "control_433dm", "control_4231", "control_442", "control_352", "control_343",
            "squeeze_433dm", "siege_442", "rest_defence_433", "patient_possession_433",
            "territorial_352", "regista_4231",
        ):
            self.assertTrue(MVP_CATALOGUE.tactics[key].when_leading.strip(), key)


class RuleTests(unittest.TestCase):
    """Each rule reads settings, so changing one setting changes the label."""

    def setUp(self) -> None:
        # Without the prose and player emphasis, which the loader checks against
        # the settings and roles each test then changes.
        self.control = replace(
            MVP_CATALOGUE.tactics["control_433dm"],
            instruction_rationale={}, attribute_emphasis=(), attribute_taper=(),
        )

    def plans(self, tactic) -> tuple[str, ...]:
        return game_plan_keys(tactic, MVP_CATALOGUE)

    def test_counter_pressing_from_a_higher_line_makes_a_tactic_territorial(self) -> None:
        pressing = replace(
            self.control,
            in_transition=replace(self.control.in_transition, when_possession_lost=("Counter-Press",)),
            out_of_possession=replace(self.control.out_of_possession, defensive_line="Higher"),
        )
        self.assertEqual(self.plans(pressing), ("territorial",))

    def test_counter_pressing_from_standard_lines_is_not_territorial(self) -> None:
        pressing = replace(
            self.control,
            in_transition=replace(self.control.in_transition, when_possession_lost=("Counter-Press",)),
        )
        self.assertEqual(self.plans(pressing), ("chance",))

    def test_counter_on_winning_the_ball_makes_it_a_counter_attack(self) -> None:
        countering = replace(
            self.control,
            in_transition=replace(self.control.in_transition, when_possession_won=("Counter",)),
        )
        self.assertEqual(self.plans(countering), ("counter",))

    def test_a_deeper_line_makes_it_a_low_block(self) -> None:
        deep = replace(
            self.control,
            out_of_possession=replace(self.control.out_of_possession, line_of_engagement="Lower"),
        )
        self.assertEqual(self.plans(deep), ("low_block",))

    def test_shorter_passing_alone_is_not_possession_control(self) -> None:
        short = replace(
            self.control,
            in_possession=replace(self.control.in_possession, passing_directness="Shorter Passing"),
        )
        self.assertNotIn("possession", self.plans(short))
        patient = replace(
            short, in_possession=replace(short.in_possession, tempo="Lower Tempo"),
        )
        self.assertEqual(self.plans(patient), ("possession",))

    def test_without_a_holder_a_tactic_is_not_chance_control(self) -> None:
        slots = tuple(
            replace(slot, role_key="dlp_dm_support", alternate_role_keys=()) if slot.position == "DM" else slot
            for slot in self.control.slots
        )
        self.assertEqual(self.plans(replace(self.control, slots=slots)), ())

    def test_settings_types_used_in_these_tests_are_the_real_ones(self) -> None:
        self.assertIsInstance(self.control.in_transition, InTransitionSettings)
        self.assertIsInstance(self.control.out_of_possession, OutOfPossessionSettings)


if __name__ == "__main__":
    unittest.main()
