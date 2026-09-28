import unittest
from dataclasses import replace

from fm_analytics.analytics import (
    FamiliarityPolicy,
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    ScoutingCandidate,
    TacticDefinition,
    TacticSlot,
    assess_weaknesses,
    evaluate_tactic,
    rank_candidates_for_tactic,
    score_role,
    sort_tactic_assessments,
)
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "tactic-scouting-test-v1"
NO_FAMILIARITY_DISCOUNT = FamiliarityPolicy(floor_multiplier=1.0)
ROLE = RoleDefinition(
    key="generic",
    name="Generic",
    eligible_positions=("GK", "DC", "MC", "ST"),
    attributes=(RoleAttribute("quality", 1),),
    catalogue_version=VERSION,
)
POSITIONS = ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST")
TACTIC = TacticDefinition(
    key="test",
    name="Test tactic",
    formation="test shape",
    mentality="Balanced",
    instructions=(),
    slots=tuple(
        TacticSlot(key=f"slot-{index}", position=position, role_key=ROLE.key)
        for index, position in enumerate(POSITIONS)
    ),
    catalogue_version=VERSION,
)
CATALOGUE = FootballCatalogue(
    version=VERSION,
    roles={ROLE.key: ROLE},
    tactics={TACTIC.key: TACTIC},
)


def owned_squad(quality: int = 10) -> tuple[PlayerSelectionInput, ...]:
    return tuple(
        PlayerSelectionInput(
            id=f"owned-{index}",
            name=f"Owned {index}",
            positions=(position,),
            attributes={
                "quality": AttributeObservation(Visibility.KNOWN, value=quality)
            },
            availability="available",
            injured=False,
            suspended=False,
            condition_percent=100,
            match_fitness_percent=100,
        )
        for index, position in enumerate(POSITIONS)
    )


def candidate(
    identifier: str,
    name: str,
    observation: AttributeObservation,
) -> ScoutingCandidate:
    return ScoutingCandidate(
        id=identifier,
        name=name,
        positions=("ST",),
        attributes={"quality": observation},
        age=22,
        scouting_knowledge=80,
    )


class TacticScoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.squad = owned_squad()
        self.baseline = evaluate_tactic(
            TACTIC,
            self.squad,
            CATALOGUE,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )
        # Every position in `owned_squad` has exactly one occupant, so every
        # slot is flagged NO_BACKUP -- deliberately, so a cover assessment can
        # be tested against "there is currently nobody at all" as well as
        # against a real current cover.
        self.weakness_report = assess_weaknesses(self.baseline, self.squad, CATALOGUE)

    def test_strong_target_matches_a_full_reoptimisation_and_weak_target_is_depth(self) -> None:
        strong = candidate(
            "strong",
            "Strong Target",
            AttributeObservation(Visibility.KNOWN, value=20),
        )
        weak = candidate(
            "weak",
            "Weak Target",
            AttributeObservation(Visibility.KNOWN, value=5),
        )

        assessments = rank_candidates_for_tactic(
            (strong, weak),
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )
        by_id = {item.candidate.id: item for item in assessments}
        augmented = evaluate_tactic(
            TACTIC,
            self.squad
            + (
                PlayerSelectionInput(
                    id="scouting:strong",
                    name="Strong Target",
                    positions=("ST",),
                    attributes=strong.attributes,
                    availability="available",
                    injured=False,
                    suspended=False,
                    condition_percent=100,
                    match_fitness_percent=100,
                ),
            ),
            CATALOGUE,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )

        self.assertTrue(by_id["strong"].starts_at_estimate)
        self.assertGreater(by_id["strong"].score_gain.estimate, 0)
        self.assertAlmostEqual(
            by_id["strong"].projected_score.estimate,
            augmented.score.central,
        )
        self.assertEqual(len(by_id["strong"].replaced_player_names), 1)
        self.assertFalse(by_id["weak"].starts_at_estimate)
        self.assertEqual(by_id["weak"].score_gain.estimate, 0)
        self.assertEqual(by_id["weak"].projected_score.estimate, self.baseline.score.central)

    def test_scouting_uncertainty_can_show_ceiling_upside_without_an_estimated_start(self) -> None:
        uncertain = candidate(
            "uncertain",
            "Uncertain Target",
            AttributeObservation(Visibility.RANGE, minimum=1, maximum=19),
        )

        assessment = rank_candidates_for_tactic(
            (uncertain,),
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )[0]

        self.assertFalse(assessment.starts_at_estimate)
        self.assertEqual(assessment.score_gain.floor, 0)
        self.assertEqual(assessment.score_gain.estimate, 0)
        self.assertGreater(assessment.score_gain.ceiling, 0)
        self.assertEqual(assessment.ranged_attributes, 1)

    def test_candidates_sort_by_their_effect_on_the_selected_tactic(self) -> None:
        candidates = (
            candidate("weak", "Weak", AttributeObservation(Visibility.KNOWN, value=5)),
            candidate("strong", "Strong", AttributeObservation(Visibility.KNOWN, value=20)),
        )
        assessments = rank_candidates_for_tactic(
            candidates,
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )

        ordered = sort_tactic_assessments(assessments, sort="tactic_gain")

        self.assertEqual([item.candidate.id for item in ordered], ["strong", "weak"])

    def test_cover_assessment_is_absent_for_starters_and_present_for_non_starters(self) -> None:
        strong = candidate(
            "strong",
            "Strong Target",
            AttributeObservation(Visibility.KNOWN, value=20),
        )
        weak = candidate(
            "weak",
            "Weak Target",
            AttributeObservation(Visibility.KNOWN, value=5),
        )

        assessments = rank_candidates_for_tactic(
            (strong, weak),
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
            weakness_report=self.weakness_report,
        )
        by_id = {item.candidate.id: item for item in assessments}

        # Strong starts, so starting supersedes cover: no cover assessment at all.
        self.assertTrue(by_id["strong"].starts_at_estimate)
        self.assertIsNone(by_id["strong"].cover_assessment)
        self.assertFalse(by_id["strong"].could_be_first_cover)

        # Weak does not start, but every slot in this squad has no backup at
        # all, so he becomes outright first cover with nothing to clear.
        self.assertFalse(by_id["weak"].starts_at_estimate)
        cover = by_id["weak"].cover_assessment
        self.assertIsNotNone(cover)
        self.assertTrue(by_id["weak"].could_be_first_cover)
        self.assertEqual(cover.position, "ST")
        self.assertIsNone(cover.current_cover_name)
        self.assertIsNone(cover.current_cover_score)
        self.assertAlmostEqual(cover.margin, cover.candidate_score.central)

    def test_cover_assessment_requires_clearing_the_current_backup(self) -> None:
        # A backup weaker than the existing quality-10 starters, so he stays
        # a backup rather than displacing one of them.
        backup_quality = 8
        squad_with_backup = self.squad + (
            PlayerSelectionInput(
                id="backup",
                name="Backup Striker",
                positions=("ST",),
                attributes={
                    "quality": AttributeObservation(Visibility.KNOWN, value=backup_quality)
                },
                availability="available",
                injured=False,
                suspended=False,
                condition_percent=100,
                match_fitness_percent=100,
            ),
        )
        baseline = evaluate_tactic(
            TACTIC, squad_with_backup, CATALOGUE, familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )
        weakness_report = assess_weaknesses(baseline, squad_with_backup, CATALOGUE)
        backup_central = score_role(
            ROLE, {"quality": AttributeObservation(Visibility.KNOWN, value=backup_quality)}
        ).score.central

        # `clears_it` must beat the backup (8) but stay below the existing
        # quality-10 starters, or he would displace one of them and start.
        too_weak = candidate(
            "too-weak", "Too Weak", AttributeObservation(Visibility.KNOWN, value=backup_quality - 2),
        )
        clears_it = candidate(
            "clears-it", "Clears It", AttributeObservation(Visibility.KNOWN, value=backup_quality + 1),
        )
        assessments = rank_candidates_for_tactic(
            (too_weak, clears_it),
            squad_with_backup,
            TACTIC,
            CATALOGUE,
            baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
            weakness_report=weakness_report,
        )
        by_id = {item.candidate.id: item for item in assessments}

        self.assertFalse(by_id["too-weak"].starts_at_estimate)
        self.assertIsNone(by_id["too-weak"].cover_assessment)

        self.assertFalse(by_id["clears-it"].starts_at_estimate)
        cover = by_id["clears-it"].cover_assessment
        self.assertIsNotNone(cover)
        self.assertEqual(cover.current_cover_name, "Backup Striker")
        self.assertAlmostEqual(cover.current_cover_score, backup_central)
        self.assertGreater(cover.candidate_score.central, cover.current_cover_score)
        self.assertAlmostEqual(
            cover.margin, round(cover.candidate_score.central - cover.current_cover_score, 6)
        )

    def test_median_scenario_is_bounded_and_could_start_tracks_the_ceiling(self) -> None:
        unknown = candidate("unknown", "Unknown Target", AttributeObservation(Visibility.UNKNOWN))
        strong = candidate(
            "strong", "Strong Target", AttributeObservation(Visibility.KNOWN, value=20),
        )

        assessments = rank_candidates_for_tactic(
            (unknown, strong),
            self.squad,
            TACTIC,
            CATALOGUE,
            self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
            weakness_report=self.weakness_report,
        )
        by_id = {item.candidate.id: item for item in assessments}

        # An unknown attribute counts at mid-scale for the median but at the
        # scale minimum for the floor and estimate, so a totally unscouted
        # candidate has a median strictly between his floor and his ceiling.
        unknown_item = by_id["unknown"]
        self.assertLessEqual(unknown_item.player_fit.lower, unknown_item.player_fit.central)
        self.assertLess(unknown_item.player_fit.central, unknown_item.player_median)
        self.assertLess(unknown_item.player_median, unknown_item.player_fit.upper)
        # Scouted for nothing at all: even though his best slot is flagged
        # NO_BACKUP (every slot in this squad is), his median would be a pure
        # mid-scale fabrication, so trial priority withholds it rather than
        # ranking him on an invented number.
        self.assertIsNone(unknown_item.trial_priority)

        # A fully known candidate has nothing left to resolve, so his median
        # equals his central estimate exactly.
        strong_item = by_id["strong"]
        self.assertAlmostEqual(strong_item.player_median, strong_item.player_fit.central)
        self.assertTrue(strong_item.starts_at_estimate)
        self.assertTrue(strong_item.could_start)

        # Weak enough that even his ceiling (identical to his central
        # estimate here, since his attribute is exactly known) cannot start.
        weak = candidate("weak", "Weak Target", AttributeObservation(Visibility.KNOWN, value=5))
        weak_item = rank_candidates_for_tactic(
            (weak,), self.squad, TACTIC, CATALOGUE, self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )[0]
        self.assertFalse(weak_item.could_start)

    def test_trial_priority_is_set_only_when_the_best_slot_is_itself_weak(self) -> None:
        strong = candidate(
            "strong", "Strong Target", AttributeObservation(Visibility.KNOWN, value=20),
        )

        with_weak_slots = rank_candidates_for_tactic(
            (strong,), self.squad, TACTIC, CATALOGUE, self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
            weakness_report=self.weakness_report,
        )[0]
        without_a_weakness_report = rank_candidates_for_tactic(
            (strong,), self.squad, TACTIC, CATALOGUE, self.baseline,
            familiarity_policy=NO_FAMILIARITY_DISCOUNT,
        )[0]

        # Every slot in this squad is flagged NO_BACKUP, so with the weakness
        # report supplied, the candidate's best slot is a weak one.
        self.assertIsNotNone(with_weak_slots.trial_priority)
        self.assertAlmostEqual(with_weak_slots.trial_priority, with_weak_slots.player_median)
        # No weakness report at all means no opinion, not zero.
        self.assertIsNone(without_a_weakness_report.trial_priority)

    def test_rejects_a_weakness_report_for_a_different_tactic(self) -> None:
        mismatched = replace(self.weakness_report, tactic_key="other")

        with self.assertRaisesRegex(ValueError, "weakness report must be for the selected tactic"):
            rank_candidates_for_tactic(
                (), self.squad, TACTIC, CATALOGUE, self.baseline,
                weakness_report=mismatched,
            )


if __name__ == "__main__":
    unittest.main()
