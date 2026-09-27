"""Unit coverage for tools.fm20_sandbox_queries that does not need live FM.

Anything that has to run FM's own code (visible attributes, interest
evaluation, RTTI/vtable resolution) can only be verified against a live
process and is covered by the manual trial recorded in
docs/scouting-workspace.md and docs/frida-discoverability.md, not here. What
*can* be verified without a running game is: the pure verdict logic, the
retry orchestration ``capture_players`` added after 27 September's flaky-read
discovery, and ``resolve_scout_persons``'s read-only join.
"""

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import fm20_sandbox_queries as queries
from tools.fm20_scouted_attributes import ReportRecord


class BandTests(unittest.TestCase):
    """The three-state interest label: FM's own exact answer, the relaxed
    margin, or nothing."""

    def test_exact_wins_over_relaxed(self) -> None:
        self.assertEqual(queries._band(True, True), "yes")
        self.assertEqual(queries._band(True, False), "yes")  # cannot happen in practice; still well-defined

    def test_relaxed_only_is_maybe(self) -> None:
        self.assertEqual(queries._band(False, True), "maybe")

    def test_neither_is_none(self) -> None:
        self.assertIsNone(queries._band(False, False))


class ResolveScoutPersonsTests(unittest.TestCase):
    """Joins a report (keyed by RowID) back to the player ID a caller asked about."""

    def test_a_report_is_returned_keyed_by_player_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mem"
            path.write_bytes(struct.pack("<i", 777).rjust(0x1010, b"\0"))
            with path.open("r+b") as stream:
                stream.seek(0x1000 + 0xC)
                stream.write(struct.pack("<i", 777))
            fd = os.open(str(path), os.O_RDONLY)
            try:
                with mock.patch.object(
                    queries, "read_report_records",
                    return_value={5: ReportRecord(level=40, staff_person=0x9000)},
                ):
                    with mock.patch.object(
                        queries, "resolve_persons_by_row_id", return_value={5: 0x1000}
                    ):
                        scouts = queries.resolve_scout_persons(fd, 0x140000000, 0x999, [777, 999])
            finally:
                os.close(fd)

        self.assertEqual(scouts, {777: 0x9000})

    def test_no_reports_at_all_is_an_empty_map_not_an_error(self) -> None:
        with mock.patch.object(queries, "read_report_records", return_value={}):
            self.assertEqual(
                queries.resolve_scout_persons(-1, 0x140000000, 0x999, [1, 2]), {}
            )

    def test_a_player_not_in_the_wanted_set_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mem"
            path.write_bytes(bytes(0x1010))
            with path.open("r+b") as stream:
                stream.seek(0x1000 + 0xC)
                stream.write(struct.pack("<i", 42))
            fd = os.open(str(path), os.O_RDONLY)
            try:
                with mock.patch.object(
                    queries, "read_report_records",
                    return_value={5: ReportRecord(level=40, staff_person=0x9000)},
                ):
                    with mock.patch.object(
                        queries, "resolve_persons_by_row_id", return_value={5: 0x1000}
                    ):
                        scouts = queries.resolve_scout_persons(fd, 0x140000000, 0x999, [1, 2])
            finally:
                os.close(fd)

        self.assertEqual(scouts, {})


class CapturePlayersRetryTests(unittest.TestCase):
    """Bounded retry over fresh sandboxes for players a pass could not read.

    ``_capture_pass`` opens a real ``FmSandbox``, so these tests replace it
    entirely; what is under test is the orchestration around it
    (tools.fm20_sandbox_queries.capture_players's own docstring records why
    this exists: a burst of same-address read failures, cleared on a later,
    fresh attempt, that a same-sandbox retry never did -- see
    docs/scouting-workspace.md).
    """

    def _capture(self, player_id: int) -> "queries.PlayerCapture":
        return queries.PlayerCapture(attributes={}, interest=queries.InterestVerdict(None, None))

    def test_a_clean_first_pass_needs_no_retry(self) -> None:
        context = mock.Mock(spec=queries.SandboxSearchContext)
        with mock.patch.object(
            queries, "_capture_pass", return_value={1: self._capture(1), 2: self._capture(2)}
        ) as capture_pass:
            result = queries.capture_players(1234, context, {1: 0x10, 2: 0x20}, {1: 0x30, 2: 0x40}, {})

        self.assertEqual(set(result), {1, 2})
        capture_pass.assert_called_once()

    def test_players_missing_from_one_pass_are_retried_in_the_next(self) -> None:
        context = mock.Mock(spec=queries.SandboxSearchContext)
        passes = [
            {1: self._capture(1)},  # player 2 failed this pass
            {2: self._capture(2)},  # recovered on a fresh sandbox
        ]
        with mock.patch.object(queries, "_capture_pass", side_effect=passes) as capture_pass:
            result = queries.capture_players(1234, context, {1: 0x10, 2: 0x20}, {1: 0x30, 2: 0x40}, {})

        self.assertEqual(set(result), {1, 2})
        self.assertEqual(capture_pass.call_count, 2)
        # The second pass is only asked about the player the first pass missed.
        self.assertEqual(list(capture_pass.call_args_list[1].args[2]), [2])

    def test_gives_up_after_the_pass_limit_without_raising(self) -> None:
        context = mock.Mock(spec=queries.SandboxSearchContext)
        with mock.patch.object(queries, "_capture_pass", return_value={}) as capture_pass:
            result = queries.capture_players(1234, context, {1: 0x10}, {1: 0x30}, {})

        self.assertEqual(result, {})
        self.assertEqual(capture_pass.call_count, queries.MAX_CAPTURE_PASSES)

    def test_a_player_missing_from_either_map_is_never_attempted(self) -> None:
        context = mock.Mock(spec=queries.SandboxSearchContext)
        with mock.patch.object(queries, "_capture_pass", return_value={}) as capture_pass:
            queries.capture_players(1234, context, {1: 0x10, 2: 0x20}, {1: 0x30}, {})

        self.assertEqual(list(capture_pass.call_args_list[0].args[2]), [1])

    def test_no_candidates_never_opens_a_sandbox(self) -> None:
        context = mock.Mock(spec=queries.SandboxSearchContext)
        with mock.patch.object(queries, "_capture_pass") as capture_pass:
            result = queries.capture_players(1234, context, {}, {}, {})

        self.assertEqual(result, {})
        capture_pass.assert_not_called()


if __name__ == "__main__":
    unittest.main()
