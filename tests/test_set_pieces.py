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
        self.assertEqual(corners.suggested.score.score.central, 86.578947)  # type: ignore[union-attr]

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

    def test_inswinging_delivery_uses_different_takers_on_each_side(self) -> None:
        attributes = {"corners": known(15), "crossing": known(15), "technique": known(15)}
        left_footed = replace(
            self.base, id="left", name="Left Foot", preferred_foot="Left", attributes=attributes,
        )
        right_footed = replace(
            self.base, id="right", name="Right Foot", preferred_foot="Right", attributes=attributes,
        )
        report = recommend_set_pieces(
            replace(self.squad, players=(left_footed, right_footed)),
            delivery_style="inswinging",
        )
        left_side = next(
            item for item in report.recommendations
            if item.task.key == "corners" and item.side == "left"
        )
        right_side = next(
            item for item in report.recommendations
            if item.task.key == "corners" and item.side == "right"
        )

        self.assertEqual(left_side.suggested.player.id, "right")  # type: ignore[union-attr]
        self.assertEqual(right_side.suggested.player.id, "left")  # type: ignore[union-attr]
        self.assertEqual(left_side.suggested.side_fit_bonus, 4.0)  # type: ignore[union-attr]

    def test_outswinging_delivery_reverses_the_preferred_foot_by_side(self) -> None:
        attributes = {"corners": known(15), "crossing": known(15), "technique": known(15)}
        left_footed = replace(self.base, id="left", preferred_foot="Left", attributes=attributes)
        right_footed = replace(self.base, id="right", preferred_foot="Right", attributes=attributes)
        report = recommend_set_pieces(
            replace(self.squad, players=(left_footed, right_footed)),
            delivery_style="outswinging",
        )
        left_side = next(
            item for item in report.recommendations
            if item.task.key == "corners" and item.side == "left"
        )

        self.assertEqual(left_side.suggested.player.id, "left")  # type: ignore[union-attr]

    def test_dedicated_taker_attributes_replace_the_proxy_when_supplied(self) -> None:
        player = replace(
            self.base,
            id="specialist",
            attributes={
                "freeKickTaking": known(18), "technique": known(14),
                "longShots": known(10), "composure": known(12),
                "finishing": known(8), "penaltyTaking": known(17),
            },
        )

        report = recommend_set_pieces(replace(self.squad, players=(player,)))
        free_kick = next(
            item for item in report.recommendations
            if item.task.key == "direct_free_kicks" and item.side == "left"
        )
        penalty = next(
            item for item in report.recommendations if item.task.key == "penalties"
        )

        self.assertEqual(free_kick.suggested.evidence_mode, "dedicated")  # type: ignore[union-attr]
        self.assertEqual(penalty.suggested.evidence_mode, "dedicated")  # type: ignore[union-attr]
        self.assertEqual(
            free_kick.suggested.score.contributions[0].attribute,  # type: ignore[union-attr]
            "freeKickTaking",
        )

    def test_long_throws_are_withheld_until_the_dedicated_rating_exists(self) -> None:
        without_rating = replace(self.base, id="without", attributes={"strength": known(20)})
        with_rating = replace(self.base, id="with", attributes={"longThrows": known(16)})

        missing = recommend_set_pieces(replace(self.squad, players=(without_rating,)))
        captured = recommend_set_pieces(replace(self.squad, players=(with_rating,)))

        missing_order = next(
            item for item in missing.recommendations if item.task.key == "long_throws"
        )
        captured_order = next(
            item for item in captured.recommendations if item.task.key == "long_throws"
        )
        self.assertIsNone(missing_order.suggested)
        self.assertEqual(captured_order.suggested.player.id, "with")  # type: ignore[union-attr]

    def test_routine_optimizer_assigns_each_player_to_one_job(self) -> None:
        attributes = {
            name: known(10)
            for name in (
                "acceleration", "aerialReach", "aggression", "agility", "anticipation",
                "balance", "bravery", "commandOfArea", "communication", "composure",
                "concentration", "corners", "crossing", "decisions", "dribbling",
                "finishing", "firstTouch", "handling", "heading", "jumpingReach",
                "longShots", "marking", "offTheBall", "pace", "passing", "positioning",
                "strength", "tackling", "technique", "workRate",
            )
        }
        players = tuple(
            replace(
                self.base,
                id=f"p{index}",
                name=f"Player {index}",
                positions=("GK",) if index == 0 else ("DC",),
                attributes=attributes,
            )
            for index in range(11)
        )

        report = recommend_set_pieces(
            replace(self.squad, players=players),
            selected_player_ids=tuple(player.id for player in players),
            lineup_positions={player.id: player.positions[0] for player in players},
        )

        for routine in report.routines:
            assigned = [item.player.id for item in routine.assignments]
            self.assertEqual(len(assigned), len(set(assigned)), routine.name)
            self.assertFalse(routine.unfilled_roles, routine.name)
        attacking = next(item for item in report.routines if item.key == "attacking_corner_left")
        taker = next(item.player.id for item in attacking.assignments if item.role.unit == "Delivery")
        box_players = {
            item.player.id for item in attacking.assignments if item.role.unit == "Box attack"
        }
        self.assertNotIn(taker, box_players)
        self.assertEqual(attacking.players_held_back, 2)

    def test_attacking_risk_changes_rest_defence_commitment(self) -> None:
        attributes = {
            name: known(12)
            for name in (
                "acceleration", "aggression", "anticipation", "balance", "bravery",
                "composure", "concentration", "corners", "crossing", "decisions",
                "finishing", "firstTouch", "heading", "jumpingReach", "longShots",
                "marking", "offTheBall", "pace", "passing", "positioning", "strength",
                "tackling", "technique",
            )
        }
        players = tuple(
            replace(self.base, id=f"p{index}", positions=("DC",), attributes=attributes)
            for index in range(10)
        )
        squad = replace(self.squad, players=players)

        counts = {}
        for risk in ("secure", "balanced", "aggressive"):
            report = recommend_set_pieces(squad, attacking_risk=risk)
            routine = next(item for item in report.routines if item.key == "attacking_corner_left")
            counts[risk] = routine.players_held_back

        self.assertEqual(counts, {"secure": 3, "balanced": 2, "aggressive": 1})


if __name__ == "__main__":
    unittest.main()
