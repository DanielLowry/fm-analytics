import unittest

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.imports import FM20_ATTRIBUTE_HEADERS


class MvpCatalogueTests(unittest.TestCase):
    def test_has_three_materially_different_complete_tactics(self) -> None:
        self.assertEqual(len(MVP_CATALOGUE.tactics), 3)
        self.assertEqual(
            {tactic.formation for tactic in MVP_CATALOGUE.tactics.values()},
            {"4-4-2", "4-2-3-1 DM AM Wide", "4-3-3 DM Wide"},
        )
        self.assertTrue(
            all(len(tactic.slots) == 11 for tactic in MVP_CATALOGUE.tactics.values())
        )

    def test_every_tactic_role_is_defined_in_the_same_version(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertEqual(tactic.catalogue_version, MVP_CATALOGUE.version)
            for slot in tactic.slots:
                self.assertIn(slot.role_key, MVP_CATALOGUE.roles)

    def test_html_import_profile_can_supply_every_scoring_attribute(self) -> None:
        importable_attributes = set(FM20_ATTRIBUTE_HEADERS.values())
        scoring_attributes = {
            attribute.name
            for role in MVP_CATALOGUE.roles.values()
            for attribute in role.attributes
        }

        self.assertEqual(scoring_attributes - importable_attributes, set())

    def test_tactics_have_unique_slot_keys(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            keys = [slot.key for slot in tactic.slots]
            self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
