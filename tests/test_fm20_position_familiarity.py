import unittest

from tools.fm20_position_familiarity import (
    PositionFamiliarity,
    UnconfirmedPositionRating,
    position_familiarity,
)


class PositionFamiliarityTests(unittest.TestCase):
    def test_confirmed_values_map_to_their_checked_category(self) -> None:
        cases = {
            20: PositionFamiliarity.NATURAL,
            19: PositionFamiliarity.NATURAL,
            16: PositionFamiliarity.ACCOMPLISHED,
            15: PositionFamiliarity.ACCOMPLISHED,
            14: PositionFamiliarity.COMPETENT,
            13: PositionFamiliarity.COMPETENT,
            12: PositionFamiliarity.COMPETENT,
            11: PositionFamiliarity.UNCONVINCING,
            9: PositionFamiliarity.UNCONVINCING,
            1: PositionFamiliarity.INEFFECTUAL,
        }
        for raw_value, expected in cases.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(position_familiarity(raw_value), expected)

    def test_unconfirmed_gap_below_unconvincing_fails_closed(self) -> None:
        for raw_value in (2, 3, 4, 5, 6, 7, 8):
            with self.subTest(raw_value=raw_value):
                with self.assertRaises(UnconfirmedPositionRating):
                    position_familiarity(raw_value)

    def test_unconfirmed_gap_below_natural_fails_closed(self) -> None:
        for raw_value in (17, 18):
            with self.subTest(raw_value=raw_value):
                with self.assertRaises(UnconfirmedPositionRating):
                    position_familiarity(raw_value)

    def test_unconfirmed_error_names_the_raw_value(self) -> None:
        with self.assertRaises(UnconfirmedPositionRating) as ctx:
            position_familiarity(17)
        self.assertEqual(ctx.exception.raw_value, 17)

    def test_rejects_values_outside_the_storage_range(self) -> None:
        for raw_value in (0, -1, 21, 100):
            with self.subTest(raw_value=raw_value):
                with self.assertRaises(ValueError):
                    position_familiarity(raw_value)


if __name__ == "__main__":
    unittest.main()
