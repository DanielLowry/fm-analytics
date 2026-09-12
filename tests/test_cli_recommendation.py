import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fm_analytics.cli import main
from fm_analytics.analytics import MVP_CATALOGUE


HTML = """
<table>
  <tr><th>UID</th><th>Name</th><th>Position</th><th>Pas</th></tr>
  <tr><td>player-1</td><td>Sam Keeper</td><td>GK</td><td>10</td></tr>
  <tr><td>player-2</td><td>Chris Centreback</td><td>D (C), DM</td><td>10</td></tr>
  <tr><td>player-3</td><td>Morgan Midfielder</td><td>M/AM (C)</td><td>10</td></tr>
</table>
"""


class RecommendationCliTests(unittest.TestCase):
    def test_renders_safe_partial_recommendation_from_fixture_and_html(self) -> None:
        fixture = (
            Path(__file__).parent.parent
            / "src/fm_analytics/fixtures/sample-game.json"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".html") as html_file:
            html_file.write(HTML)
            html_file.flush()
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "--fixture",
                        str(fixture),
                        "--fm-html",
                        html_file.name,
                        "--recommend",
                    ]
                )

        self.assertEqual(status, 0)
        self.assertIn("MVP recommendation", output.getvalue())
        self.assertIn("football scores are provisional", output.getvalue())
        self.assertIn("Best feasible partial XI", output.getvalue())
        self.assertIn("Substitutes", output.getvalue())
        self.assertIn("Weak points", output.getvalue())
        self.assertIn("Recruitment briefs", output.getvalue())

    def test_recommendation_refuses_unproven_memory_attributes(self) -> None:
        fixture = (
            Path(__file__).parent.parent
            / "src/fm_analytics/fixtures/sample-game.json"
        )
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--fixture", str(fixture), "--recommend"])

        self.assertEqual(status, 1)
        self.assertIn("requires complete manager-visible squad attributes", output.getvalue())

    def test_recommends_without_html_from_complete_visible_squad(self) -> None:
        fixture = Path(__file__).parent.parent / "src/fm_analytics/fixtures/sample-game.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        original = document["squad"]["players"][0]
        required = {
            attribute.name
            for role in MVP_CATALOGUE.roles.values()
            for attribute in role.attributes
        }
        slots = MVP_CATALOGUE.tactics["balanced_442"].slots
        document["squad"]["players"] = [
            {
                **original,
                "id": f"player-{index}",
                "name": f"Player {index}",
                "positions": [slot.position],
                "attributes": {
                    name: {"visibility": "known", "value": 10}
                    for name in required
                },
            }
            for index, slot in enumerate(slots, start=1)
        ]
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "complete-squad.json"
            snapshot_path = Path(directory) / "snapshot.sqlite3"
            fixture_path.write_text(json.dumps(document), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    "--fixture", str(fixture_path),
                    "--recommend",
                    "--snapshot-db", str(snapshot_path),
                ])

        self.assertEqual(status, 0)
        self.assertIn("Starting XI", output.getvalue())
        self.assertIn("Attribute coverage: complete", output.getvalue())
        self.assertIn("Recruitment briefs", output.getvalue())
        self.assertIn("Snapshot: created capture", output.getvalue())

    def test_no_html_requires_complete_attributes_for_each_player(self) -> None:
        fixture = Path(__file__).parent.parent / "src/fm_analytics/fixtures/sample-game.json"
        document = json.loads(fixture.read_text(encoding="utf-8"))
        required = {
            attribute.name
            for role in MVP_CATALOGUE.roles.values()
            for attribute in role.attributes
        }
        for player in document["squad"]["players"]:
            player["attributes"] = {
                name: {"visibility": "known", "value": 10}
                for name in required
            }
        document["squad"]["players"][0]["attributes"].pop("passing")
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "uneven-coverage.json"
            fixture_path.write_text(json.dumps(document), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(["--fixture", str(fixture_path), "--recommend"])

        self.assertEqual(status, 1)
        self.assertIn("requires complete manager-visible squad attributes", output.getvalue())

    def test_standalone_import_can_prove_visible_player_count(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".html") as html_file:
            html_file.write(HTML)
            html_file.flush()
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "--fm-html",
                        html_file.name,
                        "--fm-html-player-count",
                        "3",
                    ]
                )

        self.assertEqual(status, 0)
        self.assertIn("Completeness: verified against FM count 3", output.getvalue())

    def test_standalone_import_rejects_incomplete_visible_set(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".html") as html_file:
            html_file.write(HTML)
            html_file.flush()
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "--fm-html",
                        html_file.name,
                        "--fm-html-player-count",
                        "4",
                    ]
                )

        self.assertEqual(status, 1)
        self.assertIn("imported 3 unique players but FM shows 4", output.getvalue())

    def test_candidate_import_requires_visible_count(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(
                [
                    "--fixture",
                    "unused.json",
                    "--fm-html",
                    "unused.html",
                    "--recommend",
                    "--candidate-html",
                    "candidates.html",
                ]
            )

        self.assertEqual(status, 1)
        self.assertIn("requires --candidate-player-count", output.getvalue())


if __name__ == "__main__":
    unittest.main()
