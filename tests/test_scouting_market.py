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


class InterestFilterTests(unittest.TestCase):
    """FM's own transfer/loan interest, computed fresh in the sandbox each refresh."""

    def setUp(self) -> None:
        self.yes = player("yes", transfer_interest="yes")
        self.maybe = player("maybe", transfer_interest="maybe")
        self.none = player("none")  # not interested, or not captured this refresh
        self.everyone = [self.yes, self.maybe, self.none]

    def names(self, **kwargs) -> set[str]:
        found = filter_scouting_candidates(self.everyone, ScoutingFilters(**kwargs))
        return {item.name for item in found}

    def test_interested_includes_yes_and_maybe_but_not_none(self) -> None:
        self.assertEqual(self.names(transfer_interest="interested"), {"yes", "maybe"})

    def test_not_interested_is_only_none(self) -> None:
        self.assertEqual(self.names(transfer_interest="not_interested"), {"none"})

    def test_any_is_everyone(self) -> None:
        self.assertEqual(self.names(), {"yes", "maybe", "none"})

    def test_loan_interest_is_independent_of_transfer_interest(self) -> None:
        both = player("both", transfer_interest="yes", loan_interest="maybe")
        self.assertEqual(
            {item.name for item in filter_scouting_candidates(
                [self.yes, both], ScoutingFilters(loan_interest="interested")
            )},
            {"both"},
        )

    def test_from_dict_rejects_an_invalid_value(self) -> None:
        with self.assertRaises(TypeError):
            ScoutingCandidate.from_dict(
                {"id": "1", "name": "x", "positions": [], "attributes": {},
                 "transferInterest": "definitely"}
            )

    def test_invalid_choice_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ScoutingFilters(transfer_interest="bogus")
        with self.assertRaises(ValueError):
            ScoutingFilters(loan_interest="bogus")
