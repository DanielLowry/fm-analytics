import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from fm_analytics.domain.mentality import MentalityPlan
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
        self.assertIn('href="/experiments" class="active" data-fm-nav-link', body)  # in the sidebar
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
        self.assertIn("<td><span class='fm-label-cell'>Vertical</span></td><td>1</td>", body)
        self.assertIn("Copy all match data", body)
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

    def test_matches_are_deleted_after_a_second_click_and_groups_renamed_or_deleted(self) -> None:
        port = self.serve()
        self._post(port, "/experiments/store-history", f"match={quote(DETAILED)}&label=A&new_group=Trial")
        _status, body = self._get(port, "/experiments/match/1")
        self.assertIn("<summary>Delete…</summary>", body)
        self.assertIn(">Delete #1 permanently</button>", body)
        _status, body = self._get(port, "/experiments/group/Trial")
        self.assertIn("<h2>Rename or delete this group</h2>", body)
        self.assertIn(">Delete #1 permanently</button>", body)
        status, location, _body = self._post(port, "/experiments/group/edit", "name=Trial&new_name=Woking+replays&note=midfield")
        self.assertEqual((status, location), (303, "/experiments/group/Woking%20replays"))
        self.assertEqual(self.store.group("Woking replays").note, "midfield")
        status, _location, body = self._post(port, "/experiments/group/edit", "name=Nope&new_name=X&note=")
        self.assertEqual(status, 400)
        status, location, _body = self._post(port, "/experiments/delete", "id=1&back=Woking+replays")
        self.assertEqual((status, location), (303, "/experiments/group/Woking%20replays"))
        self.assertEqual(self.store.matches(), ())
        _status, body = self._get(port, "/experiments/group/" + quote("Woking replays"))
        self.assertIn("Deleted #1 for good.", body)
        status, location, _body = self._post(port, "/experiments/group/delete", "name=Woking+replays")
        self.assertEqual((status, location), (303, "/experiments"))
        self.assertEqual(self.store.groups(), ())
        _status, body = self._get(port, "/experiments")
        self.assertIn("Deleted the group &#x27;Woking replays&#x27;; its matches are still stored.", body)
        self._post(port, "/experiments/store-history", f"match={quote(DETAILED)}&label=B")
        _status, body = self._get(port, "/experiments")
        self.assertIn("formaction='/experiments/delete'", body)  # ticked matches can be deleted with no group
        status, _location, body = self._post(port, "/experiments/delete", "back=")
        self.assertEqual(status, 400)
        self.assertIn("Tick at least one", body)
        _status, body = self._get(port, "/experiments/all")
        self.assertNotIn("Rename or delete this group", body)

    def test_the_mentality_is_set_for_ticked_matches_kept_by_edits_and_copied_from_the_history(self) -> None:
        self.history.record_mentality("club:100", DETAILED, MentalityPlan.parse("Balanced"))
        port = self.serve()
        self._post(port, "/experiments/store-history", f"match={quote(DETAILED)}&label=A")
        (stored,) = self.store.matches()
        self.assertEqual(stored.label.mentality, MentalityPlan.parse("Balanced"))  # as recorded on its page
        _status, body = self._get(port, "/experiments")
        self.assertIn("<td>Balanced</td>", body)
        self.assertIn("formaction='/experiments/mentality'", body)
        status, _location, _body = self._post(
            port, "/experiments/mentality", "id=1&mentality=Attacking&change_minute=75&change_mentality=Balanced")
        self.assertEqual(status, 303)
        self.assertEqual(self.store.matches()[0].label.mentality.text, "Attacking; Balanced from 75′")
        self.assertEqual(self.store.matches()[0].label.variant, "A")  # the rest of the label is kept
        _status, body = self._get(port, "/experiments/all")
        self.assertIn("<br><span class='muted'>Attacking; Balanced from 75′</span>", body)
        # Withdrawing from Edit posts the mentality fields as shown, so it is kept.
        self._post(port, "/experiments/relabel", "id=1&label=A&withdraw=1&mentality=Attacking"
                                                 "&change_minute=75&change_mentality=Balanced")
        self.assertEqual(self.store.matches()[0].label.mentality.text, "Attacking; Balanced from 75′")
        status, _location, body = self._post(port, "/experiments/mentality", "id=1&mentality=")
        self.assertEqual(status, 400)
        self.assertIn("Choose the mentality at kickoff first.", body)
        self._post(port, "/experiments/mentality", "id=1&clear=1")
        self.assertIsNone(self.store.matches()[0].label.mentality)


if __name__ == "__main__":
    unittest.main()
