import unittest
from dataclasses import replace
from datetime import date

from fm_analytics.analytics.match_players import summarise_players
from fm_analytics.domain.matches import MatchCapture
from fm_analytics.season_export import player_json
from fm_analytics.web.match_detail_render import _crosses
from tests.match_support import capture_document, season


class CrossCoverageTests(unittest.TestCase):
    def test_old_missing_counts_do_not_dilute_new_crossing_rates(self):
        old = MatchCapture.from_document(capture_document(season())).matches[-1].detail.players[0]
        known = replace(old, stats=dict(old.stats, crosses_attempted=4, crosses_completed=1))
        (summary,) = summarise_players([
            (old, date(2020, 10, 3), "Old opponent", "Full-back"),
            (known, date(2020, 10, 10), "Woking", "Full-back"),
        ])
        exported = player_json(summary, "standard")
        self.assertEqual(summary.minutes, 180)
        self.assertEqual(exported["crossing_coverage"]["crosses_attempted"], {"appearances": 1, "minutes": 90})
        self.assertEqual(exported["per90"]["crosses_attempted"], 4)
        self.assertEqual(exported["cross_completion_pct"], 25)
        self.assertEqual(_crosses(old), "–")
        self.assertEqual(_crosses(known), "1/4")

    def test_no_observation_is_unknown_but_recorded_zero_is_known(self):
        old = MatchCapture.from_document(capture_document(season())).matches[-1].detail.players[0]
        (summary,) = summarise_players([(old, date(2020, 10, 3), "Opponent", "Goalkeeper")])
        self.assertIsNone(player_json(summary, "standard")["crosses_attempted"])
        zero = replace(old, stats=dict(old.stats, crosses_attempted=0, crosses_completed=0))
        (summary,) = summarise_players([(zero, date(2020, 10, 10), "Opponent", "Goalkeeper")])
        exported = player_json(summary, "standard")
        self.assertEqual(exported["crosses_attempted"], 0)
        self.assertEqual(exported["per90"]["crosses_attempted"], 0)
        self.assertIsNone(exported["cross_completion_pct"])
