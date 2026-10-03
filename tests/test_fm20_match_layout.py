import struct
import unittest
from datetime import date

from tools import fm20_match_layout as layout


def fm_date(day: date) -> bytes:
    return struct.pack("<HH", day.timetuple().tm_yday | 0x4A00, day.year)  # high bits are flags


def fixture_result(
    *, played: bool = True, home_goals: int = 2, away_goals: int = 2,
    home_score: bytes | None = None, away_score: bytes | None = None,
) -> bytes:
    """A result record; each side's score is FM's five bytes, 0xff for a stage not played."""
    record = bytearray(layout.FIXTURE_RESULT_SIZE)
    struct.pack_into("<QQ", record, layout.RESULT_HOME_TEAM, 0x1000, 0x2000)
    struct.pack_into("<Q", record, layout.RESULT_FIXTURE_NAME, 0x3000)
    record[layout.RESULT_DATE:layout.RESULT_DATE + 4] = fm_date(date(2019, 11, 2))
    struct.pack_into("<I", record, layout.RESULT_ATTENDANCE, 344)
    record[layout.RESULT_HOME_GOALS:layout.RESULT_HOME_GOALS + 5] = home_score or bytes([home_goals]) + b"\xff" * 4
    record[layout.RESULT_AWAY_GOALS:layout.RESULT_AWAY_GOALS + 5] = away_score or bytes([away_goals]) + b"\xff" * 4
    if played:
        record[layout.RESULT_OUTCOME:layout.RESULT_OUTCOME + 2] = b"\x09\x09"
    return bytes(record)


class FixtureResultTests(unittest.TestCase):
    def test_a_played_result_decodes(self) -> None:
        result = layout.decode_fixture_result(fixture_result())
        self.assertEqual(result["date"], date(2019, 11, 2))
        self.assertEqual((result["home_team"], result["away_team"], result["fixture_name"]), (0x1000, 0x2000, 0x3000))
        self.assertEqual((result["home_goals"], result["away_goals"], result["attendance"]), (2, 2, 344))
        self.assertEqual((result["score_at_90"], result["penalties"]), (None, None))
        self.assertTrue(result["played"])

    def test_the_score_is_after_extra_time_when_it_was_played(self) -> None:
        # Hungerford Town v Slough Town, FA Trophy replay, as FM holds it: 1-1 after 90, 2-1 after extra time.
        result = layout.decode_fixture_result(
            fixture_result(home_score=bytes.fromhex("0102ffffff"), away_score=bytes.fromhex("0101ffffff"))
        )
        self.assertEqual((result["home_goals"], result["away_goals"]), (2, 1))
        self.assertEqual((result["score_at_90"], result["penalties"]), ((1, 1), None))

    def test_a_shootout_is_read_beside_the_score(self) -> None:
        # Al-Jaish 1-1 Lokomotiv Toshkent after extra time, 3-4 on penalties.
        result = layout.decode_fixture_result(
            fixture_result(home_score=bytes.fromhex("010103ffff"), away_score=bytes.fromhex("010104ffff"))
        )
        self.assertEqual((result["home_goals"], result["away_goals"], result["penalties"]), (1, 1, (3, 4)))
        self.assertEqual(result["score_at_90"], (1, 1))

    def test_a_scheduled_copy_is_not_played_even_at_nil_nil(self) -> None:
        self.assertFalse(layout.decode_fixture_result(fixture_result(played=False, home_goals=0, away_goals=0))["played"])

    def test_an_impossible_date_is_none(self) -> None:
        self.assertIsNone(layout.decode_fm_date(struct.pack("<HH", 0, 2019)))


# Concord Rangers 2-2 Hungerford Town as FM holds it (30 September 2026), plus a
# made-up sending-off: 18' away, which does not count in the score.
CONCORD = bytes.fromhex(
    "db90010001001300" "857d010000003f00" "ad70010001004200" "258601000000 5a01".replace(" ", "")
    + "c49d010001031200"
)


class IncidentTests(unittest.TestCase):
    def test_goals_and_a_sending_off_decode_in_match_order(self) -> None:
        incidents = layout.decode_incidents(CONCORD)
        self.assertEqual(
            [(i["minute"], i["addedTime"], i["side"], i["kind"]) for i in incidents],
            [(19, 0, "away", "goal"), (63, 0, "home", "goal"), (66, 0, "away", "goal"),
             (90, 1, "home", "goal"), (18, 0, "away", "sent_off")],
        )
        self.assertEqual(incidents[0]["playerShortId"], 102619)
        self.assertEqual(layout.incident_problems(incidents, 2, 2), [])

    def test_a_list_that_does_not_add_up_or_has_a_new_type_is_reported(self) -> None:
        incidents = layout.decode_incidents(CONCORD)
        self.assertEqual(layout.incident_problems(incidents, 3, 2), ["home has 2 goals listed, the score 3"])
        unknown = bytearray(CONCORD)
        unknown[layout.INCIDENT_TYPE] = 9
        problems = layout.incident_problems(layout.decode_incidents(bytes(unknown)), 2, 2)
        self.assertIn("an incident has a type never seen before", problems)


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
               came_on=0, went_off=0, start=0, centre=0, position=0) -> bytes:
        record = bytearray(layout.PLAYER_RECORD_SIZE)
        record[layout.PLAYER_CAME_ON] = came_on
        record[layout.PLAYER_WENT_OFF] = went_off
        struct.pack_into("<H", record, layout.PLAYER_START_POSITION, start)
        record[layout.PLAYER_START_CENTRE_SIDE] = centre
        struct.pack_into("<H", record, layout.PLAYER_POSITION, position)
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

    def positions(self, **record) -> tuple:
        player = layout.decode_player_record(self.record(**record))
        return player["start_position"], player["start_centre_side"], player["position"]

    def test_where_a_starter_started_and_played_decodes(self) -> None:
        # Fundi, the left-sided Advanced Forward, and a right-back.
        self.assertEqual(self.positions(start=0x4000, centre=0x10, position=0x4000), ("ST", "left", "ST"))
        self.assertEqual(self.positions(start=0x400, centre=0x20, position=0x400), ("MC", "right", "MC"))
        self.assertEqual(self.positions(start=0x4, position=0x4), ("DR", None, "DR"))

    def test_a_substitute_has_a_position_played_but_no_start(self) -> None:
        self.assertEqual(self.positions(came_on=60, position=0x8), (None, None, "DL"))

    def test_a_starter_can_end_somewhere_else(self) -> None:
        self.assertEqual(self.positions(start=0x200, position=0x400), ("ML", None, "MC"))

    def test_anything_but_one_known_position_is_left_unknown(self) -> None:
        self.assertEqual(self.positions(start=0x4400, position=0x4400), (None, None, None))  # two bits
        self.assertEqual(self.positions(start=0x8000, position=0x8000), (None, None, None))  # beyond ST
        self.assertEqual(self.positions(start=0x4000, centre=0x27, position=0x4000), ("ST", None, "ST"))

    def test_a_player_who_never_came_on_has_no_position(self) -> None:
        self.assertEqual(self.positions(code=0, distance=0.0, start=0x4000, position=0x4000), (None, None, None))


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
