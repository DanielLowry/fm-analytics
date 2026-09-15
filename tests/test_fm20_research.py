import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.fm20_research import ControllerError, load_recipe, main, plan_recipe, run_recipe


class ResearchControllerTests(unittest.TestCase):
    def test_recipe_plan_resolves_registry_and_corpus(self) -> None:
        recipe, plan = plan_recipe("owned-footedness-survey")

        self.assertEqual(recipe["safety"], "passive-live")
        self.assertEqual(plan["operator_interaction"], "none")
        self.assertEqual(
            [item["id"] for item in plan["corpus_state_coverage"]],
            ["owned-field-survey", "owned-foot-position-trace"],
        )

    def test_recipe_id_cannot_escape_recipe_directory(self) -> None:
        with self.assertRaisesRegex(ControllerError, "recipe ID"):
            load_recipe("../anything")

    def test_dry_run_does_not_discover_or_probe_process(self) -> None:
        output = io.StringIO()
        with (
            patch("tools.fm20_research.choose_pid") as choose_pid,
            patch("tools.fm20_research.probe") as probe,
            redirect_stdout(output),
        ):
            status = main(["run", "owned-footedness-survey", "--dry-run", "--json"])

        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "planned")
        choose_pid.assert_not_called()
        probe.assert_not_called()

    def test_run_wraps_adapter_report_and_records_release(self) -> None:
        manager = SimpleNamespace(id="manager-1", active=True, club=SimpleNamespace(id="club-1"))
        snapshot = SimpleNamespace(
            pid=123,
            executable="/games/fm.exe",
            module_base="0x140000000",
            profile="FM20 20.4.4 Steam/Windows executable",
            game_date="2019-06-24",
            human_managers=(manager,),
            first_team_squad=(SimpleNamespace(id="player-1"),),
        )

        def fake_runner(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(json.dumps({
                "researchOnly": True,
                "status": "complete",
                "liveStatus": "surveyed",
            }) + "\n", encoding="utf-8")
            self.assertNotIn("trace", command)
            self.assertIn("--require-live", command)
            self.assertFalse(kwargs["check"])
            return subprocess.CompletedProcess(command, 0, "adapter result\n", "")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "session.json"
            with (
                patch("tools.fm20_research.choose_pid", return_value=123),
                patch("tools.fm20_research.probe", return_value=snapshot),
                patch("tools.fm20_research.verified_executable_digest", return_value="pinned"),
            ):
                status, actual, report = run_recipe(
                    "owned-footedness-survey", report_path=target, runner=fake_runner
                )
            saved = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertEqual(actual, target)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(saved["lifecycle"]["resourceRelease"], "confirmed-by-adapter-exit")
        self.assertTrue(saved["decision"]["passed"])
        self.assertIn("reportSha256", saved["execution"])
        self.assertNotIn("name", saved["process"])

    def test_preflight_failure_still_writes_a_controller_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "failed.json"
            with patch("tools.fm20_research.choose_pid", side_effect=ControllerError("no FM")):
                status, _, report = run_recipe("owned-footedness-survey", report_path=target)
            saved = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(status, 1)
        self.assertEqual(report["status"], "failed")
        self.assertIn("no FM", saved["error"])
        self.assertEqual(saved["lifecycle"]["resourceRelease"], "not-opened")


if __name__ == "__main__":
    unittest.main()

