import unittest

from tools.fm20_monitor import (
    DASHBOARD,
    BridgeStatusCache,
    MonitorHandler,
    MonitorSourceError,
    StatusCache,
    _snake_keys,
    build_parser,
)


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

    def test_bridge_is_the_default_monitor_source(self) -> None:
        args = build_parser().parse_args([])

        self.assertFalse(args.direct)
        self.assertEqual(args.bridge_url, "http://127.0.0.1:5072")
        self.assertEqual(BridgeStatusCache(args.bridge_url).base_url, args.bridge_url)

    def test_bridge_payload_keys_are_normalised(self) -> None:
        payload = {"dateOfBirth": "2000-01-01", "contractedClub": {"id": "1"}}

        self.assertEqual(
            _snake_keys(payload),
            {"date_of_birth": "2000-01-01", "contracted_club": {"id": "1"}},
        )

    def test_bridge_unavailable_status_is_preserved(self) -> None:
        cache = BridgeStatusCache("http://bridge.test")
        cache._read = lambda *_args, **_kwargs: {
            "status": "save_not_loaded",
            "detail": "Load a save.",
        }

        with self.assertRaises(MonitorSourceError) as context:
            cache.get()

        self.assertEqual(context.exception.status, "save_not_loaded")
        self.assertEqual(str(context.exception), "Load a save.")

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
