import json
import unittest
from datetime import date, timedelta

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.match_analysis import ReviewFilters, review_matches, side_metrics
from fm_analytics.analytics.match_diagnostics import diagnose_matches
from fm_analytics.analytics.single_match_diagnosis import diagnose_one_match
from fm_analytics.analytics.match_interventions import (
    StoredIntervention,
    evaluate_intervention,
    propose_intervention,
)
from fm_analytics.domain.matches import MatchCapture, TeamRef

from tests.match_support import (
    ALPHA, CUP, CUP_SIDE, FRIENDLY, LEAGUE, US, capture_document, detail, lineup, match, team_stats,
)
from tests.test_match_chances import baseline as chance_baseline
from tests.test_match_chances import chance_match


# Where each of Vertical 4-4-2's line-up places plays, in FM's line-up order.
POSITIONS = ("GK", "DR", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST", "ST")


def placed(players: list[dict]) -> list[dict]:
    for player, position in zip(players, POSITIONS):
        player["position"] = player["startPosition"] = position
    return players


def diagnostic_season(count: int = 10, *, unconfirmed_box_to_box: bool = False) -> list[dict]:
    """1-0 home wins, the first three drawn 1-1 by an 80th-minute goal.

    The box-to-box midfielder is rated 6.45 against the opposition's central
    midfielders' 6.8; the advanced forward scores every goal, rated 7.2.
    """
    matches = []
    for index in range(count):
        day = (date(2019, 9, 2) + timedelta(days=index)).isoformat()
        draw = index < 3
        codes = list((0x1, 0x4, 0x2, 0x2, 0x4, 0x80, 0x10000, 0x20, 0x80, 0x80000000, 0x800))
        if unconfirmed_box_to_box:
            codes[6] = 0x40000
        players = placed(lineup("home", codes))
        for player in players:
            player["stats"].update({
                "goals": 0, "assists": 0, "shots": 0,
                "key_passes": 0, "chances_created": 0,
            })
        players[6]["rating"] = 6.45
        players[10]["rating"] = 7.2
        players[10]["stats"].update({"goals": 1, "shots": 4})
        item = match(
            day, US, ALPHA, 1, 1 if draw else 0, competition=LEAGUE,
            detail=detail(
                home=team_stats(goals=1, shots=12, shots_on_target=6, clear_cut_chances=2),
                away=team_stats(goals=1 if draw else 0, shots=8, shots_on_target=3, clear_cut_chances=0),
                players=players + placed(lineup("away")),
            ),
        )
        item["incidents"] = [
            {"minute": 10, "side": "home", "kind": "goal", "playerShortId": 1010},
        ] + ([
            {"minute": 80, "side": "away", "kind": "goal", "playerShortId": 1510},
        ] if draw else [])
        matches.append(item)
    return matches


def review_for(matches: list[dict], *, game_date: str = "2019-09-20"):
    capture = MatchCapture.from_document(capture_document(matches, game_date=game_date))
    return review_matches(
        capture.matches,
        capture.league_results,
        TeamRef(US["id"], US["name"]),
        catalogue=MVP_CATALOGUE,
        filters=ReviewFilters(competitions="competitive"),
    )


def finishing_season() -> list[dict]:
    """Five matches scoring well from the chances, then ten scoring none from the same chances."""
    theirs = {"ccc_scored": 1, "ccc_saved": 1, "other_scored": 1, "other_saved": 3, "other_wide": 4}
    clinical = {"ccc_scored": 2, "other_scored": 2, "other_saved": 2, "other_wide": 4}
    wasteful = {"ccc_saved": 2, "other_saved": 4, "other_wide": 4}
    return [
        chance_match((date(2019, 9, 2) + timedelta(days=index)).isoformat(), clinical if index < 5 else wasteful, theirs)
        for index in range(15)
    ]


def _timed(day: str, goals: list[tuple[int, str]], **kwargs) -> dict:
    home = sum(side == "home" for _minute, side in goals)
    away = len(goals) - home
    item = match(day, US, ALPHA, home, away, competition=LEAGUE,
                 detail=detail(home=team_stats(goals=home), away=team_stats(goals=away)), **kwargs)
    item["incidents"] = [
        {"minute": minute, "side": side, "kind": "goal", "playerShortId": 1010 if side == "home" else 1510}
        for minute, side in goals
    ]
    return item


def lead_season(*, led_won: int, led_drawn: int, trailed_lost: int, trailed_drawn: int) -> list[dict]:
    """Matches you lead from 10′ (won 2-0 or drawn 1-1 by a 50′ equaliser), and as many they lead."""
    plans = (
        [[(10, "home"), (30, "home")]] * led_won + [[(10, "home"), (50, "away")]] * led_drawn
        + [[(10, "away"), (30, "away")]] * trailed_lost + [[(10, "away"), (50, "home")]] * trailed_drawn
    )
    return [_timed((date(2019, 9, 2) + timedelta(days=index)).isoformat(), plan) for index, plan in enumerate(plans)]


def venue_season(*, conceding: bool = False) -> list[dict]:
    """15 home wins and 15 away defeats; away you create less, or (`conceding`) allow more."""
    matches = []
    for index in range(30):
        day = (date(2019, 9, 2) + timedelta(days=index)).isoformat()
        at_home = index % 2 == 0
        ours = team_stats(goals=1 if at_home else 0, shots=14 if at_home or conceding else 9,
                          clear_cut_chances=3 if at_home or conceding else 1)
        theirs = team_stats(goals=0 if at_home else 1, shots=10,
                            clear_cut_chances=3 if conceding and not at_home else 1)
        if at_home:
            matches.append(match(day, US, ALPHA, 1, 0, competition=LEAGUE, detail=detail(home=ours, away=theirs)))
        else:
            matches.append(match(day, ALPHA, US, 1, 0, competition=LEAGUE, detail=detail(home=theirs, away=ours)))
    return matches


class MatchDiagnosticTests(unittest.TestCase):
    def test_windows_findings_and_protected_areas_are_explainable(self) -> None:
        diagnostics = diagnose_matches(review_for(diagnostic_season()))

        self.assertTrue(diagnostics.quality.team_findings_allowed)
        self.assertEqual(diagnostics.quality.eligible_team_matches, 10)
        self.assertEqual([(window.key, window.matches) for window in diagnostics.windows], [
            ("season", 10), ("last10", 10), ("last5", 5),
        ])
        self.assertIsNotNone(diagnostics.windows[-1].opponent_adjusted_for["shots"])

        keys = {finding.key for finding in diagnostics.opportunities}
        self.assertIn("game_state_protection", keys)
        self.assertIn("role_output:b2b_support", keys)
        role = next(finding for finding in diagnostics.opportunities if finding.key.startswith("role_output:"))
        self.assertIn("10 starts", " ".join(role.evidence))
        self.assertEqual(role.evaluation_matches, 5)
        self.assertTrue(role.stop_condition)

        protected = {item.key for item in diagnostics.do_not_change}
        self.assertIn("chance_creation", protected)
        self.assertIn("advanced_forward", protected)
        self.assertIn("chance_prevention", protected)
        self.assertEqual(diagnostics.unavailable[0].key, "set_pieces")
        self.assertEqual(json.loads(json.dumps(diagnostics.to_document())), diagnostics.to_document())

    def test_an_unconfirmed_role_is_never_the_subject_of_a_role_finding(self) -> None:
        diagnostics = diagnose_matches(review_for(diagnostic_season(unconfirmed_box_to_box=True)))
        self.assertGreater(diagnostics.quality.unconfirmed_role_appearances, 0)
        self.assertNotIn("individual-role output", {
            finding.problem_class for finding in diagnostics.opportunities
        })
        self.assertIn("unconfirmed_role_mapping", {issue.code for issue in diagnostics.quality.issues})

    def test_scoring_well_below_the_chances_with_creation_intact_is_finishing_not_more_attack(self) -> None:
        diagnostics = diagnose_matches(review_for(finishing_season(), game_date="2019-10-30"))
        finishing = next(
            finding for finding in diagnostics.opportunities if finding.key == "finishing_recent"
        )
        self.assertEqual(finishing.title, "Scoring less than your chances are worth")
        self.assertIn("Last 10: 0 goals from chances worth", finishing.evidence[0])
        self.assertIn("luck alone leaves a shortfall this large", finishing.evidence[0])
        self.assertIn("Keep the tactic", finishing.intervention)
        self.assertIn("chance_creation", {item.key for item in diagnostics.do_not_change})

    def test_a_usual_share_of_leads_not_won_is_not_a_finding(self) -> None:
        # Three of ten leads not won, as the opposition's are: the old rule fired at two.
        matches = lead_season(led_won=7, led_drawn=3, trailed_lost=7, trailed_drawn=3)
        diagnostics = diagnose_matches(review_for(matches, game_date="2019-10-30"))
        self.assertNotIn("game_state_protection", {finding.key for finding in diagnostics.opportunities})

    def test_leads_slipping_more_than_usual_is_counted_against_the_leads(self) -> None:
        matches = lead_season(led_won=2, led_drawn=8, trailed_lost=9, trailed_drawn=1)
        diagnostics = diagnose_matches(review_for(matches, game_date="2019-10-30"))
        finding = next(item for item in diagnostics.opportunities if item.key == "game_state_protection")
        self.assertEqual((finding.title, finding.confidence), ("Leads are slipping", "medium"))
        self.assertIn("Won 2 of the 10 matches you led (20%); sides that led in your matches won 55%",
                      finding.evidence[0])
        self.assertIn("about 1 time in 37", finding.evidence[0])

    def test_creating_less_away_is_measured_against_the_opposition_alone(self) -> None:
        # With 15 of each, allowing for the venue too would leave away creation
        # within 0.2 of what is "expected", and the finding could never fire.
        diagnostics = diagnose_matches(review_for(venue_season(), game_date="2019-10-30"))
        finding = next(item for item in diagnostics.opportunities if item.problem_class == "home/away")
        self.assertEqual((finding.key, finding.title), ("away_performance", "Creating less away than at home"))
        self.assertIn("Points a game: 0.00 away, 3.00 at home", finding.evidence)
        self.assertIn("-2.5 shots and -1.00 clear-cut chances created", finding.evidence[1])

        diagnostics = diagnose_matches(review_for(venue_season(conceding=True), game_date="2019-10-30"))
        finding = next(item for item in diagnostics.opportunities if item.problem_class == "home/away")
        self.assertEqual((finding.key, finding.title), ("away_prevention", "Conceding more away than at home"))

    def test_a_role_is_judged_against_the_opposition_in_its_position_not_a_fixed_rating(self) -> None:
        # Full-backs rated 6.55, as the opposition's are: below the old fixed 6.70, but usual for the position.
        matches = diagnostic_season()
        for item in matches:
            for player in item["detail"]["players"]:
                if player["position"] in ("DR", "DL"):
                    player["rating"] = 6.55
            item["detail"]["players"][6]["rating"] = 6.8
        diagnostics = diagnose_matches(review_for(matches))
        self.assertNotIn("individual-role output", {finding.problem_class for finding in diagnostics.opportunities})

    def test_results_are_set_against_the_chances_over_the_season(self) -> None:
        chances = diagnose_matches(review_for(chance_baseline())).chances
        season = chances.window("season")
        self.assertEqual((season.matches, season.points, season.goals_for, season.goals_against), (12, 12, 24, 24))
        self.assertAlmostEqual(season.worth_for, 24.0)
        self.assertGreater(season.scoring_odds, 0.4)  # exactly what the chances were worth
        self.assertGreater(season.expected_points, 12)  # chances like these win as often as they lose
        self.assertEqual([window.matches for window in chances.windows], [12, 10, 5])
        self.assertEqual([match.result for match in chances.matches], ["D"] * 12)
        self.assertIsNone(diagnose_matches(review_for(diagnostic_season())).chances)  # no shots listed

    def test_fewer_than_five_eligible_matches_blocks_team_and_role_findings(self) -> None:
        diagnostics = diagnose_matches(review_for(diagnostic_season(4)))
        self.assertFalse(diagnostics.quality.team_findings_allowed)
        self.assertEqual(diagnostics.opportunities, ())
        self.assertEqual(diagnostics.do_not_change, ())
        self.assertIn("team_sample_too_small", {issue.code for issue in diagnostics.quality.issues})

    def test_a_missing_core_stat_is_unknown_and_the_match_is_ineligible(self) -> None:
        matches = diagnostic_season(5)
        del matches[-1]["detail"]["home"]["clear_cut_chances"]
        review = review_for(matches)
        incomplete = review.matches[-1]
        self.assertIsNone(side_metrics(incomplete.match, incomplete.side)["clear_cut_chances"])
        diagnostics = diagnose_matches(review)
        self.assertEqual(diagnostics.quality.eligible_team_matches, 4)
        self.assertIn("invalid_or_incomplete_team_stats", {
            issue.code for issue in diagnostics.quality.issues
        })

    def test_an_extra_time_panel_is_not_compared_with_ninety_minute_matches(self) -> None:
        matches = diagnostic_season(5)
        matches[-1]["scoreAt90"] = [0, 0]
        diagnostics = diagnose_matches(review_for(matches))
        self.assertEqual(diagnostics.quality.eligible_team_matches, 4)
        self.assertIn("extra_time_not_comparable", {
            issue.code for issue in diagnostics.quality.issues
        })


def varied_season(count: int = 12) -> list[dict]:
    """1-0 home wins whose shot counts vary (8 to 12), so the usual range has a spread."""
    matches = []
    for index in range(count):
        day = (date(2019, 9, 2) + timedelta(days=index)).isoformat()
        item = match(
            day, US, ALPHA, 1, 0, competition=LEAGUE,
            detail=detail(
                home=team_stats(goals=1, shots=8 + index % 5, shots_on_target=4, clear_cut_chances=1),
                away=team_stats(goals=0, shots=10, shots_on_target=4, clear_cut_chances=1),
                players=lineup("home"),
            ),
        )
        item["incidents"] = [{"minute": 30, "side": "home", "kind": "goal", "playerShortId": 1010}]
        matches.append(item)
    return matches


def one_match(matches: list[dict], target: dict):
    """The target's own summary and the competitive review it is judged against."""
    capture = MatchCapture.from_document(capture_document(matches + [target], game_date="2019-10-20"))
    club = TeamRef(US["id"], US["name"])

    def review(scope: str):
        return review_matches(
            capture.matches, capture.league_results, club,
            catalogue=MVP_CATALOGUE, filters=ReviewFilters(competitions=scope),
        )

    summary = next(row for row in review("all").matches if row.match.date.isoformat() == target["date"])
    return review("competitive"), summary


def one_match_target(competition: dict = LEAGUE) -> dict:
    """A 1-1 draw led from 10′, 25 shots, one player rated 8.0 and one 6.0 against their usual 6.8."""
    players = lineup("home")
    players[10]["rating"] = 8.0
    players[6]["rating"] = 6.0
    item = match(
        "2019-10-01", US, ALPHA, 1, 1, competition=competition,
        detail=detail(
            home=team_stats(goals=1, shots=25, shots_on_target=4, clear_cut_chances=1),
            away=team_stats(goals=1, shots=10, shots_on_target=4, clear_cut_chances=1),
            players=players,
        ),
    )
    item["incidents"] = [
        {"minute": 10, "side": "home", "kind": "goal", "playerShortId": 1010},
        {"minute": 80, "side": "away", "kind": "goal", "playerShortId": 1510},
    ]
    return item


class OneMatchDiagnosisTests(unittest.TestCase):
    def test_one_match_is_set_against_the_usual_range_of_the_others(self) -> None:
        review, summary = one_match(varied_season(), one_match_target())
        diagnosis = diagnose_one_match(review, summary)

        self.assertIsNone(diagnosis.not_compared)
        self.assertEqual(diagnosis.baseline_matches, 12)  # the match itself is left out
        shots = next(c for c in diagnosis.checks if (c.side, c.metric) == ("ours", "shots"))
        self.assertEqual((shots.standing, shots.favourable), ("above", True))
        self.assertLessEqual(shots.usual_low, 8)
        self.assertGreaterEqual(shots.usual_high, 12)
        theirs = next(c for c in diagnosis.checks if (c.side, c.metric) == ("theirs", "shots"))
        self.assertEqual((theirs.standing, theirs.favourable), ("usual", None))
        self.assertEqual(diagnosis.headline, "Created more than usual; allowed about the usual.")

    def test_how_it_played_out_and_players_against_their_own_usual(self) -> None:
        review, summary = one_match(varied_season(), one_match_target())
        diagnosis = diagnose_one_match(review, summary)

        self.assertTrue(diagnosis.game_state[0].startswith("Led 1–0 from 10′ but drew"))
        self.assertIn("From 76′: 0 scored, 1 conceded", diagnosis.game_state)
        self.assertEqual([(p.name, p.rating, p.matches) for p in diagnosis.above_usual], [("Home 11", 8.0, 12)])
        self.assertEqual([p.name for p in diagnosis.below_usual], ["Home 7"])
        self.assertAlmostEqual(diagnosis.below_usual[0].usual, 6.8)

    def test_a_comeback_is_described(self) -> None:
        target = one_match_target()
        target["homeGoals"], target["awayGoals"] = 2, 1
        target["detail"]["home"]["goals"] = 2
        target["incidents"] = [
            {"minute": 5, "side": "away", "kind": "goal", "playerShortId": 1510},
            {"minute": 50, "side": "home", "kind": "goal", "playerShortId": 1010},
            {"minute": 85, "side": "home", "kind": "goal", "playerShortId": 1010},
        ]
        diagnosis = diagnose_one_match(*one_match(varied_season(), target))
        self.assertIn("Came back from 0–1 down to win", diagnosis.game_state)
        self.assertIn("From 76′: 1 scored, 0 conceded", diagnosis.game_state)

    def test_friendlies_and_short_histories_are_not_compared(self) -> None:
        diagnosis = diagnose_one_match(*one_match(varied_season(), one_match_target(competition=FRIENDLY)))
        self.assertIn("Friendlies", diagnosis.not_compared)
        self.assertEqual((diagnosis.checks, diagnosis.headline, diagnosis.above_usual), ((), None, ()))

        diagnosis = diagnose_one_match(*one_match(varied_season(6), one_match_target()))
        self.assertIn("needs 10 other usable matches; there are 6", diagnosis.not_compared)
        self.assertEqual(diagnosis.checks, ())
        self.assertTrue(diagnosis.game_state)

    def test_a_match_alone_in_its_opponent_band_is_still_compared(self) -> None:
        target = one_match_target(competition=CUP)
        target["away"] = CUP_SIDE
        diagnosis = diagnose_one_match(*one_match(varied_season(), target))
        self.assertIsNone(diagnosis.not_compared)
        self.assertEqual(diagnosis.compared_with, "teams outside your league at home")


class InterventionEvaluationTests(unittest.TestCase):
    def test_a_role_test_collects_only_post_start_role_exposures_then_evaluates(self) -> None:
        baseline_review = review_for(diagnostic_season(10))
        diagnostics = diagnose_matches(baseline_review)
        proposal = propose_intervention(
            baseline_review, diagnostics, "role_output:b2b_support", manager_note="Test Appau"
        )
        intervention = StoredIntervention(1, proposal, "2019-09-11T12:00:00+00:00")

        collecting = evaluate_intervention(review_for(diagnostic_season(12)), intervention)
        self.assertEqual((collecting.status, collecting.exposures), ("collecting", 2))

        matches = diagnostic_season(15)
        for item in matches[-5:]:
            box_to_box = item["detail"]["players"][6]
            box_to_box["rating"] = 7.0
            box_to_box["stats"]["chances_created"] = 1
        evaluated = evaluate_intervention(review_for(matches), intervention)
        self.assertEqual((evaluated.status, evaluated.exposures), ("supported", 5))
        self.assertTrue(evaluated.review_due)
        self.assertIn("Role rating", " ".join(evaluated.evidence))

    def test_a_finishing_test_is_judged_on_goals_against_the_chances(self) -> None:
        review = review_for(finishing_season(), game_date="2019-10-30")
        proposal = propose_intervention(review, diagnose_matches(review), "finishing_recent")
        self.assertLess(proposal.baseline.finishing_per_match, -1.0)
        intervention = StoredIntervention(1, proposal, "2019-09-17T12:00:00+00:00")

        clinical = {"ccc_scored": 2, "other_scored": 2, "other_saved": 2, "other_wide": 4}
        theirs = {"ccc_scored": 1, "ccc_saved": 1, "other_scored": 1, "other_saved": 3, "other_wide": 4}
        later = [chance_match(f"2019-09-{day}", clinical, theirs) for day in range(17, 22)]
        evaluated = evaluate_intervention(review_for(finishing_season() + later, game_date="2019-10-30"), intervention)
        self.assertEqual((evaluated.status, evaluated.exposures), ("supported", 5))
        self.assertIn("Goals against what the chances were worth", " ".join(evaluated.evidence))

    def test_a_started_test_freezes_the_finding_and_five_match_baseline(self) -> None:
        review = review_for(diagnostic_season(10))
        diagnostics = diagnose_matches(review)
        proposal = propose_intervention(review, diagnostics, "role_output:b2b_support")
        self.assertEqual(proposal.target_matches, 5)
        self.assertEqual(proposal.baseline.matches, 5)
        self.assertEqual(proposal.started_after_match_key, review.matches[-1].match.key)
        with self.assertRaisesRegex(ValueError, "no longer current"):
            propose_intervention(review, diagnostics, "not-a-finding")


if __name__ == "__main__":
    unittest.main()
