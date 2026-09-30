import unittest
from dataclasses import dataclass
from datetime import date

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.match_analysis import NO_TACTIC, ReviewFilters, review_matches
from fm_analytics.analytics.match_roles import RoleCodes, summarise_roles
from fm_analytics.analytics.match_strength import (
    Strength,
    StrengthCalculator,
    TablePosition,
    league_table,
)
from fm_analytics.domain.matches import MatchCapture, PlayerMatchStats, TeamRef

from tests.match_support import US, capture_document, lineup, season


@dataclass
class Note:
    tactic_key: str | None = None
    opponent_rating: int | None = None
    note: str = ""


def load(matches=None):
    capture = MatchCapture.from_document(capture_document(season() if matches is None else matches))
    return capture.matches, capture.league_results


def review(filters=ReviewFilters(), notes=None, confirmed=None, matches=None):
    records, leagues = load(matches)
    return review_matches(
        records, leagues, TeamRef(US["id"], US["name"]), catalogue=MVP_CATALOGUE,
        notes=notes or {}, confirmed_role_codes=confirmed or {}, filters=filters,
    )


class LeagueTableTests(unittest.TestCase):
    def test_the_table_counts_only_results_before_the_morning_of_the_match(self) -> None:
        _records, ((_league, results),) = load()
        table = league_table(results, date(2019, 9, 1))
        self.assertEqual([row.name for row in table], ["Alpha", "Bravo", "Charlie", "Hungerford Town"])
        self.assertEqual([row.points for row in table], [7, 4, 2, 2])
        self.assertEqual(table[0].played, 3)

    def test_teams_without_a_result_yet_are_still_in_the_table(self) -> None:
        _records, ((_league, results),) = load()
        table = league_table(results, date(2019, 8, 1))
        self.assertEqual(len(table), 4)
        self.assertTrue(all(row.played == 0 for row in table))


class StrengthTests(unittest.TestCase):
    def test_bands_under_each_grouping(self) -> None:
        def strength(position, played=5, ours=3, rating=None):
            return Strength(None, TablePosition(position, 22, played, 0), TablePosition(ours, 22, played, 0), rating)

        self.assertEqual(strength(7).band("table").key, "top")
        self.assertEqual(strength(8).band("table").key, "middle")
        self.assertEqual(strength(15).band("table").key, "middle")
        self.assertEqual(strength(16).band("table").key, "bottom")
        self.assertEqual(strength(2, played=2).band("table").key, "early")
        self.assertEqual(strength(2).band("relative").key, "above")
        self.assertEqual(strength(4).band("relative").key, "below")
        self.assertEqual(Strength(None, None, None, None).band("table").key, "outside")
        self.assertEqual(strength(1, rating=2).band("rating").key, "stronger")
        self.assertEqual(strength(1, rating=0).band("rating").key, "similar")
        self.assertEqual(strength(1, rating=-1).band("rating").key, "weaker")
        self.assertEqual(strength(1).band("rating").key, "unrated")

    def test_each_match_is_placed_by_the_table_on_its_own_morning(self) -> None:
        records, leagues = load()
        calculator = StrengthCalculator(leagues, US["id"])
        by_date = {
            record.date.isoformat(): calculator.strength(record, record.team("away" if record.side_of("100") == "home" else "home").id, None)
            for record in records
        }
        self.assertEqual(by_date["2019-08-10"].band("table").key, "early")
        self.assertEqual(by_date["2019-09-01"].band("table").key, "top")
        self.assertEqual((by_date["2019-09-01"].opponent.position, by_date["2019-09-01"].ours.position), (1, 4))
        self.assertEqual(by_date["2019-08-24"].band("table").key, "outside")


class ReviewTests(unittest.TestCase):
    def test_friendlies_are_left_out_by_default_and_league_only_drops_the_cup(self) -> None:
        self.assertEqual(len(review().matches), 5)
        self.assertEqual(review().excluded, 1)
        self.assertEqual(len(review(ReviewFilters(competitions="league")).matches), 4)
        self.assertEqual(len(review(ReviewFilters(competitions="all")).matches), 6)

    def test_groups_count_results_and_flag_small_samples(self) -> None:
        groups = {group.key: group for group in review().groups}
        self.assertEqual((groups["early"].matches, groups["early"].draws, groups["early"].losses), (3, 2, 1))
        self.assertTrue(groups["early"].enough)
        top = groups["top"]
        self.assertEqual((top.matches, top.wins, top.detailed), (1, 1, 1))
        self.assertFalse(top.enough)
        self.assertEqual(top.averages_for["shots"], 12)
        self.assertEqual(top.averages_against["shots"], 6)
        self.assertEqual(top.averages_for["possession"], 40)
        self.assertEqual(top.averages_for["pass_completion"], 75)
        self.assertEqual(top.averages_for["off_target"], 6)  # 12 shots, 6 on target, none blocked
        self.assertEqual(groups["outside"].matches, 1)

    def test_the_overall_record_matches_the_matches(self) -> None:
        overall = review().overall
        self.assertEqual((overall.wins, overall.draws, overall.losses), (2, 2, 1))
        self.assertEqual((overall.goals_for, overall.goals_against), (4, 4))

    def test_the_tactic_comes_from_the_note_else_from_an_exact_line_up(self) -> None:
        by_key = {s.match.key: s for s in review().matches}
        detailed = by_key["2019-09-01:100:201"]
        self.assertEqual((detailed.tactic_key, detailed.tactic_inferred), ("vertical_442", True))
        noted = review(notes={"2019-09-01:100:201": Note("wing_play_442")})
        summary = {s.match.key: s for s in noted.matches}["2019-09-01:100:201"]
        self.assertEqual((summary.tactic_key, summary.tactic_inferred), ("wing_play_442", False))
        unknown = review(ReviewFilters(tactic=NO_TACTIC))
        self.assertEqual(len(unknown.matches), 4)

    def test_a_permitted_alternate_role_still_names_the_tactic_but_two_fits_name_none(self) -> None:
        # Vertical 4-4-2 lists Pressing Forward as an alternative to its default Deep-Lying Forward.
        self.assertEqual(MVP_CATALOGUE.tactics["vertical_442"].slots[-2].role_key, "dlf_support")
        detailed = {s.match.key: s for s in review().matches}["2019-09-01:100:201"]
        self.assertEqual(detailed.tactic_key, "vertical_442")
        # With a Deep-Lying Forward the same eleven also fit Direct Counter 4-4-2.
        both = review(confirmed={0x80000000: "dlf_support"})
        self.assertIsNone({s.match.key: s for s in both.matches}["2019-09-01:100:201"].tactic_key)

    def test_venue_and_rating_filters(self) -> None:
        self.assertEqual({s.side for s in review(ReviewFilters(venue="away")).matches}, {"away"})
        rated = review(ReviewFilters(grouping="rating"), notes={"2019-08-10:202:100": Note(opponent_rating=2)})
        groups = {group.key: group.matches for group in rated.groups}
        self.assertEqual((groups["stronger"], groups["unrated"]), (1, 4))

    def test_goals_are_counted_by_period_and_by_role(self) -> None:
        goals = review().goals
        self.assertEqual(dict(zip(goals.periods, goals.scored)), {"1-15": 1, "16-30": 0, "31-45": 0, "46-60": 0, "61-75": 0, "76-90": 0, "90+": 1})
        self.assertEqual(sum(goals.conceded), 1)
        self.assertEqual(dict(goals.scorers), {"Pressing Forward (Support)": 1, "Advanced Forward (Attack)": 1})
        self.assertEqual(dict(goals.assisters), {"Winger (Support) [ML/MR]": 2})
        self.assertEqual(dict(goals.conceded_to), {"Advanced Forward (Attack)": 1})
        self.assertEqual((goals.goals_for_covered, goals.goals_for_total), (2, 4))
        # The timeline times the 2-1; the 0-0 has no goals to time.
        self.assertEqual((goals.timed_matches, goals.timed_goals_for, goals.timed_goals_against), (2, 2, 1))

    def test_a_results_incidents_time_its_goals_and_count_penalties_own_goals_and_red_cards(self) -> None:
        matches = season()
        # Bravo 2-0 us, a result with no stats: a penalty in first-half added time,
        # an own goal in second-half added time, and one of ours sent off.
        matches[2]["incidents"] = [
            {"minute": 45, "addedTime": 2, "side": "home", "kind": "penalty", "playerShortId": 1},
            {"minute": 60, "side": "away", "kind": "sent_off", "playerShortId": 2, "player": "Home 5"},
            {"minute": 90, "addedTime": 3, "side": "home", "kind": "own_goal", "playerShortId": 3},
        ]
        goals = review(matches=matches).goals
        conceded = dict(zip(goals.periods, goals.conceded))
        self.assertEqual((conceded["31-45"], conceded["90+"]), (1, 1))
        self.assertEqual((goals.timed_matches, goals.timed_goals_against), (3, 3))
        self.assertEqual((goals.penalties_against, goals.own_goals_against, goals.sent_off_ours), (1, 1, 1))
        self.assertEqual((goals.penalties_for, goals.own_goals_for, goals.sent_off_theirs), (0, 0, 0))
        # Incidents that do not account for the whole score time nothing.
        matches[2]["incidents"] = matches[2]["incidents"][:1]
        self.assertEqual(review(matches=matches).goals.timed_matches, 2)

    def test_unknown_role_codes_are_named_as_unconfirmed_not_guessed(self) -> None:
        matches = season()
        codes = (0x1, 0x4, 0x2, 0x2, 0x4, 0x80, 0x10000, 0x20, 0x80, 0x80000000, 0x40000)
        matches[-1]["detail"]["players"] = lineup("home", codes, o10={"shots": 5})
        result = review(matches=matches)
        self.assertEqual([code.code for code in result.unconfirmed_roles], [0x40000])
        self.assertIn("Unconfirmed role", result.roles[0].label)
        self.assertIsNone({s.match.key: s for s in result.matches}["2019-09-01:100:201"].tactic_key)
        confirmed = review(matches=matches, confirmed={0x40000: "af_attack"})
        self.assertEqual(confirmed.unconfirmed_roles, ())
        self.assertEqual(confirmed.roles[0].label, "Advanced Forward (Attack)")


class RoleSummaryTests(unittest.TestCase):
    def test_a_shared_role_counts_the_team_shots_once_per_match(self) -> None:
        codes = RoleCodes.build(MVP_CATALOGUE)
        wingers = [
            PlayerMatchStats.from_document({**player, "stats": {"shots": 2}})
            for player in lineup("home") if player["roleCode"] == 0x80
        ]
        (winger,) = summarise_roles([(player, "m1", 10) for player in wingers], codes)
        self.assertEqual((winger.appearances, winger.shots, winger.team_shots), (2, 4, 10))
        self.assertAlmostEqual(winger.shot_share, 0.4)
        self.assertEqual(winger.minutes, 180)
        self.assertAlmostEqual(winger.per_90(winger.shots), 2.0)

    def test_per_90_uses_the_minutes_actually_played(self) -> None:
        codes = RoleCodes.build(MVP_CATALOGUE)
        sub = PlayerMatchStats.from_document(
            {**lineup("home")[10], "cameOn": 60, "stats": {"shots": 2, "key_passes": 1, "chances_created": 1}}
        )
        (role,) = summarise_roles([(sub, "m1", 10)], codes)
        self.assertEqual(role.minutes, 30)
        self.assertAlmostEqual(role.per_90(role.shots), 6.0)
        self.assertEqual((role.key_passes, role.chances_created), (1, 1))
        self.assertAlmostEqual(role.per_90(role.chances_created), 3.0)

    def test_unused_substitutes_are_not_appearances(self) -> None:
        codes = RoleCodes.build(MVP_CATALOGUE)
        unused = PlayerMatchStats.from_document({**lineup("home")[0], "played": False, "roleCode": 0, "rating": None})
        self.assertEqual(summarise_roles([(unused, "m1", 10)], codes), ())


if __name__ == "__main__":
    unittest.main()
