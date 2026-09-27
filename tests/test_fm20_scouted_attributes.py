import contextlib
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


class ScoutedPlayerSetTests(unittest.TestCase):
    def test_a_report_without_an_explicit_knowledge_entry_is_still_captured(self) -> None:
        # 68 of 530 reports on the test save had no explicit-knowledge entry;
        # FM's Scouted list shows them, so the app must too.
        import os

        player_ids = {0x100 + 0xC: 101, 0x200 + 0xC: 102, 0x300 + 0xC: 103}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(scouted, "read_explicit_knowledge", return_value={1: 20, 3: 40}))
            stack.enter_context(mock.patch.object(scouted, "read_report_records", return_value={
                1: scouted.ReportRecord(level=30, staff_person=0x9000),
                2: scouted.ReportRecord(level=10, staff_person=0x9000),
            }))
            stack.enter_context(mock.patch.object(
                scouted, "resolve_persons_by_row_id", return_value={1: 0x100, 2: 0x200, 3: 0x300}))
            stack.enter_context(mock.patch.object(
                scouted, "read_exact", side_effect=lambda fd, address, size: struct.pack("<i", player_ids[address])))
            stack.enter_context(mock.patch.object(scouted, "read_fm_string", return_value="Name"))
            stack.enter_context(mock.patch.object(scouted, "read_scout_quality_sum", return_value=20))
            visible = stack.enter_context(mock.patch.object(
                scouted, "_read_visible_attributes_for_person", return_value=(21, {})))

            players, issues = scouted.capture_scouted_attributes(os.getpid(), 0x140000000, 0x999, "2019-07-04")

        self.assertEqual(issues, {})
        self.assertEqual(set(players), {101, 102, 103})
        self.assertEqual((players[101].knowledge, players[101].effective_knowledge, players[101].has_report), (20, 30, True))
        self.assertEqual((players[102].knowledge, players[102].effective_knowledge, players[102].has_report), (10, 10, True))
        self.assertEqual((players[103].knowledge, players[103].has_report), (40, False))
        levels = {call.args[1]: call.args[3] for call in visible.call_args_list}
        self.assertEqual(levels, {0x100: 30, 0x200: 10, 0x300: 40})

    def test_a_player_this_calculation_cannot_read_stays_listed_without_attributes(self) -> None:
        # 14 players on the test save have position ratings this reader
        # rejects; FM's own code in the sandbox reads them fine, so they must
        # stay on the list rather than vanish from it.
        import os
        from datetime import date

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(scouted, "read_explicit_knowledge", return_value={}))
            stack.enter_context(mock.patch.object(scouted, "read_report_records", return_value={
                1: scouted.ReportRecord(level=30, staff_person=0x9000),
            }))
            stack.enter_context(mock.patch.object(scouted, "resolve_persons_by_row_id", return_value={1: 0x100}))
            stack.enter_context(mock.patch.object(scouted, "read_exact", return_value=struct.pack("<i", 101)))
            stack.enter_context(mock.patch.object(scouted, "read_fm_string", return_value="Name"))
            stack.enter_context(mock.patch.object(scouted, "read_scout_quality_sum", return_value=20))
            stack.enter_context(mock.patch.object(
                scouted, "_read_visible_attributes_for_person",
                side_effect=ValueError("position rating must be between 1 and 20")))
            stack.enter_context(mock.patch.object(scouted, "decode_fm_date", return_value=date(2000, 1, 1)))

            players, issues = scouted.capture_scouted_attributes(os.getpid(), 0x140000000, 0x999, "2019-07-04")

        self.assertIn("position rating", issues[101])
        self.assertIsNone(players[101].observations)
        self.assertEqual(players[101].age, 19)
        self.assertTrue(players[101].has_report)


if __name__ == "__main__":
    unittest.main()
