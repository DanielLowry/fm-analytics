import struct
import tempfile
import unittest
import zlib
from datetime import date
from pathlib import Path

from tools import fm20_match_archive as archive

HOME_CLUB, AWAY_CLUB = 8325133, 5103652


def packed_player(short_id: int, shirt: int, side: int, *, shots: int = 0, goals: int = 0,
                  passes=(20, 15), tackles=(2, 1), headers=(3, 2), role_code=0x80, rating=700,
                  came_on=0, went_off=0, corners=0, fouls=1, start=0, centre=0, position=0) -> bytes:
    record = bytearray(archive.RECORD_LENGTH)
    struct.pack_into("<I", record, 0, short_id)
    record[archive.SHIRT], record[archive.SIDE], record[archive.SIDE + 1] = shirt, side, 2
    struct.pack_into("<H", record, archive.START_POSITION, start)
    record[archive.START_CENTRE_SIDE] = centre
    struct.pack_into("<H", record, archive.POSITION, position)
    stats = {"goals": goals, "shots": shots, "shots_on_target": shots, "passes_attempted": passes[0],
             "passes_completed": passes[1], "tackles_attempted": tackles[0], "tackles_won": tackles[1],
             "headers_attempted": headers[0], "headers_won": headers[1], "corners_taken": corners, "fouls": fouls}
    for name, offset in archive.RECORD_FIELDS:
        record[offset] = stats.get(name, 0)
    record[archive.CAME_ON], record[archive.WENT_OFF] = came_on, went_off
    struct.pack_into("<I", record, archive.ROLE_CODE, role_code)
    struct.pack_into("<H", record, archive.RATING, rating)
    struct.pack_into("<f", record, archive.DISTANCE, 10000.0 if role_code else 0.0)
    return b"\x01" + bytes(record)[:-1] + bytes([0]) + bytes(15 * shots)  # the ID is 1 byte in


def team_run(players, *, headers_attempted=None, possession=5000) -> bytes:
    total = lambda key: sum(value for value in (p[key] for p in players))  # noqa: E731
    run = bytearray(7 + 20)
    x = 7
    run[x - 7], run[x - 4] = total("corners"), total("fouls")
    struct.pack_into("<HH", run, x, total("passes_attempted"), total("passes_completed"))
    struct.pack_into("<HH", run, x + 6, total("tackles_attempted"), total("tackles_won"))
    struct.pack_into("<HH", run, x + 10, headers_attempted or total("headers_attempted"), total("headers_won"))
    struct.pack_into("<I", run, x + 16, possession)
    return bytes(run)


def side(side_number: int, *, goals_by_shirt=None, headers_attempted=None, possession=5000):
    goals_by_shirt = goals_by_shirt or {}
    records, figures = [], []
    for shirt in range(1, 17):
        goals = goals_by_shirt.get(shirt, 0)
        started = shirt <= 11
        records.append(packed_player(10_000 * (side_number + 1) + shirt, shirt, side_number,
                                     shots=goals, goals=goals, corners=1 if shirt == 7 else 0,
                                     role_code=0x80 if started or shirt == 12 else 0,
                                     came_on=60 if shirt == 12 else 0))
        figures.append({"corners": 1 if shirt == 7 else 0, "fouls": 1, "passes_attempted": 20, "passes_completed": 15,
                        "tackles_attempted": 2, "tackles_won": 1, "headers_attempted": 3, "headers_won": 2})
    return team_run(figures, headers_attempted=headers_attempted, possession=possession) + b"".join(records)


def chunk(*, home_goals=None, away_goals=None, **away) -> bytes:
    header = b"\x00" * 16 + b"\x01" + struct.pack("<I", HOME_CLUB) + b"\x00" * 8 + b"\x01" + struct.pack("<I", AWAY_CLUB)
    return header + b"\x00" * 64 + side(0, goals_by_shirt=home_goals, possession=5131) + b"\x00" * 32 + side(
        1, goals_by_shirt=away_goals, possession=4739, **away
    )


def archive_file(directory: Path, name: str, chunks) -> Path:
    path = directory / name
    path.write_bytes(b"\x02\x01sbo.\x01\x00\x00" + b"".join(zlib.compress(c) for c in chunks) + b"trailing")
    return path


class ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def test_chunks_are_read_until_the_compressed_data_ends(self) -> None:
        path = archive_file(self.directory, "pks_0.obs", [b"first", b"second"])
        self.assertEqual(list(archive.chunks(path)), [b"first", b"second"])

    def test_a_chunk_decodes_to_players_and_team_figures(self) -> None:
        detail, problems = archive.decode_match(chunk(home_goals={9: 2}, away_goals={10: 1}), 2, 1)
        self.assertEqual(problems, [])
        home = [p for p in detail["players"] if p["side"] == "home"]
        self.assertEqual(len(home), 16)
        self.assertEqual([p["order"] for p in home][:3], [0, 1, 2])
        self.assertTrue(home[10]["started"])
        self.assertFalse(home[11]["started"])
        self.assertEqual((home[11]["came_on"], home[11]["rating"]), (60, 7.0))
        self.assertFalse(home[15]["played"])  # an unused substitute: no role, no rating
        self.assertIsNone(home[15]["rating"])
        self.assertEqual(detail["home"]["possession_time"], 5131)
        self.assertEqual(detail["home"]["shots"], 2)
        self.assertEqual(detail["home"]["corners"], 1)
        self.assertEqual(detail["away"]["goals"], 1)

    def test_positions_decode_as_in_the_live_record(self) -> None:
        body = (b"\x00" * 8
                + packed_player(94381, 10, 1, start=0x4000, centre=0x10, position=0x4000)
                + packed_player(31039, 15, 1, came_on=57, start=0, position=0x8)
                + packed_player(20527, 16, 1, role_code=0, start=0, position=0))
        lines = {p["shirt"]: p for p in archive.players(body)}
        place = lambda p: (p["start_position"], p["start_centre_side"], p["position"])  # noqa: E731
        self.assertEqual(place(lines[10]), ("ST", "left", "ST"))
        self.assertEqual(place(lines[15]), (None, None, "DL"))  # a substitute has no start
        self.assertEqual(place(lines[16]), (None, None, None))  # nor does a player who never came on

    def test_the_teams_own_figures_win_where_they_differ_from_the_players_sums(self) -> None:
        detail, problems = archive.decode_match(chunk(headers_attempted=47), 0, 0)
        self.assertEqual(problems, [])
        self.assertEqual(detail["away"]["headers_attempted"], 47)  # the players' sum is 48

    def test_an_own_goal_is_in_the_score_but_no_players_tally(self) -> None:
        detail, problems = archive.decode_match(chunk(home_goals={9: 1}), 2, 0)
        self.assertEqual(problems, [])
        self.assertEqual(detail["home"]["goals"], 2)

    def test_a_score_the_players_cannot_have_produced_is_rejected(self) -> None:
        detail, problems = archive.decode_match(chunk(home_goals={9: 3}), 1, 0)
        self.assertIsNone(detail)
        self.assertTrue(any("more than" in problem for problem in problems))

    def test_the_clubs_must_appear_home_first(self) -> None:
        body = chunk()
        self.assertTrue(archive.involves(body, HOME_CLUB, AWAY_CLUB))
        self.assertFalse(archive.involves(body, AWAY_CLUB, HOME_CLUB))

    def test_a_fixture_is_filled_only_from_a_single_matching_chunk(self) -> None:
        archive_file(self.directory, "pks_0.obs", [chunk(home_goals={9: 1}), b"not a match"])
        found = archive.find_matches(self.directory, [("m1", date(2019, 8, 3), HOME_CLUB, AWAY_CLUB, 1, 0)])
        self.assertEqual(set(found), {"m1"})
        archive_file(self.directory, "pks_1.obs", [chunk(home_goals={9: 1})])
        self.assertEqual(
            archive.find_matches(self.directory, [("m1", date(2019, 8, 3), HOME_CLUB, AWAY_CLUB, 1, 0)]), {}
        )

    def test_repeat_meetings_with_the_same_score_are_told_apart_by_the_order_played(self) -> None:
        # Two 0-0s at the same ground: only the order in the archive tells them apart.
        archive_file(self.directory, "pks_0.obs", [chunk(headers_attempted=47), b"not a match", chunk(headers_attempted=46)])
        found = archive.find_matches(self.directory, [
            ("second", date(2020, 8, 1), HOME_CLUB, AWAY_CLUB, 0, 0),
            ("first", date(2019, 10, 12), HOME_CLUB, AWAY_CLUB, 0, 0),
        ])
        self.assertEqual(found["first"]["away"]["headers_attempted"], 47)
        self.assertEqual(found["second"]["away"]["headers_attempted"], 46)

    def test_one_chunk_is_never_given_to_two_meetings(self) -> None:
        # A 1-0 also adds up to 2-0 (as an own goal); with one chunk for two meetings, neither gets it.
        archive_file(self.directory, "pks_0.obs", [chunk(home_goals={9: 1})])
        self.assertEqual(archive.find_matches(self.directory, [
            ("first", date(2019, 10, 12), HOME_CLUB, AWAY_CLUB, 1, 0),
            ("second", date(2020, 8, 1), HOME_CLUB, AWAY_CLUB, 2, 0),
        ]), {})

    def test_an_order_the_scores_contradict_is_not_trusted(self) -> None:
        # Archived 0-0 then 1-0, but played 1-0 then 0-0: the 0-0 also fits the 1-0 meeting, so neither is certain.
        archive_file(self.directory, "pks_0.obs", [chunk(), chunk(home_goals={9: 1})])
        self.assertEqual(archive.find_matches(self.directory, [
            ("first", date(2019, 10, 12), HOME_CLUB, AWAY_CLUB, 1, 0),
            ("second", date(2020, 8, 1), HOME_CLUB, AWAY_CLUB, 0, 0),
        ]), {})

    def test_across_files_only_a_chunk_that_fits_one_meeting_is_used(self) -> None:
        # Order means nothing across files: here the later meeting is in the first file.
        archive_file(self.directory, "pks_0.obs", [chunk(away_goals={10: 1})])
        archive_file(self.directory, "pks_1.obs", [chunk(home_goals={9: 1})])
        found = archive.find_matches(self.directory, [
            ("first", date(2019, 10, 12), HOME_CLUB, AWAY_CLUB, 1, 0),
            ("second", date(2020, 8, 1), HOME_CLUB, AWAY_CLUB, 0, 1),
        ])
        self.assertEqual((found["first"]["home"]["shots"], found["first"]["away"]["shots"]), (1, 0))
        self.assertEqual((found["second"]["home"]["shots"], found["second"]["away"]["shots"]), (0, 1))


def shot_group(zone: int, *shots: tuple[float, float, int, int]) -> bytes:
    """One group of a player's shots: zone, count, each shot, then the byte not yet known."""
    body = b"".join(struct.pack("<ff", across, up) + bytes([minute, second, 0x55, 0x0A]) for across, up, minute, second in shots)
    return bytes([zone, len(shots)]) + body + b"\x40"


def shooter(shots: int, groups: bytes) -> tuple[bytes, dict]:
    """A chunk with one player's fixed record, his shot groups, then the next record's leading byte."""
    data = bytes(archive.SHOTS_START) + groups + b"\x01"
    return data, {"at": 0, "side": "home", "short_id": 7, "stats": {"shots": shots}}


def event_record(side: int, place: int, code: int, minute: int, added: int = 0, descriptor: bytes = bytes(8)) -> bytes:
    record = bytearray(archive.EVENT_LENGTH)
    record[0:4] = bytes([1, side, place, code])
    struct.pack_into("<I", record, 4, 243 * minute + 60 * added)
    record[8], record[9] = minute, added
    record[archive.DESCRIPTOR_AT:archive.DESCRIPTOR_AT + 8] = descriptor
    return bytes(record)


def timeline(*records: bytes, count: int | None = None) -> bytes:
    return b"\xff" * 16 + struct.pack("<H", len(records) if count is None else count) + b"".join(records) + b"\x00" * 64


LINE_UPS = [
    {"side": side, "order": order, "short_id": (100 if side == "home" else 200) + order}
    for side in ("home", "away") for order in range(16)
]


class ShotTests(unittest.TestCase):
    def test_shots_are_read_group_by_group_up_to_the_next_record(self) -> None:
        data, player = shooter(3, shot_group(0x04, (-3.339, 1.793, 48, 12))
                                  + shot_group(0x20, (2.35, 3.03, 11, 1), (-2.316, 2.688, 50, 57)))
        self.assertEqual(archive.decode_shots(data, player, len(data) - 1), [
            {"minute": 48, "second": 12, "across": -3.34, "up": 1.79},
            {"minute": 11, "second": 1, "across": 2.35, "up": 3.03},
            {"minute": 50, "second": 57, "across": -2.32, "up": 2.69},
        ])

    def test_shots_that_do_not_end_at_the_next_record_or_fit_the_count_are_refused(self) -> None:
        data, player = shooter(2, shot_group(0x04, (0.5, 0.5, 10, 0), (0.5, 0.5, 20, 0)))
        self.assertIsNone(archive.decode_shots(data, player, len(data)))  # one byte short of where it must end
        self.assertIsNone(archive.decode_shots(data, dict(player, stats={"shots": 1}), None))  # a group of two for one shot
        data, player = shooter(1, shot_group(0x04, (0.5, 0.5, 10, 75)))  # a 75th second
        self.assertIsNone(archive.decode_shots(data, player, None))

    def test_a_match_with_one_undecodable_player_has_no_shots_at_all(self) -> None:
        good, player = shooter(1, shot_group(0x04, (0.5, 0.5, 10, 0)))
        self.assertEqual(len(archive.match_shots(good, [player])), 1)
        self.assertIsNone(archive.match_shots(good, [player, dict(player, at=1, short_id=8)]))


class TimelineTests(unittest.TestCase):
    def test_the_timeline_names_each_player_and_its_goals_give_the_score(self) -> None:
        data = timeline(
            event_record(0, 7, 0x2F, 49),
            event_record(0, 7, 0x01, 49, descriptor=bytes.fromhex("0100080008c00000")),
            event_record(0, 5, 0x24, 49),
            event_record(1, 4, 0x26, 62),
            event_record(1, 0xFF, 0x31, 70),  # a team's own event
            event_record(0, 1, 0x03, 90, added=3),
        )
        events = archive.decode_events(data, LINE_UPS, 2, 0)
        self.assertEqual([(e["minute"], e["addedTime"], e["side"], e["kind"], e.get("playerShortId")) for e in events], [
            (49, 0, "home", "clear_cut_chance", 107), (49, 0, "home", "goal", 107), (49, 0, "home", "assist", 105),
            (62, 0, "away", "yellow_card", 204), (70, 0, "away", "other", None), (90, 3, "home", "penalty", 101),
        ])
        self.assertEqual(events[1]["descriptor"], "0100080008c00000")
        self.assertNotIn("descriptor", events[0])

    def test_an_own_goal_counts_for_the_other_side_and_a_lone_assist_code_is_not_an_assist(self) -> None:
        data = timeline(event_record(0, 9, 0x24, 1), event_record(1, 3, 0x02, 34))
        events = archive.decode_events(data, LINE_UPS, 1, 0)
        self.assertEqual([(e["side"], e["kind"]) for e in events], [("home", "other"), ("away", "own_goal")])

    def test_a_timeline_that_misses_a_goal_or_its_count_or_a_player_is_refused(self) -> None:
        goal = event_record(0, 7, 0x01, 49)
        self.assertIsNone(archive.decode_events(timeline(goal), LINE_UPS, 2, 0))
        self.assertIsNone(archive.decode_events(timeline(goal, count=3), LINE_UPS, 1, 0))
        self.assertIsNone(archive.decode_events(timeline(event_record(0, 30, 0x01, 49)), LINE_UPS, 1, 0))
        self.assertEqual(archive.decode_events(timeline(), LINE_UPS, 0, 0), [])


if __name__ == "__main__":
    unittest.main()
