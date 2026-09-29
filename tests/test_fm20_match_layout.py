import struct
import unittest
from datetime import date

from tools import fm20_match_layout as layout


def fm_date(day: date) -> bytes:
    return struct.pack("<HH", day.timetuple().tm_yday | 0x4A00, day.year)  # high bits are flags


def fixture_result(*, played: bool = True, home_goals: int = 2, away_goals: int = 2) -> bytes:
    record = bytearray(layout.FIXTURE_RESULT_SIZE)
    struct.pack_into("<QQ", record, layout.RESULT_HOME_TEAM, 0x1000, 0x2000)
    struct.pack_into("<Q", record, layout.RESULT_FIXTURE_NAME, 0x3000)
    record[layout.RESULT_DATE:layout.RESULT_DATE + 4] = fm_date(date(2019, 11, 2))
    struct.pack_into("<I", record, layout.RESULT_ATTENDANCE, 344)
    record[layout.RESULT_HOME_GOALS] = home_goals
    record[layout.RESULT_AWAY_GOALS] = away_goals
    if played:
        record[layout.RESULT_OUTCOME:layout.RESULT_OUTCOME + 2] = b"\x09\x09"
    return bytes(record)


class FixtureResultTests(unittest.TestCase):
    def test_a_played_result_decodes(self) -> None:
        result = layout.decode_fixture_result(fixture_result())
        self.assertEqual(result["date"], date(2019, 11, 2))
        self.assertEqual((result["home_team"], result["away_team"], result["fixture_name"]), (0x1000, 0x2000, 0x3000))
        self.assertEqual((result["home_goals"], result["away_goals"], result["attendance"]), (2, 2, 344))
        self.assertTrue(result["played"])

    def test_a_scheduled_copy_is_not_played_even_at_nil_nil(self) -> None:
        self.assertFalse(layout.decode_fixture_result(fixture_result(played=False, home_goals=0, away_goals=0))["played"])

    def test_an_impossible_date_is_none(self) -> None:
        self.assertIsNone(layout.decode_fm_date(struct.pack("<HH", 0, 2019)))


class TeamBlockTests(unittest.TestCase):
    def test_the_panel_fields_decode_at_their_offsets(self) -> None:
        block = bytearray(layout.TEAM_BLOCK_SIZE)
        values = {"possession_time": 5131, "goals": 2, "shots": 15, "shots_on_target": 6, "clear_cut_chances": 1,
                  "corners": 3, "fouls": 9, "passes_attempted": 474, "passes_completed": 344,
                  "tackles_attempted": 10, "tackles_won": 8, "headers_attempted": 68, "headers_won": 45}
        for name, offset, fmt in layout.TEAM_FIELDS:
            struct.pack_into(fmt, block, offset, values[name])
        self.assertEqual(layout.decode_team_block(bytes(block)), values)
        self.assertFalse(layout.team_block_is_empty(values))
        self.assertTrue(layout.team_block_is_empty(layout.decode_team_block(bytes(layout.TEAM_BLOCK_SIZE))))


class PlayerRecordTests(unittest.TestCase):
    def record(self, *, short_id=102619, code=0x80, distance=11985.0, shirt=11, side=1, rating=805,
               came_on=0, went_off=0) -> bytes:
        record = bytearray(layout.PLAYER_RECORD_SIZE)
        record[layout.PLAYER_CAME_ON] = came_on
        record[layout.PLAYER_WENT_OFF] = went_off
        struct.pack_into("<I", record, layout.PLAYER_ROLE_CODE, code)
        struct.pack_into("<I", record, layout.PLAYER_SHORT_ID, short_id)
        struct.pack_into("<f", record, layout.PLAYER_DISTANCE, distance)
        struct.pack_into("<H", record, layout.PLAYER_RATING, rating)
        record[layout.PLAYER_SHIRT] = shirt
        record[layout.PLAYER_SIDE] = side
        for value, (_name, offset) in enumerate(layout.PLAYER_FIELDS, start=1):
            record[offset] = value
        return bytes(record)

    def test_a_player_line_decodes(self) -> None:
        player = layout.decode_player_record(self.record())
        self.assertEqual((player["short_id"], player["role_code"], player["shirt"], player["side"]), (102619, 0x80, 11, "away"))
        self.assertEqual((player["rating"], player["played"], player["distance_m"]), (8.05, True, 11985))
        self.assertEqual(player["stats"]["goals"], 1)
        last_field = layout.PLAYER_FIELDS[-1][0]
        self.assertEqual(player["stats"][last_field], len(layout.PLAYER_FIELDS))
        self.assertEqual(set(player["stats"]), {name for name, _offset in layout.PLAYER_FIELDS})

    def test_substitution_minutes_decode(self) -> None:
        starter = layout.decode_player_record(self.record(went_off=63))
        self.assertEqual((starter["came_on"], starter["went_off"]), (None, 63))
        sub = layout.decode_player_record(self.record(came_on=63))
        self.assertEqual((sub["came_on"], sub["went_off"], sub["rating"]), (63, None, 8.05))

    def test_a_player_barely_on_the_pitch_has_no_rating_as_in_fm(self) -> None:
        # FM showed "-" for a 4-minute cameo and a rating after 13 minutes.
        self.assertIsNone(layout.decode_player_record(self.record(came_on=86))["rating"])
        self.assertEqual(layout.decode_player_record(self.record(came_on=77))["rating"], 8.05)

    def test_an_unused_substitute_has_no_rating(self) -> None:
        player = layout.decode_player_record(self.record(code=0, distance=0.0, rating=640))
        self.assertEqual((player["played"], player["rating"]), (False, None))

    def test_empty_squad_places_are_skipped(self) -> None:
        self.assertIsNone(layout.decode_player_record(self.record(short_id=layout.NO_PLAYER)))
        self.assertIsNone(layout.decode_player_record(self.record(shirt=layout.NO_SHIRT)))


class ConsistencyTests(unittest.TestCase):
    def detail(self):
        def player(side, goals=0, shots=0, on=0):
            return {"side": side, "short_id": 1, "rating": 7.0,
                    "stats": {"goals": goals, "shots": shots, "shots_on_target": on}}
        team = {"goals": 1, "shots": 3, "shots_on_target": 2, "possession_time": 5000}
        players = [player(side, 1, 3, 2) for side in ("home", "away")]
        players += [player(side) for side in ("home", "away") for _ in range(10)]
        return {"home": dict(team), "away": dict(team), "players": players}

    def test_a_match_that_adds_up_has_no_problems(self) -> None:
        self.assertEqual(layout.detail_problems(self.detail(), 1, 1), [])

    def test_mismatches_are_reported(self) -> None:
        detail = self.detail()
        detail["home"]["shots"] = 9
        problems = layout.detail_problems(detail, 2, 1)
        self.assertTrue(any("do not match the score" in problem for problem in problems))
        self.assertTrue(any("shots add up to 3, the team shows 9" in problem for problem in problems))


class EventTests(unittest.TestCase):
    def test_a_goal_and_an_unknown_event(self) -> None:
        record = bytearray(layout.EVENT_SIZE)
        record[layout.EVENT_MINUTE], record[layout.EVENT_SIDE], record[layout.EVENT_CODE] = 19, 1, 0x01
        self.assertEqual(layout.decode_event(bytes(record)), {"minute": 19, "side": "away", "kind": "goal", "code": 1})
        record[layout.EVENT_CODE] = 0x16
        self.assertEqual(layout.decode_event(bytes(record))["kind"], "other")


if __name__ == "__main__":
    unittest.main()
