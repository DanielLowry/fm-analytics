"""The Opponent page and `fm-matches opponent`: both render the one `reporting.build_opponent_report`."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fm_analytics.match_ingest import main, record_capture_file
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.reporting import build_opponent_export, build_opponent_report

from tests.match_support import ALPHA, LEAGUE, US, capture_document, season
from tests.test_opponent_report import alpha_season
from tests.web_support import FIXTURE, WebServerHelpers


def capture_with_opponents(*, fixtures: bool = True) -> dict:
    document = capture_document(season())
    document["clubMatches"] = [match.to_document() for match in alpha_season()]
    if fixtures:
        document["fixtures"] = [{"date": "2019-09-08", "competition": LEAGUE, "home": ALPHA, "away": US, "season": 2019}]
    return document


class OpponentCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.db = self.directory / "history.sqlite3"
        self.store = MatchHistoryStore(self.db)
        self.capture = self.directory / "capture.json"

    def record(self, **options) -> None:
        self.capture.write_text(json.dumps(capture_with_opponents(**options)), encoding="utf-8")
        record_capture_file(self.store, self.capture)

    def shared_report(self, **options):
        key = self.store.latest_save_key()
        return build_opponent_report(self.store.load_history(key), self.store.load_club_matches(key),
                                     fixtures=self.store.load_fixtures(key), **options)


class OpponentPageTests(WebServerHelpers, OpponentCase):
    def serve(self) -> int:
        return self._serve(FIXTURE, match_store=self.store)

    def test_with_no_history_the_page_says_how_to_start(self) -> None:
        status, body = self._get(self.serve(), "/opponent")
        self.assertEqual(status, 200)
        self.assertIn("No matches are recorded yet", body)
        self.assertIn('href="/opponent" class="active"', body)

    def test_the_page_is_on_the_next_opponent_with_every_section(self) -> None:
        self.record()
        status, body = self._get(self.serve(), "/opponent")
        self.assertEqual(status, 200)
        self.assertIn("<h2>Alpha</h2>", body)
        self.assertIn("Sunday 8 September 2019", body)
        for heading in ("What to take from it", "Suggested opposition instructions", "Their shape",
                        "Who finishes, who supplies", "How their goals come", "Style", "Against us"):
            self.assertIn(heading, body)
        self.assertIn("fm-opp-pitch", body)
        self.assertIn("Copy report to clipboard", body)
        # The same striker the shared computation finds, with the same goals.
        striker = self.shared_report().finishers[0]
        self.assertIn(f"<td>{striker.name}</td><td>ST</td><td><b>{striker.goals}</b></td>", body)

    def test_a_club_and_window_can_be_picked_and_bad_ones_are_refused(self) -> None:
        self.record()
        port = self.serve()
        status, body = self._get(port, f"/opponent?club={ALPHA['id']}&window=10")
        self.assertEqual(status, 200)
        self.assertIn("<option value='10' selected>Last 10</option>", body)
        self.assertEqual(self._get(port, "/opponent?window=7")[0], 400)
        self.assertEqual(self._get(port, "/opponent?club=999")[0], 404)

    def test_without_a_fixture_list_the_page_offers_the_clubs(self) -> None:
        self.record(fixtures=False)
        status, body = self._get(self.serve(), "/opponent")
        self.assertEqual(status, 200)
        self.assertIn("fixture list has not been read yet", body)
        self.assertIn(f"<option value='{ALPHA['id']}'>Alpha</option>", body)


class OpponentCommandTests(OpponentCase):
    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--db", str(self.db), *args])
        return code, output.getvalue()

    def test_the_command_prints_the_shared_report_on_the_next_opponent(self) -> None:
        self.record()
        code, text = self.run_cli("opponent", "--league", str(self.directory / "none.json"))
        self.assertEqual(code, 0)
        self.assertIn("Opponent report: Alpha", text)
        self.assertIn("For Alpha v Hungerford Town, 2019-09-08", text)
        striker = self.shared_report().finishers[0]
        self.assertIn(f"{striker.name:<26} ST   {striker.goals:>2}", text)
        self.assertIn("Suggested opposition instructions:", text)

    def test_a_club_is_named_by_part_of_its_name_and_json_is_the_pages_copy(self) -> None:
        self.record()
        code, text = self.run_cli("opponent", "alp", "--json", "--league", str(self.directory / "none.json"))
        self.assertEqual(code, 0)
        document = json.loads(text)
        expected = build_opponent_export(self.shared_report(club_id=ALPHA["id"]))
        self.assertEqual({key: value for key, value in document.items() if key != "generated_at"},
                         {key: value for key, value in expected.items() if key != "generated_at"})
        code, text = self.run_cli("opponent", "Nobody")
        self.assertEqual(code, 1)
        self.assertIn("names no club", text)


if __name__ == "__main__":
    unittest.main()
