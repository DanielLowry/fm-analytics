import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fm_analytics.progress import ProgressFile
from tools import fm20_sandbox_queries as queries


class CaptureProgressTests(unittest.TestCase):
    def test_sidecar_is_throttled_but_always_publishes_stage_changes_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            report = ProgressFile(path)
            with patch("fm_analytics.progress.time.monotonic", return_value=10):
                report("players", 0, 100)
                report("players", 50, 100)
                self.assertEqual(json.loads(path.read_text())["completed"], 0)
                report("players", 100, 100)
                self.assertEqual(json.loads(path.read_text())["completed"], 100)
                report("validating")
                self.assertEqual(json.loads(path.read_text())["stage"], "validating")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_progress_failure_never_fails_the_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            report = ProgressFile(Path(directory))  # cannot replace a directory
            report("players", 1, 2)
        ProgressFile(None)("players", 1, 2)

    def test_retries_report_the_new_attempt_and_number_of_remaining_players(self):
        events = []
        attempt = 0
        def capture(_pid, _context, ids, *_args, **kwargs):
            nonlocal attempt
            attempt += 1
            kwargs["progress"](len(ids), len(ids))
            return {attempt: object()}
        with patch.object(queries, "_capture_pass", side_effect=capture):
            result = queries.capture_players(1, None, {1: 2, 2: 3}, {1: 4, 2: 5}, {},
                progress=lambda *event: events.append(event))
        self.assertEqual(set(result), {1, 2})
        self.assertEqual(events, [(0, 2, 1), (2, 2, 1), (0, 1, 2), (1, 1, 2)])


if __name__ == "__main__":
    unittest.main()
