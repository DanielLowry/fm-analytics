import io
import json
import struct
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.fm20_linux_probe import ProbeError
from tools.fm20_search_caller_trace import trace_callers
from tools.fm20_visibility_capture import CaptureError
from tools.fm20_field_workbench import (
    FIELD_SPECS,
    PeImage,
    choose_validation_players,
    main,
    scan_static,
    select_trace_targets,
    survey_owned_squad,
)


def small_pe_with_rtti() -> bytes:
    data = bytearray(0xA00)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 2)
    struct.pack_into("<H", data, 0x94, 0xF0)
    struct.pack_into("<H", data, 0x98, 0x20B)
    image_base = 0x140000000
    struct.pack_into("<Q", data, 0x98 + 24, image_base)

    # Executable code section: RVA 0x1000, file offset 0x200.
    section = 0x188
    data[section:section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x200, 0x1000, 0x200, 0x200)
    struct.pack_into("<I", data, section + 36, 0x60000020)
    # Data section: RVA 0x2000, file offset 0x400.
    section += 40
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x500, 0x2000, 0x500, 0x400)
    struct.pack_into("<I", data, section + 36, 0x40000040)

    # MSVC x64 RTTI: TypeDescriptor, CompleteObjectLocator, then vtable.
    data[0x490:0x490 + len(b".?AVFOOTEDNESS_LABEL@@\0")] = b".?AVFOOTEDNESS_LABEL@@\0"
    descriptor_rva = 0x2080
    col_rva = 0x2100
    struct.pack_into("<IIIIII", data, 0x500, 1, 0, 0, descriptor_rva, 0, col_rva)
    struct.pack_into("<Q", data, 0x580, image_base + col_rva)
    struct.pack_into("<QQ", data, 0x588, image_base + 0x1050, image_base + 0x1060)
    data[0x265:0x26B] = b"\x81\xfa\x75\x6c\x61\x76"
    return bytes(data)


class FieldWorkbenchTests(unittest.TestCase):
    def test_static_scan_maps_rtti_to_candidate_methods(self) -> None:
        data = small_pe_with_rtti()

        result = scan_static(data, (FIELD_SPECS["footedness"],))

        self.assertEqual(result["imageBase"], "0x140000000")
        foot = result["fields"]["footedness"]
        self.assertTrue(foot["anchors"]["FOOTEDNESS_LABEL"])
        rtti = foot["rtti"][0]
        self.assertEqual(rtti["typeDescriptor"]["rva"], "0x2080")
        self.assertEqual(
            rtti["completeObjectLocators"][0]["vtables"][0]["firstMethodRvas"],
            ["0x1050", "0x1060"],
        )
        self.assertEqual(
            [item["rva"] for item in foot["rareMethodLeads"]],
            ["0x1060"],
        )
        self.assertEqual(foot["propertySelectorLeads"][0]["selector"], "value")
        self.assertEqual(foot["propertySelectorLeads"][0]["comparisonRva"], "0x1065")
        self.assertEqual(
            select_trace_targets(result),
            {"footedness_0x1060": "0x1060"},
        )

    def test_custom_caller_trace_rejects_invalid_targets_before_attaching(self) -> None:
        for targets in ({}, {"bad": "not-a-rva"}, {"bad": "0x0"}):
            with self.subTest(targets=targets), self.assertRaises(CaptureError):
                trace_callers(123, duration_seconds=1, targets=targets)

    def test_rejects_broken_pe_and_unmapped_offsets(self) -> None:
        with self.assertRaisesRegex(ValueError, "PE"):
            PeImage.parse(b"not a PE")
        image = PeImage.parse(small_pe_with_rtti())
        self.assertIsNone(image.offset_to_rva(0x50))
        self.assertFalse(image.is_executable_rva(0x2080))

    def test_samples_diverse_owned_positions_without_foot_guess(self) -> None:
        players = [
            SimpleNamespace(id="1", name="Left", positions=("DL", "ML")),
            SimpleNamespace(id="2", name="Right", positions=("DR",)),
            SimpleNamespace(id="3", name="Centre", positions=("MC",)),
            SimpleNamespace(id="4", name="Other", positions=("MC",)),
        ]

        sample = choose_validation_players(players, limit=3)

        self.assertEqual({item.id for item in sample}, {"1", "2", "3"})

    def test_live_survey_uses_existing_probe_and_reports_no_raw_ratings(self) -> None:
        manager = SimpleNamespace(
            id="manager-1", active=True,
            club=SimpleNamespace(id="club-1", name="Example Club"),
        )
        snapshot = SimpleNamespace(
            game_date="2019-06-24",
            human_managers=(manager,),
            first_team_squad=(
                SimpleNamespace(id="1", name="Keeper", positions=("GK",)),
                SimpleNamespace(id="2", name="Fullback", positions=("DL", "DR")),
            ),
        )
        with patch("tools.fm20_field_workbench.probe", side_effect=(snapshot, snapshot)) as probe:
            result = survey_owned_squad(123)

        self.assertEqual(probe.call_count, 2)
        self.assertEqual(result["playerCount"], 2)
        self.assertEqual(len(result["squadIdHash"]), 64)
        self.assertEqual(result["positionCounts"], {"DL": 1, "DR": 1, "GK": 1})
        for item in result["samplePlayers"]:
            self.assertEqual(set(item), {"id", "name", "positions"})

    def test_live_survey_refuses_changed_squad(self) -> None:
        manager = SimpleNamespace(
            id="manager-1", active=True,
            club=SimpleNamespace(id="club-1", name="Example Club"),
        )
        before = SimpleNamespace(
            game_date="2019-06-24", human_managers=(manager,),
            first_team_squad=(SimpleNamespace(id="1", name="One", positions=("GK",)),),
        )
        after = SimpleNamespace(
            game_date="2019-06-24", human_managers=(manager,),
            first_team_squad=(SimpleNamespace(id="2", name="Two", positions=("GK",)),),
        )
        with patch("tools.fm20_field_workbench.probe", side_effect=(before, after)):
            with self.assertRaisesRegex(ProbeError, "changed during the survey"):
                survey_owned_squad(123)

    def test_static_cli_writes_research_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fm.exe"
            report = Path(directory) / "report.json"
            executable.write_bytes(small_pe_with_rtti())
            with patch("tools.fm20_field_workbench.verified_executable_digest", return_value="pinned"):
                with redirect_stdout(io.StringIO()):
                    status = main([
                        "static", "--executable", str(executable),
                        "--field", "footedness", "--report", str(report),
                    ])
            document = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertTrue(document["researchOnly"])
        self.assertFalse(document["productionFieldQueryProven"])
        self.assertEqual(document["status"], "complete")
        self.assertNotIn("live", document)
        self.assertEqual(set(document["static"]["fields"]), {"footedness"})

    def test_guided_trace_batches_targets_and_writes_one_report(self) -> None:
        owned = {
            "managerId": "manager-1", "clubId": "club-1",
            "gameDate": "2019-06-24", "squadIdHash": "abc",
            "samplePlayers": [
                {"id": "1", "name": "Example", "positions": ["ST"]},
            ],
        }

        def fake_trace(_pid, **kwargs):
            self.assertEqual(kwargs["targets"], {"footedness_0x1060": "0x1060"})
            kwargs["ready_callback"]()
            deadline = time.monotonic() + 1
            while not kwargs["stop_requested"]() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(kwargs["stop_requested"]())
            return {"footedness_0x1060": {"callers": {"0x123": 2}}}

        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fm.exe"
            report = Path(directory) / "trace.json"
            executable.write_bytes(small_pe_with_rtti())
            with (
                patch("tools.fm20_field_workbench.verified_executable_digest", return_value="pinned"),
                patch("tools.fm20_field_workbench.choose_pid", return_value=123),
                patch("tools.fm20_field_workbench.survey_owned_squad", side_effect=(owned, owned)),
                patch("tools.fm20_field_workbench.trace_callers", side_effect=fake_trace),
                patch("tools.fm20_field_workbench.sys.stdin") as stdin,
                patch("builtins.input", return_value="done"),
                redirect_stdout(io.StringIO()),
            ):
                stdin.isatty.return_value = True
                status = main([
                    "trace", "--executable", str(executable),
                    "--field", "footedness", "--report", str(report),
                ])
            document = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertEqual(document["status"], "complete")
        self.assertEqual(document["traceStatus"], "observed")
        self.assertTrue(document["sameManagerDateSquad"])
        self.assertFalse(document["productionFieldQueryProven"])

    def test_guided_trace_failure_still_writes_report(self) -> None:
        owned = {
            "managerId": "manager-1", "clubId": "club-1",
            "gameDate": "2019-06-24", "squadIdHash": "abc",
            "samplePlayers": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fm.exe"
            report = Path(directory) / "failed.json"
            executable.write_bytes(small_pe_with_rtti())
            with (
                patch("tools.fm20_field_workbench.verified_executable_digest", return_value="pinned"),
                patch("tools.fm20_field_workbench.choose_pid", return_value=123),
                patch("tools.fm20_field_workbench.survey_owned_squad", return_value=owned),
                patch("tools.fm20_field_workbench.trace_callers", side_effect=CaptureError("detached")),
                patch("tools.fm20_field_workbench.sys.stdin") as stdin,
                redirect_stdout(io.StringIO()),
            ):
                stdin.isatty.return_value = True
                status = main([
                    "trace", "--executable", str(executable),
                    "--field", "footedness", "--report", str(report),
                ])
            document = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(status, 1)
        self.assertEqual(document["status"], "failed")
        self.assertIn("detached", document["error"])
        self.assertFalse(document["productionFieldQueryProven"])


if __name__ == "__main__":
    unittest.main()
