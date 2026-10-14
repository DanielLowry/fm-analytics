import threading
import time
import unittest
import subprocess
import tempfile
import json
from dataclasses import replace
from http.client import HTTPConnection
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

    def test_job_waits_for_rankings_and_keeps_previous_pool_until_ready(self):
        old = self.OLD_FEED
        fresh = (ScoutingCandidate("new", "New", (), {}),)
        current = [old]
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def refresh(**_kwargs):
            current[0] = fresh
            return "captured"
        server = self.server(refresh, provider=lambda: current[0])
        self.assertIs(server.scouting(), old)
        from fm_analytics.web.scouting_jobs import rank_for_position as rank
        def delayed(pool, *args, **kwargs):
            entered.set()
            release.wait(3)
            return rank(pool, *args, **kwargs)
        with patch("fm_analytics.web.scouting_jobs.rank_for_position", side_effect=delayed):
            server.request_scouting_refresh()
            self.assertTrue(entered.wait(1))
            self.assertIs(server.scouting(), old)
            status = server.scouting_refresh_status()
            self.assertEqual((status["status"], status["stage"]), ("running", "rankings"))
            self.assertLess(status["percent"], 100)
            self.assertEqual(status["generation"], 0)
            self.assertFalse(server.request_scouting_refresh())
            release.set()
            self.wait(server)
        self.assertIs(server.scouting(), fresh)
        self.assertEqual(server.scouting_refresh_status()["percent"], 100)
        self.assertEqual(server.scouting_refresh_status()["generation"], 1)

    def test_status_is_lightweight_counts_retries_and_has_an_honest_estimate(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def refresh(*, allow_rebuild=False, progress):
            progress("players", 50, 100)
            release.wait(3)
            return "done"
        server = self.server(refresh)
        with patch("fm_analytics.web.scouting_jobs.time.monotonic", return_value=100):
            server.request_scouting_refresh()
            for _ in range(100):
                if server.scouting_refresh_job.stage == "players":
                    break
                time.sleep(0.01)
        with patch("fm_analytics.web.scouting_jobs.time.monotonic", return_value=110), patch.object(server, "scouting_provider", side_effect=AssertionError("status parsed the feed")):
            status = server.scouting_refresh_status()
            self.assertEqual(status["remaining_seconds"], 30)  # 10 s current + 20 s later stages
            self.assertEqual((status["completed"], status["total"]), (50, 100))
            before = status["percent"]
            server._scouting_progress("players", 0, 2, "Retrying players (attempt 2)")
            self.assertGreaterEqual(server.scouting_refresh_status()["percent"], before)
            server._scouting_progress("preparing")  # ignore late/out-of-order events
            self.assertEqual(server.scouting_refresh_job.stage, "players")
        release.set()
        self.wait(server)
        # An uncounted stage that has exceeded its estimate shows no countdown.
        with server._scouting_refresh_lock:
            server._scouting_refresh_job = replace(server._scouting_refresh_job,
                status="running", stage="pool", stage_started=0, started=0, completed=0, total=0)
        with patch("fm_analytics.web.scouting_jobs.time.monotonic", return_value=100):
            self.assertIsNone(server.scouting_refresh_status()["remaining_seconds"])

    def test_json_start_and_status_endpoint_do_not_require_a_page_reload(self):
        release = threading.Event()
        self.addCleanup(release.set)
        port = self._serve(FIXTURE, lambda: self.OLD_FEED, lambda **_: release.wait(3) or "done")
        connection = HTTPConnection("127.0.0.1", port)
        connection.request("POST", "/scouting/refresh", headers={"Accept": "application/json"})
        response = connection.getresponse()
        state = json.loads(response.read())
        self.assertEqual(response.status, 202)
        self.assertEqual(state["status"], "running")
        status, body = self._get(port, "/scouting/refresh/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["job_id"], state["job_id"])
        release.set()
        connection.close()

    def test_command_forwards_progress_while_the_child_is_still_running(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capture.json"
            observed = threading.Event()
            events = []
            def progress(*event):
                events.append(event)
                observed.set()
            def capture(command, **_kwargs):
                path = Path(command[command.index("--progress-file") + 1])
                path.write_text(json.dumps({"stage": "players", "completed": 5, "total": 10}))
                self.assertTrue(observed.wait(2), "progress was buffered until child exit")
                target.with_suffix(".json.tmp").write_text('{"players": []}')
                return subprocess.CompletedProcess(command, 0, "done", "")
            with patch("fm_analytics.web.rendering.subprocess.run", side_effect=capture):
                _scouting_refresh_command(target)(progress=progress)
            self.assertIn(("players", 5, 10, ""), events)
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_preparation_failure_retains_the_displayed_pool_and_save_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            fresh = (ScoutingCandidate("new", "New", (), {}),)
            current = [self.OLD_FEED]
            def refresh(**_kwargs):
                path.write_text('{"source":{"managedClub":{"id":"new"}}}')
                current[0] = fresh
                return "captured"
            server = self.server(refresh, provider=lambda: current[0])
            server.scouting_capture_path = path
            server.knowledge_save_key = "club:old"
            server.scouting()
            def fail(*_args, **_kwargs):
                self.assertEqual(server.knowledge_save_key, "club:old")
                raise RuntimeError("preparation failed")
            with patch("fm_analytics.web.scouting_jobs.rank_for_position", side_effect=fail):
                server.request_scouting_refresh()
                self.wait(server)
            self.assertEqual(server.scouting_refresh_job.status, "failed")
            self.assertIs(server.scouting(), self.OLD_FEED)
            self.assertEqual(server.knowledge_save_key, "club:old")
            self.assertEqual(server.scouting_refresh_status()["generation"], 0)


if __name__ == "__main__":
    unittest.main()
