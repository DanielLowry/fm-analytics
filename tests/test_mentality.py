import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.match_breakdowns import breakdowns, score_split
from fm_analytics.domain.matches import MatchCapture
from fm_analytics.domain.mentality import MentalityPlan
from fm_analytics.match_ingest import main as fm_matches
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_match_breakdowns, build_match_export, build_match_report, build_match_review

from tests.match_support import capture_document, season
from tests.test_match_breakdowns import STRIKER, THEIR_STRIKER, goal, record, shot

KEY = "club:100"
DETAILED = "2019-09-01:100:201"


def season_with_shots() -> list[dict]:
    """`season()`, its detailed 2-1 with goal times and shots, so it can be split."""
    matches = season()
    found = matches[-1]
    found["incidents"] = [goal(12, "home", STRIKER), goal(50, "away", THEIR_STRIKER), goal(90, "home", STRIKER, added=3)]
    found["detail"]["shots"] = [shot("home", STRIKER, 11, 30), shot("away", THEIR_STRIKER, 49, 10),
                                shot("away", THEIR_STRIKER, 75, 0), shot("home", STRIKER, 92, 0)]
    return matches


class PlanTests(unittest.TestCase):
    def test_a_plan_is_read_from_text_or_form_fields_and_says_what_was_in_use_when(self) -> None:
        plan = MentalityPlan.parse("balanced, 65 Cautious; 80′ positive")
        self.assertEqual(plan.changes, ((0, "Balanced"), (65, "Cautious"), (80, "Positive")))
        self.assertEqual(plan, MentalityPlan.build("Balanced", [(80, "Positive"), (65, "cautious")]))
        self.assertEqual(plan.text, "Balanced; Cautious from 65′; Positive from 80′")
        self.assertEqual([plan.at(minute) for minute in (0, 64.9, 65, 80, 95)],
                         ["Balanced", "Balanced", "Cautious", "Positive", "Positive"])
        self.assertEqual(MentalityPlan.from_document(plan.to_document()), plan)

    def test_a_plan_that_could_not_have_been_played_is_refused(self) -> None:
        for text, message in (("", "at kickoff"), ("Brave", "not one of FM's"), ("Balanced, 65 Balanced", "already in use"),
                              ("Balanced, 65 Cautious, 65 Positive", "same minute"), ("Balanced, 130 Cautious", "up to 120"),
                              ("Balanced, Cautious", "a minute then a mentality")):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                MentalityPlan.parse(text)


class SplitTests(unittest.TestCase):
    def test_a_match_is_split_by_the_mentality_in_use_and_by_mentality_and_score(self) -> None:
        # 1-0 up from the 20th minute; Cautious from 60′.
        found = record(
            home_goals=1, away_goals=0, incidents=[goal(20, "home", STRIKER)],
            shots=[shot("home", STRIKER, 19, 30), shot("away", THEIR_STRIKER, 40, 0),
                   shot("away", THEIR_STRIKER, 70, 0), shot("away", THEIR_STRIKER, 75, 0)],
        )
        plan = MentalityPlan.parse("Balanced, 60 Cautious")
        split = score_split(found, "home", plan)
        self.assertEqual(list(split.by_mentality), ["Cautious", "Balanced"])  # FM's order, most defensive first
        self.assertEqual(round(split.by_mentality["Balanced"].minutes), 60)
        self.assertEqual(split.by_mentality["Balanced"].shots, [1, 1])
        self.assertEqual(split.by_mentality["Cautious"].shots, [0, 2])
        self.assertEqual(split.by_mentality_state[("Cautious", "ahead")].shots, [0, 2])
        self.assertEqual(round(split.by_mentality_state[("Balanced", "ahead")].minutes), 40)
        self.assertEqual(split.by_mentality["Balanced"].goals, [1, 0])
        self.assertEqual(score_split(found, "home").by_mentality, {})  # nothing recorded, nothing split

        totals = breakdowns([found, found], "100", plans=[plan, None])
        self.assertEqual(totals.mentality_matches, 1)
        self.assertEqual(totals.by_mentality["Cautious"].shots, [0, 2])
        self.assertEqual(totals.by_state["ahead"].shots, [0, 6])  # the score split still counts both


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "history.sqlite3"
        self.store = MatchHistoryStore(self.database)
        self.capture = capture_document(season_with_shots())
        self.store.record(MatchCapture.from_document(self.capture), save_key=KEY)

    def test_a_recorded_mentality_survives_reading_fm_again_and_reaches_every_view(self) -> None:
        plan = MentalityPlan.parse("Positive, 70 Balanced")
        self.store.record_mentality(KEY, DETAILED, plan)
        later = season_with_shots()
        later[-1]["attendance"] = 1234  # a later read of FM with a new version of the match itself
        result = self.store.record(MatchCapture.from_document(capture_document(later, game_date="2019-09-20")), save_key=KEY)
        self.assertEqual((result.skipped, result.versions_added), (False, 1))
        history = self.store.load_history(KEY)
        self.assertEqual(history.mentalities, {DETAILED: plan})

        report = build_match_report(history, DETAILED)
        self.assertEqual(report.summary.mentality, plan)
        self.assertIn("Positive", report.timeline.by_score.by_mentality)
        entry = build_match_export(history, report)["match"]
        self.assertEqual(entry["mentality"], [{"from": 0, "mentality": "Positive"}, {"from": 70, "mentality": "Balanced"}])
        self.assertEqual(entry["mentality_text"], "Positive; Balanced from 70′")
        self.assertIn("by_mentality", entry)
        found = build_match_breakdowns(history, build_match_review(history))
        self.assertEqual(found.mentality_matches, 1)

        self.store.record_mentality(KEY, DETAILED, None)
        self.assertEqual(self.store.load_history(KEY).mentalities, {})
        with self.assertRaisesRegex(ValueError, "no match"):
            self.store.record_mentality(KEY, "2019-09-02:100:201", plan)

    def test_the_command_line_records_shows_and_clears_it(self) -> None:
        def run(*args: str) -> str:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                fm_matches(["--db", str(self.database), "--save", KEY, *args])
            return out.getvalue()

        self.assertIn("Recorded: Balanced; Cautious from 65′.", run("mentality", DETAILED, "Balanced, 65 Cautious"))
        self.assertIn("Mentality: Balanced; Cautious from 65′", run("show", DETAILED))
        self.assertIn("By mentality and the score", run("review"))
        self.assertIn("Cleared.", run("mentality", DETAILED, "--clear"))
        self.assertIn("Mentality: not recorded", run("show", DETAILED))
        self.assertIn("not one of FM's mentalities", run("mentality", DETAILED, "Brave"))


if __name__ == "__main__":
    unittest.main()
