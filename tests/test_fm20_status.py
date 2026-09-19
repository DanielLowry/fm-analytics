import unittest
from unittest import mock

from tools import fm20_linux_probe as probe
from tools import fm20_status as status


class FmStatusTests(unittest.TestCase):
    def state(self, **patch):
        with mock.patch.object(probe, "find_fm20_processes", **patch):
            return status.fm_status()

    def test_running(self) -> None:
        result = self.state(return_value=[37270])
        self.assertEqual((result.state, result.pids), ("running", (37270,)))

    def test_not_running(self) -> None:
        self.assertEqual(self.state(return_value=[]).state, "not_running")

    def test_restricted_process_view_is_unknown_not_absent(self) -> None:
        result = self.state(side_effect=probe.ProbeError("no host process visibility"))
        self.assertEqual(result.state, "unknown")
        self.assertIn("visibility", result.detail)

    def test_running_pid_refuses_ambiguity_and_absence(self) -> None:
        with mock.patch.object(probe, "find_fm20_processes", return_value=[1, 2]):
            with self.assertRaises(probe.ProbeError):
                status.running_pid()
        with mock.patch.object(probe, "find_fm20_processes", return_value=[]):
            with self.assertRaises(probe.ProbeError):
                status.running_pid()

    def test_exit_codes(self) -> None:
        for pids, code in (([5], 0), ([], 1)):
            with mock.patch.object(probe, "find_fm20_processes", return_value=pids):
                self.assertEqual(status.main([]), code)
        with mock.patch.object(probe, "find_fm20_processes", side_effect=probe.ProbeError("x")):
            self.assertEqual(status.main([]), 2)


if __name__ == "__main__":
    unittest.main()
