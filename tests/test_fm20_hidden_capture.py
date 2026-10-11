"""The hidden-attribute read's own decoding (tools/fm20_hidden_capture.py)."""

import unittest

from fm_analytics.domain.attributes import VISIBLE_ATTRIBUTES
from fm_analytics.domain.hidden import POSITION_CODES
from tools import fm20_hidden_capture as hidden
from tools.fm20_linux_probe import ProbeError
from tools.fm20_visibility_trace import ATTRIBUTE_OFFSETS


def block(ratings: dict[str, int], raw: dict[str, int]) -> bytes:
    data = bytearray(hidden.BLOCK_SIZE)
    for index, code in enumerate(POSITION_CODES):
        data[index] = ratings.get(code, 1)
    for name, value in raw.items():
        data[ATTRIBUTE_OFFSETS[name]] = value & 0xFF
    return bytes(data)


class DecodeBlockTests(unittest.TestCase):
    def test_attributes_use_our_squads_conversion_and_ratings_are_kept_whole(self):
        # 98 -> 20 and 48 -> 10 as FM shows them; a raw 0 still shows as 1.
        attributes, ratings = hidden.decode_block(block({"DC": 20, "DM": 12}, {"tackling": 98, "passing": 48, "flair": 0}))
        self.assertEqual(set(attributes), VISIBLE_ATTRIBUTES)
        self.assertEqual((attributes["tackling"], attributes["passing"], attributes["flair"]), (20, 10, 1))
        self.assertEqual((ratings["DC"], ratings["DM"], ratings["ST"]), (20, 12, 1))
        self.assertEqual(list(ratings), list(POSITION_CODES))

    def test_a_block_that_is_not_a_players_is_refused(self):
        with self.assertRaises(ProbeError):
            hidden.decode_block(block({"DC": 0}, {}))
        with self.assertRaises(ProbeError):
            hidden.decode_block(b"\x01" * 10)


if __name__ == "__main__":
    unittest.main()
