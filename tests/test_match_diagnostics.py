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


def diagnostic_season(count: int = 10, *, unconfirmed_box_to_box: bool = False) -> list[dict]:
    matches = []
    for index in range(count):
        day = (date(2019, 9, 2) + timedelta(days=index)).isoformat()
        draw = index < 3
        codes = list((0x1, 0x4, 0x2, 0x2, 0x4, 0x80, 0x10000, 0x20, 0x80, 0x80000000, 0x800))
        if unconfirmed_box_to_box:
            codes[6] = 0x40000
        players = lineup("home", codes)
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
                players=players,
            ),
        )
        item["incidents"] = [
            {"minute": 10, "side": "home", "kind": "goal", "playerShortId": 1010},
        ] + ([
            {"minute": 80, "side": "away", "kind": "goal", "playerShortId": 1510},
        ] if draw else [])
        matches.append(item)
    return matches


def review_for(matches: list[dict]):
    capture = MatchCapture.from_document(capture_document(matches, game_date="2019-09-20"))
    return review_matches(
        capture.matches,
        capture.league_results,
        TeamRef(US["id"], US["name"]),
        catalogue=MVP_CATALOGUE,
        filters=ReviewFilters(competitions="competitive"),
    )


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

    def test_a_conversion_drop_with_stable_creation_is_finishing_not_more_attack(self) -> None:
        matches = diagnostic_season(15)
        for index, item in enumerate(matches):
            goals = 3 if index < 5 else 0
            item["homeGoals"] = goals
            item["awayGoals"] = 0
            item["detail"]["home"]["goals"] = goals
            item["detail"]["away"]["goals"] = 0
            item["detail"]["players"][10]["stats"]["goals"] = goals
            item["incidents"] = [
                {"minute": minute, "side": "home", "kind": "goal", "playerShortId": 1010}
                for minute in (10, 40, 60)[:goals]
            ]
        diagnostics = diagnose_matches(review_for(matches))
        finishing = next(
            finding for finding in diagnostics.opportunities if finding.key == "finishing_recent"
        )
        self.assertIn("from the same chances", finishing.title)
        self.assertIn("Keep the tactic", finishing.intervention)
        self.assertIn("chance_creation", {item.key for item in diagnostics.do_not_change})

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
