"""The match capture's choice of which results and fixtures to read, without FM: memory is faked."""

import struct
import unittest
from datetime import date

from tools import fm20_match_layout as layout
from tools import fm20_club_matches as club_matches

from tests.test_fm20_match_layout import fm_date

US, ALPHA, BRAVO, CUP_SIDE, RESERVES = 0x10, 0x20, 0x30, 0x40, 0x50
LEAGUE, CUP, FRIENDLY = 0x100, 0x200, 0x300


def result(day: int, home: int, away: int, fixture_name: int, season: int | None = 2020) -> dict:
    return {"date": date(2020, 9, day), "home_team": home, "away_team": away, "fixture_name": fixture_name,
            "season": season}


class LeagueClubsResultsTests(unittest.TestCase):
    def test_every_competitive_match_of_the_other_league_teams_and_none_of_ours(self) -> None:
        results = {
            ("ours", 1): result(1, US, ALPHA, LEAGUE),
            ("ours", 2): result(8, BRAVO, US, LEAGUE),
            ("league", 1): result(1, BRAVO, ALPHA, LEAGUE),
            ("cup", 1): result(4, CUP_SIDE, ALPHA, CUP),
            ("friendly", 1): result(5, ALPHA, RESERVES, FRIENDLY, season=None),
            ("elsewhere", 1): result(5, CUP_SIDE, RESERVES, CUP),
        }
        competitions = {LEAGUE: {}, CUP: {}}
        self.assertEqual(sorted(club_matches.league_clubs_results(results, competitions, US)), [("cup", 1), ("league", 1)])


class FakeMemory:
    """Scheduled fixtures at made-up addresses, read as FM's memory would give them."""

    def __init__(self, records: dict[int, bytes]):
        self.records = records

    def instances(self, rva: int) -> list[int]:
        return list(self.records) if rva == layout.FIXTURE else []

    def read(self, address: int, size: int) -> bytes:
        return self.records[address][:size]


def fixture(day: date, home: int, away: int) -> bytes:
    record = bytearray(layout.FIXTURE_SIZE)
    struct.pack_into("<QQ", record, layout.RESULT_HOME_TEAM, home, away)
    struct.pack_into("<Q", record, layout.RESULT_FIXTURE_NAME, LEAGUE)
    struct.pack_into("<H", record, layout.RESULT_SEASON, 2020)
    record[layout.RESULT_DATE:layout.RESULT_DATE + 4] = fm_date(day)
    return bytes(record)


class ScheduledFixtureTests(unittest.TestCase):
    def test_our_fixtures_once_each_without_those_already_played_or_other_clubs(self) -> None:
        memory = FakeMemory({
            1: fixture(date(2020, 10, 20), ALPHA, US),  # played: it has a result
            2: fixture(date(2020, 10, 24), US, BRAVO),
            3: fixture(date(2020, 10, 24), US, BRAVO),  # a second copy
            4: fixture(date(2020, 10, 24), ALPHA, CUP_SIDE),
        })
        found = club_matches.scheduled_fixtures(memory, US, {(date(2020, 10, 20), ALPHA, US)})
        self.assertEqual(list(found), [(date(2020, 10, 24), US, BRAVO)])
        self.assertEqual(found[(date(2020, 10, 24), US, BRAVO)]["season"], 2020)


if __name__ == "__main__":
    unittest.main()
