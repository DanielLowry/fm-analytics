"""Guards for the shared scale between what roles supply and what tactics demand.

Before these existed, 14 of 25 tactics demanded more of some system dimension
than any legal XI could supply (e.g. pressing 3.5 against a best case of 1.5),
and ten instructions were not modelled at all -- so two tactics scored a
perfect 100 precisely because their defining instructions went unmeasured.
"""

import unittest
from itertools import product

from fm_analytics.analytics.catalogue import MVP_CATALOGUE
from fm_analytics.analytics.tactical_system import (
    SYSTEM_DIMENSIONS,
    _INSTRUCTION_REQUIREMENTS,
    role_traits,
)


def best_achievable(tactic) -> dict[str, float]:
    """The largest total of each dimension over every legal role version."""
    best: dict[str, float] = {}
    options = [MVP_CATALOGUE.role_keys_for_slot(slot) for slot in tactic.slots]
    for combo in product(*options):
        if not MVP_CATALOGUE.role_version_is_legal(tactic, combo):
            continue
        totals: dict[str, float] = {}
        for role_key in combo:
            for dimension, value in role_traits(MVP_CATALOGUE.roles[role_key]).items():
                totals[dimension] = totals.get(dimension, 0.0) + value
        for dimension, value in totals.items():
            best[dimension] = max(best.get(dimension, 0.0), value)
    return best


class CalibrationTests(unittest.TestCase):
    def test_every_instruction_a_tactic_uses_is_modelled(self) -> None:
        used = {i for t in MVP_CATALOGUE.tactics.values() for i in t.instructions}
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
            for instruction in tactic.instructions:
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


if __name__ == "__main__":
    unittest.main()
