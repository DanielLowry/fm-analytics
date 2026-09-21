"""Every shipped tactic explains itself: the shape, when to use it, each slot and each instruction."""

import json
import tempfile
import unittest
from pathlib import Path

from fm_analytics.analytics.catalogue import MVP_CATALOGUE, load_catalogue

DATA = Path(__file__).resolve().parents[1] / "src" / "fm_analytics" / "analytics" / "data"


class ShippedJustificationTests(unittest.TestCase):
    def test_every_tactic_has_its_shape_and_usage_guidance(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertTrue(tactic.why_this_shape.strip(), f"{tactic.key}: whyThisShape")
            self.assertTrue(tactic.when_to_use.strip(), f"{tactic.key}: whenToUse")
            self.assertTrue(tactic.when_not_to_use.strip(), f"{tactic.key}: whenNotToUse")

    def test_every_slot_says_why_its_role_is_there(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            for slot in tactic.slots:
                self.assertTrue(slot.why.strip(), f"{tactic.key}/{slot.key}: why")

    def test_every_instruction_is_explained(self) -> None:
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertEqual(
                sorted(tactic.instruction_rationale), sorted(tactic.instructions), tactic.key
            )
            for instruction, reason in tactic.instruction_rationale.items():
                self.assertTrue(reason.strip(), f"{tactic.key}: {instruction}")

    def test_slot_text_agrees_with_the_slots_actual_alternates(self) -> None:
        # The prose is hand-written beside data it can contradict (a slot whose
        # default is Cover described as having Cover as its alternate).
        named = {
            "Cover": "cd_cover", "Defend": "cd_defend",
            "Poacher": "p_attack", "Advanced Forward": "af_attack",
        }
        for tactic in MVP_CATALOGUE.tactics.values():
            for slot in tactic.slots:
                for name, role_key in named.items():
                    if f"{name} is the alternate" in slot.why:
                        self.assertIn(
                            role_key, slot.alternate_role_keys,
                            f"{tactic.key}/{slot.key}: text says {name} is the alternate",
                        )
                        self.assertNotEqual(slot.role_key, role_key, f"{tactic.key}/{slot.key}")

    def test_no_two_tactics_share_their_shape_or_usage_text(self) -> None:
        # Guards copy-paste: each tactic's justification should be its own.
        for attribute in ("why_this_shape", "when_to_use", "when_not_to_use"):
            values = [getattr(t, attribute) for t in MVP_CATALOGUE.tactics.values()]
            self.assertEqual(len(values), len(set(values)), attribute)


class LoaderTests(unittest.TestCase):
    ROLE = {
        "key": "gk_x", "name": "Keeper", "positions": ["GK"], "positionGroup": "GK",
        "duty": "Defend", "system": {"defensiveCover": 0.5},
        "attributes": {"reflexes": {
            "effectiveWeight": 8, "dutyModifier": 0,
            "weightTier": "core", "coreSoftFloorApplies": False,
        }},
    }

    def build(self, directory: Path, **extra) -> Path:
        (directory / "roles").mkdir()
        (directory / "tactics").mkdir()
        (directory / "catalogue.json").write_text(json.dumps({"version": "v"}), encoding="utf-8")
        (directory / "roles" / "gk.json").write_text(json.dumps({"roles": [self.ROLE]}), encoding="utf-8")
        tactic = {
            "key": "shape", "name": "Shape", "formation": "1-0-0", "mentality": "Balanced",
            "instructions": ["Counter"],
            "slots": [{"key": f"s{i}", "position": "GK", "role": "gk_x", "why": f"reason {i}"} for i in range(11)],
            **extra,
        }
        (directory / "tactics" / "shape.json").write_text(json.dumps(tactic), encoding="utf-8")
        return directory

    def test_justification_fields_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = load_catalogue(self.build(
                Path(tmp), whyThisShape="a", whenToUse="b", whenNotToUse="c",
                instructionRationale={"Counter": "d"},
            ))
        tactic = catalogue.tactics["shape"]
        self.assertEqual(
            (tactic.why_this_shape, tactic.when_to_use, tactic.when_not_to_use), ("a", "b", "c")
        )
        self.assertEqual(dict(tactic.instruction_rationale), {"Counter": "d"})
        self.assertEqual(tactic.slots[3].why, "reason 3")

    def test_they_are_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tactic = load_catalogue(self.build(Path(tmp))).tactics["shape"]
        self.assertEqual((tactic.why_this_shape, dict(tactic.instruction_rationale)), ("", {}))

    def test_explaining_an_instruction_the_tactic_does_not_use_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "does not use"):
                load_catalogue(self.build(Path(tmp), instructionRationale={"Hold Shape": "x"}))

    def test_a_non_string_rationale_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "object of strings"):
                load_catalogue(self.build(Path(tmp), instructionRationale={"Counter": 3}))


if __name__ == "__main__":
    unittest.main()
