"""Result against the chances, from fixtures whose rates are easy to work out by hand.

In every baseline match each side has two clear-cut chances (one scored, one
saved) and eight other shots (one scored, three saved, four wide), so a
clear-cut chance is worth 0.5 and is always on goal, where half go in; any other
shot is worth 0.125, half are on goal, and a quarter of those go in.
"""

import json
import unittest
from datetime import date, timedelta

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.match_analysis import ReviewFilters, review_matches
from fm_analytics.analytics.chance_value import (
    PENALTY_VALUE,
    ChanceRates,
    ClassifiedShot,
    KindRecord,
    classify_shots,
    goal_chances,
)
from fm_analytics.analytics.match_chances import PATTERN_ODDS
from fm_analytics.analytics.single_match_diagnosis import diagnose_one_match
from fm_analytics.analytics.match_diagnostics import diagnose_matches
from fm_analytics.web.season_chances_render import season_chances_section
from fm_analytics.domain.matches import MatchCapture, MatchRecord, TeamRef
from fm_analytics.match_ingest import format_match_diagnosis

from tests.match_support import ALPHA, FRIENDLY, LEAGUE, US, capture_document, detail, lineup, match, team_stats

STRIKER, THEIR_STRIKER = 1010, 1510
WHERE = {"on": (0.5, 1.0), "wide": (6.0, 0.5), "over": (0.0, 4.0)}
BASE = {"ccc_scored": 1, "ccc_saved": 1, "other_scored": 1, "other_saved": 3, "other_wide": 4}


def _side(side: str, player: int, *, ccc_scored=0, ccc_saved=0, ccc_wide=0, other_scored=0,
          other_saved=0, other_wide=0, penalties=0):
    """One side's shots and timeline, each shot five minutes after the last, every goal timed to its shot."""
    shots, events = [], []
    goals = on_target = chances = 0
    plan = (
        [("penalty", "on", True)] * penalties
        + [("ccc", "on", True)] * ccc_scored + [("ccc", "on", False)] * ccc_saved + [("ccc", "wide", False)] * ccc_wide
        + [("other", "on", True)] * other_scored + [("other", "on", False)] * other_saved
        + [("other", "wide", False)] * other_wide
    )
    for index, (kind, where, scored) in enumerate(plan):
        minute = 5 + 5 * index
        across, up = WHERE[where]
        # The match clock's minute is FM's minute less one.
        shots.append({"side": side, "playerShortId": player, "minute": minute - 1, "second": 0, "across": across, "up": up})
        if kind != "other":
            chances += 1
            events.append({"minute": minute, "side": side, "kind": "clear_cut_chance", "code": 0x2F, "playerShortId": player})
        if scored:
            goals += 1
            events.append({"minute": minute, "side": side, "kind": "penalty" if kind == "penalty" else "goal",
                           "code": 3 if kind == "penalty" else 1, "playerShortId": player})
        on_target += where == "on"
    return shots, events, goals, on_target, chances


def chance_match(day: str, ours: dict, theirs: dict, *, competition=LEAGUE) -> dict:
    home_shots, home_events, home_goals, home_on, home_chances = _side("home", STRIKER, **ours)
    away_shots, away_events, away_goals, away_on, away_chances = _side("away", THEIR_STRIKER, **theirs)
    found = detail(
        home=team_stats(goals=home_goals, shots=len(home_shots), shots_on_target=home_on, clear_cut_chances=home_chances),
        away=team_stats(goals=away_goals, shots=len(away_shots), shots_on_target=away_on, clear_cut_chances=away_chances),
        players=lineup("home") + lineup("away"),
        events=home_events + away_events,
    )
    found["shots"] = sorted(home_shots + away_shots, key=lambda shot: shot["minute"])
    return match(day, US, ALPHA, home_goals, away_goals, competition=competition, detail=found)


def baseline(count: int = 12, ours: dict = BASE, theirs: dict = BASE) -> list[dict]:
    return [
        chance_match((date(2019, 9, 2) + timedelta(days=index)).isoformat(), ours, theirs) for index in range(count)
    ]


def judged(matches: list[dict], target: dict):
    """The target's diagnosis against the competitive review of everything else."""
    capture = MatchCapture.from_document(capture_document(matches + [target], game_date="2019-10-20"))
    club = TeamRef(US["id"], US["name"])

    def review(scope: str):
        return review_matches(
            capture.matches, capture.league_results, club, catalogue=MVP_CATALOGUE,
            filters=ReviewFilters(competitions=scope),
        )

    summary = next(row for row in review("all").matches if row.match.date.isoformat() == target["date"])
    return diagnose_one_match(review("competitive"), summary)


UNLUCKY = {"ccc_saved": 3, "ccc_wide": 1, "other_saved": 4, "other_wide": 4}  # twelve shots worth 3.0, no goal
SNATCHED = {"other_scored": 1, "other_wide": 3}  # four shots worth 0.5, one goal


class ClassificationTests(unittest.TestCase):
    def test_each_shot_gets_its_kind_and_a_missed_chance_its_own_shot(self) -> None:
        record = MatchRecord.from_document(chance_match("2019-10-01", {"ccc_scored": 1, "ccc_wide": 1, "penalties": 1}, {}))
        shots = classify_shots(record)
        self.assertEqual(
            [(shot.kind, shot.heading, shot.goal) for shot in shots],
            [("penalty", "on_goal", True), ("clear_cut", "on_goal", True), ("clear_cut", "wide", False)],
        )

    def test_shots_that_do_not_account_for_the_match_are_refused(self) -> None:
        document = chance_match("2019-10-01", {"other_scored": 1}, {})
        document["detail"]["home"]["shots"] = 2  # FM's panel counts a shot the list doesn't have
        self.assertIsNone(classify_shots(MatchRecord.from_document(document)))
        document = chance_match("2019-10-01", {"other_scored": 1}, {})
        document["detail"]["shots"] = []
        self.assertIsNone(classify_shots(MatchRecord.from_document(document)))


class GoalChanceTests(unittest.TestCase):
    def test_goal_chances_add_up_each_shot_on_its_own(self) -> None:
        rates = ChanceRates(10, KindRecord(10, 10, 5), KindRecord(8, 4, 1))
        shot = ClassifiedShot("home", 1, "clear_cut", "on_goal", False, "10")
        for found, expected in zip(goal_chances([shot, shot], rates), [0.25, 0.5, 0.25], strict=True):
            self.assertAlmostEqual(found, expected)
        penalty = ClassifiedShot("home", 1, "penalty", "on_goal", True, "10")
        for found, expected in zip(goal_chances([penalty], rates), [1 - PENALTY_VALUE, PENALTY_VALUE], strict=True):
            self.assertAlmostEqual(found, expected)


class ResultVsChancesTests(unittest.TestCase):
    def test_losing_with_the_better_chances_is_an_unlucky_defeat_and_says_why(self) -> None:
        chances = judged(baseline(), chance_match("2019-10-01", UNLUCKY, SNATCHED)).chances

        self.assertEqual(chances.rates.matches, 12)
        self.assertEqual((chances.rates.value("clear_cut"), chances.rates.value("other")), (0.5, 0.125))
        self.assertAlmostEqual(chances.ours.worth, 3.0)
        self.assertAlmostEqual(chances.theirs.worth, 0.5)
        self.assertEqual((chances.verdict, chances.tone, chances.played, chances.points), ("Unlucky defeat", "unlucky", "better", 0))
        self.assertGreater(chances.win, 0.8)
        self.assertAlmostEqual(chances.win + chances.draw + chances.loss, 1.0)
        self.assertAlmostEqual(chances.expected_points, 3 * chances.win + chances.draw)
        # Seven of the twelve were on goal where chances like these put eight there (shooting -0.5),
        # and none went in where 2.5 usually would (-2.5): mostly the keeper.
        self.assertEqual((chances.ours.on_goal, chances.ours.usual_on_goal), (7, 8.0))
        self.assertAlmostEqual(chances.ours.usual_scored_on_goal, 2.5)
        self.assertAlmostEqual(chances.ours.shooting, -0.5)
        self.assertIn("Most of the shortfall was shots on goal that their keeper and defenders kept out.",
                      chances.explanations[0])
        self.assertEqual([item.outcome for item in chances.ours.missed_clear_cut], ["saved or blocked"] * 3 + ["wide"])
        # Over the other twelve, the team scored exactly what its chances were worth.
        self.assertEqual((chances.team_finishing.goals, chances.team_finishing.standing), (24, "usual"))
        self.assertIn("one of those days", chances.takeaway)
        (striker,) = chances.finishers
        self.assertEqual((striker.name, striker.today_goals, striker.matches, striker.goals), ("Home 11", 0, 12, 24))

    def test_winning_with_the_worse_chances_is_a_lucky_win(self) -> None:
        chances = judged(baseline(), chance_match("2019-10-01", SNATCHED, UNLUCKY)).chances
        self.assertEqual((chances.verdict, chances.tone, chances.points), ("Lucky win", "lucky", 3))
        self.assertIn("flattered you", chances.takeaway)
        self.assertIn("Most of it was shots on goal going in more often than usual.", chances.explanations[0])

    def test_a_finishing_shortfall_over_the_other_matches_is_called_a_pattern(self) -> None:
        # Before, we never scored a clear-cut chance and they scored all of theirs, so ours fell 12 short.
        matches = baseline(ours={"ccc_saved": 2, "other_scored": 1, "other_saved": 3, "other_wide": 4},
                           theirs={"ccc_scored": 2, "other_scored": 1, "other_saved": 3, "other_wide": 4})
        chances = judged(matches, chance_match("2019-10-01", UNLUCKY, SNATCHED)).chances
        self.assertEqual(chances.verdict, "Unlucky defeat")
        self.assertEqual((chances.team_finishing.goals, chances.team_finishing.standing), (12, "below"))
        self.assertLess(chances.team_finishing.luck_odds, PATTERN_ODDS)
        self.assertIn("this fits a pattern", chances.takeaway)
        self.assertIn("a shortfall luck alone leaves about 1 time in 774", chances.takeaway)
        self.assertEqual(chances.finishers[0].standing, "below")

    def test_chances_are_set_against_your_usual_unless_the_match_is_a_friendly(self) -> None:
        competitive = judged(baseline(), chance_match("2019-10-01", UNLUCKY, SNATCHED)).chances
        ours, theirs = competitive.usual
        self.assertEqual((ours.usual, ours.standing, ours.favourable), (2.0, "above", True))
        self.assertEqual((theirs.standing, theirs.favourable), ("below", True))

        friendly = judged(baseline(), chance_match("2019-10-01", UNLUCKY, SNATCHED, competition=FRIENDLY))
        self.assertEqual(friendly.chances.verdict, "Unlucky defeat")  # judged on the same rates,
        self.assertEqual(friendly.chances.usual, ())  # but not set against the competitive usual

    def test_a_scored_penalty_is_worth_three_quarters_of_a_goal(self) -> None:
        chances = judged(baseline(), chance_match("2019-10-01", {"penalties": 1}, {})).chances
        self.assertEqual((chances.ours.penalties, chances.ours.clear_cut, chances.ours.on_goal), (1, 1, 0))
        self.assertAlmostEqual(chances.ours.worth, PENALTY_VALUE)
        self.assertEqual(chances.verdict, "Deserved win")

    def test_matches_that_cannot_be_judged_say_why(self) -> None:
        diagnosis = judged(baseline(6), chance_match("2019-10-01", UNLUCKY, SNATCHED))
        self.assertIsNone(diagnosis.chances)
        self.assertIn("needs 10 other competitive matches with every shot recorded; there are 6",
                      diagnosis.chances_not_judged)

        target = chance_match("2019-10-01", UNLUCKY, SNATCHED)
        target["scoreAt90"] = [0, 0]
        self.assertIn("extra time", judged(baseline(), target).chances_not_judged)

        target = chance_match("2019-10-01", UNLUCKY, SNATCHED)
        target["detail"]["shots"] = []
        self.assertIn("list of shots", judged(baseline(), target).chances_not_judged)

    def test_the_command_line_prints_the_same_verdict_first(self) -> None:
        text = format_match_diagnosis(judged(baseline(), chance_match("2019-10-01", UNLUCKY, SNATCHED)))
        self.assertLess(text.index("Result vs chances"), text.index("Diagnosis"))
        self.assertIn("Unlucky defeat. You had the better chances, worth 3.0 goals to their 0.5.", text)
        self.assertIn("Clear-cut chances you missed: Home 11", text)
        self.assertIn("So: The chances were there", text)


class SeasonChancesPanelTests(unittest.TestCase):
    def test_the_matches_page_sets_the_season_against_its_chances(self) -> None:
        matches = baseline()
        matches[3]["away"] = {"id": ALPHA["id"], "name": "</script><b>Alpha"}  # a name that must stay text
        capture = MatchCapture.from_document(capture_document(matches, game_date="2019-10-20"))
        review = review_matches(
            capture.matches, capture.league_results, TeamRef(US["id"], US["name"]), catalogue=MVP_CATALOGUE,
            filters=ReviewFilters(competitions="competitive"),
        )
        body = season_chances_section(diagnose_matches(review))
        self.assertIn("Over 12 matches you took <b>12</b> points", body)
        self.assertIn("Both are within what luck alone usually leaves.", body)
        self.assertEqual(body.count("class='fm-trend-hit'"), 24)  # one per match on each chart
        self.assertIn("Every match", body)
        self.assertNotIn("</script><b>Alpha", body)  # escaped in the hover data and the table alike
        rows = json.loads(body.split("class='fm-trend-data'>", 1)[1].split("</script>", 1)[0])
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["ours"], "")  # no five-match average before the fifth match
        self.assertEqual(rows[4]["ours"], "2.00")

    def test_without_enough_matches_the_panel_says_why(self) -> None:
        capture = MatchCapture.from_document(capture_document(baseline(6), game_date="2019-10-20"))
        review = review_matches(
            capture.matches, capture.league_results, TeamRef(US["id"], US["name"]), catalogue=MVP_CATALOGUE,
            filters=ReviewFilters(competitions="competitive"),
        )
        self.assertIn("Not yet: needs 10 usable matches", season_chances_section(diagnose_matches(review)))


if __name__ == "__main__":
    unittest.main()
