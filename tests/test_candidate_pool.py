import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE, ScoutingCandidate, ScoutingFilters
from fm_analytics.analytics.scouting import filter_scouting_candidates, rank_for_position
from fm_analytics.candidate_pool import compose_candidate_pool, months_before
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence import KnowledgeCapture, PlayerKnowledge, PlayerKnowledgeStore

SAVE = "club:1"


def known(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


def spread(low: int, high: int) -> AttributeObservation:
    return AttributeObservation(Visibility.RANGE, minimum=low, maximum=high)


UNKNOWN = AttributeObservation(Visibility.UNKNOWN)


def seen(player_id, name="Ada Winger", attributes=None, **profile):
    return PlayerKnowledge(
        player_id, name, {"positions": ("AML",), **profile}, attributes or {},
        attributes_observed_on=None,
    )


def feed(player_id, name="Ada Winger", attributes=None, **extra):
    return ScoutingCandidate(
        id=player_id, name=name, positions=("AML",), attributes=attributes or {},
        captured_game_date="2019-10-01", **extra,
    )


class PoolCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = PlayerKnowledgeStore(Path(directory.name) / "knowledge.sqlite3")

    def record(self, game_date, *players, save=SAVE):
        self.store.record(KnowledgeCapture(save, game_date, f"{game_date}T10:00:00", tuple(players)))

    def pool(self, *current, as_of="2019-10-01", save=SAVE, months=6):
        return compose_candidate_pool(
            current, self.store.best_known_profiles(save, as_of),
            save_key=save, as_of=as_of, out_of_date_months=months,
        )


class CurrentFeedTests(PoolCase):
    def test_with_no_history_the_feed_is_returned_object_for_object(self) -> None:
        current = (feed("1", attributes={"pace": known(14)}), feed("2", "Bo Back"))
        pool = self.pool(*current)
        self.assertEqual(len(pool), 2)
        self.assertTrue(all(a is b for a, b in zip(pool, current)))

    def test_a_candidate_history_adds_nothing_to_is_the_same_object(self) -> None:
        self.record("2019-09-08", seen("1", attributes={"pace": known(12)}))
        current = feed("1", attributes={"pace": known(14)})
        self.assertIs(self.pool(current)[0], current)

    def test_current_exact_and_ranged_values_are_never_replaced(self) -> None:
        self.record("2019-09-08", seen("1", attributes={"pace": known(18), "passing": known(17)}))
        current = feed("1", attributes={"pace": known(12), "passing": spread(8, 12)})
        (merged,) = self.pool(current)
        self.assertEqual(merged.attributes["pace"], known(12))
        self.assertEqual(merged.attributes["passing"], spread(8, 12))
        self.assertIsNone(merged.history)

    def test_a_current_unknown_is_filled_from_history_and_dated(self) -> None:
        self.record("2019-09-08", seen("1", attributes={"pace": known(14), "vision": spread(9, 13)}))
        self.record("2019-09-15", seen("1", attributes={"pace": known(14), "vision": spread(9, 13)}))
        self.record("2019-10-01", seen("1", attributes={"pace": UNKNOWN, "vision": spread(9, 13)}))
        current = feed("1", attributes={"pace": UNKNOWN, "vision": spread(9, 13)})
        (merged,) = self.pool(current)
        self.assertEqual(merged.attributes["pace"], known(14))
        self.assertEqual(merged.attributes["vision"], spread(9, 13))
        reading = merged.historical_reading("pace")
        self.assertEqual((reading.observed_on, reading.last_seen_on), ("2019-09-08", "2019-09-15"))
        self.assertIsNone(merged.historical_reading("vision"))
        self.assertTrue(merged.in_current_feed)
        self.assertEqual(merged.history.oldest_seen_on, "2019-09-15")

    def test_an_attribute_missing_from_the_feed_is_filled_too(self) -> None:
        # A dropped player: the feed has no current sheet at all.
        self.record("2019-09-08", seen("1", attributes={"pace": spread(12, 16)}))
        current = feed("1", scouting_knowledge=20, dropped_from_scout_reports=True)
        (merged,) = self.pool(current)
        self.assertEqual(merged.attributes, {"pace": spread(12, 16)})
        self.assertEqual(set(merged.history.attributes), {"pace"})

    def test_current_profile_facts_are_never_touched(self) -> None:
        self.record("2019-09-08", seen(
            "1", attributes={"pace": known(14)}, club="Old FC", has_contract=False,
            transfer_status="transfer_listed", value=5000, age=20,
        ))
        current = feed(
            "1", attributes={"pace": UNKNOWN}, club="New FC", has_contract=True,
            transfer_status=None, value=90000, age=21,
        )
        (merged,) = self.pool(current)
        self.assertEqual(
            (merged.club, merged.has_contract, merged.transfer_status, merged.value, merged.age),
            ("New FC", True, None, 90000, 21),
        )
        self.assertIsNone(merged.history.profile)

    def test_a_filled_value_is_scored(self) -> None:
        self.record("2019-09-08", seen("1", attributes={"pace": known(20), "acceleration": known(20)}))
        blank = feed("1", attributes={"pace": UNKNOWN, "acceleration": UNKNOWN})
        (merged,) = self.pool(blank)
        before = rank_for_position((blank,), MVP_CATALOGUE, "AML")[0]
        after = rank_for_position((merged,), MVP_CATALOGUE, "AML")[0]
        self.assertGreater(after.minimum, before.minimum)

    def test_a_feed_listing_a_player_twice_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.pool(feed("1"), feed("1"))


class HistoryOnlyTests(PoolCase):
    def setUp(self) -> None:
        super().setUp()
        self.record("2019-09-08", seen(
            "9", "Gone Striker", attributes={"finishing": known(15), "vision": UNKNOWN},
            club="Old FC", has_contract=False, transfer_status="transfer_listed",
            contract_end="2019-12-31", value=0, age=24, nationality="ENG",
            scouting_knowledge=60, positions=("ST",),
        ))

    def test_a_player_only_in_history_appears_once_and_is_not_current(self) -> None:
        pool = self.pool(feed("1"))
        self.assertEqual([item.id for item in pool], ["1", "9"])
        gone = pool[1]
        self.assertFalse(gone.in_current_feed)
        self.assertEqual((gone.name, gone.positions, gone.age, gone.nationality), ("Gone Striker", ("ST",), 24, "ENG"))
        self.assertEqual(gone.attributes["finishing"], known(15))
        self.assertEqual(gone.attributes["vision"], UNKNOWN)
        self.assertEqual(set(gone.history.attributes), {"finishing"})
        self.assertEqual(gone.history.profile["club"], "Old FC")
        self.assertEqual(gone.history.profile_last_seen_on, "2019-09-08")
        self.assertEqual(gone.captured_game_date, "2019-10-01")

    def test_old_market_facts_never_become_current_ones(self) -> None:
        gone = self.pool()[0]
        self.assertEqual(
            (gone.club, gone.has_contract, gone.transfer_status, gone.contract_end, gone.value,
             gone.transfer_interest, gone.loan_interest),
            (None,) * 7,
        )

    def test_he_is_listed_only_under_everyone_ever_scouted(self) -> None:
        pool = self.pool(feed("1"))
        self.assertEqual([c.id for c in filter_scouting_candidates(pool, ScoutingFilters())], ["1"])
        everyone = ScoutingFilters(include_former_scouted=True)
        self.assertEqual([c.id for c in filter_scouting_candidates(pool, everyone)], ["1", "9"])
        scouted = ScoutingFilters(include_former_scouted=True, scouted_only=True)
        self.assertEqual([c.id for c in filter_scouting_candidates(pool, scouted)], ["9"])

    def test_no_market_or_interest_filter_admits_him_on_an_old_fact(self) -> None:
        pool = self.pool()
        for filters in (
            ScoutingFilters(include_former_scouted=True, market=market)
            for market in ("gettable", "free", "listed", "expiring")
        ):
            self.assertEqual(filter_scouting_candidates(pool, filters), (), filters.market)
        for filters in (
            ScoutingFilters(include_former_scouted=True, maximum_value=1000),
            ScoutingFilters(include_former_scouted=True, transfer_interest="interested"),
            ScoutingFilters(include_former_scouted=True, loan_interest="interested"),
        ):
            self.assertEqual(filter_scouting_candidates(pool, filters), ())

    def test_same_name_with_another_id_is_another_player(self) -> None:
        pool = self.pool(feed("1", "Gone Striker"))
        self.assertEqual([(item.id, item.in_current_feed) for item in pool], [("1", True), ("9", False)])

    def test_nothing_from_after_the_feed_date_is_read(self) -> None:
        self.record("2019-11-01", seen("10", "Future Find", attributes={"pace": known(19)}))
        self.assertEqual([item.id for item in self.pool(as_of="2019-10-01")], ["9"])

    def test_history_with_only_unknowns_offers_no_values(self) -> None:
        self.record("2019-09-20", seen("11", "Blank", attributes={"pace": UNKNOWN}))
        blank = next(item for item in self.pool() if item.id == "11")
        self.assertEqual(blank.attributes, {"pace": UNKNOWN})
        self.assertEqual(blank.history.attributes, {})


class SaveIdentityTests(PoolCase):
    def test_another_saves_history_never_joins_this_pool(self) -> None:
        self.record("2019-09-08", seen("1", attributes={"pace": known(19)}), save="club:2")
        self.record("2019-09-08", seen("2", "Other Save Only"), save="club:2")
        current = feed("1", attributes={"pace": UNKNOWN})
        pool = self.pool(current)
        self.assertEqual(len(pool), 1)
        self.assertIs(pool[0], current)

    def test_a_profile_from_another_save_or_date_is_refused(self) -> None:
        self.record("2019-09-08", seen("1"), save="club:2")
        profiles = self.store.best_known_profiles("club:2", "2019-10-01")
        with self.assertRaises(ValueError):
            compose_candidate_pool((), profiles, save_key=SAVE, as_of="2019-10-01")
        with self.assertRaises(ValueError):
            compose_candidate_pool((), profiles, save_key="club:2", as_of="2019-10-02")


class OutOfDateTests(PoolCase):
    def test_age_crosses_the_threshold_on_its_own_date(self) -> None:
        self.record("2019-04-01", seen("1", attributes={"pace": known(14)}))
        self.record("2019-04-02", seen("2", "Bo Back", attributes={"pace": known(14)}))
        pool = self.pool(as_of="2019-10-01")
        self.assertEqual(pool[0].history.out_of_date_before, "2019-04-01")
        self.assertEqual([item.history.out_of_date for item in pool], [False, False])
        later = self.pool(as_of="2019-10-02")
        self.assertEqual([item.history.out_of_date for item in later], [True, False])

    def test_the_threshold_is_configurable(self) -> None:
        self.record("2019-09-01", seen("1", attributes={"pace": known(14)}))
        self.assertFalse(self.pool(months=6)[0].history.out_of_date)
        self.assertTrue(self.pool(months=0)[0].history.out_of_date)

    def test_months_are_calendar_months_clamped_to_month_end(self) -> None:
        self.assertEqual(months_before("2019-09-08", 6), "2019-03-08")
        self.assertEqual(months_before("2019-08-31", 6), "2019-02-28")
        self.assertEqual(months_before("2020-08-31", 6), "2020-02-29")
        self.assertEqual(months_before("2020-01-15", 1), "2019-12-15")
        with self.assertRaises(ValueError):
            months_before("2019-09-08", -1)


class HistoryDoesNotRewriteTheFeedTests(PoolCase):
    def test_a_replaced_candidate_keeps_every_other_field(self) -> None:
        self.record("2019-09-08", seen("1", attributes={"pace": known(14)}))
        current = feed("1", attributes={"pace": UNKNOWN}, club="New FC", scouting_knowledge=40)
        (merged,) = self.pool(current)
        self.assertEqual(replace(merged, attributes=current.attributes, history=None), current)


if __name__ == "__main__":
    unittest.main()
