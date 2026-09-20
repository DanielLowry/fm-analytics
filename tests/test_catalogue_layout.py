"""The on-disk catalogue layout: catalogue.json + roles/<pos>.json + tactics/<key>.json."""

import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.catalogue import MVP_CATALOGUE, load_catalogue
from fm_analytics.analytics.role_weights import load_role_weights

DATA = Path(__file__).resolve().parents[1] / "src" / "fm_analytics" / "analytics" / "data"

ROLE = {
    "key": "gk_x", "name": "Keeper", "positions": ["GK"],
    "positionGroup": "GK", "duty": "Defend",
    "attributes": {"reflexes": {
        "effectiveWeight": 8, "dutyModifier": 0,
        "weightTier": "core", "coreSoftFloorApplies": False,
    }},
}
TACTIC = {
    "key": "shape", "name": "Shape", "formation": "1-0-0", "mentality": "Balanced",
    "instructions": [],
    "slots": [{"key": f"s{i}", "position": "GK", "role": "gk_x"} for i in range(11)],
}


class ShippedLayoutTests(unittest.TestCase):
    def test_each_role_file_holds_exactly_its_position_group(self) -> None:
        for path in sorted((DATA / "roles").glob("*.json")):
            roles = json.loads(path.read_text(encoding="utf-8"))["roles"]
            groups = {role["positionGroup"].lower().replace("/", "_") for role in roles}
            self.assertEqual(groups, {path.stem}, f"{path.name} mixes position groups")

    def test_each_tactic_file_is_named_for_its_key(self) -> None:
        paths = sorted((DATA / "tactics").glob("*.json"))
        self.assertGreaterEqual(len(paths), 25)
        for path in paths:
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["key"], path.stem)

    def test_every_loaded_role_and_tactic_came_from_a_file(self) -> None:
        role_files = sum(
            len(json.loads(p.read_text(encoding="utf-8"))["roles"])
            for p in (DATA / "roles").glob("*.json")
        )
        self.assertEqual(len(MVP_CATALOGUE.roles), role_files)
        self.assertEqual(len(MVP_CATALOGUE.tactics), len(list((DATA / "tactics").glob("*.json"))))

    def test_weights_carry_the_catalogue_version(self) -> None:
        self.assertEqual(load_role_weights().version, MVP_CATALOGUE.version)

    def test_no_superseded_weight_files_linger(self) -> None:
        self.assertEqual(list(DATA.glob("role_weights*.json")), [])


class DirectoryLoadingTests(unittest.TestCase):
    def build(self, directory: Path, *, tactic_filename: str = "shape.json") -> Path:
        (directory / "roles").mkdir()
        (directory / "tactics").mkdir()
        (directory / "catalogue.json").write_text(json.dumps({"version": "dir-v1"}), encoding="utf-8")
        (directory / "roles" / "gk.json").write_text(json.dumps({"roles": [ROLE]}), encoding="utf-8")
        (directory / "tactics" / tactic_filename).write_text(json.dumps(TACTIC), encoding="utf-8")
        return directory

    def test_a_directory_loads_with_inline_weights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(Path(tmp)))
        self.assertEqual(catalogue.version, "dir-v1")
        self.assertEqual([a.name for a in catalogue.roles["gk_x"].attributes], ["reflexes"])
        self.assertEqual(catalogue.roles["gk_x"].attributes[0].weight, 8)
        self.assertIn("shape", catalogue.tactics)

    def test_a_tactic_file_whose_name_disagrees_with_its_key_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "file name must match"):
                load_catalogue(self.build(Path(tmp), tactic_filename="other.json"))

    def test_a_role_defined_twice_across_files_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = self.build(Path(tmp))
            (directory / "roles" / "gk_again.json").write_text(
                json.dumps({"roles": [ROLE]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate role"):
                load_catalogue(directory)


if __name__ == "__main__":
    unittest.main()
