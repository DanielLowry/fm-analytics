"""The game plan the opponent report suggests: read from the opponent's style against its league."""

import unittest

from fm_analytics.analytics.game_plan_suggestion import MIN_MATCHES, suggest_plan
from fm_analytics.analytics.match_strength import TablePosition
from fm_analytics.analytics.opponent_report import StyleFigure

TEAMS = 24


def figure(key, label, value, rank, league, unit=""):
    return StyleFigure(key, label, value, 50.0, league, rank, TEAMS, unit)


def style(possession_rank=12, completion_rank=12, headers_rank=12):
    return (
        figure("possession", "Possession", 50.0, possession_rank, 50.0, "%"),
        figure("pass_completion", "Pass completion", 72.0, completion_rank, 71.0, "%"),
        figure("headers_attempted", "Headers contested", 76.0, headers_rank, 76.0),
    )


def place(position, played=10):
    return TablePosition(position, TEAMS, played, 0)


class SuggestionTests(unittest.TestCase):
    def plans(self, figures, theirs=None, ours=None, matches=8):
        found = suggest_plan(figures, matches, theirs, ours)
        return tuple(plan.key for plan in found.plans) if found else None

    def test_a_side_that_keeps_the_ball_is_pressed(self) -> None:
        self.assertEqual(self.plans(style(possession_rank=2, completion_rank=3)), ("territorial",))

    def test_a_side_that_goes_long_is_met_with_a_higher_line(self) -> None:
        found = suggest_plan(style(completion_rank=23), 8, None, None)
        self.assertEqual(tuple(plan.key for plan in found.plans), ("territorial",))
        self.assertEqual(found.style, "go long and fight for second balls")
        # Only the figure that decided it is given as a reason.
        self.assertTrue(found.reasons[0].startswith("pass completion 72%, 23rd of 24"))
        self.assertFalse(any(reason.startswith("headers") for reason in found.reasons))
        self.assertEqual(self.plans(style(headers_rank=1)), ("territorial",))

    def test_a_side_that_lets_its_opponents_have_the_ball_is_controlled_with_it(self) -> None:
        self.assertEqual(self.plans(style(possession_rank=22)), ("possession", "chance"))

    def test_nothing_marked_is_chance_control(self) -> None:
        self.assertEqual(self.plans(style()), ("chance",))

    def test_a_side_above_us_is_countered_rather_than_controlled(self) -> None:
        self.assertEqual(self.plans(style(possession_rank=2, completion_rank=2), place(4), place(9)), ("counter",))
        # Close below the top third on both sides: two places is not enough to say they are stronger.
        self.assertEqual(self.plans(style(), place(10), place(12)), ("chance",))
        # Early in the season the table says too little.
        self.assertEqual(self.plans(style(), place(1, played=2), place(20, played=2)), ("chance",))

    def test_too_few_matches_suggest_nothing(self) -> None:
        self.assertIsNone(suggest_plan(style(), MIN_MATCHES - 1, None, None))
        self.assertIsNone(suggest_plan((), 10, None, None))

    def test_without_enough_of_the_league_to_rank_against_nothing_is_suggested(self) -> None:
        # Only us and them recorded: "1st of 2" says nothing about how they play.
        thin = tuple(StyleFigure(f.key, f.label, f.value, f.against, f.league, 1, 2, f.unit) for f in style())
        self.assertIsNone(suggest_plan(thin, 8, None, None))

    def test_the_style_reads_as_a_sentence_after_they(self) -> None:
        for found in (suggest_plan(style(), 8, None, None),
                      suggest_plan(style(), 8, place(2), place(12))):
            self.assertIn(found.style, ("show no clear pattern", "are above you in the table"))


if __name__ == "__main__":
    unittest.main()
