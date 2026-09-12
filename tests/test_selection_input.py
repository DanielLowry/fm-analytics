import unittest
from datetime import date

from fm_analytics.analytics import overlay_squad_export
from fm_analytics.domain import Club, Player, Squad, Visibility
from fm_analytics.imports import parse_fm_html_export, parse_fm_squad_html_export


def squad() -> Squad:
    return Squad(
        club=Club("10", "Example FC"),
        as_of_date=date(2020, 1, 1),
        players=(
            Player(
                id="1",
                name="Alex  Exact",
                date_of_birth=None,
                age=20,
                positions=("MC",),
                club_id="10",
                condition_percent=95,
                match_fitness_percent=90,
                availability="available",
                injured=False,
                suspended=False,
                contract=None,
                attributes={},
            ),
        ),
    )


def export(name: str = "Alex Exact", uid: str = "1") -> str:
    return f"""
    <table>
      <tr><th>UID</th><th>Name</th><th>Position</th><th>Pas</th></tr>
      <tr><td>{uid}</td><td>{name}</td><td>M/AM (C)</td><td>12-15</td></tr>
      <tr><td>2</td><td>Extra Player</td><td>ST (C)</td><td>?</td></tr>
    </table>
    """


class SelectionInputTests(unittest.TestCase):
    def test_overlays_only_visible_positions_and_attributes(self) -> None:
        result = overlay_squad_export(squad(), parse_fm_html_export(export()))

        player = result.squad.players[0]
        self.assertEqual(player.condition_percent, 95)
        self.assertEqual(player.positions, ("MC", "AMC"))
        self.assertEqual(player.attributes["passing"].visibility, Visibility.RANGE)
        self.assertEqual(result.matched_players, 1)
        self.assertEqual(result.extra_export_player_ids, ("2",))

    def test_rejects_missing_squad_player(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing players"):
            overlay_squad_export(squad(), parse_fm_html_export(export(uid="3")))

    def test_rejects_identity_name_conflict(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting names"):
            overlay_squad_export(
                squad(),
                parse_fm_html_export(export(name="Different Person")),
            )

    def test_name_only_stock_view_binds_to_live_id_and_keeps_live_position(self) -> None:
        html = """
        <table>
          <tr><th>Name</th><th>Acc</th><th>Pac</th></tr>
          <tr><td>Alex Exact</td><td>12</td><td>13</td></tr>
        </table>
        """

        result = overlay_squad_export(
            squad(),
            parse_fm_squad_html_export(html),
        )

        player = result.squad.players[0]
        self.assertEqual(player.id, "1")
        self.assertEqual(player.positions, ("MC",))
        self.assertEqual(player.attributes["pace"].value, 13)


if __name__ == "__main__":
    unittest.main()
