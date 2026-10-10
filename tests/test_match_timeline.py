import unittest

from fm_analytics.analytics.goal_descriptions import describe_goal
from fm_analytics.analytics.match_timeline import build_timeline
from fm_analytics.domain.matches import MatchRecord

from tests.match_support import ALPHA, US, detail, lineup, match, team_stats


def event(minute, side, kind, code, player=None, added=0, descriptor=None):
    found = {"minute": minute, "side": side, "kind": kind, "code": code}
    if descriptor:
        found["descriptor"] = descriptor
    if added:
        found["addedTime"] = added
    if player is not None:
        found["playerShortId"] = player
    return found


def shot(side, player, minute, second, across, up):
    return {"side": side, "playerShortId": player, "minute": minute, "second": second, "across": across, "up": up}


# Line-up short IDs: home order n is 1000 + n, away order n is 1500 + n.
STRIKER, WINGER, THEIR_STRIKER, THEIR_BACK = 1010, 1008, 1510, 1503


def record(events, shots=(), formations=None, home_goals=2, away_goals=1) -> MatchRecord:
    found = detail(
        home=team_stats(goals=home_goals), away=team_stats(goals=away_goals),
        players=lineup("home") + lineup("away"), events=events,
    )
    found["shots"] = list(shots)
    if formations:
        found["formations"] = formations
    return MatchRecord.from_document(match("2019-09-01", US, ALPHA, home_goals, away_goals, detail=found))


class TimelineTests(unittest.TestCase):
    def test_a_goal_carries_its_assist_and_the_chance_it_came_from(self) -> None:
        timeline = build_timeline(record([
            event(30, "home", "clear_cut_chance", 0x2F, STRIKER),
            event(30, "home", "goal", 0x01, STRIKER),
            event(30, "home", "assist", 0x24, WINGER),
            event(60, "away", "clear_cut_chance", 0x2F, THEIR_STRIKER),
        ], home_goals=1, away_goals=0), "home")
        goal, chance = timeline.entries
        self.assertEqual((goal.label, goal.player, goal.assisted_by, goal.from_clear_cut_chance, goal.ours),
                         ("Goal", "Home 11", "Home 9", True, True))
        self.assertEqual((chance.label, chance.player, chance.ours), ("Clear-cut chance", "Away 11", False))
        self.assertTrue(timeline.named)

    def test_a_sending_off_is_told_once_and_an_own_goal_counts_for_the_other_side(self) -> None:
        timeline = build_timeline(record([
            event(20, "away", "yellow_card", 0x26, THEIR_BACK),
            event(44, "away", "own_goal", 0x02, THEIR_BACK),
            event(45, "away", "second_yellow", 0x0E, THEIR_BACK, added=2),
            event(45, "away", "sent_off", 0x05, THEIR_BACK, added=2),
            event(70, "home", "other", 0x28, STRIKER),
        ], home_goals=1, away_goals=0), "home")
        self.assertEqual(
            [(entry.clock, entry.label, entry.player, entry.ours) for entry in timeline.entries],
            [("20", "Booked", "Away 4", False), ("44", "Own goal", "Away 4", True),
             ("45+2", "Sent off (second booking)", "Away 4", False)],
        )

    def test_each_goal_is_its_scorers_shot_on_goal_nearest_its_minute(self) -> None:
        timeline = build_timeline(record(
            [event(49, "home", "goal", 0x01, STRIKER), event(52, "home", "penalty", 0x03, STRIKER),
             event(90, "away", "goal", 0x01, THEIR_STRIKER, added=2)],
            shots=[
                shot("home", STRIKER, 20, 1, 0.5, 1.0),   # on goal, but far from either goal: saved
                shot("home", STRIKER, 48, 12, -3.34, 1.79),
                shot("home", STRIKER, 51, 20, -3.23, 0.35),
                shot("home", WINGER, 51, 40, 8.6, 1.7),
                shot("away", THEIR_STRIKER, 91, 3, 0.0, 0.4),
                shot("away", THEIR_STRIKER, 92, 0, 0.0, 3.4),
            ],
        ), "home")
        self.assertEqual(
            [(entry.clock, entry.ours, entry.player, entry.outcome) for entry in timeline.shots],
            [("21", True, "Home 11", "on_goal"), ("49", True, "Home 11", "goal"), ("52", True, "Home 11", "goal"),
             ("52", True, "Home 9", "wide"), ("90+2", False, "Away 11", "goal"), ("90+3", False, "Away 11", "over")],
        )
        self.assertEqual((timeline.ours.shots, timeline.ours.on_goal, timeline.ours.wide, timeline.ours.first_half),
                         (4, 3, 1, 1))
        self.assertEqual((timeline.theirs.on_goal, timeline.theirs.over, timeline.theirs.second_half), (1, 1, 2))

    def test_the_opposition_formation_is_theirs_whichever_side_we_were(self) -> None:
        match = record([], formations={"away": "4-3-3 Narrow"}, home_goals=0, away_goals=0)
        self.assertEqual(build_timeline(match, "home").opponent_formation, "4-3-3 Narrow")
        self.assertIsNone(build_timeline(match, "away").opponent_formation)

    def test_a_timeline_read_from_the_live_match_alone_names_nobody(self) -> None:
        timeline = build_timeline(record([event(12, "home", "goal", 0x01)], home_goals=1, away_goals=0), "home")
        self.assertEqual([(entry.label, entry.player) for entry in timeline.entries], [("Goal", None)])
        self.assertFalse(timeline.named)
        self.assertIsNone(timeline.ours)  # no shots were read


class GoalDescriptionTests(unittest.TestCase):
    """The goals the manager read off FM's replays, and the season-wide patterns."""

    def test_the_goals_read_off_fms_replays(self) -> None:
        for descriptor, words in (
            ("0140000002a00000", "Shot in the area, from a cross"),  # Neufville 3′ v Chippenham, right foot
            ("0180001008200100", "Shot on the edge of the area"),  # Chambers 53′, just inside the area
            ("0340400002400000", "Header in the area, from a cross"),  # Holden 2′ at Hayes
            ("0340000001400000", "Header in the six-yard box, from a cross"),  # Okosieme 60′ v Chippenham
            ("0108010000c40800", "Direct free kick from outside the area"),  # Ashby 72′ v Chippenham
            ("0350000002c00000", "Header in the area, from a cross"),  # Zebroski 73′: open play, not a set piece
            ("0540000002e00000", "Volley in the area, from a cross"),  # Ekongo 45+1′ at Hayes, right foot
        ):
            self.assertEqual(describe_goal(descriptor).text, words)

    def test_penalties_and_unknown_areas(self) -> None:
        penalty = describe_goal("0120000002800000")
        self.assertEqual((penalty.how, penalty.text), ("penalty", "Penalty in the area"))
        unknown_area = describe_goal("0110000004000000")
        self.assertEqual((unknown_area.strike, unknown_area.area, unknown_area.text), ("shot", None, "Shot"))
        self.assertIsNone(describe_goal(None))

    def test_a_goal_in_the_timeline_says_how_and_an_offside_goal_is_ruled_out(self) -> None:
        timeline = build_timeline(record([
            event(3, "home", "goal", 0x01, STRIKER, descriptor="0140000002a00000"),
            event(40, "home", "offside_goal", 0x29, WINGER),
            event(52, "home", "penalty", 0x03, STRIKER, descriptor="0120000002800000"),
        ], home_goals=2, away_goals=0), "home")
        goal, offside, penalty = timeline.entries
        self.assertEqual(goal.how.text, "Shot in the area, from a cross")
        self.assertEqual((offside.label, offside.player, offside.how), ("Goal ruled out for offside", "Home 9", None))
        self.assertIsNone(penalty.how)  # "Penalty scored" says it all


class CornerGuessTests(unittest.TestCase):
    def test_a_cross_from_this_matchs_corner_taker_is_only_ever_a_guess_at_a_corner(self) -> None:
        found = detail(
            home=team_stats(goals=2), away=team_stats(goals=0),
            players=lineup("home", o8={"corners_taken": 6}) + lineup("away"),
            events=[
                event(20, "home", "goal", 0x01, STRIKER, descriptor="0340000001400000"),  # header from a cross
                event(20, "home", "assist", 0x24, WINGER),  # who took the corners
                event(60, "home", "goal", 0x01, 1009, descriptor="0340000001400000"),
                event(60, "home", "assist", 0x24, 1005),  # took none
            ],
        )
        timeline = build_timeline(MatchRecord.from_document(match("2019-09-01", US, ALPHA, 2, 0, detail=found)), "home")
        self.assertEqual([entry.possibly_from_a_corner for entry in timeline.entries], [True, False])
