import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.chance_value import ChanceRates, KindRecord
from fm_analytics.analytics.experiments import experiment_report
from fm_analytics.domain.experiments import MatchLabel
from fm_analytics.domain.matches import MatchCapture, MatchRecord
from fm_analytics.experiment_ingest import (
    ALL_STORED, latest_played, main as fm_experiments, store_from_history, with_default_variant,
)
from fm_analytics.match_ingest import record_capture_file
from fm_analytics.persistence.experiments import ExperimentStore
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_experiment_export, build_match_export, build_match_report

from tests.match_support import ALPHA, BRAVO, US, capture_document, detail, lineup, match, season, team_stats

# A clear-cut chance is worth 0.4 of a goal, any other shot 0.1.
RATES = ChanceRates(10, KindRecord(10, 6, 4), KindRecord(100, 40, 10))


def replay(*, shots=(10, 10), chances=(1, 1), goals=(1, 1), tactic="Ball-Winning Counter 4-3-3 DM") -> MatchRecord:
    """The same fixture as `season()`'s detailed match, played with these team figures."""
    found = detail(
        home=team_stats(goals=goals[0], shots=shots[0], clear_cut_chances=chances[0]),
        away=team_stats(goals=goals[1], shots=shots[1], clear_cut_chances=chances[1]),
        players=lineup("home") + lineup("away"),
    )
    found["savedTactics"] = {"home": {"name": tactic, "slots": []}}
    return MatchRecord.from_document(match("2019-09-01", US, ALPHA, goals[0], goals[1], detail=found))


CLUB = MatchCapture.from_document(capture_document(season())).managed_club


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.store = ExperimentStore(self.directory / "experiments.sqlite3")

    def test_a_match_is_stored_once_labelled_and_can_join_and_leave_groups(self) -> None:
        self.store.create_group("Woking replays", "same fixture, different midfield")
        first = self.store.store(replay(), CLUB, MatchLabel("BWM", note="as usual", tags={"mentality": "balanced"}),
                                 groups=["Woking replays"])
        again = self.store.store(replay(), CLUB, MatchLabel("ignored"))
        second = self.store.store(replay(goals=(2, 0)), CLUB, MatchLabel("CM(D)"))
        self.assertEqual((first.added, again.added, again.match_id, second.added), (True, False, first.match_id, True))
        self.store.set_membership("Woking replays", [second.match_id], member=True)
        group = self.store.group("Woking replays")
        self.assertEqual([item.label.variant for item in group.matches], ["BWM", "CM(D)"])
        self.assertEqual(group.matches[0].label.tags, {"mentality": "balanced"})
        self.store.set_membership("Woking replays", [first.match_id], member=False)
        self.assertEqual([item.id for item in self.store.group("Woking replays").matches], [second.match_id])

    def test_relabelling_and_withdrawing_are_kept_as_later_rows_and_can_be_undone(self) -> None:
        stored = self.store.store(replay(), CLUB, MatchLabel("BWM"))
        self.store.relabel(stored.match_id, MatchLabel("BWM, CM(D) at half-time", note="changed at 46′"))
        self.store.relabel(stored.match_id, MatchLabel("BWM, CM(D) at half-time"), withdrawn=True)
        (current,) = self.store.matches()
        self.assertEqual((current.label.variant, current.withdrawn), ("BWM, CM(D) at half-time", True))
        self.store.relabel(stored.match_id, current.label, withdrawn=False)
        self.assertFalse(self.store.matches()[0].withdrawn)

    def test_deleting_removes_matches_from_every_group_for_good_and_all_or_nothing(self) -> None:
        self.store.create_group("Woking replays")
        first = self.store.store(replay(), CLUB, MatchLabel("BWM"), groups=["Woking replays"])
        second = self.store.store(replay(goals=(2, 0)), CLUB, MatchLabel("CM(D)"), groups=["Woking replays"])
        self.store.relabel(first.match_id, MatchLabel("BWM again"))
        with self.assertRaisesRegex(ValueError, "no stored match 99"):
            self.store.delete([first.match_id, 99])
        self.assertEqual(len(self.store.matches()), 2)  # nothing was deleted
        self.store.delete([first.match_id])
        self.assertEqual([item.id for item in self.store.matches()], [second.match_id])
        self.assertEqual([item.id for item in self.store.group("Woking replays").matches], [second.match_id])
        again = self.store.store(replay(), CLUB, MatchLabel("BWM"))
        self.assertTrue(again.added)  # stored afresh, with only its new label
        self.assertEqual(self.store.matches()[-1].label.variant, "BWM")

    def test_a_group_is_renamed_with_its_matches_and_deleting_it_keeps_them_stored(self) -> None:
        self.store.create_group("Woking replays", "first try")
        self.store.create_group("Other")
        stored = self.store.store(replay(), CLUB, MatchLabel("BWM"), groups=["Woking replays", "Other"])
        self.store.edit_group("Woking replays", "  Woking: midfield  ", "second try")
        group = self.store.group("Woking: midfield")
        self.assertEqual((group.note, [item.id for item in group.matches]), ("second try", [stored.match_id]))
        self.assertIsNone(self.store.group("Woking replays"))
        self.store.edit_group("Other", "Other", "just a note")  # keeping the name is fine
        with self.assertRaisesRegex(ValueError, "already a group"):
            self.store.edit_group("Other", "Woking: midfield", "")
        with self.assertRaisesRegex(ValueError, "no group"):
            self.store.edit_group("Nope", "Something", "")
        self.store.delete_group("Woking: midfield")
        self.assertEqual([group.name for group in self.store.groups()], ["Other"])
        self.assertEqual(self.store.matches()[0].groups, ("Other",))

    def test_a_match_without_stats_another_clubs_match_or_an_unknown_group_is_refused(self) -> None:
        bare = MatchRecord.from_document(match("2019-09-01", US, ALPHA, 1, 0))
        with self.assertRaisesRegex(ValueError, "stats"):
            self.store.store(bare, CLUB, MatchLabel("BWM"))
        with self.assertRaisesRegex(ValueError, "no group"):
            self.store.store(replay(), CLUB, MatchLabel("BWM"), groups=["Nope"])
        with self.assertRaisesRegex(ValueError, "label"):
            self.store.store(replay(), CLUB, MatchLabel("  "))


class ComparisonTests(unittest.TestCase):
    def stored(self, variants):
        store = ExperimentStore(Path(self.directory.name) / "experiments.sqlite3")
        for label, figures in variants:
            for shots, chances in figures:
                store.store(replay(shots=shots, chances=chances), CLUB, MatchLabel(label))
        return store.matches()

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_labels_are_compared_on_the_balance_of_chances_best_first(self) -> None:
        stored = self.stored([
            ("BWM", [((8, 14), (1, 2)), ((9, 13), (1, 1)), ((7, 15), (0, 2))]),
            ("CM(D)", [((10, 8), (2, 1)), ((11, 9), (2, 0)), ((12, 7), (1, 1))]),
        ])
        report = experiment_report("Woking replays", stored, RATES)
        best, other = report.variants
        self.assertEqual((best.variant, best.count, other.variant), ("CM(D)", 3, "BWM"))
        self.assertEqual(best.average("shots"), (11.0, 8.0))
        (comparison,) = report.comparisons
        self.assertEqual((comparison.variant, comparison.against, comparison.verdict), ("BWM", "CM(D)", "clear"))
        self.assertLess(comparison.difference, -comparison.margin)

    def test_a_small_or_noisy_difference_is_not_called_and_says_how_many_runs_would_settle_it(self) -> None:
        few = experiment_report("x", self.stored([("A", [((10, 10), (1, 1))]), ("B", [((11, 10), (1, 1))])]), RATES)
        self.assertEqual(few.comparisons[0].verdict, "too few runs")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        noisy = experiment_report("y", self.stored([
            ("A", [((14, 6), (3, 0)), ((6, 14), (0, 3)), ((10, 10), (1, 1))]),
            ("B", [((13, 7), (2, 0)), ((7, 13), (0, 2)), ((9, 11), (1, 1))]),
        ]), RATES)
        (comparison,) = noisy.comparisons
        self.assertEqual(comparison.verdict, "not clear yet")
        self.assertGreater(comparison.runs_needed, 3)


class ExportTests(unittest.TestCase):
    def test_each_match_is_exported_as_its_own_page_copies_it_with_the_comparison_and_withdrawn_ones_marked(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        capture = root / "capture.json"
        capture.write_text(json.dumps(capture_document(season())), encoding="utf-8")
        history_store = MatchHistoryStore(root / "history.sqlite3")
        record_capture_file(history_store, capture)
        history = history_store.load_history(history_store.latest_save_key())
        store = ExperimentStore(root / "experiments.sqlite3")
        real = store_from_history(store, history, "2019-09-01:100:201", MatchLabel("Vertical"))
        replays = [store.store(replay(shots=(8 + n, 10), goals=(n % 2, 1)), CLUB, MatchLabel("BWM")) for n in range(3)]
        store.relabel(replays[2].match_id, MatchLabel("BWM"), withdrawn=True)

        document = build_experiment_export(ALL_STORED, store.matches(), history)
        page_copy = build_match_export(history, build_match_report(history, "2019-09-01:100:201"))["match"]
        first = document["matches"][0]
        self.assertEqual((first["stored_match_id"], first["label"]), (real.match_id, "Vertical"))
        self.assertEqual(first["match"], page_copy)  # exactly what the match page's copy holds
        self.assertIn("result_vs_chances", first["match"]["diagnosis"])
        self.assertIn("timeline", first["match"])
        self.assertEqual(document["group"], {"name": ALL_STORED, "note": "", "matches": 4, "compared": 3, "withdrawn": 1})
        withdrawn = document["matches"][3]
        self.assertEqual((withdrawn["withdrawn"], withdrawn["figures"]), (True, None))
        self.assertEqual(withdrawn["match"]["date"], "2019-09-01")  # still listed in full
        bwm = next(variant for variant in document["variants"] if variant["label"] == "BWM")
        self.assertEqual(bwm["stored_match_ids"], [replays[0].match_id, replays[1].match_id])
        self.assertIn("by_period", bwm["breakdowns"])
        self.assertEqual(bwm["players"][0]["apps"], 2)  # each label's own player lines
        self.assertIn("by_period", document["breakdowns"])
        self.assertEqual(document["players"][0]["apps"], 3)  # three matches compared
        self.assertEqual(json.loads(json.dumps(document)), document)  # plain JSON throughout


class IngestTests(unittest.TestCase):
    def test_the_match_just_played_is_the_latest_and_its_label_defaults_to_fms_tactic_name(self) -> None:
        capture = MatchCapture.from_document(capture_document(season()))
        self.assertEqual(latest_played(capture).key, "2019-09-01:100:201")
        with self.assertRaisesRegex(ValueError, "2019-08-10 Bravo v Hungerford Town could not be read"):
            latest_played(capture, "2019-08-10:202:100")
        # Without its stats the latest match is refused, never swapped for an earlier one.
        later = MatchCapture.from_document(capture_document(season() + [match("2019-09-07", BRAVO, US, 1, 0)]))
        with self.assertRaisesRegex(ValueError, "2019-09-07 Bravo v Hungerford Town could not be read"):
            latest_played(later)
        label = with_default_variant(MatchLabel(""), replay(tactic="Vertical 4-4-2"), US["id"])
        self.assertEqual(label.variant, "Vertical 4-4-2")
        self.assertEqual(with_default_variant(MatchLabel("Mine"), replay(), US["id"]).variant, "Mine")

    def test_the_command_line_stores_from_the_history_groups_compares_and_exports_without_touching_the_history(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        capture = root / "capture.json"
        capture.write_text(json.dumps(capture_document(season())), encoding="utf-8")
        history = MatchHistoryStore(root / "history.sqlite3")
        record_capture_file(history, capture)
        before = (root / "history.sqlite3").read_bytes()

        def run(*args: str) -> str:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                fm_experiments(["--db", str(root / "experiments.sqlite3"), "--history", str(root / "history.sqlite3"), *args])
            return out.getvalue()

        self.assertIn("Done.", run("group", "create", "Alpha tests"))
        self.assertIn("Stored as #1.", run("store-history", "2019-09-01:100:201", "--label", "Vertical", "--group",
                                           "Alpha tests", "--tag", "mentality=positive", "--note", "real match"))
        self.assertIn("Alpha tests: 1 matches", run("list"))
        self.assertIn("Vertical", run("compare", "Alpha tests"))
        exported = json.loads(run("export", "Alpha tests"))
        self.assertEqual(exported["matches"][0]["tags"], {"mentality": "positive"})
        self.assertEqual(exported["matches"][0]["match"]["date"], "2019-09-01")
        self.assertIn("withdrawn", run("withdraw", "1") + run("list"))
        self.assertIn("Done.", run("group", "rename", "Alpha tests", "--to", "Alpha replays"))
        self.assertIn("groups: Alpha replays", run("list"))
        self.assertIn("Done.", run("group", "delete", "Alpha replays"))
        self.assertIn("#1: played in Balanced; Cautious from 70′.", run("mentality", "1", "--set", "Balanced, 70 Cautious"))
        self.assertIn("Vertical (Balanced; Cautious from 70′) (withdrawn)", run("list"))
        self.assertIn("Deleted #1: 2019-09-01 v Alpha, Vertical.", run("delete", "1"))
        self.assertIn("No stored matches yet.", run("list"))
        self.assertIn("error: no stored match 1", run("delete", "1"))
        self.assertEqual((root / "history.sqlite3").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
