import os
import struct
import tempfile
import unittest
from unittest import mock

from tools.fm20_linux_probe import ProbeError
from tools import fm20_search_results as results


BASE = 0x140000000
SIZE = 0x4000


def image(sessions):
    """A fake memory image: each session is (address, the people it matched).

    A session entry is a wrapper pointing at a person, not the person itself,
    which is what the reader has to follow.
    """
    buffer = bytearray(SIZE)
    people = [0x1000 + i * 0x20 for i in range(8)]
    player_ids = list(range(101, 109))
    wrapper_for = {}
    for index, (person, player_id) in enumerate(zip(people, player_ids)):
        wrapper = 0x1400 + index * 8
        struct.pack_into("<Q", buffer, wrapper, person)
        struct.pack_into("<i", buffer, person + 0xC, player_id)
        wrapper_for[person] = wrapper
    for address, entries in sessions:
        struct.pack_into("<Q", buffer, address, BASE + results.VTABLE_RVA)
        if entries is None:  # an idle session: empty vector
            struct.pack_into("<QQ", buffer, address + results.RESULTS_VECTOR_OFFSET, 0, 0)
            continue
        store = address + 0x100
        for index, entry in enumerate(entries):
            struct.pack_into("<Q", buffer, store + index * 8, wrapper_for.get(entry, entry))
        struct.pack_into(
            "<QQ", buffer, address + results.RESULTS_VECTOR_OFFSET,
            store, store + len(entries) * 8,
        )
    return bytes(buffer), people, player_ids


class ReadActiveSearchResultsTests(unittest.TestCase):
    def run_against(self, blob, player_ids):
        with tempfile.NamedTemporaryFile() as handle:
            handle.write(blob)
            handle.flush()
            fd = os.open(handle.name, os.O_RDONLY)
            try:
                with mock.patch.object(results, "_writable_regions", return_value=[(0, SIZE)]), \
                     mock.patch.object(results.os, "open", return_value=fd), \
                     mock.patch.object(results.os, "close"):
                    return results.read_active_search_results(1234, BASE, player_ids)
            finally:
                os.close(fd)

    def test_returns_the_one_session_holding_results(self) -> None:
        blob, _people, player_ids = image([
            (0x200, None), (0x800, [0x1000, 0x1020, 0x1040]),
            (0x1800, None),
        ])
        self.assertEqual(self.run_against(blob, player_ids), (101, 102, 103))

    def test_no_search_on_screen_is_none_not_an_error(self) -> None:
        blob, _people, player_ids = image([(0x200, None), (0x800, None)])
        self.assertIsNone(self.run_against(blob, player_ids))

    def test_a_vector_holding_anything_outside_the_capture_is_rejected_whole(self) -> None:
        blob, _people, player_ids = image([(0x800, [0x1000, 0x2AD0])])
        self.assertIsNone(self.run_against(blob, player_ids))

    def test_two_live_searches_refuse_rather_than_guess(self) -> None:
        blob, _people, player_ids = image([
            (0x400, [0x1000]), (0xC00, [0x1020, 0x1040])
        ])
        with self.assertRaises(ProbeError):
            self.run_against(blob, player_ids)

    def test_an_empty_pool_is_refused(self) -> None:
        blob, _people, _player_ids = image([(0x800, [0x1000])])
        with self.assertRaises(ProbeError):
            self.run_against(blob, [])


if __name__ == "__main__":
    unittest.main()
