import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.client import HTTPConnection
from pathlib import Path

from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.knowledge_ingest import (
    capture_from_document,
    default_save_key,
    main,
    record_capture_file,
)
from fm_analytics.persistence.player_knowledge import PlayerKnowledgeStore, RecordResult
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.rendering import _knowledge_notice
from fm_analytics.web.server import SquadWebServer

FIXTURE = Path(__file__).resolve().parent.parent / "src/fm_analytics/fixtures/sample-game.json"


def document(game_date="2019-09-08", captured_at="2026-09-26T19:00:00+00:00", players=None):
    return {
        "schemaVersion": 2,
        "capturedAt": captured_at,
        "gameDate": game_date,
        "source": {"managedClub": {"id": "5103652", "name": "Hungerford Town"}},
        "players": players if players is not None else [scouted(), dropped()],
    }


def scouted(pace=None, observed="2019-09-08"):
    return {
        "id": "10", "name": "Ada Winger", "positions": ["AML"], "age": 21,
        "club": "Billericay Town", "hasContract": True, "contractType": "part_time",
        "contractEnd": "2020-06-30", "transferStatus": "not_set", "value": 5000,
        "transferInterest": "yes", "scoutingKnowledge": 60,
        "attributesObservedAt": observed,
        "attributes": {
            "pace": pace or {"visibility": "range", "minimum": 12, "maximum": 16},
            "passing": {"visibility": "known", "value": 11},
            "vision": {"visibility": "unknown"},
        },
    }


def dropped():
    return {
        "id": "11", "name": "Bob Winger", "positions": [], "droppedFromScoutReports": True,
        "scoutingKnowledge": 30, "attributes": {},
        "lastKnownAttributes": {"pace": {"visibility": "range", "minimum": 8, "maximum": 12}},
        "lastKnownAttributesObservedAt": "2019-07-21",
    }


class CaptureFromDocumentTests(unittest.TestCase):
    def test_the_save_is_named_after_the_managed_club(self) -> None:
        self.assertEqual(default_save_key(document()), "club:5103652")
        self.assertEqual(capture_from_document(document()).club_name, "Hungerford Town")

    def test_a_capture_that_does_not_name_a_club_needs_an_explicit_save(self) -> None:
        bare = {**document(), "source": {}}
        with self.assertRaisesRegex(ValueError, "explicit save key"):
            capture_from_document(bare)
        self.assertEqual(capture_from_document(bare, save_key="mine").save_key, "mine")

    def test_a_capture_without_a_game_date_is_refused(self) -> None:
        bare = document()
        del bare["gameDate"]
        with self.assertRaisesRegex(ValueError, "gameDate"):
            capture_from_document(bare)

    def test_profile_facts_and_attributes_come_through_unchanged(self) -> None:
        winger = capture_from_document(document()).players[0]
        self.assertEqual(winger.player_id, "10")
        self.assertEqual(winger.profile["club"], "Billericay Town")
        self.assertEqual(winger.profile["contract_end"], "2020-06-30")
        self.assertEqual(winger.attributes["pace"], AttributeObservation(Visibility.RANGE, minimum=12, maximum=16))
        self.assertEqual(winger.attributes["vision"], AttributeObservation(Visibility.UNKNOWN))
        self.assertEqual(winger.attributes_observed_on, "2019-09-08")

    def test_a_dropped_player_carries_his_last_known_sheet_with_its_date(self) -> None:
        bob = capture_from_document(document()).players[1]
        self.assertEqual(bob.attributes, {})
        self.assertEqual(bob.last_known_observed_on, "2019-07-21")
        self.assertIs(bob.profile["dropped_from_scout_reports"], True)


class RecordFileTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.store = PlayerKnowledgeStore(self.directory / "k.sqlite3")

    def write(self, name: str, doc: dict) -> Path:
        path = self.directory / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_recording_a_file_then_a_refresh_with_nothing_new_adds_nothing(self) -> None:
        path = self.write("a.json", document())
        first = record_capture_file(self.store, path)
        self.assertEqual((first.players_seen, first.new_players), (2, 2))
        path = self.write("a.json", document(captured_at="2026-09-27T09:00:00+00:00"))
        self.assertTrue(record_capture_file(self.store, path).skipped)

    def test_a_later_refresh_records_only_what_moved(self) -> None:
        record_capture_file(self.store, self.write("a.json", document()))
        narrowed = {"visibility": "range", "minimum": 13, "maximum": 15}
        later = document(
            "2019-09-15", players=[scouted(pace=narrowed, observed="2019-09-15"), dropped()]
        )
        result = record_capture_file(self.store, self.write("b.json", later))
        # Only pace moved: passing and vision are unchanged, and so is Bob.
        self.assertEqual(result.attribute_rows, 1)
        history = self.store.attribute_history("club:5103652", "10", "pace")
        self.assertEqual(
            [(item.observed_on, item.observation.minimum, item.observation.maximum) for item in history],
            [("2019-09-08", 12, 16), ("2019-09-15", 13, 15)],
        )

    def test_a_file_that_is_not_a_capture_is_an_error(self) -> None:
        path = self.write("bad.json", [])
        with self.assertRaises(ValueError):
            record_capture_file(self.store, path)


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.db = str(self.directory / "k.sqlite3")

    def write(self, name: str, doc: dict) -> str:
        path = self.directory / name
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    def run_cli(self, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--db", self.db, *args])
        return code, output.getvalue()

    def test_captures_are_recorded_oldest_game_date_first_whatever_order_they_are_given(self) -> None:
        newer = self.write("newer.json", document("2019-09-08"))
        older = self.write("older.json", document("2019-06-24", players=[scouted()]))
        code, text = self.run_cli("ingest", newer, older)
        self.assertEqual(code, 0, text)
        self.assertLess(text.index("older.json"), text.index("newer.json"))

    def test_status_summarises_each_save(self) -> None:
        self.run_cli("ingest", self.write("a.json", document()))
        code, text = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("club:5103652 (Hungerford Town): 2 players", text)

    def test_status_on_an_empty_database_says_so(self) -> None:
        code, text = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("No saves recorded", text)

    def test_a_capture_from_before_the_save_is_an_error_unless_rewind_is_allowed(self) -> None:
        self.run_cli("ingest", self.write("now.json", document("2019-09-08")))
        earlier = self.write("earlier.json", document("2019-09-01", players=[scouted()]))
        code, text = self.run_cli("ingest", earlier)
        self.assertEqual(code, 1)
        self.assertIn("already holds 2019-09-08", text)
        code, text = self.run_cli("ingest", earlier, "--allow-rewind")
        self.assertEqual(code, 0, text)

    def test_a_named_save_keeps_its_own_history(self) -> None:
        path = self.write("a.json", document())
        self.run_cli("ingest", path)
        self.run_cli("ingest", path, "--save", "second-save")
        _, text = self.run_cli("status")
        self.assertIn("club:5103652", text)
        self.assertIn("second-save", text)


class WebRecordingTests(unittest.TestCase):
    def make_server(self, recorder):
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(FIXTURE),
            scouting_refresh=lambda **_options: "refreshed",
            knowledge_recorder=recorder,
        )
        self.addCleanup(server.server_close)
        return server

    def test_a_successful_refresh_records_and_remembers_the_result(self) -> None:
        calls = []

        def recorder():
            calls.append(1)
            return RecordResult("club:1", "2019-09-08", skipped=True)

        server = self.make_server(recorder)
        self.assertEqual(server.refresh_scouting(), "refreshed")
        self.assertEqual(calls, [1])
        message, ok = server.knowledge_note
        self.assertTrue(ok)
        self.assertIn("nothing new", message)

    def test_a_recording_failure_does_not_fail_the_refresh_but_is_not_hidden(self) -> None:
        def recorder():
            raise OSError("disk full")

        server = self.make_server(recorder)
        with redirect_stderr(io.StringIO()) as printed:
            self.assertEqual(server.refresh_scouting(), "refreshed")
        self.assertIn("NOT recorded", printed.getvalue())  # also reaches the console
        message, ok = server.knowledge_note
        self.assertFalse(ok)
        self.assertIn("NOT recorded", message)
        self.assertIn("disk full", message)

    def test_a_failed_capture_is_not_recorded(self) -> None:
        def failing_refresh(**_options):
            raise RuntimeError("FM is not running")

        calls = []
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(FIXTURE),
            scouting_refresh=failing_refresh,
            knowledge_recorder=lambda: calls.append(1),
        )
        self.addCleanup(server.server_close)
        with self.assertRaises(RuntimeError):
            server.refresh_scouting()
        self.assertEqual(calls, [])
        self.assertIsNone(server.knowledge_note)

    def test_without_a_recorder_nothing_happens(self) -> None:
        server = self.make_server(None)
        server.record_knowledge()
        self.assertIsNone(server.knowledge_note)

    def test_the_scouting_page_shows_a_failure_to_keep_history(self) -> None:
        server = self.make_server(lambda: (_ for _ in ()).throw(OSError("read-only file system")))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        with redirect_stderr(io.StringIO()):
            server.record_knowledge()
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/scouting")
        body = connection.getresponse().read().decode("utf-8")
        connection.close()
        self.assertIn("Player knowledge was NOT recorded", body)
        self.assertIn("read-only file system", body)

    def test_notice_escapes_its_message_and_is_empty_when_there_is_none(self) -> None:
        self.assertEqual(_knowledge_notice(None), "")
        self.assertIn("&lt;b&gt;", _knowledge_notice(("<b>x</b>", False)))


if __name__ == "__main__":
    unittest.main()
