"""A tactic's "In Possession" phase settings: parsing, validation, and the
completeness flag the tactic page uses to say what has not been set yet.
"""

import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.analytics.in_possession import InPossessionSettings

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
COMPLETE_IN_POSSESSION = {
    "attackingWidth": "Fairly Wide",
    "passingDirectness": "Slightly More Direct Passing",
    "tempo": "Higher Tempo",
    "passIntoSpace": True,
    "playOutOfDefence": False,
    "focusPlay": "Down the Left",
    "workBallIntoBox": False,
}


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

    def test_a_fully_specified_block_leaves_nothing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(
                self.build(Path(tmp), {**TACTIC, "inPossession": COMPLETE_IN_POSSESSION})
            )
        tactic = catalogue.tactics["shape"]
        self.assertEqual(tactic.in_possession_missing_fields, ())
        self.assertEqual(tactic.in_possession.attacking_width, "Fairly Wide")
        self.assertTrue(tactic.in_possession.pass_into_space)

    def test_a_partially_specified_block_reports_what_it_left_out(self) -> None:
        partial = {"attackingWidth": "Fairly Wide", "tempo": "Higher Tempo"}
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(Path(tmp), {**TACTIC, "inPossession": partial}))
        tactic = catalogue.tactics["shape"]
        self.assertIn("passing directness", tactic.in_possession_missing_fields)
        self.assertIn("focus play", tactic.in_possession_missing_fields)
        self.assertEqual(len(tactic.in_possession_missing_fields), 5)

    def test_player_dependent_fields_default_without_being_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(
                self.build(Path(tmp), {**TACTIC, "inPossession": COMPLETE_IN_POSSESSION})
            )
        settings = catalogue.tactics["shape"].in_possession
        self.assertFalse(settings.overlap_left)
        self.assertEqual(settings.crossing_type, "Mixed")
        self.assertEqual(settings.time_wasting, "Sometimes")

    def test_an_unknown_in_possession_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {**TACTIC, "inPossession": {**COMPLETE_IN_POSSESSION, "dribbleMore": True}}
            with self.assertRaisesRegex(ValueError, "unknown key.*dribbleMore"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_non_boolean_flag_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {**TACTIC, "inPossession": {**COMPLETE_IN_POSSESSION, "passIntoSpace": "yes"}}
            with self.assertRaisesRegex(ValueError, "passIntoSpace must be true/false"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_a_non_string_enum_value_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {**TACTIC, "inPossession": {**COMPLETE_IN_POSSESSION, "tempo": 5}}
            with self.assertRaisesRegex(ValueError, "tempo must be a string"):
                load_catalogue(self.build(Path(tmp), tactic))

    def test_an_invalid_combination_inside_the_block_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = {
                **TACTIC,
                "inPossession": {**COMPLETE_IN_POSSESSION, "dribbleLess": True, "runAtDefence": True},
            }
            with self.assertRaisesRegex(ValueError, "dribbleLess and runAtDefence"):
                load_catalogue(self.build(Path(tmp), tactic))


if __name__ == "__main__":
    unittest.main()
