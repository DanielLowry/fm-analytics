import unittest

from fm_analytics.analytics import (
    ScoutingCandidate,
    ScoutingFilters,
    contract_months_left,
    filter_scouting_candidates,
)


def player(identifier: str, **kwargs) -> ScoutingCandidate:
    kwargs.setdefault("captured_game_date", "2019-07-18")
    return ScoutingCandidate(id=identifier, name=identifier, positions=("DC",), attributes={}, **kwargs)


class MarketFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.free = player("free", has_contract=False)
        self.listed = player("listed", transfer_status="transfer_listed", club="A")
        self.soon = player("soon", club="B", contract_end="2019-12-31")
        self.long = player("long", club="C", contract_end="2022-06-30")
        self.unreadable = player("unreadable")  # no contract facts at all
        self.everyone = [self.free, self.listed, self.soon, self.long, self.unreadable]

    def names(self, **kwargs) -> set[str]:
        found = filter_scouting_candidates(self.everyone, ScoutingFilters(**kwargs))
        return {item.name for item in found}

    def test_months_left_counts_whole_months(self) -> None:
        self.assertEqual(contract_months_left(self.soon), 5)
        self.assertIsNone(contract_months_left(self.free))

    def test_each_market_option(self) -> None:
        self.assertEqual(self.names(market="free"), {"free"})
        self.assertEqual(self.names(market="listed"), {"listed"})
        self.assertEqual(self.names(market="expiring"), {"soon"})
        self.assertEqual(self.names(market="gettable"), {"free", "listed", "soon"})
        self.assertEqual(len(self.names()), 5)

    def test_expiring_window_is_adjustable_and_unknown_is_never_gettable(self) -> None:
        self.assertEqual(self.names(market="expiring", expiring_months=2), set())
        self.assertNotIn("unreadable", self.names(market="gettable", expiring_months=600))

    def test_invalid_market_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ScoutingFilters(market="bogus")


if __name__ == "__main__":
    unittest.main()


class ActiveSearchMatchTests(unittest.TestCase):
    """The capture can read FM's on-screen result list, never its criteria."""

    def setUp(self) -> None:
        self.matched = player("matched", matched_active_search=True)
        self.missed = player("missed", matched_active_search=False)
        self.unknown = player("unknown")  # no search was showing at capture time
        self.everyone = [self.matched, self.missed, self.unknown]

    def names(self, **kwargs) -> set[str]:
        found = filter_scouting_candidates(self.everyone, ScoutingFilters(**kwargs))
        return {item.name for item in found}

    def test_filters_both_ways_and_defaults_to_everyone(self) -> None:
        self.assertEqual(self.names(search_match="matched"), {"matched"})
        self.assertEqual(self.names(search_match="unmatched"), {"missed"})
        self.assertEqual(self.names(), {"matched", "missed", "unknown"})

    def test_a_player_with_no_reading_is_never_claimed_either_way(self) -> None:
        for choice in ("matched", "unmatched"):
            self.assertNotIn("unknown", self.names(search_match=choice))

    def test_from_dict_rejects_a_non_boolean(self) -> None:
        with self.assertRaises(TypeError):
            ScoutingCandidate.from_dict(
                {"id": "1", "name": "x", "positions": [], "attributes": {},
                 "matchedActiveSearch": "yes"}
            )

    def test_invalid_choice_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ScoutingFilters(search_match="bogus")
