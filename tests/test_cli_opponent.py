"""The `--opponent-*` flags: the only way a manager sets an opponent today.

These guard the wiring and the wording, not the football. The numbers
themselves are covered by `test_opponent.py`; what matters here is that the
flags exist for every declared axis, reach the scoring policy, and that the
output says whose judgement the profile is.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fm_analytics.analytics import AXIS_DEFINITIONS, OpponentProfile
from fm_analytics.cli import build_parser, main, opponent_from_args
from tests.test_cli_recommendation import HTML

FIXTURE = Path(__file__).parent.parent / "src/fm_analytics/fixtures/sample-game.json"


def run_cli(*extra: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".html") as html_file:
        html_file.write(HTML)
        html_file.flush()
        output = io.StringIO()
        with redirect_stdout(output):
            main(["--fixture", str(FIXTURE), "--fm-html", html_file.name, "--recommend", *extra])
        return output.getvalue()


class FlagDefinitionTests(unittest.TestCase):
    def test_every_declared_axis_gets_a_flag(self) -> None:
        # Flags are generated from AXIS_DEFINITIONS, so a new slider needs no
        # change in cli.py -- this fails if that generation is replaced by a
        # hand-written list that someone forgets to extend.
        help_text = build_parser().format_help()
        for axis in AXIS_DEFINITIONS:
            self.assertIn(f"--opponent-{axis.key.replace('_', '-')}", help_text, axis.key)

    def test_each_flag_explains_both_ends_in_plain_words(self) -> None:
        # argparse hard-wraps help text, so compare on collapsed whitespace.
        help_text = " ".join(build_parser().format_help().split())
        for axis in AXIS_DEFINITIONS:
            self.assertIn(axis.low, help_text, axis.key)
            self.assertIn(axis.high, help_text, axis.key)

    def test_the_help_says_the_profile_is_not_measured(self) -> None:
        # The manager-visible boundary matters here: nothing in FM is read to
        # set these, and the help must not imply otherwise.
        self.assertIn("your judgement, not measurements", build_parser().format_help())

    def test_no_flags_means_a_neutral_profile(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(opponent_from_args(args), OpponentProfile.neutral())
        self.assertTrue(opponent_from_args(args).is_neutral)

    def test_flags_reach_the_profile(self) -> None:
        args = build_parser().parse_args(
            ["--opponent-aerial-threat", "2", "--opponent-quality", "-1"]
        )
        self.assertEqual(
            opponent_from_args(args), OpponentProfile(aerial_threat=2, quality=-1)
        )

    def test_an_out_of_range_setting_is_refused_by_the_parser(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--opponent-quality", "3"])


class OutputTests(unittest.TestCase):
    def test_a_neutral_run_says_no_opponent_is_set(self) -> None:
        output = run_cli()
        self.assertIn("no opponent is set", output)
        self.assertNotIn("Assumed opponent", output)
        self.assertNotIn(", opponent ", output)

    def test_a_set_opponent_is_named_with_its_provenance(self) -> None:
        output = run_cli("--opponent-aerial-threat", "2")
        self.assertIn("Assumed opponent (your estimate, not measured from the game)", output)
        self.assertIn("Aerial threat: +2 (dominant)", output)

    def test_one_step_leans_rather_than_mangling_the_end_label(self) -> None:
        # The labels describe the extremes, so +1 must not read
        # "much stronger than us, slightly".
        output = run_cli("--opponent-quality", "1")
        self.assertIn("Quality: +1 (leaning much stronger than us)", output)

    def test_an_axis_with_team_shape_floors_adds_an_advisory_check(self) -> None:
        output = run_cli("--opponent-quality", "2")
        self.assertIn("advisory opponent check", output)
        self.assertIn("shown as an advisory check below", output)
        self.assertIn("does not affect the tactic score", output)

    def test_an_axis_that_only_moves_selection_says_so_instead(self) -> None:
        # Aerial threat deliberately imposes no team-shape floor (the system
        # model has no aerial-defence dimension), so no opponent check is
        # reported. Without the explanation a manager would set the slider, see
        # no new number, and reasonably conclude it did nothing.
        output = run_cli("--opponent-aerial-threat", "2")
        self.assertNotIn("advisory opponent check", output)
        self.assertIn("impose no team-shape requirement", output)

    def test_only_the_axes_actually_set_are_listed(self) -> None:
        output = run_cli("--opponent-pressing", "-2")
        self.assertIn("Pressing: -2 (passive)", output)
        self.assertNotIn("Aerial threat", output)

    def test_a_neutral_run_is_unchanged_by_passing_explicit_zeros(self) -> None:
        self.assertEqual(run_cli(), run_cli("--opponent-quality", "0", "--opponent-pressing", "0"))


if __name__ == "__main__":
    unittest.main()
