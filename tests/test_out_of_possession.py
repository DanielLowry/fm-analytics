"""Defensive choices, neutral states, legacy conflicts and scoring compatibility."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE, OutOfPossessionSettings
from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.analytics.out_of_possession import (
    DEFENSIVE_WIDTH_OPTIONS, LINE_OPTIONS, PRESSING_INTENSITY_OPTIONS, out_of_possession_selected_instructions,
)
from fm_analytics.analytics.tactical_system import assess_instruction_suitability, effective_instructions
from fm_analytics.web.out_of_possession_render import out_of_possession_section
from tests.test_in_possession import ROLE, TACTIC


class DefensiveSettingsTests(unittest.TestCase):
    def load(self, block=None, **overrides):
        tactic = {**TACTIC, **overrides}
        if block is not None:
            tactic["outOfPossession"] = block
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalogue.json"
            path.write_text(json.dumps({"version": "v", "roles": [ROLE], "tactics": [tactic]}))
            return load_catalogue(path).tactics["shape"]

    def test_old_catalogues_load_and_display_missing_settings(self):
        tactic = self.load()
        self.assertIsNone(tactic.out_of_possession)
        self.assertEqual(len(tactic.out_of_possession_missing_fields), 8)
        section = out_of_possession_section(tactic)
        self.assertIn("Out of possession", section)
        self.assertIn("Out-of-possession settings not yet specified:", section)
        self.assertEqual(section.count("Not set</b>"), 8)

    def test_every_requested_line_and_pressing_level_loads_and_displays(self):
        for line in LINE_OPTIONS:
            for pressing in PRESSING_INTENSITY_OPTIONS:
                with self.subTest(line=line, pressing=pressing):
                    tactic = self.load({
                        "lineOfEngagement": line, "defensiveLine": line, "defensiveWidth": "Standard",
                        "pressingIntensity": pressing, "useTighterMarking": "Neutral",
                        "preventShortGKDistribution": "Neutral",
                        "useOffsideTrap": False, "tackling": "Neutral",
                    })
                    self.assertTrue(tactic.out_of_possession.is_complete)
                    section = out_of_possession_section(tactic)
                    self.assertIn(f"Line of engagement</span><b>{line}", section)
                    self.assertIn(f"Defensive line</span><b>{line}", section)
                    self.assertIn(f"Pressing intensity</span><b>{pressing}", section)
                    self.assertNotIn("Not set", section)

    def test_true_false_and_neutral_are_distinct_from_missing(self):
        for choice, display in ((True, "Yes"), (False, "No"), ("Neutral", "Neutral")):
            with self.subTest(choice=choice):
                tactic = self.load({"useTighterMarking": choice, "preventShortGKDistribution": choice})
                self.assertEqual(len(tactic.out_of_possession_missing_fields), 6)
                section = out_of_possession_section(tactic)
                self.assertIn(f"Use tighter marking</span><b>{display}", section)
                self.assertIn(f"Prevent short GK distribution</span><b>{display}", section)
                scored = ("Prevent Short GK Distribution",) if choice is True else ()
                self.assertEqual(effective_instructions(tactic), scored)

    def test_defensive_width_loads_displays_and_never_scores(self):
        # Narrow, Standard or Wide on FM20's screen, confirmed by the manager on 11 October 2026.
        self.assertEqual(DEFENSIVE_WIDTH_OPTIONS, ("Narrow", "Standard", "Wide"))
        for width in DEFENSIVE_WIDTH_OPTIONS:
            with self.subTest(width=width):
                tactic = self.load({"defensiveWidth": width})
                self.assertNotIn("defensive width", tactic.out_of_possession_missing_fields)
                self.assertIn(f"Defensive width</span><b>{width}</b>", out_of_possession_section(tactic))
                self.assertEqual(effective_instructions(tactic), ())
                shown = out_of_possession_selected_instructions(tactic.out_of_possession)
                self.assertEqual(shown, () if width == "Standard" else (f"{width} Defensive Width",))
        explained = self.load({"defensiveWidth": "Narrow"}, instructionRationale={"Narrow Defensive Width": "Compact."})
        self.assertIn("Narrow Defensive Width", explained.instruction_rationale)

    def test_invalid_choices_types_nulls_and_unknown_keys_are_refused(self):
        for block in (
            [], {"typo": True}, {"lineOfEngagement": "Very High"},
            {"defensiveLine": ["Higher", "Lower"]}, {"pressingIntensity": True},
            {"useTighterMarking": 1}, {"useTighterMarking": "yes"},
            {"preventShortGKDistribution": 0}, {"preventShortGKDistribution": []},
            {"defensiveLine": None}, {"useTighterMarking": None},
            {"defensiveWidth": "Very Wide"}, {"defensiveWidth": True}, {"defensiveWidth": None},
            {"useOffsideTrap": 1}, {"useOffsideTrap": []}, {"useOffsideTrap": None},
            {"tackling": "Hard"}, {"tackling": True}, {"tackling": None},
        ):
            with self.subTest(block=block), self.assertRaisesRegex(ValueError, "outOfPossession"):
                self.load(block)
        with self.assertRaises(ValueError):
            OutOfPossessionSettings(use_tighter_marking=1)

    def test_duplicate_and_conflicting_legacy_instructions_are_refused(self):
        for block, instruction in (
            ({"lineOfEngagement": "Standard"}, "Standard Line of Engagement"),
            ({"lineOfEngagement": "Higher"}, "Lower Line of Engagement"),
            ({"defensiveLine": "Standard"}, "Standard Defensive Line"),
            ({"defensiveLine": "Lower"}, "Drop Off More Defensive Line"),
            ({"pressingIntensity": "Standard"}, "Much More Urgent Pressing"),
            ({"useTighterMarking": False}, "Use Tighter Marking"),
            ({"preventShortGKDistribution": "Neutral"}, "Prevent Short GK Distribution"),
            ({"useOffsideTrap": False}, "Use Offside Trap"),
            ({"tackling": "Neutral"}, "Get Stuck In"),
        ):
            with self.subTest(block=block), self.assertRaisesRegex(ValueError, "duplicates or conflicts"):
                self.load(block, instructions=[instruction])

    def test_structured_instructions_retain_their_rationale(self):
        tactic = self.load(
            {"lineOfEngagement": "Standard", "useTighterMarking": True},
            instructionRationale={"Standard Line of Engagement": "Compact block.", "Use Tighter Marking": "Stay close."},
        )
        self.assertEqual(len(tactic.instruction_rationale), 2)
        with self.assertRaisesRegex(ValueError, "does not use"):
            self.load({"useTighterMarking": False}, instructionRationale={"Use Tighter Marking": "Stay close."})

    def test_scored_choices_keep_the_existing_legacy_demands(self):
        tactic = self.load({
            "lineOfEngagement": "Much Lower", "defensiveLine": "Lower",
            "pressingIntensity": "Extremely Urgent", "preventShortGKDistribution": True,
        })
        self.assertEqual(effective_instructions(tactic), (
            "Much Lower Line of Engagement", "Drop Off More Defensive Line",
            "Much More Urgent Pressing", "Prevent Short GK Distribution",
        ))

    def test_choices_without_existing_rules_are_displayed_without_invented_scores(self):
        for pressing in ("Standard", "More Urgent", "Less Urgent", "Much Less Urgent"):
            tactic = self.load({"defensiveLine": "Much Higher", "pressingIntensity": pressing, "useTighterMarking": True})
            self.assertEqual(effective_instructions(tactic), ())
            instructions = out_of_possession_selected_instructions(tactic.out_of_possession)
            self.assertIn("Much Higher Defensive Line", instructions)
            self.assertIn("Use Tighter Marking", instructions)
            if pressing != "Standard":
                self.assertIn(f"{pressing} Pressing", instructions)

    def test_vertical_442_migration_preserves_scoring_and_explanations(self):
        tactic = MVP_CATALOGUE.tactics["vertical_442"]
        old = replace(tactic, out_of_possession=None, instructions=tactic.instructions + (
            "Standard Line of Engagement", "Standard Defensive Line",
        ))
        roles = [MVP_CATALOGUE.role_for_slot(slot, slot.role_key) for slot in tactic.slots]
        self.assertEqual(assess_instruction_suitability(roles, tactic), assess_instruction_suitability(roles, old))
        self.assertEqual(set(effective_instructions(tactic)), set(effective_instructions(old)))
        self.assertIn("Standard Defensive Line", tactic.instruction_rationale)

    def test_legacy_instructions_are_visible_until_migrated(self):
        tactic = self.load(instructions=["Higher Defensive Line", "Much More Urgent Pressing"])
        self.assertIn("Existing defensive instructions: Higher Defensive Line; Much More Urgent Pressing.", out_of_possession_section(tactic))
