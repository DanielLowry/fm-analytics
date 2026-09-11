import unittest

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    RecruitmentBrief,
    WeaknessPolicy,
    assess_weaknesses,
    build_recruitment_briefs,
    evaluate_tactic,
    shortlist_candidates,
)
from fm_analytics.imports import parse_fm_html_export
from tests.test_xi_selection import CATALOGUE, TACTIC, legal_squad


class RecruitmentTests(unittest.TestCase):
    def test_briefs_retain_the_thresholds_that_created_the_weaknesses(self) -> None:
        squad = legal_squad()
        evaluation = evaluate_tactic(TACTIC, squad, CATALOGUE)
        policy = WeaknessPolicy(
            version="custom-thresholds",
            starter_score_threshold=60,
            backup_score_threshold=45,
        )
        report = assess_weaknesses(
            evaluation,
            squad,
            CATALOGUE,
            policy=policy,
        )

        briefs = build_recruitment_briefs(report, CATALOGUE)

        self.assertTrue(any(brief.need == "starter" for brief in briefs))
        self.assertTrue(any(brief.need == "depth" for brief in briefs))
        self.assertEqual(
            {brief.minimum_role_score for brief in briefs if brief.need == "starter"},
            {60},
        )
        self.assertEqual(
            {brief.minimum_role_score for brief in briefs if brief.need == "depth"},
            {45},
        )

    def test_shortlist_separates_proven_and_possible_candidates(self) -> None:
        html = """
        <table>
          <tr><th>UID</th><th>Name</th><th>Position</th><th>Pas</th><th>Vis</th><th>Fir</th><th>Dec</th><th>Cmp</th><th>Pos</th><th>Tea</th><th>Tec</th></tr>
          <tr><td>1</td><td>Known Good</td><td>M (C)</td><td>15</td><td>15</td><td>15</td><td>15</td><td>15</td><td>15</td><td>15</td><td>15</td></tr>
          <tr><td>2</td><td>Ranged Prospect</td><td>M (C)</td><td>8-16</td><td>8-16</td><td>8-16</td><td>8-16</td><td>8-16</td><td>8-16</td><td>8-16</td><td>8-16</td></tr>
          <tr><td>3</td><td>Known Weak</td><td>M (C)</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td></tr>
          <tr><td>4</td><td>Wrong Position</td><td>ST (C)</td><td>20</td><td>20</td><td>20</td><td>20</td><td>20</td><td>20</td><td>20</td><td>20</td></tr>
        </table>
        """
        exported = parse_fm_html_export(html)
        brief = RecruitmentBrief(
            tactic_key="positive_433dm",
            slot_keys=("MCL",),
            position="MC",
            role_key="dlp_support",
            need="starter",
            minimum_role_score=50,
            reason="upgrade required",
        )

        result = shortlist_candidates(brief, exported.players, MVP_CATALOGUE)

        self.assertEqual(
            [candidate.player_name for candidate in result.candidates],
            ["Known Good", "Ranged Prospect"],
        )
        self.assertEqual(result.candidates[0].verdict, "meets_threshold")
        self.assertEqual(
            result.candidates[1].verdict,
            "possible_with_more_scouting",
        )
        self.assertTrue(result.candidates[1].scout_more)

        excluding_current = shortlist_candidates(
            brief,
            exported.players,
            MVP_CATALOGUE,
            excluded_player_ids=frozenset(("1",)),
        )
        self.assertNotIn(
            "Known Good",
            [candidate.player_name for candidate in excluding_current.candidates],
        )

    def test_candidate_below_even_optimistic_bound_is_excluded(self) -> None:
        html = """
        <table><tr><th>UID</th><th>Name</th><th>Position</th><th>Fin</th><th>OtB</th><th>Acc</th><th>Pac</th><th>Ant</th><th>Cmp</th><th>Dri</th><th>Fir</th></tr>
        <tr><td>1</td><td>Known Weak</td><td>ST (C)</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td><td>3</td></tr></table>
        """
        exported = parse_fm_html_export(html)
        brief = RecruitmentBrief(
            tactic_key="positive_433dm",
            slot_keys=("ST",),
            position="ST",
            role_key="af_attack",
            need="starter",
            minimum_role_score=20,
            reason="upgrade required",
        )

        result = shortlist_candidates(brief, exported.players, MVP_CATALOGUE)

        self.assertEqual(result.candidates, ())


if __name__ == "__main__":
    unittest.main()
