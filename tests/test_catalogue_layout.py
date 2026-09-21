"""The on-disk catalogue layout: catalogue.json + roles/<pos>.json + tactics/<key>.json."""

import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.catalogue import MVP_CATALOGUE, load_catalogue

DATA = Path(__file__).resolve().parents[1] / "src" / "fm_analytics" / "analytics" / "data"

ROLE = {
    "key": "gk_x", "name": "Keeper", "positions": ["GK"],
    "system": {"defensiveCover": 0.5},
    "attributes": {"reflexes": 8},
}
TACTIC = {
    "key": "shape", "name": "Shape", "formation": "1-0-0", "mentality": "Balanced",
    "instructions": [],
    "slots": [{"key": f"s{i}", "position": "GK", "role": "gk_x"} for i in range(11)],
}


class ShippedLayoutTests(unittest.TestCase):
    def test_each_role_file_holds_exactly_the_positions_its_name_says(self) -> None:
        # dl_dr.json holds roles for DL/DR, wbl_wbr.json for WBL/WBR, and so on.
        for path in sorted((DATA / "roles").glob("*.json")):
            roles = json.loads(path.read_text(encoding="utf-8"))["roles"]
            for role in roles:
                self.assertEqual(
                    "_".join(role["positions"]).lower(), path.stem,
                    f"{role['key']} does not belong in {path.name}",
                )

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

    def test_a_role_used_by_a_tactic_without_system_traits_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = self.build(Path(tmp))
            bare = {k: v for k, v in ROLE.items() if k != "system"}
            (directory / "roles" / "gk.json").write_text(
                json.dumps({"roles": [bare]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "no system traits"):
                load_catalogue(directory)

    def test_a_role_defined_twice_across_files_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = self.build(Path(tmp))
            (directory / "roles" / "gk_again.json").write_text(
                json.dumps({"roles": [ROLE]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate role"):
                load_catalogue(directory)



class UnreadKeysAreRefusedTests(unittest.TestCase):
    """Config nothing reads is an error, so it cannot mislead whoever edits it."""

    def build(self, directory: Path, *, role=None, tactic=None, catalogue=None) -> Path:
        (directory / "roles").mkdir()
        (directory / "tactics").mkdir()
        (directory / "catalogue.json").write_text(
            json.dumps(catalogue or {"version": "v"}), encoding="utf-8"
        )
        (directory / "roles" / "gk.json").write_text(
            json.dumps({"roles": [role or ROLE]}), encoding="utf-8"
        )
        (directory / "tactics" / "shape.json").write_text(
            json.dumps(tactic or TACTIC), encoding="utf-8"
        )
        return directory

    def refused(self, match: str, **kwargs) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, match):
                load_catalogue(self.build(Path(tmp), **kwargs))

    def test_an_unknown_role_key_is_refused(self) -> None:
        self.refused("unknown key.*duty", role={**ROLE, "duty": "Defend"})

    def test_an_unknown_tactic_key_is_refused(self) -> None:
        # The typo that would otherwise silently drop a whole justification.
        self.refused("unknown key.*whyThisShap", tactic={**TACTIC, "whyThisShap": "x"})

    def test_an_unknown_slot_key_is_refused(self) -> None:
        slots = [{**TACTIC["slots"][0], "notes": "x"}, *TACTIC["slots"][1:]]
        self.refused("unknown key.*notes", tactic={**TACTIC, "slots": slots})

    def test_an_unknown_catalogue_key_is_refused(self) -> None:
        self.refused("unknown key.*tacticResearchNotes",
                     catalogue={"version": "v", "tacticResearchNotes": {}})

    def test_the_message_says_what_is_allowed(self) -> None:
        self.refused("Known keys", role={**ROLE, "duty": "Defend"})

    def test_no_shipped_file_carries_a_key_the_loader_ignores(self) -> None:
        # The strict loader already guarantees it, but this names the property.
        self.assertGreater(len(MVP_CATALOGUE.roles), 0)


if __name__ == "__main__":
    unittest.main()
