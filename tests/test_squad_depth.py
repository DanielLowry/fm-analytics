import unittest

from fm_analytics.analytics import (
    AttributePriority,
    FamiliarityPolicy,
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    assess_squad_depth,
    evaluate_tactic,
)
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "squad-depth-test-v1"
NO_FAMILIARITY_PENALTY = FamiliarityPolicy(penalty_weight=0)

# Every position below appears at most once per tactic. `assess_weaknesses`
# flags a single shared backup covering several simultaneous starting slots
# of the *same* position as its own weakness (SHARED_COVER); keeping every
# position single-slot here keeps that mechanic out of this module's tests,
# which are about cross-tactic aggregation, not depth-model detail already
# covered by test_weaknesses.py.
ROLE_A = RoleDefinition(
    key="role_a",
    name="Role A",
    eligible_positions=("GK", "DL", "DR", "DC", "MC1", "MC2", "AML", "AMR", "ST1", "ST2", "DM"),
    attributes=(RoleAttribute("quality", 1, AttributePriority.REQUIRED),),
    catalogue_version=VERSION,
)
ROLE_B = RoleDefinition(
    key="role_b",
    name="Role B",
    eligible_positions=("AMC",),
    attributes=(RoleAttribute("quality", 1, AttributePriority.REQUIRED),),
    catalogue_version=VERSION,
)
# A distinct scoring attribute at the same DM position: a player can be a
# poor fit for one tactic's DM role and a good fit for another's without
# their underlying attributes changing at all.
ROLE_C = RoleDefinition(
    key="role_c",
    name="Role C",
    eligible_positions=("DM",),
    attributes=(RoleAttribute("flair", 1, AttributePriority.REQUIRED),),
    catalogue_version=VERSION,
)


def _slots(*positions_and_roles: tuple[str, str]) -> tuple[TacticSlot, ...]:
    return tuple(
        TacticSlot(key=f"slot-{index}", position=position, role_key=role_key)
        for index, (position, role_key) in enumerate(positions_and_roles)
    )


TACTIC_1 = TacticDefinition(
    key="tactic_1",
    name="Tactic One",
    formation="tactic-1",
    mentality="Balanced",
    instructions=(),
    slots=_slots(
        ("GK", "role_a"), ("DL", "role_a"), ("DR", "role_a"), ("DC", "role_a"),
        ("DM", "role_c"), ("MC1", "role_a"), ("MC2", "role_a"),
        ("AML", "role_a"), ("AMR", "role_a"), ("ST1", "role_a"), ("ST2", "role_a"),
    ),
    catalogue_version=VERSION,
)
TACTIC_2 = TacticDefinition(
    key="tactic_2",
    name="Tactic Two",
    formation="tactic-2",
    mentality="Balanced",
    instructions=(),
    slots=_slots(
        ("GK", "role_a"), ("DL", "role_a"), ("DR", "role_a"), ("DC", "role_a"),
        ("DM", "role_a"), ("AMC", "role_b"), ("MC1", "role_a"), ("MC2", "role_a"),
        ("AML", "role_a"), ("AMR", "role_a"), ("ST1", "role_a"),
    ),
    catalogue_version=VERSION,
)
CATALOGUE = FootballCatalogue(
    version=VERSION,
    roles={ROLE_A.key: ROLE_A, ROLE_B.key: ROLE_B, ROLE_C.key: ROLE_C},
    tactics={TACTIC_1.key: TACTIC_1, TACTIC_2.key: TACTIC_2},
)


def player(
    number: int, position: str, quality: int = 15, *, flair: int | None = None
) -> PlayerSelectionInput:
    attributes = {"quality": AttributeObservation(Visibility.KNOWN, value=quality)}
    if flair is not None:
        attributes["flair"] = AttributeObservation(Visibility.KNOWN, value=flair)
    return PlayerSelectionInput(
        id=str(number),
        name=f"Player {number:02}",
        positions=(position,),
        attributes=attributes,
        availability="available",
        injured=False,
        suspended=False,
        condition_percent=100,
        match_fitness_percent=100,
    )


def squad() -> list[PlayerSelectionInput]:
    return [
        # GK: one weak keeper, no backup -> weak in every tactic that fields
        # it (both) -> persistent.
        player(1, "GK", quality=10),
        # DL: strong starter plus a strong backup -> never weak.
        player(2, "DL", quality=15),
        player(3, "DL", quality=15),
        # DR, DC, MC1, MC2, AML, AMR, ST1, ST2: single strong starters, not
        # under test here.
        player(4, "DR", quality=15),
        player(5, "DC", quality=15),
        player(6, "MC1", quality=15),
        player(7, "MC2", quality=15),
        player(8, "AML", quality=15),
        player(9, "AMR", quality=15),
        player(10, "ST1", quality=15),
        player(11, "ST2", quality=15),
        # DM: same two players score oppositely depending on which tactic's
        # role is asking. TACTIC_1's role_c scores flair: player 20 starts
        # (flair 18), player 21 is cover that drops off sharply (flair 5).
        # TACTIC_2's role_a scores quality: player 21 starts (quality 15),
        # player 20 is close enough behind (quality 13) -> weak in TACTIC_1 only.
        player(20, "DM", quality=13, flair=18),
        player(21, "DM", quality=15, flair=5),
        # AMC: fielded only by TACTIC_2, one weak starter with no backup.
        player(30, "AMC", quality=10),
    ]


def evaluations():
    players = squad()
    return [
        evaluate_tactic(TACTIC_1, players, CATALOGUE, familiarity_policy=NO_FAMILIARITY_PENALTY),
        evaluate_tactic(TACTIC_2, players, CATALOGUE, familiarity_policy=NO_FAMILIARITY_PENALTY),
    ], players


class SquadDepthTests(unittest.TestCase):
    def test_rejects_an_empty_tactic_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            assess_squad_depth([], squad(), CATALOGUE)

    def test_rejects_duplicate_tactics(self) -> None:
        evals, players = evaluations()
        with self.assertRaisesRegex(ValueError, "distinct"):
            assess_squad_depth([evals[0], evals[0]], players, CATALOGUE)

    def test_gk_is_persistent_across_both_tactics(self) -> None:
        evals, players = evaluations()

        report = assess_squad_depth(evals, players, CATALOGUE)

        gk = report.positions["GK"]
        self.assertEqual(gk.tactics_with_this_position, ("tactic_1", "tactic_2"))
        self.assertTrue(gk.is_persistent)
        self.assertFalse(gk.is_occasional)
        self.assertIn(gk, report.persistent_weaknesses)

    def test_dm_is_occasional_because_only_one_tactics_role_exposes_the_gap(self) -> None:
        evals, players = evaluations()

        report = assess_squad_depth(evals, players, CATALOGUE)

        dm = report.positions["DM"]
        self.assertEqual(dm.tactics_with_a_weakness, ("tactic_1",))
        self.assertFalse(dm.is_persistent)
        self.assertTrue(dm.is_occasional)
        self.assertIn(dm, report.occasional_weaknesses)

    def test_amc_counts_as_persistent_despite_appearing_in_only_one_tactic(self) -> None:
        evals, players = evaluations()

        report = assess_squad_depth(evals, players, CATALOGUE)

        amc = report.positions["AMC"]
        self.assertEqual(amc.tactics_with_this_position, ("tactic_2",))
        self.assertTrue(amc.is_persistent)
        self.assertIn(amc, report.persistent_weaknesses)

    def test_dl_has_no_weaknesses_in_either_tactic(self) -> None:
        evals, players = evaluations()

        report = assess_squad_depth(evals, players, CATALOGUE)

        dl = report.positions["DL"]
        self.assertEqual(dl.tactics_with_a_weakness, ())
        self.assertFalse(dl.is_persistent)
        self.assertFalse(dl.is_occasional)
        self.assertNotIn(dl, report.persistent_weaknesses)
        self.assertNotIn(dl, report.occasional_weaknesses)

    def test_per_tactic_reports_are_kept_alongside_the_aggregate(self) -> None:
        evals, players = evaluations()

        report = assess_squad_depth(evals, players, CATALOGUE)

        self.assertEqual(set(report.per_tactic), {"tactic_1", "tactic_2"})

    def test_tagged_weaknesses_record_which_tactic_they_came_from(self) -> None:
        evals, players = evaluations()

        report = assess_squad_depth(evals, players, CATALOGUE)

        dm_tactic_keys = {tagged.tactic_key for tagged in report.positions["DM"].weaknesses}
        self.assertEqual(dm_tactic_keys, {"tactic_1"})


if __name__ == "__main__":
    unittest.main()
