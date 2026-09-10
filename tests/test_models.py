import unittest

from fm_analytics.domain.models import AttributeObservation, Player, Visibility


class AttributeObservationTests(unittest.TestCase):
    def test_known_attribute(self) -> None:
        observation = AttributeObservation.from_dict(
            {"visibility": "known", "value": 15}
        )
        self.assertEqual(observation.value, 15)
        self.assertEqual(observation.display(), "15")

    def test_range_attribute(self) -> None:
        observation = AttributeObservation.from_dict(
            {"visibility": "range", "minimum": 10, "maximum": 14}
        )
        self.assertEqual(observation.display(), "10-14")

    def test_unknown_attribute_rejects_leaked_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot contain values"):
            AttributeObservation.from_dict(
                {"visibility": "unknown", "value": 13}
            )

    def test_invalid_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "minimum cannot exceed"):
            AttributeObservation(
                visibility=Visibility.RANGE, minimum=15, maximum=10
            )


class PlayerTests(unittest.TestCase):
    def test_rejects_out_of_range_visible_percentage(self) -> None:
        raw = {
            "id": "1",
            "name": "Player",
            "positions": ["MC"],
            "clubId": "2",
            "conditionPercent": 101,
        }

        with self.assertRaisesRegex(ValueError, "conditionPercent"):
            Player.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
