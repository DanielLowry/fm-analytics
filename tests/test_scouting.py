import unittest

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    ScoutRecommendation,
    ScoutingCandidate,
    ScoutingFilters,
    assess_scouting_candidates,
    available_fact_values,
)
from fm_analytics.domain import AttributeObservation, Visibility


def candidate(identifier: str, attributes, **kwargs) -> ScoutingCandidate:
    return ScoutingCandidate(
        id=identifier, name=kwargs.pop("name", identifier), positions=("ST",),
        attributes=attributes, **kwargs,
    )


class ScoutingTests(unittest.TestCase):
    def test_unscouted_eligible_player_is_recommended_for_scouting(self) -> None:
        result = assess_scouting_candidates(
            [candidate("unknown", {})], MVP_CATALOGUE,
            ScoutingFilters(role_key="af_attack"),
        )

        self.assertEqual(result[0].recommendation, ScoutRecommendation.SCOUT_FIRST)
        self.assertEqual(result[0].known_attributes, 0)
        self.assertEqual(result[0].unknown_attributes, 8)
        self.assertTrue(result[0].scout_next)

    def test_ranges_keep_a_floor_and_ceiling_and_need_more_scouting(self) -> None:
        attributes = {
            name: AttributeObservation(Visibility.RANGE, minimum=8, maximum=16)
            for name in ("finishing", "offTheBall", "acceleration", "pace", "anticipation", "composure", "dribbling", "firstTouch")
        }
        result = assess_scouting_candidates(
            [candidate("range", attributes)], MVP_CATALOGUE,
            ScoutingFilters(role_key="af_attack", visibility="partial"),
        )

        self.assertEqual(result[0].recommendation, ScoutRecommendation.SCOUT_TO_DECIDE)
        self.assertLess(result[0].role_score.score.lower, result[0].role_score.score.upper)
        self.assertEqual(result[0].ranged_attributes, 8)

    def test_visible_filters_do_not_substitute_missing_values(self) -> None:
        candidates = [
            candidate("young", {}, age=19, club="Hungerford Town", footedness="Right", facts={"contract": "Part-time"}),
            candidate("old", {}, age=31, club="Bath City", footedness="Left", facts={"contract": "Full-time"}),
        ]
        result = assess_scouting_candidates(
            candidates, MVP_CATALOGUE,
            ScoutingFilters(role_key="af_attack", maximum_age=25, footedness="Right", facts={"contract": "Part-time"}),
        )

        self.assertEqual([item.candidate.id for item in result], ["young"])
        self.assertEqual(available_fact_values(candidates)["contract"], ("Full-time", "Part-time"))

    def test_unlikely_players_are_hidden_unless_explicitly_requested(self) -> None:
        low_attributes = {
            name: AttributeObservation(Visibility.KNOWN, value=1)
            for name in ("finishing", "offTheBall", "acceleration", "pace", "anticipation", "composure", "dribbling", "firstTouch")
        }
        default = assess_scouting_candidates(
            [candidate("low", low_attributes)], MVP_CATALOGUE,
            ScoutingFilters(role_key="af_attack", minimum_ceiling=50),
        )
        included = assess_scouting_candidates(
            [candidate("low", low_attributes)], MVP_CATALOGUE,
            ScoutingFilters(role_key="af_attack", minimum_ceiling=50, include_unlikely=True),
        )

        self.assertEqual(default, ())
        self.assertEqual(included[0].recommendation, ScoutRecommendation.UNLIKELY)

    def test_unknown_position_stays_in_the_general_scouting_queue_but_never_matches_a_position_filter(self) -> None:
        unknown_position = ScoutingCandidate(
            id="unplaced", name="Unplaced", positions=(), attributes={},
        )

        general = assess_scouting_candidates(
            [unknown_position], MVP_CATALOGUE, ScoutingFilters(role_key="af_attack"),
        )
        striker_only = assess_scouting_candidates(
            [unknown_position], MVP_CATALOGUE,
            ScoutingFilters(role_key="af_attack", position="ST"),
        )

        self.assertEqual(general[0].recommendation, ScoutRecommendation.SCOUT_FIRST)
        self.assertEqual(striker_only, ())


if __name__ == "__main__":
    unittest.main()
