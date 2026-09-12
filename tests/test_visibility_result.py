import unittest

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from fm_analytics.domain.models import AttributeObservation, Visibility


class VisibilityResultTests(unittest.TestCase):
    def test_decodes_unknown_without_a_concealed_value_input(self) -> None:
        self.assertEqual(
            decode_visible_bound_bytes(0xFF, 0xFF),
            AttributeObservation(visibility=Visibility.UNKNOWN),
        )

    def test_decodes_exact_visible_value(self) -> None:
        self.assertEqual(
            decode_visible_bound_bytes(12, 12),
            AttributeObservation(visibility=Visibility.KNOWN, value=12),
        )

    def test_decodes_visible_range(self) -> None:
        self.assertEqual(
            decode_visible_bound_bytes(5, 12),
            AttributeObservation(
                visibility=Visibility.RANGE,
                minimum=5,
                maximum=12,
            ),
        )

    def test_rejects_partial_unknown_sentinel(self) -> None:
        with self.assertRaisesRegex(ValueError, "two unknown sentinels"):
            decode_visible_bound_bytes(0xFF, 12)

    def test_rejects_invalid_or_reversed_visible_bounds(self) -> None:
        for lower, upper in ((0, 12), (5, 21), (13, 12), (True, 12)):
            with self.subTest(lower=lower, upper=upper):
                with self.assertRaises(ValueError):
                    decode_visible_bound_bytes(lower, upper)


if __name__ == "__main__":
    unittest.main()
