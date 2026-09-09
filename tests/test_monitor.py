import unittest

from tools.fm20_monitor import DASHBOARD, StatusCache


class MonitorTests(unittest.TestCase):
    def test_dashboard_has_status_and_export_controls(self) -> None:
        self.assertIn('id="source-status"', DASHBOARD)
        self.assertIn('href="/api/status.json?download=1"', DASHBOARD)
        self.assertIn("setInterval(refresh, 30000)", DASHBOARD)

    def test_empty_cache_has_configured_ttl(self) -> None:
        cache = StatusCache(ttl_seconds=15)
        self.assertEqual(cache.ttl_seconds, 15)


if __name__ == "__main__":
    unittest.main()

