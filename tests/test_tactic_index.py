"""The generated tactic index must match the catalogue it describes."""

import unittest

from tools.tactic_index import OUTPUT, render


class TacticIndexTests(unittest.TestCase):
    def test_the_committed_index_is_up_to_date(self) -> None:
        self.assertTrue(OUTPUT.exists(), f"{OUTPUT} is missing")
        self.assertEqual(
            OUTPUT.read_text(encoding="utf-8"),
            render(),
            "docs/tactic-catalogue.md is stale; run: uv run python tools/tactic_index.py",
        )

    def test_every_tactic_appears(self) -> None:
        from fm_analytics.analytics.catalogue import MVP_CATALOGUE

        text = OUTPUT.read_text(encoding="utf-8")
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertIn(f"`{tactic.key}`", text, tactic.key)
            self.assertIn(tactic.name, text, tactic.key)


if __name__ == "__main__":
    unittest.main()
