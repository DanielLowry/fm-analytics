import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import recommend_set_pieces
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility


FIXTURE = Path(__file__).resolve().parent.parent / "src/fm_analytics/fixtures/sample-game.json"


def known(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


class SetPieceRecommendationTests(unittest.TestCase):
    def setUp(self) -> None:
        _game, squad = load_fixture(FIXTURE)
        self.base = squad.players[0]
        self.squad = squad

    def test_ranks_the_best_visible_corner_taker_first(self) -> None:
        weak = replace(
            self.base, id="weak", name="Weak Delivery",
            attributes={"corners": known(6), "crossing": known(6), "technique": known(6)},
        )
        strong = replace(
            self.base, id="strong", name="Strong Delivery",
            attributes={"corners": known(18), "crossing": known(17), "technique": known(16)},
        )
        report = recommend_set_pieces(replace(self.squad, players=(weak, strong)))

        corners = next(item for item in report.recommendations if item.task.key == "corners")

        self.assertEqual(corners.suggested.player.id, "strong")  # type: ignore[union-attr]
        self.assertEqual(corners.suggested.score.score.central, 86.578948)  # type: ignore[union-attr]

    def test_unavailable_players_are_not_suggested_even_when_they_are_best(self) -> None:
        available = replace(
            self.base, id="available", name="Available",
            attributes={"corners": known(8), "crossing": known(8), "technique": known(8)},
        )
        injured = replace(
            self.base, id="injured", name="Injured", availability="injured", injured=True,
            attributes={"corners": known(20), "crossing": known(20), "technique": known(20)},
        )
        report = recommend_set_pieces(replace(self.squad, players=(available, injured)))
        corners = next(item for item in report.recommendations if item.task.key == "corners")

        self.assertEqual(corners.suggested.player.id, "available")  # type: ignore[union-attr]
        self.assertEqual([player.id for player in report.unavailable_players], ["injured"])

    def test_unknown_inputs_remain_an_honest_score_range(self) -> None:
        blank = replace(self.base, id="blank", attributes={})
        report = recommend_set_pieces(replace(self.squad, players=(blank,)))
        penalties = next(item for item in report.recommendations if item.task.key == "penalties")
        score = penalties.candidates[0].score.score

        self.assertEqual((score.lower, score.central, score.upper), (0.0, 0.0, 100.0))
        self.assertIsNone(penalties.suggested)


if __name__ == "__main__":
    unittest.main()
