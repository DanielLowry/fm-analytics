import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from fm_analytics.match_ingest import record_capture_file
from fm_analytics.persistence.experiments import ExperimentStore
from fm_analytics.persistence.match_history import MatchHistoryStore

from tests.match_support import capture_document, season
from tests.web_support import FIXTURE, WebServerHelpers

DETAILED = "2019-09-01:100:201"


class ExperimentPagesTests(WebServerHelpers, unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.history = MatchHistoryStore(root / "history.sqlite3")
        capture = root / "capture.json"
        capture.write_text(json.dumps(capture_document(season())), encoding="utf-8")
        record_capture_file(self.history, capture)
        self.store = ExperimentStore(root / "experiments.sqlite3")

    def serve(self) -> int:
        return self._serve(FIXTURE, match_store=self.history, match_capture=lambda: "read",
                           experiment_store=self.store)

    def test_a_match_is_stored_only_when_asked_then_grouped_compared_and_shown_on_its_own_page(self) -> None:
        port = self.serve()
        _status, body = self._get(port, "/experiments")
        self.assertIn("Nothing is stored here unless you ask", body)
        self.assertIn("needs fm-web started with <code>--direct-live</code>", body)  # this server can't read FM
        self.assertEqual(self.store.matches(), ())
        _status, body = self._get(port, "/matches/" + quote(DETAILED, safe=""))
        self.assertIn("Store this match for experiments", body)
        status, location, _body = self._post(
            port, "/experiments/store-history",
            f"match={quote(DETAILED)}&label=Vertical&tactic=&note=real&tags=mentality%3Dpositive&new_group=Alpha+tests",
        )
        self.assertEqual((status, location), (303, "/experiments/match/1"))
        (stored,) = self.store.matches()
        self.assertEqual((stored.label.variant, stored.label.tags, stored.groups), ("Vertical", {"mentality": "positive"}, ("Alpha tests",)))
        _status, body = self._get(port, "/experiments/match/1")
        self.assertIn("Stored match #1, labelled <strong>Vertical</strong>, in Alpha tests", body)
        self.assertNotIn("action='/matches/note'", body)  # a stored match never saves to the history
        _status, body = self._get(port, "/experiments/group/" + quote("Alpha tests"))
        self.assertIn("<h2>By label</h2>", body)
        self.assertIn("<td>Vertical</td><td>1</td>", body)
        self.assertIn("Copy experiment to clipboard", body)
        status, location, _body = self._post(port, "/experiments/relabel", "id=1&label=Vertical+2&back=Alpha+tests&withdraw=1")
        self.assertEqual(status, 303)
        self.assertTrue(self.store.matches()[0].withdrawn)
        _status, body = self._get(port, "/experiments")
        self.assertIn(">Restore</button>", body)

    def test_matches_are_put_in_a_group_and_taken_out_from_the_list(self) -> None:
        port = self.serve()
        self._post(port, "/experiments/store-history", f"match={quote(DETAILED)}&label=A")
        self._post(port, "/experiments/group", "name=Trial&note=")
        status, _location, _body = self._post(port, "/experiments/membership", "group=Trial&member=1&id=1")
        self.assertEqual(status, 303)
        self.assertEqual(self.store.group("Trial").matches[0].id, 1)
        self._post(port, "/experiments/membership", "group=Trial&member=0&id=1")
        self.assertEqual(self.store.group("Trial").matches, ())
        status, _location, body = self._post(port, "/experiments/membership", "group=Trial&member=1")
        self.assertEqual(status, 400)
        self.assertIn("Tick at least one", body)


if __name__ == "__main__":
    unittest.main()
