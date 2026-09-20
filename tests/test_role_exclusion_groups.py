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


if __name__ == "__main__":
    unittest.main()
