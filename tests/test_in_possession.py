"""A tactic's "In Possession" phase settings: parsing, validation, the
completeness flag the tactic page uses to say what has not been set yet, and
the bridge that feeds fixed settings into instruction-fit scoring.
"""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.analytics.in_possession import (
    FIXED_TOGGLES,
    IN_POSSESSION_CLASHES,
    PLAYER_DEPENDENT_TOGGLES,
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
    "selected": ["Pass Into Space", "Focus Play Down The Left"],
}
COMPLETE_IN_POSSESSION = {"fixed": COMPLETE_FIXED}


def _settings(*selected: str) -> InPossessionSettings:
    """Settings selecting these toggles, each in the group it belongs to."""
    return InPossessionSettings(
        fixed_selected=tuple(name for name in selected if name in FIXED_TOGGLES),
        player_selected=tuple(name for name in selected if name in PLAYER_DEPENDENT_TOGGLES),
    )


class InPossessionSettingsUnitTests(unittest.TestCase):
    """The dataclass's own validation, with no catalogue involved."""

    def test_defaults_have_every_fixed_field_missing(self) -> None:
        settings = InPossessionSettings()
        self.assertEqual(
            settings.missing_fixed_fields,
            ("attacking width", "passing directness", "tempo", "which instructions are selected"),
        )
        self.assertFalse(settings.is_complete)

    def test_all_fixed_fields_set_is_complete_even_selecting_nothing(self) -> None:
        # Selecting no toggle is FM's default, and a complete answer.
        settings = InPossessionSettings(
            attacking_width="Standard", passing_directness="Standard", tempo="Standard",
            fixed_selected=(),
        )
        self.assertEqual(settings.missing_fixed_fields, ())
        self.assertTrue(settings.is_complete)

    def test_partial_settings_report_only_what_is_missing(self) -> None:
        settings = InPossessionSettings(attacking_width="Fairly Wide", tempo="Higher Tempo")
        self.assertEqual(
            settings.missing_fixed_fields, ("passing directness", "which instructions are selected")
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

    def test_rejects_an_unknown_crossing_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "crossingType must be one of"):
            InPossessionSettings(crossing_type="Curled")

    def test_rejects_an_unknown_time_wasting(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeWasting must be one of"):
            InPossessionSettings(time_wasting="Constantly")

    def test_rejects_an_unknown_or_repeated_toggle(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown instruction.*Focus Play Down The Middleish"):
            InPossessionSettings(fixed_selected=("Focus Play Down The Middleish",))
        with self.assertRaisesRegex(ValueError, "more than once"):
            InPossessionSettings(player_selected=("Overlap Left", "Overlap Left"))

    def test_a_toggle_belongs_to_one_group(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixed.selected: unknown instruction.*Hit Early Crosses"):
            InPossessionSettings(fixed_selected=("Hit Early Crosses",))

    def test_every_fm20_clash_is_refused_whichever_group_each_side_is_in(self) -> None:
        # Confirmed against FM20's screen, 7 October 2026.
        self.assertEqual(set(IN_POSSESSION_CLASHES), {
            ("Focus Play Through The Middle", "Focus Play Down The Left"),
            ("Focus Play Through The Middle", "Focus Play Down The Right"),
            ("Overlap Left", "Underlap Left"),
            ("Overlap Right", "Underlap Right"),
            ("Work Ball Into Box", "Hit Early Crosses"),
            ("Work Ball Into Box", "Shoot On Sight"),
            ("Dribble Less", "Run At Defence"),
            ("Be More Expressive", "Be More Disciplined"),
        })
        for first, second in IN_POSSESSION_CLASHES:
            with self.subTest(first=first, second=second):
                with self.assertRaisesRegex(ValueError, f"'{first}' and '{second}' cannot both be selected"):
                    _settings(first, second)

    def test_combinations_fm20_allows(self) -> None:
        for selected in (
            ("Focus Play Down The Left", "Focus Play Down The Right"),
            ("Shoot On Sight", "Hit Early Crosses"),
            ("Overlap Left", "Underlap Right"),
            ("Overlap Left", "Overlap Right"),
            ("Play Out Of Defence", "Pass Into Space", "Work Ball Into Box", "Play For Set Pieces"),
        ):
            with self.subTest(selected=selected):
                self.assertEqual(set(_settings(*selected).selected), set(selected))

    def test_unavailable_names_what_locks_each_instruction(self) -> None:
        self.assertEqual(
            _settings("Work Ball Into Box").unavailable,
            {"Hit Early Crosses": ("Work Ball Into Box",), "Shoot On Sight": ("Work Ball Into Box",)},
        )
        # Hit Early Crosses locks Work Ball Into Box, but Shoot On Sight stays available.
        self.assertEqual(
            _settings("Hit Early Crosses").unavailable, {"Work Ball Into Box": ("Hit Early Crosses",)}
        )
        self.assertEqual(
            _settings("Focus Play Down The Left", "Focus Play Down The Right").unavailable,
            {"Focus Play Through The Middle": ("Focus Play Down The Left", "Focus Play Down The Right")},
        )
        self.assertEqual(_settings().unavailable, {})


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

    def test_selected_fixed_toggles_become_their_instruction_string(self) -> None:
        settings = _settings("Pass Into Space", "Play Out Of Defence", "Work Ball Into Box")
        self.assertEqual(
            in_possession_instruction_strings(settings),
            ("Pass Into Space", "Play Out Of Defence", "Work Ball Into Box"),
        )

    def test_unselected_toggles_contribute_nothing(self) -> None:
        self.assertEqual(in_possession_instruction_strings(_settings()), ())

    def test_player_dependent_fields_never_contribute(self) -> None:
        # Fallbacks only; they must never reach instruction-fit scoring however they are set.
        settings = replace(
            _settings("Overlap Left", "Overlap Right", "Hit Early Crosses", "Shoot On Sight",
                      "Play For Set Pieces", "Run At Defence", "Be More Expressive"),
            crossing_type="Whipped",
        )
        self.assertEqual(in_possession_instruction_strings(settings), ())

    def test_focus_play_never_contributes(self) -> None:
        # There is no scored "Focus Play" instruction in the legacy vocabulary.
        self.assertEqual(in_possession_instruction_strings(_settings("Focus Play Down The Left")), ())


class InPossessionSelectedInstructionsTests(unittest.TestCase):
    """Every selected setting under its FM name, for presentation and rationale keys."""

    def test_none_settings_yield_nothing(self) -> None:
        self.assertEqual(in_possession_selected_instructions(None), ())

    def test_defaults_yield_only_time_wasting(self) -> None:
        # Mixed crossing is FM's default, not a choice; time wasting always has a value.
        self.assertEqual(
            in_possession_selected_instructions(InPossessionSettings()), ("Sometimes Time Wasting",)
        )

    def test_fixed_settings_appear_as_their_scored_strings_then_focus(self) -> None:
        settings = replace(
            _settings("Focus Play Down The Right", "Work Ball Into Box"), attacking_width="Fairly Wide"
        )
        self.assertEqual(
            in_possession_selected_instructions(settings),
            ("Fairly Wide", "Work Ball Into Box", "Focus Play Down The Right", "Sometimes Time Wasting"),
        )

    def test_player_dependent_choices_appear_by_name(self) -> None:
        settings = replace(
            _settings("Overlap Left", "Play For Set Pieces", "Be More Disciplined"), crossing_type="Floated",
        )
        self.assertEqual(
            in_possession_selected_instructions(settings),
            (
                "Floated Crosses", "Overlap Left", "Play For Set Pieces", "Be More Disciplined",
                "Sometimes Time Wasting",
            ),
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
        self.assertEqual(len(tactic.in_possession_missing_fields), 4)

    def test_a_fully_specified_fixed_block_leaves_nothing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(
                self.build(Path(tmp), {**TACTIC, "inPossession": COMPLETE_IN_POSSESSION})
            )
        tactic = catalogue.tactics["shape"]
        self.assertEqual(tactic.in_possession_missing_fields, ())
        self.assertEqual(tactic.in_possession.attacking_width, "Fairly Wide")
        self.assertEqual(tactic.in_possession.fixed_selected, ("Pass Into Space", "Focus Play Down The Left"))

    def test_a_partially_specified_fixed_block_reports_what_it_left_out(self) -> None:
        partial = {"fixed": {"attackingWidth": "Fairly Wide", "tempo": "Higher Tempo"}}
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(Path(tmp), {**TACTIC, "inPossession": partial}))
        tactic = catalogue.tactics["shape"]
        self.assertEqual(
            tactic.in_possession_missing_fields, ("passing directness", "which instructions are selected")
        )

    def test_an_in_possession_block_with_no_fixed_object_is_all_missing(self) -> None:
        # "dependsOnPlayers" alone, with no "fixed" object at all.
        depends_only = {"inPossession": {"dependsOnPlayers": {"selected": ["Overlap Left"]}}}
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(Path(tmp), {**TACTIC, **depends_only}))
        tactic = catalogue.tactics["shape"]
        self.assertIsNotNone(tactic.in_possession)
        self.assertEqual(tactic.in_possession.player_selected, ("Overlap Left",))
        self.assertEqual(len(tactic.in_possession_missing_fields), 4)

    def test_player_dependent_fields_default_without_being_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(
                self.build(Path(tmp), {**TACTIC, "inPossession": COMPLETE_IN_POSSESSION})
            )
        settings = catalogue.tactics["shape"].in_possession
        self.assertEqual(settings.player_selected, ())
        self.assertEqual(settings.crossing_type, "Mixed")
        self.assertEqual(settings.time_wasting, "Sometimes")

    def test_an_unknown_top_level_in_possession_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {**TACTIC, "inPossession": {**COMPLETE_IN_POSSESSION, "dribbleMore": True}}
            with self.assertRaisesRegex(ValueError, "unknown key.*dribbleMore"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_an_unknown_key_inside_fixed_is_refused(self) -> None:
        # Includes the old one-key-per-toggle format: toggles are listed under "selected".
        for key in ("overlapLeft", "passIntoSpace", "focusPlay"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                tactic = {**TACTIC, "inPossession": {"fixed": {**COMPLETE_FIXED, key: True}}}
                with self.assertRaisesRegex(ValueError, f"inPossession.fixed.*unknown key.*{key}"):
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

    def test_selected_must_be_a_list_of_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {"fixed": {**COMPLETE_FIXED, "selected": "Pass Into Space"}},
            }
            with self.assertRaisesRegex(ValueError, "fixed.selected must be an array of instruction names"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_toggle_listed_in_the_wrong_group_says_where_it_belongs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {"fixed": {**COMPLETE_FIXED, "selected": ["Hit Early Crosses"]}},
            }
            with self.assertRaisesRegex(
                ValueError, r"\['Hit Early Crosses'\] belong in inPossession.dependsOnPlayers.selected"
            ):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_an_unknown_toggle_is_refused_naming_the_tactic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {**TACTIC, "inPossession": {"dependsOnPlayers": {"selected": ["Overlap Middle"]}}}
            with self.assertRaisesRegex(
                ValueError, "tactic 'shape' inPossession: dependsOnPlayers.selected: unknown instruction"
            ):
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
                    "dependsOnPlayers": {"selected": ["Dribble Less", "Run At Defence"]},
                },
            }
            with self.assertRaisesRegex(ValueError, "'Dribble Less' and 'Run At Defence' cannot both be selected"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_clash_across_fixed_and_player_dependent_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {
                    "fixed": {**COMPLETE_FIXED, "selected": ["Work Ball Into Box"]},
                    "dependsOnPlayers": {"selected": ["Shoot On Sight"]},
                },
            }
            with self.assertRaisesRegex(ValueError, "'Work Ball Into Box' and 'Shoot On Sight' cannot both"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_clash_with_a_legacy_instruction_string_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "instructions": ["Hit Early Crosses"],
                "inPossession": {"fixed": {**COMPLETE_FIXED, "selected": ["Work Ball Into Box"]}},
                "instructionRationale": {"Hit Early Crosses": "Early balls."},
            }
            with self.assertRaisesRegex(
                ValueError, "tactic 'shape': 'Work Ball Into Box' and 'Hit Early Crosses' cannot both"
            ):
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
