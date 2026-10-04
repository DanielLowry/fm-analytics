import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch

from tools.fm20_match_duty_survey import slot_report, survey, unique_matches
from tools.fm20_match_tactics import (
    ARRAY_HEADER, DUTY_MASK, Slot, TacticDecodeError, candidate_prefixes, decode_prefix,
)
from tools.fm20_research import _adapter_command, _adapter_passed, plan_recipe


def string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<I", len(encoded)) + encoded


def slot(position: int, code: int, *, primary: int = 0, secondary: int = 0) -> bytes:
    instructions = (b"\x01\x01" + struct.pack("<I", primary)
                    + (struct.pack("<Q", 0x20) + b"\x01\x02\x02" + bytes(13)) * primary
                    + struct.pack("<I", secondary) + bytes(12 * secondary))
    return b"\x21\x00\x02" + struct.pack("<IQ", position, code) + instructions + b"\xff\x00"


def tactic(name="Example", *, override=True) -> bytes:
    header = ARRAY_HEADER + b"\x00" + string(name) + b"\x00" + string("") * 3
    settings = b"\x03" + bytes(8) + b"\x01\x02\x03" + bytes(13) + string("") + b"LLUN"
    slots = (slot(0x200400, 0x200020, primary=2, secondary=1)
             + slot(0x100400, 0x400020)
             + slot(4, 0x400000004) + slot(1, 0x200001) * 8)
    if not override:
        return header + settings + slots + b"\x00"
    return (header + settings + slots + b"\x01" + struct.pack("<I", 2)
            + struct.pack("<II", 92314, 0)
            + struct.pack("<II", 100628, 1) + slot(0x100400, 0x800020))


class MatchTacticDecoderTests(unittest.TestCase):
    def test_same_role_separate_duties_and_full_width_mask(self):
        decoded = decode_prefix(tactic())
        defend, support, automatic = decoded.slots[:3]
        self.assertEqual((defend.role, support.role), (0x20, 0x20))
        self.assertEqual((defend.duty, support.duty), (0x200000, 0x400000))
        self.assertEqual(automatic.duty, 0x400000000)
        self.assertEqual(automatic.role, 4)
        self.assertEqual(slot_report(automatic)["dutyCode"], "0x400000000")
        self.assertIsNone(slot_report(automatic)["duty"])
        self.assertEqual(DUTY_MASK, 0x406E00000)

    def test_variable_instructions_and_player_overrides_keep_boundaries(self):
        data = tactic()
        decoded = decode_prefix(data)
        self.assertEqual(decoded.prefix_end, len(data))
        self.assertEqual(decoded.overrides[0], (92314, ()))
        self.assertEqual(decoded.overrides[1], (100628, (Slot(0x100400, 0x800020),)))

    def test_every_truncated_prefix_is_rejected(self):
        data = tactic()
        for length in range(len(data)):
            with self.subTest(length=length), self.assertRaises(TacticDecodeError):
                decode_prefix(data[:length])

    def test_invalid_markers_and_unknown_high_bits_are_rejected(self):
        data = tactic()
        at = data.index(b"\x21\x00\x02", len(ARRAY_HEADER))
        for start, replacement in [(0, b"\xff"), (at, b"\x20"), (at + 7, struct.pack("<Q", 1 << 63))]:
            bad = data[:start] + replacement + data[start + len(replacement):]
            with self.subTest(start=start), self.assertRaises(TacticDecodeError):
                decode_prefix(bad)

    def test_count_and_string_limits_fail_closed(self):
        data = tactic()
        at = data.index(b"\x21\x00\x02", len(ARRAY_HEADER))
        for offset in [6, at + 17, len(data) - len(slot(0x100400, 0x800020)) - 4]:
            bad = data[:offset] + struct.pack("<I", 0xFFFFFFFF) + data[offset + 4:]
            with self.subTest(offset=offset), self.assertRaises(TacticDecodeError):
                decode_prefix(bad)

    def test_candidates_preserve_conflicts_instead_of_selecting_a_name(self):
        first, second = tactic("Vertical 4-4-2"), tactic("4-4-2", override=False)
        data = b"noise" + first + b"trailer" + second + ARRAY_HEADER
        candidates = candidate_prefixes(data)
        self.assertEqual([candidate.name for candidate in candidates], ["Vertical 4-4-2", "4-4-2"])
        self.assertEqual([candidate.offset for candidate in candidates], [5, 5 + len(first) + 7])
        self.assertEqual(candidates[0].prefix_end, 5 + len(first))


class MatchDutySurveyTests(unittest.TestCase):
    def test_survey_reads_only_managed_fixtures_and_preserves_unlinked_candidates(self):
        rows = {
            "ours": {"date": date(2020, 3, 28), "home_team": 11,
                     "away_team": 12, "home_goals": 0, "away_goals": 0},
            "other": {"home_team": 21, "away_team": 22},
        }
        chunk = tactic()
        detail = {"players": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pks_0.obs"
            path.write_bytes(b"existing FM archive")
            with (
                patch("tools.fm20_match_duty_survey.first_team_address", return_value=11),
                patch("tools.fm20_match_duty_survey.played_results", return_value=rows),
                patch("tools.fm20_match_duty_survey.Clubs", return_value=lambda team: {"id": str(team)}),
                patch("tools.fm20_match_duty_survey.archive.chunks", return_value=iter([chunk])),
                patch("tools.fm20_match_duty_survey.archive.involves", return_value=True) as involves,
                patch("tools.fm20_match_duty_survey.archive.decode_match", return_value=(detail, [])),
            ):
                report = survey(None, Path(directory))
        involves.assert_called_once_with(chunk, 11, 12)
        self.assertTrue(report["stable"])
        self.assertFalse(report["appearancesLinked"])
        self.assertFalse(report["labelsUiVerified"])
        self.assertEqual(report["arraysFound"], 1)
        self.assertEqual(report["matches"][0]["candidates"][0]["slots"][1]["duty"], "Support")

    def test_repeated_fixtures_and_reused_chunks_cannot_supply_evidence(self):
        row = {"date": "2020-03-28", "home": {"id": "1"}, "away": {"id": "2"},
               "archive": "pks_0.obs", "chunkIndex": 0}
        self.assertEqual(unique_matches([row]), [row])
        self.assertEqual(unique_matches([row, {**row, "chunkIndex": 1}]), [])
        self.assertEqual(unique_matches([row, {**row, "date": "2020-01-01"}]), [])

    def test_controller_decision_is_research_only_and_requires_stability(self):
        recipe, plan = plan_recipe("match-duty-archive-survey")
        command = _adapter_command(recipe, 7432, Path("/games/fm.exe"), "0x140000000", Path("/tmp/report"))
        self.assertIn("fm20_match_duty_survey.py", command[1])
        self.assertNotIn("--remote-address", command)
        self.assertEqual(plan["operator_interaction"], "none")
        completed = subprocess.CompletedProcess(command, 0, "", "")
        report = {"status": "complete", "researchOnly": True, "stable": True,
                  "matchesRead": 1, "arraysFound": 2, "appearancesLinked": False, "labelsUiVerified": False}
        self.assertTrue(_adapter_passed(recipe, completed, report)[0])
        for field, value in [("stable", False), ("arraysFound", 0), ("appearancesLinked", True),
                             ("labelsUiVerified", True), ("researchOnly", False)]:
            with self.subTest(field=field):
                self.assertFalse(_adapter_passed(recipe, completed, {**report, field: value})[0])


class TeamTacticTests(unittest.TestCase):
    """Choosing a side's tactic by FM's own line-up (`team_tactic`)."""

    # Our Vertical 4-4-2 as position codes (right before left) and role codes.
    LINE_UP = [(0x1, 0x1), (0x4, 0x4), (0x200010, 0x2), (0x100010, 0x2), (0x8, 0x4), (0x100, 0x80),
               (0x200400, 0x20), (0x100400, 0x20), (0x200, 0x80), (0x204000, 0x80000000), (0x104000, 0x80000)]
    DUTIES = [0x200000, 0x400000, 0x200000, 0x200000, 0x400000, 0x400000,
              0x400000, 0x200000, 0x400000, 0x400000, 0x800000]

    def prefix(self, name, duties=None, roles=None):
        from tools.fm20_match_tactics import TacticPrefix
        roles = roles or [role for _code, role in self.LINE_UP]
        slots = tuple(Slot(code, role | duty) for (code, _), role, duty in zip(self.LINE_UP, roles, duties or self.DUTIES))
        return TacticPrefix(0, name, slots, (), 0)

    def test_the_tactic_placing_every_starter_is_chosen_whatever_its_name(self):
        from tools.fm20_match_tactics import team_tactic
        ours = self.prefix("Vertical 4-4-2")
        default = self.prefix("4-4-2", roles=[role for _c, role in self.LINE_UP[:9]] + [0x400, 0x800])
        self.assertIs(team_tactic((default, ours), self.LINE_UP), ours)

    def test_copies_must_agree_on_every_duty(self):
        from tools.fm20_match_tactics import team_tactic
        swapped = self.DUTIES[:6] + [0x200000, 0x400000] + self.DUTIES[8:]
        self.assertIsNone(team_tactic((self.prefix("A"), self.prefix("B", swapped)), self.LINE_UP))
        self.assertIsNotNone(team_tactic((self.prefix("A"), self.prefix("A copy")), self.LINE_UP))

    def test_nothing_is_chosen_without_a_full_line_up(self):
        from tools.fm20_match_tactics import team_tactic
        self.assertIsNone(team_tactic((self.prefix("A"),), self.LINE_UP[:10]))
        other = list(self.LINE_UP)
        other[6] = (0x200400, 0x10000)  # a Box-to-Box Midfielder started there instead
        self.assertIsNone(team_tactic((self.prefix("A"),), other))

    def test_a_position_and_centre_side_become_fms_code(self):
        from tools.fm20_match_layout import position_code
        self.assertEqual(position_code("MC", "right"), 0x200400)
        self.assertEqual(position_code("ST", "left"), 0x104000)
        self.assertEqual(position_code("DR", None), 0x4)
