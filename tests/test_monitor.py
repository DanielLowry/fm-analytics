import unittest

from tools.fm20_monitor import DASHBOARD, MonitorHandler, StatusCache


class MonitorTests(unittest.TestCase):
    def test_dashboard_has_status_and_export_controls(self) -> None:
        self.assertIn('id="source-status"', DASHBOARD)
        self.assertIn('href="/api/status.json?download=1"', DASHBOARD)
        self.assertIn('href="/api/squad.json?download=1"', DASHBOARD)
        self.assertIn('id="squad"', DASHBOARD)
        self.assertIn("Match fitness", DASHBOARD)
        self.assertIn("contractText", DASHBOARD)
        self.assertIn("setInterval(refresh, 30000)", DASHBOARD)

    def test_empty_cache_has_configured_ttl(self) -> None:
        cache = StatusCache(ttl_seconds=15)
        self.assertEqual(cache.ttl_seconds, 15)

    def test_squad_document_selects_the_active_manager_club(self) -> None:
        source = {
            "status": "live",
            "observed_at": "2026-01-02T03:04:05+00:00",
            "game_date": "2019-06-24",
            "human_managers": [
                {"active": False, "club": None},
                {"active": True, "club": {"id": "7", "name": "Club"}},
            ],
            "first_team_squad": [{"id": "1", "name": "Player"}],
        }

        document = MonitorHandler._squad_document(source)

        self.assertEqual(document["club"]["name"], "Club")
        self.assertEqual(document["player_count"], 1)


if __name__ == "__main__":
    unittest.main()
