import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from fm_analytics import match_ingest
from fm_analytics.analytics.match_analysis import ReviewFilters
from fm_analytics.match_ingest import format_review, main, record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_match_review

from tests.match_support import capture_document, season

DETAILED = "2019-09-01:100:201"


class CliCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.db = self.directory / "history.sqlite3"
        self.capture = self.directory / "capture.json"
        self.capture.write_text(json.dumps(capture_document(season())), encoding="utf-8")

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--db", str(self.db), *map(str, args)])
        return code, output.getvalue()


class IngestAndReadTests(CliCase):
    def test_ingest_then_status(self) -> None:
        code, text = self.run_cli("ingest", self.capture)
        self.assertEqual(code, 0)
        self.assertIn("6 matches seen, 6 new or changed, 8 league results added", text)
        code, text = self.run_cli("status")
        self.assertIn("club:100 (Hungerford Town): 6 matches, 1 with full stats", text)

    def test_the_save_is_the_managed_club_unless_named(self) -> None:
        record_capture_file(MatchHistoryStore(self.db), self.capture)
        self.assertEqual(MatchHistoryStore(self.db).latest_save_key(), "club:100")
        code, _text = self.run_cli("--save", "my-save", "ingest", self.capture)
        self.assertEqual(code, 0)
        self.assertEqual(MatchHistoryStore(self.db).latest_save_key(), "my-save")

    def test_review_prints_the_shared_computation(self) -> None:
        self.run_cli("ingest", self.capture)
        code, text = self.run_cli("review", "--group", "relative")
        self.assertEqual(code, 0)
        history = MatchHistoryStore(self.db).load_history("club:100")
        expected = format_review(build_match_review(history, filters=ReviewFilters(grouping="relative")))
        self.assertEqual(text.strip(), expected.strip())
        self.assertIn("Above us", text)

    def test_list_show_and_note(self) -> None:
        self.run_cli("ingest", self.capture)
        code, text = self.run_cli("list")
        self.assertIn(DETAILED, text)
        self.assertIn("full stats", text)
        code, text = self.run_cli("show", DETAILED)
        self.assertEqual(code, 0)
        self.assertIn("Vertical 4-4-2 (from the line-up)", text)
        self.assertIn("Advanced Forward (Attack)", text)
        code, text = self.run_cli("note", DETAILED, "--tactic", "wing_play_442", "--rating", "1", "--text", "tight")
        self.assertEqual(code, 0)
        _code, text = self.run_cli("show", DETAILED)
        self.assertIn("Wing Play 4-4-2", text)

    def test_bad_input_is_an_error_not_a_crash(self) -> None:
        self.run_cli("ingest", self.capture)
        self.assertEqual(self.run_cli("note", DETAILED, "--tactic", "no_such_tactic")[0], 1)
        self.assertEqual(self.run_cli("note", DETAILED, "--rating", "5")[0], 1)
        self.assertEqual(self.run_cli("show", "2019-01-01:1:2")[0], 1)
        self.assertEqual(self.run_cli("role-code", "0x40000", "no_such_role")[0], 1)
        code, text = self.run_cli("role-code", "0x40000", "af_attack")
        self.assertEqual(code, 0)
        self.assertIn("Advanced Forward (Attack)", text)

    def test_review_before_any_capture_says_what_to_do(self) -> None:
        code, text = self.run_cli("review")
        self.assertEqual(code, 1)
        self.assertIn("fm-matches capture", text)


class CaptureTests(CliCase):
    def test_capture_runs_the_read_only_tool_then_records_its_output(self) -> None:
        def fake_run(command, **kwargs):
            self.assertEqual(command[1:3], [str(match_ingest.CAPTURE_TOOL), "capture"])
            Path(command[-1]).write_text(self.capture.read_text(encoding="utf-8"), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "Captured 6 matches.", "")

        output = self.directory / "out.json"
        with mock.patch.object(match_ingest.subprocess, "run", side_effect=fake_run):
            code, text = self.run_cli("capture", "--output", output)
        self.assertEqual(code, 0)
        self.assertIn("Captured 6 matches. Recorded: 6 matches seen", text)

    def test_a_failed_read_is_reported(self) -> None:
        failed = subprocess.CompletedProcess([], 2, "", "FM20 cannot be read: FM20 is not running")
        with mock.patch.object(match_ingest.subprocess, "run", return_value=failed):
            code, text = self.run_cli("capture", "--output", self.directory / "out.json")
        self.assertEqual(code, 1)
        self.assertIn("FM20 is not running", text)


if __name__ == "__main__":
    unittest.main()
