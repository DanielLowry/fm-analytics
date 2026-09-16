import unittest
from datetime import date

from fm_analytics.domain.models import (
    AttributeObservation,
    Player,
    Squad,
    SquadTeam,
    Visibility,
)


class AttributeObservationTests(unittest.TestCase):
    def test_known_attribute(self) -> None:
        observation = AttributeObservation.from_dict(
            {"visibility": "known", "value": 15}
        )
        self.assertEqual(observation.value, 15)
        self.assertEqual(observation.display(), "15")
        self.assertEqual(
            observation.to_dict(), {"visibility": "known", "value": 15}
        )

    def test_range_attribute(self) -> None:
        observation = AttributeObservation.from_dict(
            {"visibility": "range", "minimum": 10, "maximum": 14}
        )
        self.assertEqual(observation.display(), "10-14")
        self.assertEqual(
            observation.to_dict(),
            {"visibility": "range", "minimum": 10, "maximum": 14},
        )

    def test_unknown_attribute_serializes_without_numeric_fields(self) -> None:
        observation = AttributeObservation.from_dict({"visibility": "unknown"})

        self.assertEqual(observation.to_dict(), {"visibility": "unknown"})

    def test_unknown_attribute_rejects_leaked_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbid numeric fields"):
            AttributeObservation.from_dict(
                {"visibility": "unknown", "value": 13}
            )

    def test_invalid_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "minimum cannot exceed"):
            AttributeObservation(
                visibility=Visibility.RANGE, minimum=15, maximum=10
            )


class PlayerTests(unittest.TestCase):
    def test_rejects_out_of_range_visible_percentage(self) -> None:
        raw = {
            "id": "1",
            "name": "Player",
            "dateOfBirth": None,
            "age": 22,
            "positions": ["MC"],
            "clubId": "2",
            "conditionPercent": 101,
            "matchFitnessPercent": None,
            "availability": "available",
            "injured": False,
            "suspended": False,
            "contract": None,
            "attributes": {},
        }

        with self.assertRaisesRegex(ValueError, "conditionPercent"):
            Player.from_dict(raw)

    def test_rejects_coerced_identifier_and_percentage_types(self) -> None:
        raw = {
            "id": 1,
            "name": "Player",
            "dateOfBirth": None,
            "age": 22,
            "positions": ["MC"],
            "clubId": "2",
            "conditionPercent": "97",
            "matchFitnessPercent": None,
            "availability": "available",
            "injured": False,
            "suspended": False,
            "contract": None,
            "attributes": {},
        }

        with self.assertRaisesRegex(TypeError, "id must be a string"):
            Player.from_dict(raw)

    @staticmethod
    def _raw(**overrides):
        base = {
            "id": "1",
            "name": "Player",
            "dateOfBirth": None,
            "age": 22,
            "positions": ["MC"],
            "clubId": "2",
            "conditionPercent": None,
            "matchFitnessPercent": None,
            "availability": "available",
            "injured": False,
            "suspended": False,
            "contract": None,
            "attributes": {},
        }
        base.update(overrides)
        return base

    def test_position_familiarity_defaults_to_empty_when_absent(self) -> None:
        player = Player.from_dict(self._raw())

        self.assertEqual(player.position_familiarity, {})
        self.assertEqual(player.to_dict()["positionFamiliarity"], {})

    def test_position_familiarity_defaults_to_empty_when_null(self) -> None:
        player = Player.from_dict(self._raw(positionFamiliarity=None))

        self.assertEqual(player.position_familiarity, {})

    def test_position_familiarity_round_trips(self) -> None:
        raw = self._raw(positionFamiliarity={"MC": 17, "DM": 9})

        player = Player.from_dict(raw)

        self.assertEqual(player.position_familiarity, {"MC": 17, "DM": 9})
        self.assertEqual(player.to_dict()["positionFamiliarity"], {"MC": 17, "DM": 9})

    def test_position_familiarity_rejects_out_of_range_rating(self) -> None:
        raw = self._raw(positionFamiliarity={"MC": 21})

        with self.assertRaisesRegex(ValueError, "positionFamiliarity"):
            Player.from_dict(raw)

    def test_position_familiarity_rejects_non_integer_rating(self) -> None:
        raw = self._raw(positionFamiliarity={"MC": "17"})

        with self.assertRaisesRegex(ValueError, "positionFamiliarity"):
            Player.from_dict(raw)


def _player(player_id: str, name: str) -> Player:
    return Player(
        id=player_id,
        name=name,
        date_of_birth=None,
        age=17,
        positions=("MC",),
        club_id="2",
        condition_percent=None,
        match_fitness_percent=None,
        availability="available",
        injured=False,
        suspended=False,
        contract=None,
        attributes={},
    )


class SquadTeamTests(unittest.TestCase):
    def test_marker_zero_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-zero"):
            SquadTeam(marker=0, players=(_player("1", "Youth Player"),))

    def test_round_trips_through_dict(self) -> None:
        team = SquadTeam(marker=9, players=(_player("1", "Youth Player"),))

        raw = team.to_dict()

        self.assertEqual(raw["marker"], 9)
        self.assertEqual(SquadTeam.from_dict(raw), team)


class SquadTests(unittest.TestCase):
    def test_other_teams_defaults_to_empty_and_does_not_affect_players(self) -> None:
        squad = Squad(club=None, as_of_date=date(2019, 6, 24), players=(_player("1", "First Teamer"),))

        self.assertEqual(squad.other_teams, ())
        self.assertEqual(squad.all_players(), squad.players)

    def test_all_players_combines_first_team_and_every_other_team(self) -> None:
        first_team = (_player("1", "First Teamer"),)
        youth = SquadTeam(marker=9, players=(_player("2", "Youth A"), _player("3", "Youth B")))
        reserves = SquadTeam(marker=12, players=(_player("4", "Reserve"),))
        squad = Squad(
            club=None, as_of_date=date(2019, 6, 24), players=first_team,
            other_teams=(youth, reserves),
        )

        self.assertEqual(squad.players, first_team)
        self.assertEqual(
            [player.id for player in squad.all_players()], ["1", "2", "3", "4"]
        )

    def test_round_trips_other_teams_through_dict(self) -> None:
        squad = Squad(
            club=None,
            as_of_date=date(2019, 6, 24),
            players=(_player("1", "First Teamer"),),
            other_teams=(SquadTeam(marker=9, players=(_player("2", "Youth A"),)),),
        )

        raw = squad.to_dict()
        restored = Squad.from_dict(raw)

        self.assertEqual(raw["otherTeams"], [{
            "marker": 9,
            "players": [_player("2", "Youth A").to_dict()],
        }])
        self.assertEqual(restored, squad)

    def test_missing_other_teams_key_defaults_to_empty_for_backward_compatibility(self) -> None:
        squad = Squad.from_dict({
            "club": None,
            "asOfDate": "2019-06-24",
            "players": [],
        })

        self.assertEqual(squad.other_teams, ())


if __name__ == "__main__":
    unittest.main()
