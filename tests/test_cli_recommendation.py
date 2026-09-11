import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fm_analytics.cli import main


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
        self.assertIn("Best feasible partial XI", output.getvalue())
        self.assertIn("Substitutes", output.getvalue())
        self.assertIn("Weak points", output.getvalue())
        self.assertIn("Recruitment briefs", output.getvalue())

    def test_recommendation_refuses_unproven_memory_attributes(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--recommend"])

        self.assertEqual(status, 1)
        self.assertIn("requires at least one --fm-html", output.getvalue())

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
