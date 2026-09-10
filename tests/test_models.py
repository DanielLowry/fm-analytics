import unittest

from fm_analytics.domain.models import AttributeObservation, Player, Visibility


class AttributeObservationTests(unittest.TestCase):
    def test_known_attribute(self) -> None:
        observation = AttributeObservation.from_dict(
            {"visibility": "known", "value": 15}
        )
        self.assertEqual(observation.value, 15)
        self.assertEqual(observation.display(), "15")
        self.assertEqual(
            observation.to_dict(), {"visibility": "known", "value": 15}
        )

    def test_range_attribute(self) -> None:
        observation = AttributeObservation.from_dict(
            {"visibility": "range", "minimum": 10, "maximum": 14}
        )
        self.assertEqual(observation.display(), "10-14")
        self.assertEqual(
            observation.to_dict(),
            {"visibility": "range", "minimum": 10, "maximum": 14},
        )

    def test_unknown_attribute_serializes_without_numeric_fields(self) -> None:
        observation = AttributeObservation.from_dict({"visibility": "unknown"})

        self.assertEqual(observation.to_dict(), {"visibility": "unknown"})

    def test_unknown_attribute_rejects_leaked_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbid numeric fields"):
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
            "dateOfBirth": None,
            "age": 22,
            "positions": ["MC"],
            "clubId": "2",
            "conditionPercent": 101,
            "matchFitnessPercent": None,
            "availability": "available",
            "injured": False,
            "suspended": False,
            "contract": None,
            "attributes": {},
        }

        with self.assertRaisesRegex(ValueError, "conditionPercent"):
            Player.from_dict(raw)

    def test_rejects_coerced_identifier_and_percentage_types(self) -> None:
        raw = {
            "id": 1,
            "name": "Player",
            "dateOfBirth": None,
            "age": 22,
            "positions": ["MC"],
            "clubId": "2",
            "conditionPercent": "97",
            "matchFitnessPercent": None,
            "availability": "available",
            "injured": False,
            "suspended": False,
            "contract": None,
            "attributes": {},
        }

        with self.assertRaisesRegex(TypeError, "id must be a string"):
            Player.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
