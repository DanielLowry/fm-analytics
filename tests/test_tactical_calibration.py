"""Guards for the shared scale between what roles supply and what tactics demand.

Before these existed, 14 of 25 tactics demanded more of some system dimension
than any legal XI could supply (e.g. pressing 3.5 against a best case of 1.5),
and ten instructions were not modelled at all -- so two tactics scored a
perfect 100 precisely because their defining instructions went unmeasured.
"""

import unittest
from dataclasses import replace
from itertools import product

from fm_analytics.analytics.catalogue import (
    MVP_CATALOGUE,
    FootballCatalogue,
    RoleExclusionGroup,
    TacticDefinition,
    TacticSlot,
    TacticSystemRequirements,
)
from fm_analytics.analytics.role_scoring import RoleAttribute, RoleDefinition
from fm_analytics.analytics.tactical_system import (
    SYSTEM_DIMENSIONS,
    _INSTRUCTION_REQUIREMENTS,
    assess_coherence,
    assess_instruction_suitability,
    effective_instructions,
    role_traits,
)


def best_achievable(tactic, catalogue=MVP_CATALOGUE) -> dict[str, float]:
    """The largest total of each dimension over every legal role version."""
    best: dict[str, float] = {}
    options = [catalogue.role_keys_for_slot(slot) for slot in tactic.slots]
    for combo in product(*options):
        if not catalogue.role_version_is_legal(tactic, combo):
            continue
        totals: dict[str, float] = {}
        for role_key in combo:
            for dimension, value in role_traits(catalogue.roles[role_key]).items():
                totals[dimension] = totals.get(dimension, 0.0) + value
        for dimension, value in totals.items():
            best[dimension] = max(best.get(dimension, 0.0), value)
    return best


def role_version_assessments(tactic, catalogue=MVP_CATALOGUE):
    """Assess each legal version against balance and instructions together."""
    options = [catalogue.role_keys_for_slot(slot) for slot in tactic.slots]
    for combo in product(*options):
        if catalogue.role_version_is_legal(tactic, combo):
            roles = tuple(catalogue.roles[key] for key in combo)
            yield (
                combo,
                assess_coherence(tactic, roles),
                assess_instruction_suitability(roles, tactic),
            )


def satisfying_role_versions(tactic, catalogue=MVP_CATALOGUE):
    return tuple(
        combo
        for combo, coherence, instruction in role_version_assessments(tactic, catalogue)
        if not coherence.shortfalls and not instruction.shortfalls
    )


class CalibrationTests(unittest.TestCase):
    def test_every_instruction_a_tactic_uses_is_modelled(self) -> None:
        # Includes fixed in-possession settings that stand in for a legacy
        # instruction string (see `effective_instructions`), so a tactic
        # converted to the structured schema keeps the same coverage guarantee.
        used = {i for t in MVP_CATALOGUE.tactics.values() for i in effective_instructions(t)}
        self.assertEqual(sorted(used - set(_INSTRUCTION_REQUIREMENTS)), [])

    def test_every_role_a_tactic_can_use_has_system_traits(self) -> None:
        used = {
            key
            for t in MVP_CATALOGUE.tactics.values()
            for slot in t.slots
            for key in slot.role_keys
        }
        self.assertEqual(
            sorted(k for k in used if not MVP_CATALOGUE.roles[k].system_traits), []
        )

    def test_every_role_in_the_catalogue_has_system_traits(self) -> None:
        self.assertEqual(
            sorted(k for k, r in MVP_CATALOGUE.roles.items() if not r.system_traits), []
        )

    def test_role_traits_use_only_known_dimensions(self) -> None:
        known = set(SYSTEM_DIMENSIONS) | {"attackDuty"}
        for key, role in MVP_CATALOGUE.roles.items():
            self.assertLessEqual(set(role.system_traits) - known, set(), key)
        for name, demand in _INSTRUCTION_REQUIREMENTS.items():
            self.assertLessEqual(set(demand) - known, set(), name)

    def test_no_instruction_demands_more_than_any_role_version_can_supply(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            demands: dict[str, float] = {}
            for instruction in effective_instructions(tactic):
                for dimension, need in _INSTRUCTION_REQUIREMENTS[instruction].items():
                    demands[dimension] = max(demands.get(dimension, 0.0), need)
            best = best_achievable(tactic)
            unreachable = {
                d: (best.get(d, 0.0), need)
                for d, need in demands.items()
                if best.get(d, 0.0) < need
            }
            self.assertEqual(
                unreachable, {}, f"{tactic.key}: instruction demands no role version can meet"
            )

    def test_no_tactic_requires_more_balance_than_any_role_version_can_supply(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            requirements = tactic.system_requirements
            best = best_achievable(tactic)
            unreachable = {
                d: (best.get(d, 0.0), need)
                for d, need in requirements.minimums.items()
                if best.get(d, 0.0) < need
            }
            self.assertEqual(
                unreachable, {}, f"{tactic.key}: balance minimums no role version can meet"
            )

    def test_every_tactic_has_a_role_version_meeting_all_requirements_together(self) -> None:
        # Separate per-dimension maxima can come from incompatible versions.
        # At least one legal version must also clear both duty/creator caps;
        # compromised alternates remain permitted.
        for tactic in MVP_CATALOGUE.tactics.values():
            with self.subTest(tactic=tactic.key):
                if satisfying_role_versions(tactic):
                    continue
                combo, coherence, instruction = max(
                    role_version_assessments(tactic),
                    key=lambda version: min(version[1].score, version[2].score),
                )
                roles = ", ".join(
                    f"{slot.key}={key}" for slot, key in zip(tactic.slots, combo)
                )
                self.fail(
                    f"{tactic.key}: no legal role version meets all requirements together; "
                    f"closest version: {roles}; balance shortfalls: {coherence.shortfalls}; "
                    f"instruction shortfalls: {instruction.shortfalls}"
                )

    def test_every_shipped_tactic_declares_its_own_system_requirements(self) -> None:
        # The inferred fallback held every tactic to the same thresholds; a
        # low block and a gegenpress need different things.
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertTrue(tactic.system_requirements.minimums, tactic.key)
            self.assertIsNotNone(tactic.system_requirements.maximum_attack_duties, tactic.key)

    def test_pressing_instructions_are_discriminating_not_free(self) -> None:
        """A passive shape must not clear a high-press demand by accumulation.

        Small pressing traits add up across eleven players; if the demand sat
        within reach of an XI with no pressing roles, it would tell a manager
        nothing.
        """
        passive = MVP_CATALOGUE.tactics["balanced_442"]
        best = best_achievable(passive)
        self.assertLess(
            best.get("pressing", 0.0),
            _INSTRUCTION_REQUIREMENTS["Much More Urgent Pressing"]["pressing"],
        )


class JointFeasibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        version = "joint-calibration-test"
        self.roles = {
            key: RoleDefinition(
                key=key,
                name=key,
                eligible_positions=("GK", "ST"),
                attributes=(RoleAttribute("passing", 1),),
                catalogue_version=version,
                system_traits=traits,
            )
            for key, traits in (
                ("filler", {"restDefence": 3.0, "boxPresence": 1.5}),
                ("creator", {"creativity": 2.0}),
                ("presser", {"pressing": 2.5}),
            )
        }
        self.tactic = TacticDefinition(
            key="joint-calibration",
            name="Joint calibration",
            formation="test",
            mentality="Balanced",
            instructions=("Counter-Press",),
            slots=tuple(
                TacticSlot(f"slot-{index}", "GK", "filler") for index in range(10)
            ) + (TacticSlot("ST", "ST", "creator", ("presser",)),),
            catalogue_version=version,
            system_requirements=TacticSystemRequirements(minimums={"creativity": 2.0}),
        )

    def catalogue(self, tactic=None, roles=None, groups=()) -> FootballCatalogue:
        tactic = tactic or self.tactic
        return FootballCatalogue(
            version=tactic.catalogue_version,
            roles=roles or self.roles,
            tactics={tactic.key: tactic},
            exclusive_role_groups=groups,
        )

    def test_separately_reachable_balance_and_instruction_demands_are_not_enough(self) -> None:
        catalogue = self.catalogue()
        best = best_achievable(self.tactic, catalogue)
        self.assertEqual(best["creativity"], 2.0)
        self.assertEqual(best["pressing"], 2.5)
        assessments = list(role_version_assessments(self.tactic, catalogue))
        self.assertTrue(any(not coherence.shortfalls for _, coherence, _ in assessments))
        self.assertTrue(any(not instruction.shortfalls for _, _, instruction in assessments))
        self.assertEqual(satisfying_role_versions(self.tactic, catalogue), ())

    def test_a_satisfying_alternate_is_enough_even_when_the_default_falls_short(self) -> None:
        roles = {
            **self.roles,
            "presser": replace(
                self.roles["presser"], system_traits={"pressing": 2.5, "creativity": 2.0}
            ),
        }
        catalogue = self.catalogue(roles=roles)
        satisfying = satisfying_role_versions(self.tactic, catalogue)
        self.assertEqual(len(satisfying), 1)
        self.assertEqual(satisfying[0][-1], "presser")

    def test_duty_and_creator_caps_are_part_of_feasibility(self) -> None:
        for trait, requirements in (
            ("attackDuty", TacticSystemRequirements(maximum_attack_duties=1)),
            ("creativity", TacticSystemRequirements(maximum_creators=1)),
        ):
            with self.subTest(trait=trait):
                roles = {
                    **self.roles,
                    "creator": replace(
                        self.roles["creator"],
                        system_traits={trait: 1.0 if trait == "attackDuty" else 2.0},
                    ),
                }
                slots = self.tactic.slots[:9] + (
                    TacticSlot("STL", "ST", "creator"),
                    TacticSlot("STR", "ST", "creator"),
                )
                tactic = replace(
                    self.tactic, instructions=(), slots=slots, system_requirements=requirements
                )
                self.assertEqual(satisfying_role_versions(tactic, self.catalogue(tactic, roles)), ())

    def test_an_illegal_satisfying_combination_does_not_count(self) -> None:
        tactic = replace(
            self.tactic,
            slots=self.tactic.slots[:9] + (
                TacticSlot("STL", "ST", "creator", ("presser",)),
                TacticSlot("STR", "ST", "creator", ("presser",)),
            ),
            system_requirements=TacticSystemRequirements(minimums={"pressing": 5.0}),
        )
        group = RoleExclusionGroup("Only one presser", "ST", frozenset({"presser"}))
        unrestricted = self.catalogue(tactic)
        restricted = self.catalogue(tactic, groups=(group,))
        self.assertEqual(len(satisfying_role_versions(tactic, unrestricted)), 1)
        self.assertEqual(satisfying_role_versions(tactic, restricted), ())


if __name__ == "__main__":
    unittest.main()
