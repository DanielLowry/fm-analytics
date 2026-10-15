"""Independent expectations from the manager's FM20 menus, 14 October 2026."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.set_piece_config import DATA_DIR, SET_PIECE_WEIGHTS, load_set_piece_weights
from fm_analytics.analytics.set_piece_routines import DEFENDING_FREE_KICK_INSTRUCTIONS_BY_VARIANT, defensive_roles


# Deliberately written independently of the application's availability table.
VERIFIED_MENUS = {
    "direct_free_kick": {
        "Stay forward", "Wall", "Edge of area", "Go back", "Man mark",
    },
    "direct_small_chance": {
        "Stay forward", "Wall", "Edge of area", "Go back", "Man mark", "Man mark tall player",
    },
    "indirect_wide": {
        "Stay forward", "Wall", "Edge of area", "Go back", "Man mark", "Man mark tall player",
        "Zonally mark 6 yard box centre", "Zonally mark 6 yard box near post", "Zonally mark 6 yard box far post",
    },
    "indirect_deep": {
        "Stay forward", "Wall", "Edge of area", "Go back", "Man mark", "Man mark tall player",
        "Zonally mark 6 yard box centre", "Zonally mark 6 yard box near post", "Zonally mark 6 yard box far post",
    },
}


class FreeKickAvailabilityTests(unittest.TestCase):
    def test_supported_instructions_match_each_verified_menu_exactly(self):
        self.assertEqual(DEFENDING_FREE_KICK_INSTRUCTIONS_BY_VARIANT, VERIFIED_MENUS)

    def test_candidates_use_only_their_own_menu_and_consider_every_supported_job(self):
        for kind, allowed in VERIFIED_MENUS.items():
            templates = SET_PIECE_WEIGHTS.defensive_templates.get(kind, (None,))
            seen = set()
            for template in templates:
                roles = defensive_roles(kind, template)
                with self.subTest(kind=kind, template=template.key if template else None):
                    self.assertEqual(len(roles), 11)
                    self.assertEqual(len({r.key for r in roles}), 11)
                    self.assertEqual(sum(r.goalkeeper for r in roles), 1)
                    jobs = {r.instruction for r in roles if not r.goalkeeper}
                    self.assertLessEqual(jobs, allowed)
                    seen.update(jobs)
                    for instruction in allowed:
                        if instruction.startswith("Zonally"):
                            self.assertLessEqual(sum(r.instruction == instruction for r in roles), 1)
                    if template:
                        self.assertEqual(template.box_defenders, sum(r.unit == "Box defence" for r in roles))
            self.assertEqual(seen, allowed, kind)

    def test_general_cover_is_distinct_from_zonal_and_tall_player_defence(self):
        roles = defensive_roles("indirect_wide")
        profiles = {r.instruction: r for r in roles}
        self.assertEqual(profiles["Go back"].zone, "General box cover")
        self.assertEqual(profiles["Zonally mark 6 yard box centre"].zone, "Six-yard box centre")
        self.assertNotEqual(profiles["Go back"].attributes, profiles["Zonally mark 6 yard box centre"].attributes)
        self.assertNotEqual(profiles["Man mark"].attributes, profiles["Man mark tall player"].attributes)
        self.assertGreater(profiles["Zonally mark 6 yard box centre"].importance, profiles["Go back"].importance)

    def test_deep_wall_is_an_available_tactical_choice(self):
        choices = SET_PIECE_WEIGHTS.defensive_templates["indirect_deep"]
        self.assertEqual({t.jobs["wall"] for t in choices}, {0, 1, 2})
        for template in choices:
            self.assertGreaterEqual(template.box_defenders, 6)

    def test_small_chance_wall_and_edge_keep_their_reviewed_group_influence(self):
        for template in SET_PIECE_WEIGHTS.defensive_templates["direct_small_chance"]:
            roles = defensive_roles("direct_small_chance", template)
            self.assertAlmostEqual(sum(r.importance for r in roles if r.instruction == "Wall"), 5.6)
            self.assertAlmostEqual(sum(r.importance for r in roles if r.instruction == "Edge of area"), 1.0)

    def test_a_template_cannot_be_used_for_a_different_variant(self):
        wide = SET_PIECE_WEIGHTS.defensive_templates["indirect_wide"][0]
        with self.assertRaisesRegex(ValueError, "different free-kick variant"):
            defensive_roles("direct_small_chance", wide)

    def test_unavailable_profile_entries_are_rejected_even_if_they_have_zero_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "weights"
            for kind, job in (("direct_free_kick", "tall"), ("direct_small_chance", "zonal_centre")):
                shutil.copytree(DATA_DIR, destination, dirs_exist_ok=True)
                path = destination / "defending_free_kicks.json"
                data = json.loads(path.read_text())
                data["variants"][kind][job] = {"profile": "zonal_defence", "importance": 1}
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "unexpected keys.*" + job):
                    load_set_piece_weights(destination)


if __name__ == "__main__":
    unittest.main()
