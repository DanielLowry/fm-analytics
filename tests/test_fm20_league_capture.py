import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fm_analytics.domain import AttributeObservation, Club, GameState, Manager, Squad, Visibility
from fm_analytics.domain.leagues import LeagueCapture, LeagueRoster
from fm_analytics.domain.matches import Competition
from tools import fm20_league_capture as capture
from tools.fm20_linux_probe import POSITION_CODES, decode_positions
from tools.fm20_visible_positions import (
    POSITION_THRESHOLD_RVA,
    PositionReadError,
    read_position_threshold,
    visible_positions,
)


def ratings(**values):
    return bytes(values.get(code, 1) for code in POSITION_CODES)


class VisiblePositionTests(unittest.TestCase):
    def test_full_knowledge_matches_the_owned_squad_rule_including_its_fallback(self):
        for row in (ratings(DC=20, DR=12, DM=10), ratings(ST=9, AMC=8)):
            self.assertEqual(visible_positions(row, 1), decode_positions(row))

    def test_partial_knowledge_shows_only_what_fm_shows(self):
        # Luke Moore, Dorking Wanderers, 3 October 2026: FM answered 16.
        row = ratings(ML=15, MC=15, AML=20, AMC=20, AMR=18, ST=16)
        self.assertEqual(visible_positions(row, 16), ("AML", "AMC", "AMR", "ST"))

    def test_unknown_player_shows_natural_positions_only(self):
        # Adam Mann's case: Accomplished positions were shown as Ineffectual.
        row = ratings(AML=20, AMC=16, AMR=16, ST=20)
        self.assertEqual(visible_positions(row, 18), ("AML", "ST"))

    def test_no_shown_position_is_position_needed_not_the_hidden_best(self):
        self.assertEqual(visible_positions(ratings(MC=17, DM=15), 18), ())

    def test_impossible_ratings_fail_closed(self):
        for row in (b"\x14" * 14, bytes([21] + [1] * 14)):
            with self.assertRaises(PositionReadError):
                visible_positions(row, 1)

    def test_threshold_comes_from_fms_function_for_the_active_manager(self):
        calls = []

        class Box:
            module_base = 0x140000000

            def __init__(self, answer):
                self.answer = answer

            def call(self, *args):
                calls.append(args)
                return 0x1200 | self.answer  # only the low byte is FM's answer

        self.assertEqual(read_position_threshold(Box(16), 0xAAA, 0xBBB), 16)
        self.assertEqual(calls[0], (0x140000000 + POSITION_THRESHOLD_RVA, 0xAAA, 1, 0xBBB))
        with self.assertRaises(PositionReadError):
            read_position_threshold(Box(12), 0xAAA, 0xBBB)


class FakeMemory:
    fd, module_base = 7, 0x140000000

    def __init__(self, words, kinds=None):
        self.words, self.kinds = words, kinds or {}

    def u64(self, address):
        return self.words.get(address, 0)

    def read(self, address, size):
        return bytes([self.kinds.get(address, 0)]) + bytes(size - 1)


class MembershipTests(unittest.TestCase):
    def members(self, memory, managed=0x100):
        with patch.object(capture.probe, "read_pointer_collection", return_value=(0x100, 0x200, 0x300, 0x400, 0)):
            return capture.league_members(memory, managed)

    def test_every_first_team_linked_to_our_league_is_a_participant(self):
        league = capture.TEAM_LEAGUE
        memory = FakeMemory({0x100 + league: 0xC0, 0x200 + league: 0xC0, 0x300 + league: 0xC0, 0x400 + league: 0xD0},
                            kinds={0x300 + capture.TEAM_KIND: 9})  # 0x300 is a reserve side
        self.assertEqual(self.members(memory), (0xC0, (0x100, 0x200)))

    def test_no_league_or_missing_managed_team_is_refused(self):
        with self.assertRaises(capture.LeagueCaptureError):
            self.members(FakeMemory({}))
        with self.assertRaises(capture.LeagueCaptureError):
            self.members(FakeMemory({0x100 + capture.TEAM_LEAGUE: 0xC0}), managed=0x900)

    def test_played_results_cross_check_only_this_leagues_fixtures(self):
        comp = capture.layout.FIXTURE_NAME_COMP
        memory = FakeMemory({0x10 + comp: 0xC0, 0x20 + comp: 0xE0})
        rows = {1: {"fixture_name": 0x10, "home_team": 0x100, "away_team": 0x200},
                2: {"fixture_name": 0x20, "home_team": 0x100, "away_team": 0x900}}  # a cup tie
        self.assertEqual(capture.played_league_teams(rows, memory, 0xC0), {0x100, 0x200})

    def test_a_played_club_missing_from_the_link_marks_membership_incomplete(self):
        self.assertTrue(capture.membership_evidence((1, 2, 3), {1, 2})[0])
        self.assertTrue(capture.membership_evidence((1, 2, 3), set())[0])  # preseason
        complete, text = capture.membership_evidence((1, 2), {1, 2, 3})
        self.assertFalse(complete)
        self.assertIn("may be incomplete", text)

    def test_season_label_follows_the_english_calendar(self):
        self.assertEqual(capture.season_label(date(2020, 5, 28)), "2019/20")
        self.assertEqual(capture.season_label(date(2020, 8, 1)), "2020/21")


ALPHA, BETA = ratings(DC=20, DR=16, DM=13), ratings(ST=20, AMC=17)


class SquadReadTests(unittest.TestCase):
    def test_ordinary_and_staff_role_players_count_and_placeholders_do_not(self):
        vector = {0x500 + 8 * index: interface for index, interface in enumerate((0x2001, 0x3001, 0x4001))}
        memory = FakeMemory({0x700 + 0x38: 0x500, 0x700 + 0x40: 0x518, **vector})
        people = {0x2001: 0x2001 + 0x1C8, 0x3001: 0x3001 + 0x2A0}  # 0x4001: a virtual placeholder

        def person(fd, interface):
            if interface not in people:
                raise OSError("not a person")
            return people[interface]

        with (
            patch.object(capture, "_person", side_effect=person),
            patch.object(FakeMemory, "read", lambda self, address, size: (address - 0xC).to_bytes(4, "little")),
            patch.object(capture, "_valid_player_interface", return_value=True),
        ):
            players, placeholders = capture.read_squad(memory, 0x700)
        # The fake read gives each person's own address as his ID.
        self.assertEqual(players, {people[0x2001]: 0x2001, people[0x3001]: 0x3001})
        self.assertEqual(placeholders, 1)

    def test_a_player_listed_twice_is_refused(self):
        memory = FakeMemory({0x700 + 0x38: 0x500, 0x700 + 0x40: 0x510, 0x500: 0x2001, 0x508: 0x2009})
        with (
            patch.object(capture, "_person", return_value=0x9000),
            patch.object(FakeMemory, "read", lambda self, address, size: (5).to_bytes(4, "little")),
            patch.object(capture, "_valid_player_interface", return_value=True),
            self.assertRaises(capture.LeagueCaptureError),
        ):
            capture.read_squad(memory, 0x700)


class RivalRosterTests(unittest.TestCase):
    def roster(self, interfaces, visible, placeholders=0):
        identities = {0x2001: ("Alpha One", date(1995, 1, 1), 25), 0x2002: ("Beta Two", None, None)}

        def identity(fd, person, as_of):
            if person - 0x1C8 not in identities:
                raise OSError("unreadable person")
            return identities[person - 0x1C8]

        with (
            patch.object(capture, "_person", side_effect=lambda fd, interface: interface + 0x1C8),
            patch.object(capture, "read_identity", side_effect=identity),
        ):
            return capture.rival_roster(7, Club("77", "Rivals FC"), interfaces, placeholders, date(2020, 5, 28), visible)

    def test_players_carry_only_what_fm_shows_and_unknown_readiness(self):
        known = {"pace": AttributeObservation(Visibility.RANGE, minimum=8, maximum=12)}
        roster = self.roster({1: 0x2001, 2: 0x2002}, {1: (known, 16, ALPHA), 2: ({}, 18, BETA)}, placeholders=2)
        alpha, beta = roster.squad.players
        self.assertEqual((alpha.id, alpha.positions, alpha.age), ("1", ("DC", "DR"), 25))  # DM 13 hidden
        self.assertEqual(beta.positions, ("ST",))
        for player in (alpha, beta):
            self.assertEqual(player.availability, "unknown")
            self.assertIsNone(player.condition_percent)
            self.assertEqual(player.position_familiarity, {})
        self.assertEqual(alpha.attributes, known)
        self.assertTrue(roster.roster_complete and roster.positions_complete)
        self.assertIn("1 natural-only, 1 partial", roster.evidence)
        self.assertIn("2 virtual placeholder(s) FM does not show left out", roster.evidence)

    def test_unreadable_member_or_missed_sandbox_read_is_explicit(self):
        roster = self.roster({1: 0x2001, 3: 0x2003}, {})
        self.assertFalse(roster.roster_complete)
        self.assertFalse(roster.positions_complete)
        (only,) = roster.squad.players
        self.assertEqual((only.attributes, only.positions), ({}, ()))
        self.assertEqual(len(roster.errors), 2)

    def test_rival_rosters_pass_the_league_contract(self):
        game = GameState(date(2020, 5, 28), Manager("m", "Manager"), Club("1", "Ours"))
        ours = LeagueRoster(Squad(Club("1", "Ours"), game.game_date, ()), True, True, "Our first team")
        rival = self.roster({1: 0x2001, 2: 0x2002}, {1: ({}, 1, ALPHA), 2: ({}, 18, BETA)})
        document = LeagueCapture("club:1", game, "2019/20", Competition("5", "League"), True, "link",
                                 "manager-visible", (ours, rival)).to_document()
        self.assertEqual(LeagueCapture.from_document(document).teams[1], rival)

    def test_capture_file_is_replaced_whole(self):
        game = GameState(date(2020, 5, 28), Manager("m", "Manager"), Club("1", "Ours"))
        league = LeagueCapture("club:1", game, "2019/20", Competition("5", "League"), False, "link",
                               "manager-visible", ())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "league.json"
            output.write_text("old", encoding="utf-8")
            capture.write_capture(league, output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["saveKey"], "club:1")
            self.assertEqual([path.name for path in Path(directory).iterdir()], ["league.json"])


if __name__ == "__main__":
    unittest.main()
