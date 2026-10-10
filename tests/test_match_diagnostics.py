import json
import unittest
from datetime import date, timedelta

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.match_analysis import ReviewFilters, review_matches, side_metrics
from fm_analytics.analytics.match_diagnostics import diagnose_matches
from fm_analytics.analytics.match_interventions import (
    StoredIntervention,
    evaluate_intervention,
    propose_intervention,
)
from fm_analytics.domain.matches import MatchCapture, TeamRef

from tests.match_support import ALPHA, LEAGUE, US, capture_document, detail, lineup, match, team_stats


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
