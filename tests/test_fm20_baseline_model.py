import unittest

from tools.fm20_baseline_model import (
    PlayerScaleBand,
    adjust_baseline_level,
    calculate_dynamic_relationship_base,
    select_observer_rating,
)


class Fm20BaselineModelTests(unittest.TestCase):
    def test_dynamic_base_uses_score_and_four_player_scale_bands(self) -> None:
        expected = {
            PlayerScaleBand.BELOW_3000: 25,
            PlayerScaleBand.FROM_3000: 30,
            PlayerScaleBand.FROM_4000: 35,
            PlayerScaleBand.FROM_5000: 40,
        }
        for band, base in expected.items():
            with self.subTest(band=band):
                self.assertEqual(
                    calculate_dynamic_relationship_base(
                        knowledge_score=100,
                        player_scale_band=band,
                    ),
                    base,
                )
        self.assertEqual(
            calculate_dynamic_relationship_base(
                knowledge_score=90,
                player_scale_band=PlayerScaleBand.FROM_4000,
            ),
            33,
        )
        with self.assertRaisesRegex(ValueError, "knowledge score"):
            calculate_dynamic_relationship_base(
                knowledge_score=101,
                player_scale_band=PlayerScaleBand.FROM_4000,
            )

    def test_selects_one_of_two_observer_bytes_at_boundary(self) -> None:
        self.assertEqual(
            select_observer_rating(
                player_selector=22,
                raw_at_2c=53,
                raw_at_2d=28,
            ),
            6,
        )
        self.assertEqual(
            select_observer_rating(
                player_selector=23,
                raw_at_2c=53,
                raw_at_2d=28,
            ),
            11,
        )

    def test_relationship_and_observer_rating_both_affect_knowledge(self) -> None:
        examples = (
            (0, 10, 0),
            (0, 11, 2),
            (15, 5, 5),
            (15, 6, 7),
            (20, 6, 12),
            (20, 11, 22),
        )
        for base, rating, expected in examples:
            with self.subTest(base=base, rating=rating):
                self.assertEqual(
                    adjust_baseline_level(
                        relationship_base=base,
                        observer_rating=rating,
                        relationship_bonus=False,
                    ),
                    expected,
                )

    def test_low_rating_penalty_bonus_and_clamps(self) -> None:
        self.assertEqual(
            adjust_baseline_level(
                relationship_base=30,
                observer_rating=3,
                relationship_bonus=False,
            ),
            2,
        )
        self.assertEqual(
            adjust_baseline_level(
                relationship_base=20,
                observer_rating=11,
                relationship_bonus=True,
            ),
            42,
        )
        self.assertEqual(
            adjust_baseline_level(
                relationship_base=0,
                observer_rating=1,
                relationship_bonus=False,
            ),
            0,
        )
        self.assertEqual(
            adjust_baseline_level(
                relationship_base=80,
                observer_rating=20,
                relationship_bonus=True,
            ),
            100,
        )

    def test_unverified_inputs_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "player selector"):
            select_observer_rating(
                player_selector=128,
                raw_at_2c=53,
                raw_at_2d=28,
            )
        with self.assertRaisesRegex(ValueError, "observer rating byte"):
            select_observer_rating(
                player_selector=23,
                raw_at_2c=128,
                raw_at_2d=28,
            )
        with self.assertRaisesRegex(ValueError, "relationship base"):
            adjust_baseline_level(
                relationship_base=101,
                observer_rating=10,
                relationship_bonus=False,
            )
        with self.assertRaisesRegex(ValueError, "observer rating"):
            adjust_baseline_level(
                relationship_base=20,
                observer_rating=0,
                relationship_bonus=False,
            )
        with self.assertRaisesRegex(TypeError, "relationship bonus"):
            adjust_baseline_level(
                relationship_base=20,
                observer_rating=10,
                relationship_bonus=1,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
