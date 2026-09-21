import unittest

from fm_analytics.analytics import (
    FootballCatalogue,
    PlayerSelectionInput,
    RoleAttribute,
    RoleDefinition,
    TacticDefinition,
    TacticSlot,
    evaluate_tactic,
)
from fm_analytics.analytics.catalogue import RoleExclusionGroup
from fm_analytics.domain import AttributeObservation, Visibility


VERSION = "role-exclusion-test-v1"
POSITIONS = ("GK", "DC", "DC", "DC", "DC", "MC", "MC", "MC", "MC", "ST", "ST")


def observation(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


def role(key: str, attribute: str) -> RoleDefinition:
    return RoleDefinition(
        key=key,
        name=key,
        eligible_positions=tuple(sorted(set(POSITIONS))),
        attributes=(RoleAttribute(attribute, 1),),
        catalogue_version=VERSION,
    )


FILLER = role("filler", "quality")
DEFEND = role("defend", "defend")
COVER = role("cover", "cover")
COVER_GROUP = RoleExclusionGroup("Cover", "DC", frozenset({"cover"}))


def tactic(dc_roles: tuple[tuple[str, tuple[str, ...]], ...]) -> TacticDefinition:
    """A tactic whose first two DC slots take the given (role, alternates)."""
    dc_iter = iter(dc_roles)
    slots = []
    for index, position in enumerate(POSITIONS):
        if position == "DC" and (dc := next(dc_iter, None)) is not None:
            slots.append(TacticSlot(f"slot-{index}", position, dc[0], dc[1]))
        else:
            slots.append(TacticSlot(f"slot-{index}", position, "filler"))
    return TacticDefinition(
        key="t", name="T", formation="test", mentality="Balanced",
        instructions=(), slots=tuple(slots), catalogue_version=VERSION,
    )


def squad() -> list[PlayerSelectionInput]:
    result = []
    for index, position in enumerate(POSITIONS, 1):
        # Every defender is far better at Cover than Defend, so an unrestricted
        # optimiser would happily play Cover/Cover.
        attributes = {"quality": observation(15)}
        if position == "DC":
            attributes |= {"cover": observation(20), "defend": observation(5)}
        result.append(
            PlayerSelectionInput(
                id=str(index), name=f"Player {index}", positions=(position,),
                attributes=attributes, availability="available", injured=False,
                suspended=False, condition_percent=100, match_fitness_percent=100,
            )
        )
    return result


def catalogue(item: TacticDefinition, groups=()) -> FootballCatalogue:
    return FootballCatalogue(
        version=VERSION,
        roles={r.key: r for r in (FILLER, DEFEND, COVER)},
        tactics={item.key: item},
        exclusive_role_groups=tuple(groups),
    )


def dc_roles(evaluation) -> list[str]:
    return sorted(
        a.intrinsic_role_score.role_key
        for a in evaluation.assignments
        if a.slot.position == "DC"
    )


class RoleExclusionGroupTests(unittest.TestCase):
    def test_without_a_group_two_cover_centre_backs_are_chosen(self) -> None:
        item = tactic((("defend", ("cover",)), ("defend", ("cover",))))
        evaluation = evaluate_tactic(item, squad(), catalogue(item))
        self.assertEqual(dc_roles(evaluation), ["cover", "cover", "filler", "filler"])

    def test_group_stops_the_optimiser_choosing_two_cover_centre_backs(self) -> None:
        item = tactic((("defend", ("cover",)), ("defend", ("cover",))))
        evaluation = evaluate_tactic(item, squad(), catalogue(item, [COVER_GROUP]))
        roles = dc_roles(evaluation)
        self.assertEqual(roles.count("cover"), 1)
        self.assertEqual(roles.count("defend"), 1)

    def test_group_only_counts_slots_at_its_own_position(self) -> None:
        # One Cover role at DC and another at MC do not exclude each other.
        slots = list(tactic((("cover", ()),)).slots)
        slots[5] = TacticSlot("slot-5", "MC", "cover")
        mixed = TacticDefinition(
            key="t", name="T", formation="test", mentality="Balanced",
            instructions=(), slots=tuple(slots), catalogue_version=VERSION,
        )
        legal = catalogue(mixed, [COVER_GROUP])
        self.assertTrue(
            legal.role_version_is_legal(mixed, tuple(s.role_key for s in mixed.slots))
        )

    def test_pinned_violation_fails_at_catalogue_construction(self) -> None:
        item = tactic((("cover", ()), ("cover", ())))
        with self.assertRaisesRegex(ValueError, "no role version"):
            catalogue(item, [COVER_GROUP])

    def test_group_naming_an_unknown_role_is_rejected(self) -> None:
        item = tactic((("defend", ()), ("defend", ())))
        with self.assertRaisesRegex(ValueError, "unknown roles"):
            catalogue(item, [RoleExclusionGroup("Ghost", "DC", frozenset({"ghost"}))])


class WholeXiGroupTests(unittest.TestCase):
    """A group with no position limits the role across all eleven slots."""

    def test_a_positionless_group_counts_slots_at_every_position(self) -> None:
        group = RoleExclusionGroup("Free roles", None, frozenset({"cover"}))
        slots = (
            TacticSlot("a", "DC", "cover"),
            TacticSlot("b", "ST", "cover"),
            TacticSlot("c", "MC", "filler"),
        )
        self.assertTrue(group.is_violated_by(slots, ("cover", "cover", "filler")))
        self.assertFalse(group.is_violated_by(slots, ("cover", "filler", "filler")))

    def test_a_positioned_group_still_ignores_other_positions(self) -> None:
        group = RoleExclusionGroup("Cover", "DC", frozenset({"cover"}))
        slots = (TacticSlot("a", "DC", "cover"), TacticSlot("b", "ST", "cover"))
        self.assertFalse(group.is_violated_by(slots, ("cover", "cover")))

    def test_the_shipped_free_roles_group_covers_every_such_role(self) -> None:
        from fm_analytics.analytics.catalogue import MVP_CATALOGUE

        group = next(g for g in MVP_CATALOGUE.exclusive_role_groups if g.name == "Free roles")
        self.assertIsNone(group.position)
        self.assertEqual(
            group.role_keys,
            {"treq_st_attack", "treq_amc_attack", "treq_aml_amr_attack", "eng_support", "raum_attack"},
        )


    def test_every_cover_and_stopper_centre_back_is_in_a_group(self) -> None:
        # A tactic with two Covers has nobody to be covered; with two Stoppers,
        # nobody covers. Nothing but this group stops the optimiser choosing
        # either, so a new Cover/Stopper role must be added to it.
        from fm_analytics.analytics.catalogue import MVP_CATALOGUE

        grouped = {key for g in MVP_CATALOGUE.exclusive_role_groups if g.position == "DC" for key in g.role_keys}
        for key, role in MVP_CATALOGUE.roles.items():
            if "DC" in role.eligible_positions and key.endswith(("_cover", "_stopper")):
                self.assertIn(key, grouped, f"{key} is not in an exclusion group")


if __name__ == "__main__":
    unittest.main()
