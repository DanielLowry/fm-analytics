import threading
import time
import unittest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from fm_analytics.analytics import ScoutingCandidate
from fm_analytics.web.providers import fixture_provider, scouting_json_provider
from fm_analytics.web.server import SquadWebServer
from fm_analytics.web.rendering import _scouting_refresh_command
from tests.web_support import FIXTURE, WebServerHelpers


class ScoutingRefreshJobTests(WebServerHelpers, unittest.TestCase):
    OLD_FEED = (ScoutingCandidate("old", "Old", (), {}),)

    def server(self, refresh, *, provider=lambda: ScoutingRefreshJobTests.OLD_FEED, recorder=None):
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(FIXTURE),
            scouting_provider=provider, scouting_refresh=refresh,
            knowledge_recorder=recorder,
        )
        self.addCleanup(server.server_close)
        return server

    def wait(self, server):
        for _ in range(100):
            if server.scouting_refresh_job.status != "running":
                return
            time.sleep(0.01)
        self.fail("refresh did not finish")

    def test_duplicate_start_is_refused_and_reads_keep_the_old_feed(self):
        release = threading.Event()
        server = self.server(lambda **_kwargs: release.wait(2) or "done")

        self.assertTrue(server.request_scouting_refresh())
        self.assertFalse(server.request_scouting_refresh())
        self.assertEqual(server.scouting(), self.OLD_FEED)
        release.set()
        self.wait(server)
        self.assertEqual(server.scouting_refresh_job.status, "succeeded")

    def test_failure_is_retained_and_knowledge_is_recorded_only_after_success(self):
        records = []

        class Result:
            def summary(self):
                records.append("recorded")
                return "recorded"

        failing = self.server(
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("capture failed")),
            recorder=Result,
        )
        failing.request_scouting_refresh()
        self.wait(failing)
        self.assertEqual(failing.scouting_refresh_job.status, "failed")
        self.assertIn("capture failed", failing.scouting_refresh_job.error)
        self.assertEqual(records, [])
        self.assertEqual(failing.scouting(), self.OLD_FEED)

        succeeding = self.server(lambda **_kwargs: "done", recorder=Result)
        succeeding.request_scouting_refresh()
        self.wait(succeeding)
        self.assertEqual(records, ["recorded"])
        self.assertEqual(succeeding.scouting_refresh_job.status, "succeeded")

    def test_post_returns_while_capture_runs_and_duplicate_has_a_clear_message(self):
        release = threading.Event()
        self.addCleanup(release.set)
        port = self._serve(
            FIXTURE, lambda: self.OLD_FEED,
            lambda **_kwargs: release.wait(5) or "done",
        )
        started = time.monotonic()
        status, location, _ = self._post(port, "/scouting/refresh")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(status, 303)
        self.assertIn("refreshed=started", location)
        _, duplicate, _ = self._post(port, "/scouting/refresh")
        self.assertIn("refreshed=running", duplicate)
        status, page = self._get(port, duplicate)
        self.assertEqual(status, 200)
        self.assertIn("already running", page)
        self.assertIn("Reload to check refresh status", page)
        self.assertIn("Old", page)
        release.set()

    def test_command_failure_and_timeout_leave_the_last_good_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "scouting.json"
            temporary = target.with_suffix(".json.tmp")
            target.write_text('{"old": true}', encoding="utf-8")
            for failure in (False, True):
                with self.subTest(timeout=failure):
                    def capture(*_args, **_kwargs):
                        temporary.write_text('{"partial":', encoding="utf-8")
                        if failure:
                            raise subprocess.TimeoutExpired("capture", 240)
                        return subprocess.CompletedProcess("capture", 1, "", "broken")

                    with patch("fm_analytics.web.rendering.subprocess.run") as run:
                        run.side_effect = capture
                        with self.assertRaises(RuntimeError):
                            _scouting_refresh_command(target)()
                    self.assertEqual(target.read_text(encoding="utf-8"), '{"old": true}')
                    self.assertFalse(temporary.exists())

    def test_closing_the_server_does_not_wait_for_a_running_capture(self):
        release = threading.Event()
        server = self.server(lambda **_kwargs: release.wait(2) or "done")
        server.request_scouting_refresh()
        started = time.monotonic()
        server.server_close()
        self.assertLess(time.monotonic() - started, 0.5)
        release.set()

    def test_malformed_success_is_not_promoted_to_last_good_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "scouting.json"
            target.write_text('{"players": []}', encoding="utf-8")
            def capture(*_args, **_kwargs):
                target.with_suffix(".json.tmp").write_text('{"partial":', encoding="utf-8")
                return subprocess.CompletedProcess("capture", 0, "done", "")

            with patch("fm_analytics.web.rendering.subprocess.run") as run:
                run.side_effect = capture
                with self.assertRaises(ValueError):
                    _scouting_refresh_command(target)()
            self.assertEqual(target.read_text(encoding="utf-8"), '{"players": []}')

    def test_first_capture_becomes_readable_and_sets_the_save_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "scouting.json"
            provider = scouting_json_provider(target, allow_missing=True)

            def refresh(**_kwargs):
                target.write_text(
                    '{"source": {"managedClub": {"id": "2"}}, "players": [{"id": "new", "name": "New",'
                    ' "positions": [], "attributes": {}}]}', encoding="utf-8",
                )
                return "done"

            server = SquadWebServer(
                ("127.0.0.1", 0), fixture_provider(FIXTURE), scouting_provider=provider,
                scouting_refresh=refresh, scouting_capture_path=target,
            )
            self.addCleanup(server.server_close)
            self.assertEqual(server.scouting(), ())
            server.request_scouting_refresh()
            self.wait(server)
            self.assertEqual(server.scouting()[0].id, "new")
            self.assertEqual(server.knowledge_save_key, "club:2")


if __name__ == "__main__":
    unittest.main()
