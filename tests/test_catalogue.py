import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.imports import FM20_ATTRIBUTE_HEADERS


class MvpCatalogueTests(unittest.TestCase):
    def test_has_several_materially_different_complete_tactics(self) -> None:
        # "Materially different" is enforced structurally: every tactic uses
        # a distinct formation label, rather than pinning an exact roster of
        # formations that would need editing each time the catalogue grows.
        self.assertGreaterEqual(len(MVP_CATALOGUE.tactics), 7)
        formations = [tactic.formation for tactic in MVP_CATALOGUE.tactics.values()]
        self.assertEqual(len(formations), len(set(formations)))
        self.assertTrue(
            all(len(tactic.slots) == 11 for tactic in MVP_CATALOGUE.tactics.values())
        )

    def test_has_a_materially_wider_role_catalogue_than_the_mvp_baseline(self) -> None:
        # Not "every FM20 role" (an explicit Phase 04 non-goal), just wider
        # than the original thirteen-role MVP cut.
        self.assertGreaterEqual(len(MVP_CATALOGUE.roles), 20)

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


class CatalogueLoaderTests(unittest.TestCase):
    """The MVP catalogue is data now; these test the loader, not a specific roster."""

    def _write(self, tmp_path: Path, document: dict) -> Path:
        path = tmp_path / "catalogue.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def _minimal_document(self) -> dict:
        return {
            "version": "test-v1",
            "roles": [
                {
                    "key": "gk",
                    "name": "Keeper",
                    "positions": ["GK"],
                    "required": ["reflexes"],
                    "desirable": ["handling"],
                }
            ],
            "tactics": [
                {
                    "key": "shape",
                    "name": "Shape",
                    "formation": "1-0-0",
                    "mentality": "Balanced",
                    "instructions": [],
                    "slots": [{"key": "GK", "position": "GK", "role": "gk"}] * 1,
                }
            ],
        }

    def test_loads_a_well_formed_minimal_catalogue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = self._minimal_document()
            # A real tactic needs eleven slots; pad with the same role so the
            # loader itself, not football realism, is under test here.
            document["tactics"][0]["slots"] = [
                {"key": f"slot-{i}", "position": "GK", "role": "gk"} for i in range(11)
            ]
            path = self._write(Path(directory), document)

            catalogue = load_catalogue(path)

        self.assertEqual(catalogue.version, "test-v1")
        self.assertIn("gk", catalogue.roles)
        self.assertIn("shape", catalogue.tactics)

    def test_rejects_duplicate_role_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = self._minimal_document()
            document["roles"].append(document["roles"][0])
            path = self._write(Path(directory), document)

            with self.assertRaisesRegex(ValueError, "duplicate role"):
                load_catalogue(path)

    def test_rejects_a_role_missing_required_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = self._minimal_document()
            del document["roles"][0]["required"]
            path = self._write(Path(directory), document)

            with self.assertRaises(ValueError):
                load_catalogue(path)

    def test_rejects_a_tactic_referencing_an_unknown_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = self._minimal_document()
            document["tactics"][0]["slots"] = [
                {"key": f"slot-{i}", "position": "GK", "role": "ghost"} for i in range(11)
            ]
            path = self._write(Path(directory), document)

            with self.assertRaisesRegex(ValueError, "unknown roles"):
                load_catalogue(path)


if __name__ == "__main__":
    unittest.main()
