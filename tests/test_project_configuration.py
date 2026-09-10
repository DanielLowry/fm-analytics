import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ProjectConfigurationTests(unittest.TestCase):
    def test_python_project_exposes_application_and_bridge_commands(self) -> None:
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('fm-analytics = "fm_analytics.cli:main"', project)
        self.assertIn('fm-bridge = "fm_analytics.bridge.server:main"', project)

    def test_csharp_bridge_project_has_been_removed(self) -> None:
        self.assertFalse((ROOT / "src/FMBridge").exists())

    def test_fixture_is_packaged_with_the_python_bridge(self) -> None:
        fixture = ROOT / "src/fm_analytics/fixtures/sample-game.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertIn("game", payload)
        self.assertIn("squad", payload)


if __name__ == "__main__":
    unittest.main()
