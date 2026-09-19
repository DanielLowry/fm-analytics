import struct
import unittest
from unittest import mock

from tools import fm20_scouted_attributes as scouted
from tools.fm20_linux_probe import ProbeError


class ScoutQualityTests(unittest.TestCase):
    def _sum(self, first: int, second: int):
        with mock.patch.object(scouted, "read_exact", return_value=struct.pack("<bb", first, second)):
            return scouted.read_scout_quality_sum(0, 0x1000)

    def test_sums_the_two_ratings_on_the_one_to_twenty_scale_fm_uses(self) -> None:
        # FM converts each signed byte as (b + 2) / 5, so 43 -> 9 and 33 -> 7.
        self.assertEqual(self._sum(43, 33), 16)
        self.assertEqual(self._sum(53, 53), 22)

    def test_clamps_to_the_valid_rating_range(self) -> None:
        self.assertEqual(self._sum(127, 127), 40)

    def test_an_implausible_pair_reads_as_no_report_rather_than_a_guess(self) -> None:
        # A scout with a 1 in either skill is far more likely to be a wrong
        # address than a real person, and an over-narrow range is the
        # unsafe direction, so this must degrade to "unknown".
        self.assertIsNone(self._sum(0, 50))
        self.assertIsNone(self._sum(-100, 60))

    def test_an_unreadable_scout_reads_as_no_report(self) -> None:
        with mock.patch.object(scouted, "read_exact", side_effect=ProbeError("bad address")):
            self.assertIsNone(scouted.read_scout_quality_sum(0, 0x1000))


class ReportRecordTests(unittest.TestCase):
    def test_a_missing_manager_pointer_yields_no_records(self) -> None:
        with mock.patch.object(scouted, "read_u64", return_value=0):
            self.assertEqual(scouted.read_report_records(0, 0x140000000, 0x5000), {})

    def test_a_malformed_vector_yields_no_records_instead_of_raising(self) -> None:
        # begin > end: some other build's layout must not crash a refresh.
        words = {0x5000 + scouted.CONTEXT_MANAGER_PERSON_OFFSET: 0x9000}
        vector = 0x9000 - scouted.REPORT_VECTOR_FROM_MANAGER_PERSON
        words[vector], words[vector + 8] = 0x2000, 0x1000

        with mock.patch.object(scouted, "read_u64", side_effect=lambda fd, a: words.get(a, 0)):
            self.assertEqual(scouted.read_report_records(0, 0x140000000, 0x5000), {})


if __name__ == "__main__":
    unittest.main()
