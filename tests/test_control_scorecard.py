"""The control scorecard: our matches by opponent third and game plan, beside the league's top third.

The test league has four teams, so a third is one team: by the morning of
1 September 2019 Alpha is top, Bravo and Charlie are the middle, and we are
bottom; by 8 September Bravo has overtaken Alpha (see `tests.match_support`).
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.control_scorecard import benchmark_rows, control_scorecard, match_measures
from fm_analytics.domain.matches import MatchRecord
from fm_analytics.match_ingest import format_control, record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_control_scorecard, build_match_review, build_season_export
from fm_analytics.breakdowns_export import control_scorecard_json
from tests.match_support import ALPHA, BRAVO, CHARLIE, CUP, capture_document, detail, match, season, team_stats


def club_match(day, home, away, *, competition=None, home_stats=None, away_stats=None, season_year=2019):
    raw = match(day, home, away, 1, 0, detail=detail(home=home_stats, away=away_stats),
                **({"competition": competition} if competition else {}))
    return MatchRecord.from_document(dict(raw, season=season_year))


class HistoryCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        capture = Path(directory.name) / "capture.json"
        capture.write_text(json.dumps(capture_document(season())), encoding="utf-8")
        store = MatchHistoryStore(Path(directory.name) / "history.sqlite3")
        record_capture_file(store, capture)
        self.history = store.load_history("club:100")
        # Alpha (top) at home to Bravo (middle): Alpha's side is the benchmark.
        self.top_v_middle = club_match(
            "2019-09-01", ALPHA, BRAVO,
            home_stats=team_stats(possession_time=6000, passes_attempted=500, passes_completed=400, corners=7,
                                  shots_on_target=6, clear_cut_chances=2),
            away_stats=team_stats(possession_time=4000, passes_attempted=300, passes_completed=200, corners=2,
                                  shots_on_target=1, clear_cut_chances=0),
        )


class MeasureTests(unittest.TestCase):
    def test_margins_are_ours_minus_theirs_and_their_passing_is_theirs(self) -> None:
        measures = match_measures(
            {"possession": 60.0, "pass_completion": 80.0, "crosses_attempted": 30, "corners": 7,
             "shots_on_target": 6, "clear_cut_chances": 2},
            {"possession": 40.0, "pass_completion": 66.7, "crosses_attempted": 12, "corners": 2,
             "shots_on_target": 1, "clear_cut_chances": 0},
        )
        self.assertEqual(measures, {
            "possession": 60.0, "pass_completion": 80.0, "crosses": 30, "corner_margin": 5,
            "opponent_pass_completion": 66.7, "sot_margin": 5, "ccc_margin": 2,
        })

    def test_a_missing_figure_leaves_only_its_measures_blank(self) -> None:
        measures = match_measures(
            {"possession": 50.0, "pass_completion": 70.0, "crosses_attempted": None, "corners": 3,
             "shots_on_target": 4, "clear_cut_chances": 1},
            {"possession": 50.0, "pass_completion": 70.0, "crosses_attempted": None, "corners": None,
             "shots_on_target": 4, "clear_cut_chances": 1},
        )
        self.assertIsNone(measures["crosses"])
        self.assertIsNone(measures["corner_margin"])
        self.assertEqual(measures["sot_margin"], 0)

    def test_a_match_without_stats_has_no_measures(self) -> None:
        self.assertIsNone(match_measures(None, {"possession": 50.0}))


class BenchmarkTests(HistoryCase):
    def rows(self, club_matches, season=None):
        return benchmark_rows(club_matches, self.history.league_results, self.history.club.id, season=season)

    def test_only_the_top_third_sides_count_by_their_opponents_third(self) -> None:
        rows = self.rows([self.top_v_middle])
        self.assertEqual([len(rows[key]) for key in ("top", "middle", "bottom")], [0, 1, 0])
        alpha = rows["middle"][0]
        self.assertEqual(alpha["possession"], 60.0)
        self.assertEqual(alpha["corner_margin"], 5)
        self.assertEqual(alpha["sot_margin"], 5)
        self.assertAlmostEqual(alpha["opponent_pass_completion"], 66.7, places=1)

    def test_the_table_on_the_morning_of_the_match_decides_who_is_top(self) -> None:
        # By 8 September Bravo is top and Alpha middle: now Bravo's side counts.
        later = club_match("2019-09-08", ALPHA, BRAVO)
        rows = self.rows([later])
        self.assertEqual(len(rows["middle"]), 1)
        self.assertEqual(rows["middle"][0]["possession"], 50.0)

    def test_early_season_cup_and_other_season_matches_are_left_out(self) -> None:
        early = club_match("2019-08-10", ALPHA, CHARLIE)
        cup = club_match("2019-09-01", ALPHA, CHARLIE, competition=CUP)
        rows = self.rows([early, cup])
        self.assertEqual(sum(len(found) for found in rows.values()), 0)
        self.assertEqual(sum(len(found) for found in self.rows([self.top_v_middle], season=2020).values()), 0)


class ScorecardTests(HistoryCase):
    def test_our_matches_split_by_third_and_game_plan_beside_the_benchmark(self) -> None:
        review = build_match_review(self.history)
        scorecard = build_control_scorecard(self.history, review, [self.top_v_middle])
        by_key = {band.key: band for band in scorecard.bands}
        # Our one match with stats, at home to Alpha (top) on 1 September, in a Vertical 4-4-2.
        top = by_key["top"]
        self.assertEqual(top.ours.matches, 1)
        self.assertEqual(top.ours.values["possession"], 40.0)
        self.assertEqual(top.ours.values["sot_margin"], 4)
        self.assertEqual([(row.key, row.matches) for row in top.plans], [("counter", 1)])
        self.assertEqual(by_key["middle"].benchmark.matches, 1)
        self.assertEqual(scorecard.benchmark_matches, 1)
        self.assertFalse(top.ours.enough)

    def test_a_tactic_with_two_plans_counts_in_both_and_an_unknown_one_on_its_own(self) -> None:
        def summary(tactic_key):
            return SimpleNamespace(
                tactic_key=tactic_key, strength=SimpleNamespace(band=lambda _grouping: SimpleNamespace(key="bottom")),
                ours={"possession": 55.0, "pass_completion": 75.0, "corners": 5, "shots_on_target": 5,
                      "clear_cut_chances": 1},
                theirs={"possession": 45.0, "pass_completion": 70.0, "corners": 2, "shots_on_target": 2,
                        "clear_cut_chances": 1},
            )
        review = SimpleNamespace(
            matches=(summary("siege_442"), summary(None)), filters=SimpleNamespace(season=None),
            club=self.history.club,
        )
        scorecard = control_scorecard(review, (), self.history.league_results, MVP_CATALOGUE)
        bottom = next(band for band in scorecard.bands if band.key == "bottom")
        self.assertEqual(bottom.ours.matches, 2)
        self.assertEqual([(row.key, row.matches) for row in bottom.plans],
                         [("territorial", 1), ("direct", 1), ("unknown", 1)])
        self.assertFalse(scorecard.has_benchmark)


class OutputTests(HistoryCase):
    def test_the_export_text_and_json_carry_the_same_scorecard(self) -> None:
        review = build_match_review(self.history)
        scorecard = build_control_scorecard(self.history, review, [self.top_v_middle])
        text = format_control(scorecard)
        self.assertIn("Control against each third", text)
        self.assertIn("League top third", text)
        document = control_scorecard_json(scorecard)
        middle = next(row for row in document["by_opponent_third"] if row["third"] == "Middle third")
        self.assertEqual(middle["league_top_third"]["matches_with_full_stats"], 1)
        self.assertEqual(middle["league_top_third"]["possession"], 60.0)

    def test_the_season_export_includes_the_scorecard_after_the_trends(self) -> None:
        document = build_season_export(self.history, detail="basic", club_matches=[self.top_v_middle])
        keys = list(document)
        self.assertEqual(keys[keys.index("season_trends") + 1], "control_scorecard")
        self.assertIn("1 club-sides", document["control_scorecard"]["benchmark"])

    def test_without_club_matches_there_is_no_benchmark(self) -> None:
        document = build_season_export(self.history, detail="basic")
        self.assertIn("no benchmark", document["control_scorecard"]["benchmark"])
        self.assertTrue(all(row["league_top_third"] is None for row in document["control_scorecard"]["by_opponent_third"]))


if __name__ == "__main__":
    unittest.main()
