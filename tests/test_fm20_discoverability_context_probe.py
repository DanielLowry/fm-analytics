import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.fm20_discoverability_context_probe import (
    parse_extra_target,
    scan_backlinks,
    writable_regions,
)


class ContextProbeTests(unittest.TestCase):
    def test_writable_regions_exclude_readonly_and_cap_address(self):
        regions = list(writable_regions(
            "00100000-00102000 rw-p 00000000 00:00 0\n"
            "00102000-00103000 r--p 00000000 00:00 0\n"
            "00103000-00105000 rw-p 00000000 00:00 0 [heap]\n",
            0x104000,
        ))
        self.assertEqual(regions, [(0x100000, 0x102000, ""),
                                   (0x103000, 0x104000, "[heap]")])

    def test_scan_backlinks_finds_pointer_across_chunk_boundary(self):
        target = 0x123456789ABCDEF0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory"
            path.write_bytes(b"A" * 13 + struct.pack("<Q", target) + b"B" * 10)
            fd = os.open(path, os.O_RDONLY)
            try:
                with patch("tools.fm20_discoverability_context_probe.CHUNK_BYTES", 16):
                    result = scan_backlinks(fd, [(0, 31, "heap")], {"source": target})
            finally:
                os.close(fd)
        self.assertEqual(result["scannedBytes"], 31)
        self.assertEqual(result["skippedRegions"], [])
        self.assertEqual([item["address"] for item in result["hits"]["source"]], [13])

    def test_extra_target_parser(self):
        self.assertEqual(parse_extra_target("array=0x1234"), ("array", 0x1234))
        with self.assertRaises(ValueError):
            parse_extra_target("array=0")


if __name__ == "__main__":
    unittest.main()
