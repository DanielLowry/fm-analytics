"""Transition constraints, catalogue compatibility, and score-preserving migration."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import InTransitionSettings, MVP_CATALOGUE
from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.analytics.in_transition import (
    DISTRIBUTION_TARGET_OPTIONS, DISTRIBUTION_TYPE_OPTIONS,
    in_transition_selected_instructions,
)
from fm_analytics.analytics.tactical_system import assess_instruction_suitability, effective_instructions
from fm_analytics.web.in_transition_render import in_transition_section
from tests.test_in_possession import ROLE, TACTIC

COMPLETE = {
    "whenPossessionLost": "Counter-Press",
    "whenPossessionWon": "Counter",
    "goalkeeperPace": "Distribute Quickly",
    "distributionTargets": list(DISTRIBUTION_TARGET_OPTIONS),
    "distributionTypes": list(DISTRIBUTION_TYPE_OPTIONS),
}


class TransitionTests(unittest.TestCase):
    def load(self, block=None, **overrides):
        tactic = {**TACTIC, **overrides}
        if block is not None:
            tactic["inTransition"] = block
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalogue.json"
            path.write_text(json.dumps({"version": "v", "roles": [ROLE], "tactics": [tactic]}))
            return load_catalogue(path).tactics["shape"]

    def test_old_catalogues_load_and_flag_the_unauthored_phase(self):
        tactic = self.load()
        self.assertIsNone(tactic.in_transition)
        self.assertEqual(len(tactic.in_transition_missing_fields), 5)
        self.assertIn("Transition settings not yet specified:", in_transition_section(tactic))

    def test_all_options_load_and_distribution_allows_multiple(self):
        tactic = self.load(COMPLETE)
        settings = tactic.in_transition
        self.assertTrue(settings.is_complete)
        self.assertEqual(settings.distribution_targets, DISTRIBUTION_TARGET_OPTIONS)
        self.assertEqual(settings.distribution_types, DISTRIBUTION_TYPE_OPTIONS)
        section = in_transition_section(tactic)
        for option in DISTRIBUTION_TARGET_OPTIONS + DISTRIBUTION_TYPE_OPTIONS:
            self.assertIn(option, section)
            self.assertIn(option, in_transition_selected_instructions(settings))
        self.assertNotIn("Not set", section)

    def test_explicit_neutral_choices_are_complete_and_do_not_score(self):
        tactic = self.load({
            "whenPossessionLost": "Neither", "whenPossessionWon": "Neither",
            "goalkeeperPace": "Neither", "distributionTargets": [], "distributionTypes": [],
        })
        self.assertTrue(tactic.in_transition.is_complete)
        self.assertEqual(effective_instructions(tactic), ())
        section = in_transition_section(tactic)
        self.assertIn("Neither selected", section)
        self.assertIn("None selected", section)
        self.assertNotIn("Not set", section)

    def test_partial_settings_leave_only_unauthored_fields_missing(self):
        tactic = self.load({"whenPossessionWon": "Hold Shape"})
        self.assertEqual(len(tactic.in_transition_missing_fields), 4)
        self.assertNotIn("when possession has been won", tactic.in_transition_missing_fields)
        self.assertEqual(effective_instructions(tactic), ("Hold Shape",))

    def test_invalid_options_types_and_unknown_keys_are_refused(self):
        invalid = (
            [], {"typo": True}, {"whenPossessionLost": "Press"},
            {"whenPossessionLost": ["Counter-Press", "Regroup"]},
            {"whenPossessionWon": ["Counter", "Hold Shape"]},
            {"whenPossessionWon": True}, {"goalkeeperPace": 1},
            {"goalkeeperPace": ["Distribute Quickly", "Slow Pace Down"]},
            {"distributionTargets": "Distribute To Flanks"},
            {"distributionTargets": ["Anywhere"]}, {"distributionTypes": [True]},
            {"distributionTypes": ["Roll It Out", "Roll It Out"]},
            {"distributionTargets": ["Distribute To Flanks", "Distribute To Flanks"]},
            {"whenPossessionWon": None}, {"distributionTypes": None},
        )
        for block in invalid:
            with self.subTest(block=block), self.assertRaisesRegex(ValueError, "inTransition"):
                self.load(block)

    def test_dataclass_rejects_invalid_direct_construction(self):
        for values in (
            {"when_possession_lost": ["Counter-Press", "Regroup"]},
            {"when_possession_won": "Counter and Hold Shape"},
            {"goalkeeper_pace": "Fast"}, {"distribution_types": ("Unknown",)},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                InTransitionSettings(**values)

    def test_legacy_duplicates_and_conflicting_choices_are_refused(self):
        for block, legacy in (
            ({"whenPossessionWon": "Counter"}, "Counter"),
            ({"whenPossessionWon": "Counter"}, "Hold Shape"),
            ({"whenPossessionWon": "Neither"}, "Counter"),
            ({"whenPossessionLost": "Regroup"}, "Counter-Press"),
            ({"whenPossessionLost": "Neither"}, "Regroup"),
        ):
            with self.subTest(block=block, legacy=legacy), self.assertRaises(ValueError):
                self.load(block, instructions=[legacy])

    def test_structured_instruction_rationale_is_preserved(self):
        tactic = self.load({"whenPossessionWon": "Counter"}, instructionRationale={"Counter": "Use runners."})
        self.assertEqual(tactic.instruction_rationale["Counter"], "Use runners.")
        with self.assertRaisesRegex(ValueError, "does not use"):
            self.load({"whenPossessionWon": "Neither"}, instructionRationale={"Counter": "Use runners."})

    def test_distribution_settings_do_not_change_instruction_fit(self):
        tactic = self.load(COMPLETE)
        self.assertEqual(effective_instructions(tactic), ("Counter-Press", "Counter"))

    def test_migrated_tactics_keep_the_same_scoring_and_explanations(self):
        for key, legacy in (("vertical_442", ("Regroup", "Counter")), ("wing_play_442", ("Counter",))):
            tactic = MVP_CATALOGUE.tactics[key]
            old = replace(tactic, in_transition=None, instructions=tactic.instructions + legacy)
            roles = [MVP_CATALOGUE.role_for_slot(slot, slot.role_key) for slot in tactic.slots]
            self.assertEqual(assess_instruction_suitability(roles, tactic), assess_instruction_suitability(roles, old))
            self.assertEqual(set(effective_instructions(tactic)), set(effective_instructions(old)))
            for instruction in legacy:
                self.assertIn(instruction, tactic.instruction_rationale)

    def test_legacy_transition_choices_are_visible_until_migrated(self):
        tactic = self.load(instructions=["Counter", "Regroup"])
        self.assertIn("Existing transition instructions: Counter; Regroup.", in_transition_section(tactic))
