"""Unit coverage for tools.fm20_sandbox_pool that does not need a live FM.

Whether FM's list builder runs correctly in the sandbox can only be checked
against a real process (docs/scouting-workspace.md, "Player Search without
opening Player Search"). What is checked here is the live cross-check every
sandboxed player must pass before a refresh uses him.
"""

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import fm20_sandbox_pool as pool
from tools.fm20_sandbox_queries import SandboxQueryError


class ConfirmedLiveTests(unittest.TestCase):
    def _memory(self, words: dict[int, int]) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "mem"
        data = bytearray(0x3000)
        for address, value in words.items():
            data[address:address + 4] = struct.pack("<i", value)
        path.write_bytes(bytes(data))
        return path

    def test_only_players_still_the_same_player_live_are_kept(self) -> None:
        path = self._memory({0x1000 + 0xC: 10, 0x2000 + 0xC: 99})
        real_open = os.open
        with mock.patch.object(pool.os, "open", side_effect=lambda _p, flags: real_open(str(path), flags)):
            confirmed = pool._confirmed_live(1234, {10: 0x1000, 11: 0x2000, 12: 0x9000})

        # 11's Person now holds a different player; 12's is unreadable.
        self.assertEqual(confirmed, {10: 0x1000})

    def test_a_build_that_yields_no_confirmable_player_is_an_error(self) -> None:
        box = mock.MagicMock()
        with mock.patch.object(pool, "FmSandbox", return_value=box), \
                mock.patch.object(pool, "_source_records", return_value={10: 0x1000}), \
                mock.patch.object(pool, "_confirmed_live", return_value={}):
            with self.assertRaises(SandboxQueryError):
                pool.build_pool_in_sandbox(1234, 0x140000000, (1, 2, 3))

        box.call.assert_called_once_with(
            0x140000000 + pool.PLAYER_SEARCH_BUILDER_RVA, 1, 2, 3,
            timeout_seconds=pool.BUILD_TIMEOUT_SECONDS,
        )
        box.close.assert_called_once()


class RetryTests(unittest.TestCase):
    def test_a_stopped_build_is_retried_in_a_fresh_sandbox(self) -> None:
        from tools.fm20_sandbox import SandboxError

        outcomes = [SandboxError("stopped in Wine"), {10: 0x1000}]
        with mock.patch.object(pool, "_build_once", side_effect=outcomes) as build:
            self.assertEqual(pool.build_pool_in_sandbox(1234, 0x140000000, (1, 2, 3)), {10: 0x1000})
        self.assertEqual(build.call_count, 2)

    def test_gives_up_after_the_attempt_limit_with_the_last_reason(self) -> None:
        from tools.fm20_sandbox import SandboxError

        with mock.patch.object(pool, "_build_once", side_effect=SandboxError("stopped in Wine")) as build:
            with self.assertRaisesRegex(SandboxQueryError, "stopped in Wine"):
                pool.build_pool_in_sandbox(1234, 0x140000000, (1, 2, 3))
        self.assertEqual(build.call_count, pool.MAX_BUILD_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
