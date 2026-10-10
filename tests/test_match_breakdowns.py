import unittest

from fm_analytics.analytics.match_breakdowns import breakdowns, score_split
from fm_analytics.domain.matches import MatchRecord

from tests.match_support import ALPHA, BRAVO, US, detail, lineup, match, team_stats

# Line-up short IDs: home order n is 1000 + n, away order n is 1500 + n.
STRIKER, THEIR_STRIKER, THEIR_BACK = 1010, 1510, 1503


def shot(side, player, minute, second, across=0.0, up=0.5):
    return {"side": side, "playerShortId": player, "minute": minute, "second": second, "across": across, "up": up}


def goal(minute, side, player, *, kind="goal", added=0):
    return {"minute": minute, "addedTime": added, "side": side, "kind": kind, "playerShortId": player, "player": None}


def record(*, home_goals, away_goals, incidents, shots, events=(), formations=None, away=ALPHA) -> MatchRecord:
    found = detail(home=team_stats(goals=home_goals, shots=7, clear_cut_chances=1),
                   away=team_stats(goals=away_goals, shots=9, clear_cut_chances=2),
                   players=lineup("home") + lineup("away"), events=list(events))
    found["shots"] = list(shots)
    if formations:
        found["formations"] = formations
    document = match("2019-09-01", US, away, home_goals, away_goals, detail=found)
    document["incidents"] = list(incidents)
    return MatchRecord.from_document(document)


class ScoreSplitTests(unittest.TestCase):
    def test_a_match_behind_from_the_fifth_minute_is_split_at_that_goal_and_the_goals_own_shot_counts_before_it(self) -> None:
        early = record(
            home_goals=0, away_goals=1,
            incidents=[goal(5, "away", THEIR_STRIKER)],
            shots=[shot("away", THEIR_STRIKER, 4, 20), shot("home", STRIKER, 13, 0, across=6.0),
                   shot("away", THEIR_STRIKER, 62, 5, up=3.2)],
            events=[{"minute": 30, "side": "home", "kind": "clear_cut_chance", "code": 47, "playerShortId": STRIKER}],
        )
        split = score_split(early, "home")
        level, behind = split.by_state["level"], split.by_state["behind"]
        self.assertEqual((round(level.minutes), level.shots, level.on_goal, level.goals), (5, [0, 1], [0, 1], [0, 1]))
        self.assertEqual((behind.shots, behind.on_goal, behind.clear_cut_chances, behind.goals), ([1, 1], [0, 0], [1, 0], [0, 0]))
        self.assertEqual(split.by_state["ahead"].minutes, 0)
        self.assertEqual(split.by_period["1–15"].shots, [1, 1])
        self.assertEqual(split.by_period["61–75"].shots, [0, 1])

    def test_without_shots_or_with_untimed_goals_there_is_no_split(self) -> None:
        self.assertIsNone(score_split(record(home_goals=0, away_goals=0, incidents=[], shots=[]), "home"))
        self.assertIsNone(score_split(record(home_goals=1, away_goals=0, incidents=[], shots=[shot("home", STRIKER, 3, 0)]), "home"))


class BreakdownTests(unittest.TestCase):
    def test_a_run_of_matches_is_split_by_score_goal_type_formation_and_player_leaving_red_cards_out(self) -> None:
        won = record(
            home_goals=1, away_goals=0, formations={"away": "4-3-3 Narrow"},
            incidents=[goal(20, "home", STRIKER)],
            shots=[shot("home", STRIKER, 19, 30), shot("home", STRIKER, 70, 0, across=5.0),
                   shot("away", THEIR_STRIKER, 80, 0, up=3.0)],
            events=[
                {"minute": 20, "side": "home", "kind": "goal", "code": 1, "playerShortId": STRIKER,
                 "descriptor": "0340000001400000"},
                {"minute": 55, "side": "away", "kind": "yellow_card", "code": 0x26, "playerShortId": THEIR_BACK},
                {"minute": 60, "side": "home", "kind": "yellow_card", "code": 0x26, "playerShortId": STRIKER},
            ],
        )
        red = record(
            home_goals=0, away_goals=1, away=BRAVO, formations={"away": "4-3-3 Narrow"},
            incidents=[goal(10, "away", THEIR_STRIKER, kind="penalty"),
                       {"minute": 50, "addedTime": 0, "side": "home", "kind": "sent_off", "playerShortId": 1003}],
            shots=[shot("away", THEIR_STRIKER, 9, 0)],
            events=[{"minute": 10, "side": "away", "kind": "penalty", "code": 3, "playerShortId": THEIR_STRIKER,
                     "descriptor": "0120000002800000"}],
        )
        found = breakdowns([won, red], US["id"])
        self.assertEqual((found.split_matches, found.left_out), (1, {"a sending-off": 1}))
        self.assertEqual(found.by_state["ahead"].shots, [1, 1])
        self.assertEqual(dict(found.goals_for["how"]), {"cross": 1})
        self.assertEqual(dict(found.goals_for["strike"]), {"header": 1})
        self.assertEqual(dict(found.goals_against["how"]), {"penalty": 1})
        (narrow,) = found.formations
        self.assertEqual((narrow.formation, narrow.played, narrow.won, narrow.lost, narrow.shots), ("4-3-3 Narrow", 2, 1, 1, (14, 18)))
        striker = found.players["Home 11"]
        self.assertEqual((striker.yellow_cards, striker.shots_on_goal, striker.shots_wide, striker.headers), (1, 1, 1, 1))
        self.assertNotIn("Away 4", found.players)  # only our players


if __name__ == "__main__":
    unittest.main()
