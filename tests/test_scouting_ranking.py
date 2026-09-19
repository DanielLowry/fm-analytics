import unittest

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    ScoutingCandidate,
    ScoutingFilters,
    rank_for_position,
)
from fm_analytics.analytics.role_scoring import score_role
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.web.scouting_render import attribute_sheet, score_bar

ROLE = MVP_CATALOGUE.roles["cd_defend"]


def known(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


def ranged(low: int, high: int) -> AttributeObservation:
    return AttributeObservation(Visibility.RANGE, minimum=low, maximum=high)


def candidate(identifier: str, attributes, **kwargs) -> ScoutingCandidate:
    return ScoutingCandidate(
        id=identifier, name=kwargs.pop("name", identifier), positions=("DC",),
        attributes=attributes, **kwargs,
    )


class MedianScoreTests(unittest.TestCase):
    def test_nothing_known_spans_the_whole_scale_with_the_median_in_the_middle(self) -> None:
        score = score_role(ROLE, {})

        self.assertEqual((score.score.lower, score.median, score.score.upper), (0.0, 50.0, 100.0))

    def test_the_conservative_estimate_is_left_alone(self) -> None:
        # The squad optimiser relies on unknown counting as the scale minimum
        # in `score.central`; the new median must not have changed it.
        self.assertEqual(score_role(ROLE, {}).score.central, 0.0)

    def test_fully_known_collapses_to_one_number(self) -> None:
        full = {attribute.name: known(15) for attribute in ROLE.attributes}
        score = score_role(ROLE, full)

        self.assertEqual(score.score.lower, score.median)
        self.assertEqual(score.median, score.score.upper)

    def test_median_is_always_between_the_floor_and_the_ceiling(self) -> None:
        attributes = {ROLE.attributes[0].name: ranged(4, 12), ROLE.attributes[1].name: known(9)}
        score = score_role(ROLE, attributes)

        self.assertLessEqual(score.score.lower, score.median)
        self.assertLessEqual(score.median, score.score.upper)


class RankForPositionTests(unittest.TestCase):
    def setUp(self) -> None:
        strong = {attribute.name: known(16) for attribute in ROLE.attributes}
        weak = {attribute.name: known(4) for attribute in ROLE.attributes}
        self.candidates = [
            candidate("weak", weak, name="Known Weak"),
            candidate("strong", strong, name="Known Strong"),
            candidate("blank", {}, name="Never Scouted"),
        ]

    def test_ranks_by_median_best_first(self) -> None:
        ranked = rank_for_position(self.candidates, MVP_CATALOGUE, "DC")

        self.assertEqual([r.candidate.id for r in ranked], ["strong", "blank", "weak"])

    def test_an_unscouted_player_outranks_a_known_poor_one_but_not_a_known_strong_one(self) -> None:
        ranked = {r.candidate.id: r for r in rank_for_position(self.candidates, MVP_CATALOGUE, "DC")}

        self.assertGreater(ranked["blank"].median, ranked["weak"].median)
        self.assertLess(ranked["blank"].median, ranked["strong"].median)
        # ...and his range is the honest reason: he could still be anything.
        self.assertGreater(ranked["blank"].maximum - ranked["blank"].minimum, 90)

    def test_ceiling_and_upside_sorts_surface_the_unscouted_player(self) -> None:
        by_ceiling = rank_for_position(self.candidates, MVP_CATALOGUE, "DC", sort="ceiling")
        by_upside = rank_for_position(self.candidates, MVP_CATALOGUE, "DC", sort="upside")

        self.assertEqual(by_ceiling[0].candidate.id, "blank")
        self.assertEqual(by_upside[0].candidate.id, "blank")

    def test_reports_how_much_of_the_role_is_actually_known(self) -> None:
        strong = next(r for r in rank_for_position(self.candidates, MVP_CATALOGUE, "DC") if r.candidate.id == "strong")
        blank = next(r for r in rank_for_position(self.candidates, MVP_CATALOGUE, "DC") if r.candidate.id == "blank")

        self.assertEqual(strong.unknown_attributes, 0)
        self.assertEqual(blank.known_attributes + blank.ranged_attributes, 0)

    def test_an_unknown_sort_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            rank_for_position(self.candidates, MVP_CATALOGUE, "DC", sort="nonsense")
        with self.assertRaises(ValueError):
            ScoutingFilters(ranking_sort="nonsense")

    def test_a_position_no_role_covers_ranks_nobody(self) -> None:
        self.assertEqual(rank_for_position(self.candidates, MVP_CATALOGUE, "XX"), ())


class RenderingTests(unittest.TestCase):
    def test_attribute_sheet_shows_ranges_and_dashes_for_hidden_attributes(self) -> None:
        sheet = attribute_sheet(candidate("p", {
            "pace": ranged(9, 15), "heading": known(12),
            "finishing": AttributeObservation(Visibility.UNKNOWN),
        }))

        self.assertIn("9-15", sheet)
        self.assertIn(">12<", sheet)
        self.assertIn("attr-hidden", sheet)
        self.assertIn("(2 shown)", sheet)

    def test_score_bar_clamps_and_keeps_the_median_tick_in_range(self) -> None:
        bar = score_bar(-5, 50, 130)

        self.assertIn("left:0.0%", bar)
        self.assertIn("width:100.0%", bar)


if __name__ == "__main__":
    unittest.main()


class LabelTests(unittest.TestCase):
    def test_compound_attribute_names_read_like_fms(self) -> None:
        sheet = attribute_sheet(candidate("p", {"firstTouch": ranged(3, 9), "offTheBall": known(11)}))

        self.assertIn("First Touch", sheet)
        self.assertIn("Off The Ball", sheet)
