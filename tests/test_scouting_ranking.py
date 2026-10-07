import unittest

from dataclasses import replace
from unittest.mock import patch

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    ScoutingCandidate,
    ScoutingFilters,
    assess_scouting_candidates,
    filter_position_rankings,
    filter_scouting_candidates,
    rank_for_position,
    scouting_mode,
    sort_for_mode,
    sort_scouting_assessments,
)
from fm_analytics.analytics import scouting as scouting_module
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

    # FM's sandboxed answer names every attribute for every player and returns
    # the other family's set as unknown, so these sheets carry both sets.
    _EVERY_ATTRIBUTE = {a.name for role in MVP_CATALOGUE.roles.values() for a in role.attributes}

    def _full_sheet(self, **shown: AttributeObservation) -> dict[str, AttributeObservation]:
        sheet = {name: AttributeObservation(Visibility.UNKNOWN) for name in self._EVERY_ATTRIBUTE}
        sheet.update(shown)
        return sheet

    def test_an_outfielder_whose_goalkeeping_attributes_are_unknown_is_not_a_goalkeeper(self) -> None:
        # Harry Edmondson (a striker) was a Sweeper Keeper: his unknown
        # Handling, Reflexes, ... were taken for a goalkeeper's sheet.
        sheet = self._full_sheet(heading=ranged(4, 10), acceleration=ranged(12, 19))
        ranked = rank_for_position([
            ScoutingCandidate(id="h", name="Striker", positions=(), raw_positions=("ST",), attributes=sheet),
        ], MVP_CATALOGUE, None)

        self.assertNotIn("GK", MVP_CATALOGUE.roles[ranked[0].role_key].eligible_positions)

    def test_a_keeper_whose_outfield_attributes_are_unknown_is_still_a_goalkeeper(self) -> None:
        sheet = self._full_sheet(handling=ranged(8, 15), reflexes=ranged(10, 15))
        ranked = rank_for_position([
            ScoutingCandidate(id="k", name="Keeper", positions=(), attributes=sheet),
        ], MVP_CATALOGUE, None)

        self.assertIn(ranked[0].role_key, {"gk_defend", "sk_defend"})

    def test_a_sheet_with_nothing_shown_follows_his_positions_not_the_goalkeeping_names(self) -> None:
        striker = ScoutingCandidate(
            id="s", name="Unscouted", positions=(), raw_positions=("ST",), attributes=self._full_sheet(),
        )
        ranked = rank_for_position([striker], MVP_CATALOGUE, None, include_raw_external_positions=True)

        self.assertIn("ST", MVP_CATALOGUE.roles[ranked[0].role_key].eligible_positions)

    def test_without_any_known_position_every_role_is_tried(self) -> None:
        nobody = ScoutingCandidate(id="n", name="No Positions", positions=(), attributes={})

        self.assertEqual(len(rank_for_position([nobody], MVP_CATALOGUE, None)), 1)

    def test_a_position_no_role_covers_ranks_nobody(self) -> None:
        self.assertEqual(rank_for_position(self.candidates, MVP_CATALOGUE, "XX"), ())


class FalseGoalkeeperTests(unittest.TestCase):
    """The GK list once held hundreds of outfielders (Phil Bardsley, Jon Stead...).

    Their raw position ratings had read as all zeros, the capture turned that
    into GK, and with GK chosen their unknown goalkeeping attributes scored
    them above genuine keepers.
    """

    _EVERY_ATTRIBUTE = {a.name for role in MVP_CATALOGUE.roles.values() for a in role.attributes}
    _RAW = {"include_raw_external_positions": True}

    def _sheet(self, **shown: AttributeObservation) -> dict[str, AttributeObservation]:
        sheet = {name: AttributeObservation(Visibility.UNKNOWN) for name in self._EVERY_ATTRIBUTE}
        sheet.update(shown)
        return sheet

    def _player(self, identifier, sheet, raw_positions=("GK",), familiarity=None) -> ScoutingCandidate:
        return ScoutingCandidate(
            id=identifier, name=identifier, positions=(), raw_positions=raw_positions,
            raw_position_familiarity=familiarity, attributes=sheet,
        )

    def test_an_unread_all_zero_position_record_gives_no_position(self) -> None:
        unread = ScoutingCandidate.from_dict({
            "id": "z", "name": "Unread", "positions": [], "rawPositions": ["GK"],
            "rawPositionFamiliarity": {"GK": 0, "DC": 0, "ST": 0}, "attributes": {},
        })

        self.assertEqual(unread.positions_for(**self._RAW), ())
        # Not "unfamiliar everywhere" either: an unread record is no rating.
        self.assertIsNone(unread.raw_position_familiarity)
        self.assertEqual(filter_scouting_candidates([unread], ScoutingFilters(position="GK", **self._RAW)), ())

    def test_an_outfield_sheet_is_not_a_goalkeeper_whatever_the_raw_read_says(self) -> None:
        outfielder = self._player("o", self._sheet(tackling=ranged(10, 14)))
        keeper = self._player("k", self._sheet(handling=ranged(10, 14)))

        listed = filter_scouting_candidates([outfielder, keeper], ScoutingFilters(position="GK", **self._RAW))

        self.assertEqual([item.id for item in listed], ["k"])

    def test_a_keeper_sheet_is_not_an_outfielder_whatever_the_raw_read_says(self) -> None:
        keeper = self._player("k", self._sheet(reflexes=known(14)), raw_positions=("GK", "DC"))

        self.assertEqual(keeper.positions_for(**self._RAW), ("GK",))

    def test_a_sheet_that_cannot_say_keeps_its_raw_positions(self) -> None:
        nothing_shown = self._player("n", self._sheet())
        both_shown = self._player("b", self._sheet(handling=known(3), tackling=known(12)), ("DC",))

        self.assertEqual(nothing_shown.positions_for(**self._RAW), ("GK",))
        self.assertEqual(both_shown.positions_for(**self._RAW), ("DC",))

    def test_a_goalkeeper_role_lists_no_outfielder_without_a_position(self) -> None:
        outfielder = self._player("o", self._sheet(heading=ranged(12, 16)), raw_positions=())
        keeper = self._player("k", self._sheet(handling=ranged(12, 16)), raw_positions=())
        unscouted = self._player("u", self._sheet(), raw_positions=())

        listed = assess_scouting_candidates(
            [outfielder, keeper, unscouted], MVP_CATALOGUE, ScoutingFilters(role_key="gk_defend"),
        )

        self.assertEqual(sorted(item.candidate.id for item in listed), ["k", "u"])


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


class KnowledgeCellTests(unittest.TestCase):
    """The count covers the role's attributes, so the total must be visible."""

    def ranking(self, visibilities):
        from fm_analytics.web.scouting_render import _knowledge_cell

        attributes = {
            "finishing": AttributeObservation(visibility=Visibility.KNOWN, value=15),
        }
        item = rank_for_position(
            [candidate("1", attributes)], MVP_CATALOGUE, "ST",
            sort="median", descending=True, include_raw_external_positions=True,
        )[0]
        return _knowledge_cell(item), item

    def test_a_fully_known_role_shows_the_denominator(self) -> None:
        cell, item = self.ranking(None)
        total = item.known_attributes + item.ranged_attributes + item.unknown_attributes
        self.assertIn(f"of {total} known", cell)
        self.assertGreater(total, 0)

    def test_gaps_are_spelled_out_rather_than_left_as_bare_numbers(self) -> None:
        cell, item = self.ranking(None)
        if item.unknown_attributes:
            self.assertIn("unknown", cell)
        if item.ranged_attributes:
            self.assertIn("ranged", cell)


class ModeSortTests(unittest.TestCase):
    def test_mode_follows_tactic_then_role(self) -> None:
        self.assertEqual(scouting_mode("balanced_442", "cd_defend"), "tactic")
        self.assertEqual(scouting_mode(None, "cd_defend"), "role")
        self.assertEqual(scouting_mode(None, None), "ranking")

    def test_a_sort_the_table_has_no_column_for_falls_back_to_the_default(self) -> None:
        self.assertEqual(sort_for_mode("age", "role"), "age")
        self.assertEqual(sort_for_mode("tactic_gain", "ranking"), "median")
        self.assertEqual(sort_for_mode("role", "role"), "priority")
        self.assertEqual(sort_for_mode("priority", "tactic"), "tactic_gain")
        self.assertEqual(sort_for_mode(None, "tactic"), "tactic_gain")
        self.assertEqual(sort_for_mode("adjusted", "tactic"), "tactic_gain")


class RoleTargetSortTests(unittest.TestCase):
    def setUp(self) -> None:
        strong = {attribute.name: known(16) for attribute in ROLE.attributes}
        self.assessments = assess_scouting_candidates(
            [
                candidate("old", strong, name="Old Strong", age=33, value=10),
                candidate("young", {}, name="Young Blank", age=17, value=900),
                candidate("mid", {ROLE.attributes[0].name: known(9)}, name="Mid Partial", age=25),
            ],
            MVP_CATALOGUE,
            ScoutingFilters(role_key="cd_defend", position="DC"),
        )

    def names(self, **kwargs) -> list[str]:
        return [item.candidate.name for item in sort_scouting_assessments(self.assessments, **kwargs)]

    def test_priority_puts_proven_fits_first_and_flips(self) -> None:
        best_first = self.names(sort="priority", descending=True)

        self.assertEqual(best_first[0], "Old Strong")
        self.assertEqual(self.names(sort="priority", descending=False), best_first[::-1])

    def test_any_column_sorts_either_way_with_missing_values_last(self) -> None:
        self.assertEqual(self.names(sort="age", descending=False), ["Young Blank", "Mid Partial", "Old Strong"])
        self.assertEqual(self.names(sort="age", descending=True), ["Old Strong", "Mid Partial", "Young Blank"])
        # Only two players have a value; the third is last whichever way it goes.
        self.assertEqual(self.names(sort="value", descending=False)[-1], "Mid Partial")
        self.assertEqual(self.names(sort="value", descending=True)[-1], "Mid Partial")

    def test_median_sorts_by_the_estimate_not_the_conservative_score(self) -> None:
        by_median = self.names(sort="median", descending=True)

        self.assertEqual(by_median[0], "Old Strong")
        # An unscouted player's median (50) is above a partly-known low one's.
        self.assertLess(by_median.index("Young Blank"), by_median.index("Mid Partial"))

    def test_unknown_sorts_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            sort_scouting_assessments(self.assessments, sort="role")


class RoleFamiliarityTests(unittest.TestCase):
    """With a role chosen, the raw-positions opt-in gives the same in-position score as the ranking."""

    POLICY = FamiliarityPolicy()
    WINGER = "winger_ml_mr_support"

    def winger(self, identifier: str, ratings) -> ScoutingCandidate:
        return ScoutingCandidate(
            id=identifier, name=identifier, positions=("ML", "MR"), attributes={},
            raw_position_familiarity=ratings,
        )

    def assess(self, players, position="ML", policy=POLICY):
        return assess_scouting_candidates(
            players, MVP_CATALOGUE, ScoutingFilters(role_key=self.WINGER, position=position),
            familiarity_policy=policy,
        )

    def test_the_chosen_position_rating_discounts_all_three_scores(self) -> None:
        item = self.assess([self.winger("w", with_ratings(ML=15, MR=20))])[0]
        multiplier = self.POLICY.multiplier(15)

        self.assertEqual((item.familiarity, item.multiplier), (15, multiplier))
        for got, plain in (
            (item.adjusted_minimum, item.role_score.score.lower),
            (item.adjusted_median, item.median),
            (item.adjusted_maximum, item.role_score.score.upper),
        ):
            self.assertAlmostEqual(got, plain * multiplier, places=5)
        # The role score itself stays attribute-based.
        self.assertEqual(item.median, 50.0)

    def test_with_no_position_chosen_his_best_position_for_the_role_counts(self) -> None:
        item = self.assess([self.winger("w", with_ratings(ML=5, MR=18))], position=None)[0]

        self.assertEqual(item.familiarity, 18)

    def test_it_is_the_figure_the_position_ranking_shows(self) -> None:
        player = self.winger("w", with_ratings(ML=12))
        role_item = self.assess([player])[0]
        ranking = rank_for_position([player], MVP_CATALOGUE, "ML", familiarity_policy=self.POLICY)[0]

        self.assertEqual(
            (role_item.familiarity, role_item.multiplier, role_item.adjusted_median),
            (ranking.familiarity, ranking.multiplier, ranking.adjusted_median),
        )

    def test_nothing_is_adjusted_without_the_opt_in_or_without_ratings(self) -> None:
        unticked = self.assess([self.winger("a", with_ratings(ML=15))], policy=None)[0]
        unrated = self.assess([self.winger("b", None)])[0]

        for item in (unticked, unrated):
            self.assertIsNone(item.familiarity)
            self.assertIsNone(item.multiplier)
            self.assertIsNone(item.adjusted_median)

    def test_the_familiarity_sorts_put_players_without_ratings_last(self) -> None:
        assessments = self.assess([
            self.winger("a", with_ratings(ML=5)),
            self.winger("b", with_ratings(ML=18)),
            self.winger("c", None),
        ])

        for sort in ("familiarity", "adjusted"):
            ordered = sort_scouting_assessments(assessments, sort=sort)
            self.assertEqual([item.candidate.id for item in ordered], ["b", "a", "c"], sort)


class InformationFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        strong = {attribute.name: known(16) for attribute in ROLE.attributes}
        self.rankings = rank_for_position(
            [
                candidate("full", strong, attributes_observed_at="2019-07-21"),
                candidate("partial", {ROLE.attributes[0].name: ranged(4, 12)},
                          attributes_observed_at="2019-07-21"),
                candidate("blank", {}, attributes_observed_at="2019-07-21"),
                candidate("uncaptured", {}),
            ],
            MVP_CATALOGUE, "DC",
        )

    def kept(self, **filters) -> set[str]:
        return {r.candidate.id for r in filter_position_rankings(self.rankings, ScoutingFilters(**filters))}

    def test_visibility_buckets_match_the_role_tables(self) -> None:
        self.assertEqual(self.kept(visibility="known"), {"full"})
        self.assertEqual(self.kept(visibility="partial"), {"partial"})
        # "Nothing known" never includes a player whose attributes were not read.
        self.assertEqual(self.kept(visibility="unknown"), {"blank"})

    def test_the_floor_and_ceiling_filters_use_min_and_max(self) -> None:
        self.assertEqual(self.kept(minimum_floor=50), {"full"})
        # A fully known 16 across the role tops out well below 90; an unknown
        # profile could still reach 100, so it stays.
        kept = self.kept(minimum_ceiling=90)
        self.assertNotIn("full", kept)
        self.assertLessEqual({"blank", "uncaptured"}, kept)
        self.assertEqual(self.kept(minimum_ceiling=101), set())
        self.assertEqual(self.kept(minimum_ceiling=101, include_unlikely=True),
                         {"full", "partial", "blank", "uncaptured"})

    def test_the_range_filter_keeps_players_scouting_has_pinned_down(self) -> None:
        ranges = {r.candidate.id: r.maximum - r.minimum for r in self.rankings}

        self.assertEqual(self.kept(maximum_range=0), {"full"})
        # One ranged attribute narrows the spread a little; everyone else could be anything.
        self.assertEqual(self.kept(maximum_range=ranges["partial"]), {"full", "partial"})
        self.assertEqual(self.kept(maximum_range=100), {"full", "partial", "blank", "uncaptured"})
        with self.assertRaises(ValueError):
            ScoutingFilters(maximum_range=-1)

    def test_the_range_sort_is_max_minus_min(self) -> None:
        by_range = rank_for_position(
            [r.candidate for r in self.rankings], MVP_CATALOGUE, "DC", sort="upside", descending=False
        )

        self.assertEqual(by_range[0].candidate.id, "full")
        self.assertEqual(by_range[1].candidate.id, "partial")


class RankingCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pool = [
            candidate("a", {ROLE.attributes[0].name: known(12)}, name="A", age=20),
            candidate("b", {ROLE.attributes[0].name: known(8)}, name="B", age=30),
        ]

    def calls_for(self, position: str | None = "DC", **kwargs) -> int:
        with patch.object(scouting_module, "score_role", wraps=scouting_module.score_role) as spy:
            rank_for_position(self.pool, MVP_CATALOGUE, position, **kwargs)
            return spy.call_count

    def test_a_cache_scores_each_player_once_however_the_list_is_re_sorted(self) -> None:
        cache: dict = {}

        first = self.calls_for(cache=cache)
        again = self.calls_for(cache=cache, sort="age", descending=True)

        self.assertGreater(first, 0)
        self.assertEqual(again, 0)

    def test_cached_results_are_identical_to_uncached_ones(self) -> None:
        cache: dict = {}
        rank_for_position(self.pool, MVP_CATALOGUE, "DC", cache=cache)

        self.assertEqual(
            rank_for_position(self.pool, MVP_CATALOGUE, "DC", sort="age", cache=cache),
            rank_for_position(self.pool, MVP_CATALOGUE, "DC", sort="age"),
        )

    def test_a_new_capture_of_the_same_player_is_scored_afresh(self) -> None:
        cache: dict = {}
        rank_for_position(self.pool, MVP_CATALOGUE, "DC", cache=cache)
        recaptured = [
            candidate("a", {ROLE.attributes[0].name: known(20)}, name="A", age=20), self.pool[1],
        ]

        ranked = {r.candidate.id: r for r in rank_for_position(recaptured, MVP_CATALOGUE, "DC", cache=cache)}

        self.assertEqual(
            ranked["a"].median, rank_for_position(recaptured[:1], MVP_CATALOGUE, "DC")[0].median
        )

    def test_arguments_that_change_the_ranking_do_not_share_an_entry(self) -> None:
        pool = [replace(player, raw_position_familiarity=with_ratings(DC=8)) for player in self.pool]
        raw = dict(include_raw_external_positions=True, familiarity_policy=FamiliarityPolicy())
        cache: dict = {}
        rank_for_position(pool, MVP_CATALOGUE, "DC", cache=cache)

        for position, options in (("DC", raw), ("MC", {}), (None, raw)):
            with self.subTest(position=position, options=options):
                self.assertEqual(
                    rank_for_position(pool, MVP_CATALOGUE, position, cache=cache, **options),
                    rank_for_position(pool, MVP_CATALOGUE, position, **options),
                )
        self.assertIsNotNone(rank_for_position(pool, MVP_CATALOGUE, "DC", cache=cache, **raw)[0].multiplier)

    def test_a_new_raw_positions_choice_reuses_the_role_scores(self) -> None:
        # Ticking "raw positions" re-ranked the whole pool from scratch: half a
        # minute for a Player Search pool, though no attribute score changes.
        cache: dict = {}
        rank_for_position(self.pool, MVP_CATALOGUE, "DC", cache=cache)

        self.assertEqual(self.calls_for(
            cache=cache, include_raw_external_positions=True, familiarity_policy=FamiliarityPolicy(),
        ), 0)
        # Roles never tried for these players still have to be scored.
        self.assertGreater(self.calls_for(cache=cache, position="MC"), 0)

    def test_players_with_nothing_visible_share_one_set_of_role_scores(self) -> None:
        blanks = [candidate(name, {}) for name in ("x", "y", "z")]

        with patch.object(scouting_module, "score_role", wraps=scouting_module.score_role) as spy:
            rank_for_position(blanks, MVP_CATALOGUE, "DC", cache={})

        self.assertEqual(spy.call_count, sum("DC" in role.eligible_positions for role in MVP_CATALOGUE.roles.values()))
