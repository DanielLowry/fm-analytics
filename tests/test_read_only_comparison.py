"""Old-save comparisons must never change the application's databases."""
import hashlib
import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from fm_analytics.cli import load_fixture
from fm_analytics.persistence import SnapshotStore, SnapshotStoreError
from fm_analytics.web.server import _build_provider, build_parser, main
from tests.web_support import FIXTURE, WebServerHelpers, write_complete_fixture


class ReadOnlyStartupTests(unittest.TestCase):
    def test_startup_never_opens_history_stores_or_ingests_existing_captures(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stale_capture = root / "capture.json"
            stale_capture.write_text('{"players": []}')
            paths = [root / f"{kind}.sqlite3" for kind in ("knowledge", "matches", "league")]
            for path in paths:
                path.write_bytes(b"An existing database must remain untouched")
            before = {path: path.read_bytes() for path in paths}
            for name in ("PlayerKnowledgeStore", "MatchHistoryStore", "LeagueHistoryStore",
                         "record_capture_file", "record_match_capture", "capture_and_record"):
                stack.enter_context(patch("fm_analytics.web.server." + name, side_effect=AssertionError(name + " must not run")))
            stack.enter_context(patch("fm_analytics.web.server.DEFAULT_MATCH_CAPTURE", stale_capture))
            stack.enter_context(patch("fm_analytics.web.server._default_scouting_path", return_value=stale_capture))
            stack.enter_context(patch("fm_analytics.web.server.TacticRankingExecutor"))
            stack.enter_context(patch("fm_analytics.web.server.threading.Thread"))
            server_class = stack.enter_context(patch("fm_analytics.web.server.SquadWebServer"))
            self.assertEqual(main([
                "--direct-live", "--read-only", "--league-json", str(stale_capture),
                "--knowledge-db", str(paths[0]), "--match-db", str(paths[1]), "--league-db", str(paths[2]),
            ]), 0)
            options = server_class.call_args.kwargs
            self.assertTrue(options["read_only"])
            for name in ("knowledge_store", "knowledge_recorder", "match_store", "match_capture",
                         "league_store", "league_capture", "scouting_refresh"):
                self.assertIsNone(options[name], name)
            self.assertEqual(options["scouting_provider"](), ())
            server_class.return_value.record_knowledge.assert_not_called()
            self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_read_only_snapshot_loads_an_older_capture_without_touching_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshots.sqlite3"
            game, squad = load_fixture(FIXTURE)
            old_date = date(2011, 6, 24)
            old_game, old_squad = replace(game, game_date=old_date), replace(squad, as_of_date=old_date)
            old = SnapshotStore(path).capture(old_game, old_squad, source="old-save")
            SnapshotStore(path).capture(game, squad, source="new-save")
            before = (hashlib.sha256(path.read_bytes()).digest(), path.stat().st_mtime_ns, set(path.parent.iterdir()))
            args = build_parser().parse_args(["--snapshot-db", str(path), "--capture-id", str(old.id), "--read-only"])
            provider = _build_provider(args)
            self.assertEqual(provider(), (old_game, old_squad))
            self.assertEqual(provider(), (old_game, old_squad))
            readonly = SnapshotStore(path, read_only=True)
            with self.assertRaises(SnapshotStoreError):
                readonly.capture(game, squad, source="should-not-write")
            with closing(readonly._connect()) as connection:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM captures")
            after = (hashlib.sha256(path.read_bytes()).digest(), path.stat().st_mtime_ns, set(path.parent.iterdir()))
            self.assertEqual(after, before)

    def test_read_only_does_not_create_a_missing_snapshot_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing" / "snapshots.sqlite3"
            args = build_parser().parse_args(["--snapshot-db", str(path), "--read-only"])
            with self.assertRaisesRegex(SystemExit, "read-only"):
                _build_provider(args)
            self.assertFalse(path.parent.exists())

    def test_read_only_refuses_schema_upgrades_without_writing_a_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE original (value TEXT)")
                connection.execute("PRAGMA user_version = 2")
            before = path.read_bytes()
            args = build_parser().parse_args(["--snapshot-db", str(path), "--read-only"])
            with self.assertRaisesRegex(SystemExit, "cannot create or upgrade"):
                _build_provider(args)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])


class ReadOnlyPageTests(WebServerHelpers, unittest.TestCase):
    def test_old_save_xi_copy_excludes_bench_and_preserves_observed_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_complete_fixture(Path(directory))
            raw = json.loads(path.read_text())
            raw["game"]["gameDate"] = raw["squad"]["asOfDate"] = "2011-06-24"
            for player in raw["squad"]["players"]:
                player["positionFamiliarity"] = {player["positions"][0]: 20, "SW": 1}
                player["attributes"]["longThrows"] = {"visibility": "range", "minimum": 7, "maximum": 12}
            raw["squad"]["players"].append({
                **raw["squad"]["players"][-1], "id": "bench-only", "name": "Bench Only",
                "injured": True,
            })
            path.write_text(json.dumps(raw))
            store = Mock()
            capture = Mock(side_effect=AssertionError("Captures must not run"))
            port = self._serve(path, read_only=True, knowledge_store=store, knowledge_recorder=capture,
                               match_store=store, match_capture=capture, league_store=store, league_capture=capture)
            for attempt in range(2):
                status, body = self._get(port, "/tactics/balanced_442?opp_aerial_threat=2")
                self.assertEqual(status, 200)
                self.assertIn("Read-only comparison", body)
                text = json.loads(re.search(r"data-player-copy-text>(.*?)</script>", body, re.S).group(1))
                self.assertIn("Game date: 2011-06-24", text)
                self.assertEqual(text.count("\nName: "), 11)
                self.assertNotIn("Bench Only", text)
                self.assertNotIn("SW: 1/20", text)
                self.assertIn("Long Throws: 7-12", text)
                self.assertIn("Corners: ?", text)
            for action in ("/scouting/verdict", "/scouting/refresh", "/matches/capture", "/matches/note",
                           "/matches/role-code", "/matches/intervention/start", "/matches/intervention/finish", "/league/capture"):
                status, _location, body = self._post(port, action)
                self.assertEqual(status, 403, action)
                self.assertIn("Recording and editing are disabled", body)
            self.assertEqual(store.mock_calls, [])
            capture.assert_not_called()
            status, body = self._get(port, "/scouting")
            self.assertEqual(status, 200)
            self.assertNotIn("Capture and refresh", body)


if __name__ == "__main__":
    unittest.main()
