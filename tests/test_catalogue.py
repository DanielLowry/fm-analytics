import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.catalogue import load_catalogue
from fm_analytics.analytics.tactical_system import effective_instructions
from fm_analytics.imports import FM20_ATTRIBUTE_HEADERS


class MvpCatalogueTests(unittest.TestCase):
    def test_has_several_materially_different_complete_tactics(self) -> None:
        # "Materially different" is enforced structurally: every tactic asks
        # its eleven slots to do a distinct set of jobs, rather than pinning
        # an exact roster that would need editing each time the catalogue
        # grows. Several tactics deliberately share a formation shape (e.g.
        # more than one 4-4-2) while differing in role identity, mentality,
        # and instructions, so formation label alone is not a valid proxy —
        # role composition is.
        self.assertGreaterEqual(len(MVP_CATALOGUE.tactics), 7)
        role_profiles = [
            tuple(sorted(slot.role_key for slot in tactic.slots))
            for tactic in MVP_CATALOGUE.tactics.values()
        ]
        self.assertEqual(len(role_profiles), len(set(role_profiles)))
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


class CentreBackRoleRuleTests(unittest.TestCase):
    """The centre-back rules in analytics/CLAUDE.md, which the balance checks cannot see."""

    BALL_PLAYERS = {"bpd_defend", "bpd_stopper", "bpd_cover", "libero_support", "libero_attack"}

    def test_a_tactic_that_plays_out_of_defence_fixes_a_ball_playing_centre_back(self) -> None:
        # Midfielders alone meet Play Out Of Defence's balance demand, so a tactic
        # can pass that check with nobody at the back who can start the build-up.
        for tactic in MVP_CATALOGUE.tactics.values():
            if "Play Out Of Defence" not in effective_instructions(tactic):
                continue
            if tactic.source is not None:
                # Published originals remain faithful benchmarks, even where
                # their authors do not follow our design preferences.
                continue
            fixed = [
                slot.key for slot in tactic.slots
                if slot.position == "DC" and set(MVP_CATALOGUE.role_keys_for_slot(slot)) <= self.BALL_PLAYERS
            ]
            self.assertTrue(fixed, f"{tactic.key}: plays out of defence with no fixed ball-playing centre-back")

    def test_no_nonsense_centre_backs_only_where_clearing_the_ball_fits_the_plan(self) -> None:
        # The No-Nonsense Centre-Back defends as well as a Central Defender by every
        # balance measure and nothing charges for the ball he gives away, so it is
        # offered only in tactics that go forward early or sit deep.
        keeps_the_ball = {
            "Shorter Passing", "Slightly Shorter Passing", "Play Out Of Defence", "Hold Shape",
        }
        for tactic in MVP_CATALOGUE.tactics.values():
            offered = sorted(
                role_key
                for slot in tactic.slots
                for role_key in MVP_CATALOGUE.role_keys_for_slot(slot)
                if role_key.startswith("nncb_")
            )
            if not offered:
                continue
            self.assertNotIn(tactic.mentality, {"Positive", "Attacking"}, tactic.key)
            self.assertEqual(
                sorted(keeps_the_ball & set(effective_instructions(tactic))), [], tactic.key
            )


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
                    "attributes": {"reflexes": 8, "handling": 4},
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

    def test_rejects_a_role_with_no_attributes(self) -> None:
        # There is no fallback weighting: a role with no attributes is an error,
        # not a flat guess that would score plausibly while being badly wrong.
        with tempfile.TemporaryDirectory() as directory:
            document = self._minimal_document()
            del document["roles"][0]["attributes"]
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
