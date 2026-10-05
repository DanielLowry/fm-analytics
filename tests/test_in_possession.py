"""A tactic's "In Possession" phase settings: parsing, validation, the
completeness flag the tactic page uses to say what has not been set yet, and
the bridge that feeds fixed settings into instruction-fit scoring.
"""

import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.analytics.in_possession import (
    InPossessionSettings,
    in_possession_instruction_strings,
    in_possession_selected_instructions,
)

ROLE = {
    "key": "gk_x", "name": "Keeper", "description": "Stops shots.", "positions": ["GK"],
    "system": {"defensiveCover": 0.5},
    "attributes": {"reflexes": 8},
}
TACTIC = {
    "key": "shape", "name": "Shape", "formation": "1-0-0", "mentality": "Balanced",
    "instructions": [],
    "slots": [{"key": f"s{i}", "position": "GK", "role": "gk_x"} for i in range(11)],
}
COMPLETE_FIXED = {
    "attackingWidth": "Fairly Wide",
    "passingDirectness": "Slightly More Direct Passing",
    "tempo": "Higher Tempo",
    "passIntoSpace": True,
    "playOutOfDefence": False,
    "focusPlay": "Down the Left",
    "workBallIntoBox": False,
}
COMPLETE_IN_POSSESSION = {"fixed": COMPLETE_FIXED}


class InPossessionSettingsUnitTests(unittest.TestCase):
    """The dataclass's own validation, with no catalogue involved."""

    def test_defaults_have_every_fixed_field_missing(self) -> None:
        settings = InPossessionSettings()
        self.assertEqual(
            settings.missing_fixed_fields,
            (
                "attacking width", "passing directness", "tempo", "pass into space",
                "play out of defence", "focus play", "work ball into box",
            ),
        )
        self.assertFalse(settings.is_complete)

    def test_all_fixed_fields_set_is_complete(self) -> None:
        settings = InPossessionSettings(
            attacking_width="Standard",
            passing_directness="Standard",
            tempo="Standard",
            pass_into_space=False,
            play_out_of_defence=False,
            focus_play="Balanced",
            work_ball_into_box=False,
        )
        self.assertEqual(settings.missing_fixed_fields, ())
        self.assertTrue(settings.is_complete)

    def test_partial_settings_report_only_what_is_missing(self) -> None:
        settings = InPossessionSettings(attacking_width="Fairly Wide", tempo="Higher Tempo")
        self.assertEqual(
            settings.missing_fixed_fields,
            ("passing directness", "pass into space", "play out of defence", "focus play",
             "work ball into box"),
        )

    def test_rejects_an_unknown_attacking_width(self) -> None:
        with self.assertRaisesRegex(ValueError, "attackingWidth must be one of"):
            InPossessionSettings(attacking_width="Sort Of Wide")

    def test_rejects_an_unknown_passing_directness(self) -> None:
        with self.assertRaisesRegex(ValueError, "passingDirectness must be one of"):
            InPossessionSettings(passing_directness="Kind Of Direct")

    def test_rejects_an_unknown_tempo(self) -> None:
        with self.assertRaisesRegex(ValueError, "tempo must be one of"):
            InPossessionSettings(tempo="Medium Tempo")

    def test_rejects_an_unknown_focus_play(self) -> None:
        with self.assertRaisesRegex(ValueError, "focusPlay must be one of"):
            InPossessionSettings(focus_play="Down the Middleish")

    def test_rejects_an_unknown_crossing_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "crossingType must be one of"):
            InPossessionSettings(crossing_type="Curled")

    def test_rejects_an_unknown_time_wasting(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeWasting must be one of"):
            InPossessionSettings(time_wasting="Constantly")

    def test_rejects_overlap_and_underlap_on_the_same_left_side(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlapLeft and underlapLeft"):
            InPossessionSettings(overlap_left=True, underlap_left=True)

    def test_rejects_overlap_and_underlap_on_the_same_right_side(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlapRight and underlapRight"):
            InPossessionSettings(overlap_right=True, underlap_right=True)

    def test_allows_overlap_left_and_underlap_right_together(self) -> None:
        InPossessionSettings(overlap_left=True, underlap_right=True)  # different sides: fine

    def test_rejects_dribble_less_and_run_at_defence_together(self) -> None:
        with self.assertRaisesRegex(ValueError, "dribbleLess and runAtDefence"):
            InPossessionSettings(dribble_less=True, run_at_defence=True)

    def test_rejects_expressive_and_disciplined_together(self) -> None:
        with self.assertRaisesRegex(ValueError, "beMoreExpressive and beMoreDisciplined"):
            InPossessionSettings(be_more_expressive=True, be_more_disciplined=True)


class InPossessionInstructionStringsTests(unittest.TestCase):
    """The bridge from fixed settings to legacy instruction-fit scoring strings."""

    def test_none_settings_yield_no_strings(self) -> None:
        self.assertEqual(in_possession_instruction_strings(None), ())

    def test_unset_fixed_fields_and_defaults_yield_no_strings(self) -> None:
        self.assertEqual(in_possession_instruction_strings(InPossessionSettings()), ())

    def test_standard_is_treated_as_no_instruction(self) -> None:
        settings = InPossessionSettings(
            attacking_width="Standard", passing_directness="Standard", tempo="Standard",
        )
        self.assertEqual(in_possession_instruction_strings(settings), ())

    def test_named_enum_values_pass_through_as_instruction_strings(self) -> None:
        settings = InPossessionSettings(
            attacking_width="Fairly Wide",
            passing_directness="Slightly More Direct Passing",
            tempo="Higher Tempo",
        )
        strings = in_possession_instruction_strings(settings)
        self.assertIn("Fairly Wide", strings)
        self.assertIn("Slightly More Direct Passing", strings)
        self.assertIn("Higher Tempo", strings)

    def test_true_booleans_become_their_instruction_string(self) -> None:
        settings = InPossessionSettings(
            pass_into_space=True, play_out_of_defence=True, work_ball_into_box=True,
        )
        strings = in_possession_instruction_strings(settings)
        self.assertIn("Pass Into Space", strings)
        self.assertIn("Play Out Of Defence", strings)
        self.assertIn("Work Ball Into Box", strings)

    def test_false_booleans_contribute_nothing(self) -> None:
        settings = InPossessionSettings(
            pass_into_space=False, play_out_of_defence=False, work_ball_into_box=False,
        )
        self.assertEqual(in_possession_instruction_strings(settings), ())

    def test_player_dependent_fields_never_contribute(self) -> None:
        # overlapLeft/hitEarlyCrosses/etc. are fallbacks only; they must never
        # reach instruction-fit scoring however they are set.
        settings = InPossessionSettings(
            overlap_left=True, overlap_right=True, hit_early_crosses=True,
            shoot_on_sight=True, play_for_set_pieces=True, run_at_defence=True,
            be_more_expressive=True, crossing_type="Whipped",
        )
        self.assertEqual(in_possession_instruction_strings(settings), ())

    def test_focus_play_never_contributes(self) -> None:
        # There is no scored "Focus Play" instruction in the legacy vocabulary.
        settings = InPossessionSettings(focus_play="Down the Left")
        self.assertEqual(in_possession_instruction_strings(settings), ())


class InPossessionSelectedInstructionsTests(unittest.TestCase):
    """Every selected setting under its FM name, for presentation and rationale keys."""

    def test_none_settings_yield_nothing(self) -> None:
        self.assertEqual(in_possession_selected_instructions(None), ())

    def test_defaults_yield_nothing(self) -> None:
        # Mixed crossing is FM's default, not a choice.
        self.assertEqual(in_possession_selected_instructions(InPossessionSettings()), ())

    def test_fixed_settings_appear_as_their_scored_strings(self) -> None:
        settings = InPossessionSettings(attacking_width="Fairly Wide", work_ball_into_box=True)
        self.assertEqual(
            in_possession_selected_instructions(settings),
            in_possession_instruction_strings(settings),
        )

    def test_player_dependent_choices_appear_by_name(self) -> None:
        settings = InPossessionSettings(
            crossing_type="Floated", overlap_left=True, play_for_set_pieces=True,
            be_more_disciplined=True,
        )
        self.assertEqual(
            in_possession_selected_instructions(settings),
            ("Floated Crosses", "Overlap Left", "Play For Set Pieces", "Be More Disciplined"),
        )


class CatalogueLoadingTests(unittest.TestCase):
    """Parsing `inPossession` blocks out of tactic JSON via `load_catalogue`."""

    def build(self, directory: Path, tactic: dict) -> Path:
        (directory / "roles").mkdir()
        (directory / "tactics").mkdir()
        (directory / "catalogue.json").write_text(json.dumps({"version": "v"}), encoding="utf-8")
        (directory / "roles" / "gk.json").write_text(json.dumps({"roles": [ROLE]}), encoding="utf-8")
        (directory / "tactics" / "shape.json").write_text(json.dumps(tactic), encoding="utf-8")
        return directory

    def test_a_tactic_with_no_in_possession_block_reports_every_field_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(Path(tmp), TACTIC))
        tactic = catalogue.tactics["shape"]
        self.assertIsNone(tactic.in_possession)
        self.assertEqual(len(tactic.in_possession_missing_fields), 7)

    def test_a_fully_specified_fixed_block_leaves_nothing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(
                self.build(Path(tmp), {**TACTIC, "inPossession": COMPLETE_IN_POSSESSION})
            )
        tactic = catalogue.tactics["shape"]
        self.assertEqual(tactic.in_possession_missing_fields, ())
        self.assertEqual(tactic.in_possession.attacking_width, "Fairly Wide")
        self.assertTrue(tactic.in_possession.pass_into_space)

    def test_a_partially_specified_fixed_block_reports_what_it_left_out(self) -> None:
        partial = {"fixed": {"attackingWidth": "Fairly Wide", "tempo": "Higher Tempo"}}
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(Path(tmp), {**TACTIC, "inPossession": partial}))
        tactic = catalogue.tactics["shape"]
        self.assertIn("passing directness", tactic.in_possession_missing_fields)
        self.assertIn("focus play", tactic.in_possession_missing_fields)
        self.assertEqual(len(tactic.in_possession_missing_fields), 5)

    def test_an_in_possession_block_with_no_fixed_object_is_all_missing(self) -> None:
        # "dependsOnPlayers" alone, with no "fixed" object at all.
        depends_only = {"inPossession": {"dependsOnPlayers": {"overlapLeft": True}}}
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(Path(tmp), {**TACTIC, **depends_only}))
        tactic = catalogue.tactics["shape"]
        self.assertIsNotNone(tactic.in_possession)
        self.assertTrue(tactic.in_possession.overlap_left)
        self.assertEqual(len(tactic.in_possession_missing_fields), 7)

    def test_player_dependent_fields_default_without_being_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(
                self.build(Path(tmp), {**TACTIC, "inPossession": COMPLETE_IN_POSSESSION})
            )
        settings = catalogue.tactics["shape"].in_possession
        self.assertFalse(settings.overlap_left)
        self.assertEqual(settings.crossing_type, "Mixed")
        self.assertEqual(settings.time_wasting, "Sometimes")

    def test_an_unknown_top_level_in_possession_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {**TACTIC, "inPossession": {**COMPLETE_IN_POSSESSION, "dribbleMore": True}}
            with self.assertRaisesRegex(ValueError, "unknown key.*dribbleMore"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_an_unknown_key_inside_fixed_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {"fixed": {**COMPLETE_FIXED, "overlapLeft": True}},
            }
            with self.assertRaisesRegex(ValueError, "inPossession.fixed.*unknown key.*overlapLeft"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_an_unknown_key_inside_depends_on_players_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {"dependsOnPlayers": {"attackingWidth": "Fairly Wide"}},
            }
            with self.assertRaisesRegex(
                ValueError, "inPossession.dependsOnPlayers.*unknown key.*attackingWidth"
            ):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_non_boolean_flag_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {"fixed": {**COMPLETE_FIXED, "passIntoSpace": "yes"}},
            }
            with self.assertRaisesRegex(ValueError, "fixed.passIntoSpace must be true/false"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_non_string_enum_value_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {**TACTIC, "inPossession": {"fixed": {**COMPLETE_FIXED, "tempo": 5}}}
            with self.assertRaisesRegex(ValueError, "fixed.tempo must be a string"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_an_invalid_combination_inside_depends_on_players_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {
                    "fixed": COMPLETE_FIXED,
                    "dependsOnPlayers": {"dribbleLess": True, "runAtDefence": True},
                },
            }
            with self.assertRaisesRegex(ValueError, "dribbleLess and runAtDefence"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_fixed_value_duplicated_in_instructions_is_refused(self) -> None:
        # Once "Fairly Wide" is set structurally it must not also live as a
        # literal instructions string, or scoring would double-count it.
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "instructions": ["Fairly Wide"],
                "inPossession": {"fixed": {"attackingWidth": "Fairly Wide"}},
            }
            with self.assertRaisesRegex(ValueError, "'Fairly Wide'.*double-count"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_fixed_value_with_no_legacy_string_does_not_conflict(self) -> None:
        # "Very Wide" has no legacy instruction-string equivalent yet, so it
        # cannot collide with anything in `instructions`.
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "instructions": ["Counter"],
                "inPossession": {"fixed": {"attackingWidth": "Very Wide"}},
            }
            catalogue = load_catalogue(self.build(Path(tmp), tactic))
        self.assertEqual(catalogue.tactics["shape"].in_possession.attacking_width, "Very Wide")

    def test_rationale_may_explain_any_selected_setting(self) -> None:
        rationale = {"Fairly Wide": "Stretch them.", "Floated Crosses": "Use the target man."}
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {
                    "fixed": {"attackingWidth": "Fairly Wide"},
                    "dependsOnPlayers": {"crossingType": "Floated"},
                },
                "instructionRationale": rationale,
            }
            catalogue = load_catalogue(self.build(Path(tmp), tactic))
        self.assertEqual(dict(catalogue.tactics["shape"].instruction_rationale), rationale)

    def test_rationale_for_a_setting_left_unselected_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {"dependsOnPlayers": {"crossingType": "Mixed"}},
                "instructionRationale": {"Floated Crosses": "Use the target man."},
            }
            with self.assertRaisesRegex(ValueError, "does not use.*Floated Crosses"):
                load_catalogue(self.build(Path(tmp), tactic))


if __name__ == "__main__":
    unittest.main()
