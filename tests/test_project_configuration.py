import json
import unittest
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent.parent


class ProjectConfigurationTests(unittest.TestCase):
    def test_fixture_updates_implicit_content_item(self) -> None:
        project = ElementTree.parse(ROOT / "src/FMBridge/FMBridge.csproj")
        content_items = project.findall(".//Content")

        self.assertFalse(
            any(item.get("Include") == "fixtures/sample-game.json" for item in content_items)
        )
        self.assertTrue(
            any(item.get("Update") == "fixtures/sample-game.json" for item in content_items)
        )
        self.assertTrue(
            any(
                item.get("Include") == "../../tools/fm20_linux_probe.py"
                for item in content_items
            )
        )

    def test_dotnet_sdk_stays_within_version_eight(self) -> None:
        with (ROOT / "global.json").open(encoding="utf-8") as global_file:
            configuration = json.load(global_file)["sdk"]

        self.assertTrue(configuration["version"].startswith("8.0."))
        self.assertEqual(configuration["rollForward"], "latestFeature")
        self.assertFalse(configuration["allowPrerelease"])


if __name__ == "__main__":
    unittest.main()
