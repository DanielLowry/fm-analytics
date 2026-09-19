import unittest

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    ScoutingCandidate,
    ScoutingFilters,
    rank_for_position,
)
from fm_analytics.analytics.role_scoring import score_role
from fm_analytics.bridge.fm20_visibility_algorithm import PositionFamily, thresholds_for_attribute
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

    def test_every_column_can_be_sorted_in_either_direction(self) -> None:
        cands = [
            candidate("a", {}, name="Alpha", age=30, scouting_knowledge=10),
            candidate("b", {}, name="Bravo", age=18, scouting_knowledge=40),
            candidate("c", {}, name="Charlie", age=24, scouting_knowledge=25),
        ]
        expectations = {
            "age": ["b", "c", "a"],       # youngest first by default
            "scouted": ["b", "c", "a"],   # most-scouted first by default
            "name": ["a", "b", "c"],
        }
        for sort, expected in expectations.items():
            with self.subTest(sort=sort):
                ranked = rank_for_position(cands, MVP_CATALOGUE, "DC", sort=sort)
                self.assertEqual([r.candidate.id for r in ranked], expected)
        flipped = rank_for_position(cands, MVP_CATALOGUE, "DC", sort="age", descending=True)
        self.assertEqual([r.candidate.id for r in flipped], ["a", "c", "b"])

    def test_min_and_max_sort_on_the_honest_bounds(self) -> None:
        cands = self.candidates
        by_min = rank_for_position(cands, MVP_CATALOGUE, "DC", sort="minimum")
        by_max = rank_for_position(cands, MVP_CATALOGUE, "DC", sort="ceiling")

        self.assertEqual(by_min[0].candidate.id, "strong")   # best floor
        self.assertEqual(by_min[-1].candidate.id, "blank")   # a floor of 0
        self.assertEqual(by_max[0].candidate.id, "blank")    # a ceiling of 100

    def test_a_missing_value_sorts_last_in_either_direction(self) -> None:
        cands = [
            candidate("known-age", {}, name="Has Age", age=20),
            candidate("no-age", {}, name="No Age"),
        ]
        for descending in (True, False):
            ranked = rank_for_position(cands, MVP_CATALOGUE, "DC", sort="age", descending=descending)
            self.assertEqual(ranked[-1].candidate.id, "no-age")

    def test_without_a_position_each_player_uses_the_roles_for_his_own_positions(self) -> None:
        striker = ScoutingCandidate(
            id="s", name="Striker", positions=(), raw_positions=("ST",), attributes={},
        )
        ranked = rank_for_position([striker], MVP_CATALOGUE, None, include_raw_external_positions=True)
        striker_roles = {r.name for r in MVP_CATALOGUE.roles.values() if "ST" in r.eligible_positions}

        self.assertEqual(len(ranked), 1)
        self.assertIn(ranked[0].role_name, striker_roles)

    def test_an_outfielder_is_never_shown_as_a_goalkeeper_just_because_those_attributes_are_absent(self) -> None:
        outfield_attributes = {
            name: ranged(3, 9)
            for role in MVP_CATALOGUE.roles.values() if "GK" not in role.eligible_positions
            for name in (a.name for a in role.attributes)
        }
        ranked = rank_for_position(
            [candidate("d", outfield_attributes, name="Outfielder")], MVP_CATALOGUE, None,
        )

        self.assertNotIn("Goalkeeper", ranked[0].role_name)
        self.assertNotIn("Sweeper Keeper", ranked[0].role_name)

    def test_a_goalkeeper_with_goalkeeping_attributes_is_ranked_as_one(self) -> None:
        # A real keeper carries exactly FM's goalkeeper attribute set, which has
        # no Heading, Marking or Tackling, so the outfield roles do not apply.
        every_attribute = {a.name for role in MVP_CATALOGUE.roles.values() for a in role.attributes}
        keeper_attributes = {}
        for name in every_attribute:
            try:
                thresholds_for_attribute(PositionFamily.GOALKEEPER, name)
            except ValueError:
                continue
            keeper_attributes[name] = ranged(10, 16)
        ranked = rank_for_position([candidate("k", keeper_attributes, name="Keeper")], MVP_CATALOGUE, None)

        self.assertIn(ranked[0].role_key, {"gk_defend", "sk_defend"})

    def test_without_any_known_position_every_role_is_tried(self) -> None:
        nobody = ScoutingCandidate(id="n", name="No Positions", positions=(), attributes={})

        self.assertEqual(len(rank_for_position([nobody], MVP_CATALOGUE, None)), 1)

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


from fm_analytics.analytics.xi_models import FamiliarityPolicy  # noqa: E402

ALL_POSITIONS = ("GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "AMC", "AMR", "ST", "WBL", "WBR")


def with_ratings(**overrides: int) -> dict[str, int]:
    return {position: overrides.get(position, 1) for position in ALL_POSITIONS}


class FamiliarityTests(unittest.TestCase):
    POLICY = FamiliarityPolicy()

    def _one(self, ratings, position="DC", policy=POLICY):
        player = candidate("p", {}, name="P", raw_position_familiarity=ratings)
        return rank_for_position([player], MVP_CATALOGUE, position, familiarity_policy=policy)[0]

    def test_a_natural_keeps_the_full_score_and_an_awkward_player_is_halved(self) -> None:
        natural = self._one(with_ratings(DC=20))
        awkward = self._one(with_ratings(DC=1))

        self.assertEqual((natural.familiarity, natural.multiplier, natural.adjusted_median), (20, 1.0, 50.0))
        self.assertEqual((awkward.familiarity, awkward.multiplier, awkward.adjusted_median), (1, 0.5, 25.0))

    def test_the_multiplier_is_the_one_the_tactics_page_uses(self) -> None:
        ranking = self._one(with_ratings(DC=12))

        self.assertEqual(ranking.multiplier, self.POLICY.multiplier(12))

    def test_all_three_scores_are_adjusted_and_the_plain_ones_are_left_alone(self) -> None:
        ranking = self._one(with_ratings(DC=1))

        # (The banded scores carry a 1e-6 rounding artifact -- 100.000001 -- that
        # is invisible at the one decimal the page shows.)
        for got, want in zip((ranking.minimum, ranking.median, ranking.maximum), (0.0, 50.0, 100.0)):
            self.assertAlmostEqual(got, want, places=4)
        for got, want in zip(
            (ranking.adjusted_minimum, ranking.adjusted_median, ranking.adjusted_maximum), (0.0, 25.0, 50.0),
        ):
            self.assertAlmostEqual(got, want, places=4)

    def test_a_raw_zero_rating_is_treated_as_the_worst_rating_not_below_the_floor(self) -> None:
        ranking = self._one(with_ratings(DC=0))

        self.assertEqual(ranking.multiplier, self.POLICY.floor_multiplier)

    def test_nothing_is_adjusted_without_the_opt_in(self) -> None:
        ranking = self._one(with_ratings(DC=1), policy=None)

        self.assertIsNone(ranking.multiplier)
        self.assertIsNone(ranking.adjusted_median)

    def test_a_player_without_ratings_is_left_unadjusted_not_assumed_unfamiliar(self) -> None:
        ranking = self._one(None)

        self.assertIsNone(ranking.multiplier)
        self.assertEqual(ranking.median, 50.0)

    def test_with_no_position_chosen_the_role_is_picked_where_he_is_comfortable(self) -> None:
        # Identical attributes for every role; only familiarity separates them.
        player = ScoutingCandidate(
            id="p", name="P", positions=(), attributes={}, raw_position_familiarity=with_ratings(ST=20),
        )
        ranking = rank_for_position([player], MVP_CATALOGUE, None, familiarity_policy=self.POLICY)[0]
        role = MVP_CATALOGUE.roles[ranking.role_key]

        self.assertIn("ST", role.eligible_positions)
        self.assertEqual(ranking.multiplier, 1.0)

    def test_the_familiarity_sorts_put_players_without_ratings_last(self) -> None:
        players = [
            candidate("a", {}, name="A", raw_position_familiarity=with_ratings(DC=5)),
            candidate("b", {}, name="B", raw_position_familiarity=with_ratings(DC=18)),
            candidate("c", {}, name="C"),
        ]
        by_rating = rank_for_position(players, MVP_CATALOGUE, "DC", sort="familiarity", familiarity_policy=self.POLICY)
        by_today = rank_for_position(players, MVP_CATALOGUE, "DC", sort="adjusted", familiarity_policy=self.POLICY)

        self.assertEqual([r.candidate.id for r in by_rating], ["b", "a", "c"])
        self.assertEqual([r.candidate.id for r in by_today], ["b", "a", "c"])

    def test_ratings_must_be_valid(self) -> None:
        with self.assertRaises(ValueError):
            candidate("bad", {}, raw_position_familiarity={"DC": 25})
        with self.assertRaises(ValueError):
            candidate("bad", {}, raw_position_familiarity={"DC": True})

    def test_ratings_round_trip_from_the_capture_contract(self) -> None:
        parsed = ScoutingCandidate.from_dict({
            "id": "1", "name": "N", "positions": [], "attributes": {},
            "rawPositionFamiliarity": {"DC": 17, "DR": 3},
        })

        self.assertEqual(parsed.raw_position_familiarity, {"DC": 17, "DR": 3})
