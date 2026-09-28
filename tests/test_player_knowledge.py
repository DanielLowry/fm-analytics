import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence.player_knowledge import (
    MAX_VERDICT_NOTE_LENGTH,
    MIGRATIONS,
    KnowledgeCapture,
    KnowledgeStoreError,
    PlayerKnowledge,
    PlayerKnowledgeStore,
    TimelineError,
    Verdict,
)


def known(value: int) -> AttributeObservation:
    return AttributeObservation(Visibility.KNOWN, value=value)


def spread(low: int, high: int) -> AttributeObservation:
    return AttributeObservation(Visibility.RANGE, minimum=low, maximum=high)


UNKNOWN = AttributeObservation(Visibility.UNKNOWN)


def player(player_id="1", name="Ada Winger", profile=None, attributes=None, **extra):
    return PlayerKnowledge(
        player_id, name, {"positions": ("AML",), **(profile or {})}, attributes or {}, **extra
    )


def capture(game_date, *players, key="club:1", captured_at="2026-09-26T10:00:00+00:00"):
    return KnowledgeCapture(
        key, game_date, captured_at, tuple(players), club_id="1", club_name="Hungerford Town"
    )


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "knowledge.sqlite3"
        self.store = PlayerKnowledgeStore(self.path)

    def count(self, table: str) -> int:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class RecordingTests(StoreCase):
    def test_first_recording_reports_what_it_added(self) -> None:
        result = self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(14), "passing": spread(9, 13)}))
        )
        self.assertFalse(result.skipped)
        self.assertEqual(
            (result.players_seen, result.new_players, result.profile_rows, result.attribute_rows),
            (1, 1, 1, 2),
        )

    def test_recording_the_same_capture_twice_adds_nothing(self) -> None:
        first = capture("2019-09-08", player(attributes={"pace": known(14)}))
        self.store.record(first)
        before = [self.count(t) for t in ("ingests", "profile_observations", "attribute_observations")]
        again = self.store.record(first)
        self.assertTrue(again.skipped)
        self.assertEqual(
            before,
            [self.count(t) for t in ("ingests", "profile_observations", "attribute_observations")],
        )

    def test_the_same_content_captured_at_another_moment_is_still_skipped(self) -> None:
        self.store.record(capture("2019-09-08", player(), captured_at="2026-09-26T10:00:00+00:00"))
        again = self.store.record(
            capture("2019-09-08", player(), captured_at="2026-09-26T18:30:00+00:00")
        )
        self.assertTrue(again.skipped)

    def test_only_attributes_that_changed_are_appended(self) -> None:
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": spread(10, 16), "passing": known(11)}))
        )
        result = self.store.record(
            capture("2019-09-15", player(attributes={"pace": spread(12, 15), "passing": known(11)}))
        )
        self.assertEqual(result.attribute_rows, 1)
        history = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual(
            [(item.observed_on, item.observation) for item in history],
            [("2019-09-08", spread(10, 16)), ("2019-09-15", spread(12, 15))],
        )
        self.assertEqual(len(self.store.attribute_history("club:1", "1", "passing")), 1)

    def test_an_attribute_fading_to_unknown_is_kept_alongside_what_was_known(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        self.store.record(capture("2019-10-01", player(attributes={"pace": UNKNOWN})))
        history = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual([item.observation for item in history], [known(14), UNKNOWN])

    def test_a_profile_change_adds_a_profile_row_and_no_attribute_row(self) -> None:
        self.store.record(
            capture("2019-09-08", player(profile={"transfer_status": "not_set"}, attributes={"pace": known(14)}))
        )
        result = self.store.record(
            capture("2019-09-15", player(profile={"transfer_status": "transfer_listed"}, attributes={"pace": known(14)}))
        )
        self.assertEqual((result.profile_rows, result.attribute_rows), (1, 0))
        history = self.store.profile_history("club:1", "1")
        self.assertEqual([row["transfer_status"] for row in history], ["not_set", "transfer_listed"])
        self.assertEqual(history[0]["positions"], ["AML"])

    def test_an_unchanged_profile_is_not_repeated_when_only_attributes_change(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        result = self.store.record(capture("2019-09-15", player(attributes={"pace": known(15)})))
        self.assertEqual((result.profile_rows, result.attribute_rows), (0, 1))

    def test_a_player_missing_from_a_later_capture_keeps_his_history(self) -> None:
        self.store.record(
            capture("2019-09-08", player("1", attributes={"pace": known(14)}), player("2", "Bob"))
        )
        self.store.record(capture("2019-09-15", player("2", "Bob")))
        self.assertEqual(len(self.store.attribute_history("club:1", "1")), 1)
        self.assertEqual(self.store.saves()[0].players, 2)

    def test_being_dropped_from_scout_reports_is_recorded_as_a_profile_fact(self) -> None:
        self.store.record(capture("2019-09-08", player(profile={"dropped_from_scout_reports": False})))
        self.store.record(capture("2019-10-01", player(profile={"dropped_from_scout_reports": True})))
        flags = [r["dropped_from_scout_reports"] for r in self.store.profile_history("club:1", "1")]
        self.assertEqual(flags, [False, True])


class LastKnownAndBackdatingTests(StoreCase):
    def test_a_last_known_snapshot_is_recorded_at_the_date_it_was_seen(self) -> None:
        dropped = player(
            attributes={}, last_known_attributes={"pace": spread(8, 12)},
            last_known_observed_on="2019-07-21",
        )
        self.store.record(capture("2019-09-08", dropped))
        (record,) = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual((record.observed_on, record.source), ("2019-07-21", "last_known"))
        self.assertEqual(record.observation, spread(8, 12))

    def test_seeing_him_earlier_moves_first_seen_back_and_last_seen_forward(self) -> None:
        self.store.record(
            capture(
                "2019-09-08",
                player(last_known_attributes={"pace": known(9)}, last_known_observed_on="2019-07-21"),
            )
        )
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT first_seen_on, last_seen_on FROM players").fetchone()
        self.assertEqual(row, ("2019-07-21", "2019-09-08"))

    def test_a_backdated_reading_equal_to_what_was_already_known_is_skipped(self) -> None:
        self.store.record(capture("2019-06-24", player(attributes={"pace": spread(8, 12)})))
        result = self.store.record(
            capture(
                "2019-09-08",
                player(attributes={"pace": known(11)}, attributes_observed_on="2019-09-08",
                       last_known_attributes={"pace": spread(8, 12)}, last_known_observed_on="2019-06-24"),
            )
        )
        states = [item.observation for item in self.store.attribute_history("club:1", "1", "pace")]
        self.assertEqual(states, [spread(8, 12), known(11)])
        self.assertEqual(result.attribute_rows, 1)

    def test_a_carried_forward_reading_keeps_its_own_older_date(self) -> None:
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(14)}, attributes_observed_on="2019-08-01"))
        )
        (record,) = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual(record.observed_on, "2019-08-01")


class SaveIsolationAndTimelineTests(StoreCase):
    def test_two_saves_never_share_a_history(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)}), key="club:1"))
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(9)}), key="save-b"))
        self.assertEqual(
            self.store.attribute_history("club:1", "1")[0].observation, known(14)
        )
        self.assertEqual(
            self.store.attribute_history("save-b", "1")[0].observation, known(9)
        )
        self.assertEqual({save.key for save in self.store.saves()}, {"club:1", "save-b"})

    def test_a_capture_older_than_the_save_is_refused_and_leaves_nothing_behind(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        before = self.count("attribute_observations")
        with self.assertRaisesRegex(TimelineError, "2019-09-01.*2019-09-08"):
            self.store.record(capture("2019-09-01", player(attributes={"pace": known(3)})))
        self.assertEqual(self.count("attribute_observations"), before)
        self.assertEqual(self.count("ingests"), 1)

    def test_a_rewind_can_be_allowed_explicitly(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        result = self.store.record(
            capture("2019-09-01", player(attributes={"pace": known(13)})), allow_rewind=True
        )
        self.assertFalse(result.skipped)
        self.assertEqual(self.store.saves()[0].first_game_date, "2019-09-01")

    def test_the_same_day_may_be_recorded_again_with_new_information(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": spread(8, 14)})))
        result = self.store.record(capture("2019-09-08", player(attributes={"pace": spread(10, 12)})))
        self.assertEqual(result.attribute_rows, 1)


class BestKnownProfileTests(StoreCase):
    def test_exact_and_range_readings_round_trip_with_their_dates_and_sources(self) -> None:
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(14), "passing": spread(9, 13)}))
        )
        profile = self.store.best_known_profile("club:1", "1", "2019-09-08")

        self.assertEqual((profile.save_key, profile.player_id, profile.name, profile.as_of),
                         ("club:1", "1", "Ada Winger", "2019-09-08"))
        pace = profile.attributes["pace"].best_known
        self.assertEqual(pace.observation, known(14))
        self.assertEqual(pace.observation.visibility, Visibility.KNOWN)
        self.assertEqual((pace.observed_on, pace.source), ("2019-09-08", "current"))
        passing = profile.attributes["passing"].best_known
        self.assertEqual(passing.observation, spread(9, 13))
        self.assertEqual(passing.observation.visibility, Visibility.RANGE)
        self.assertEqual((passing.observation.minimum, passing.observation.maximum), (9, 13))
        # The same row `profile_history` reports, decoded the same way.
        self.assertEqual(profile.profile, self.store.profile_history("club:1", "1")[-1])
        self.assertEqual(profile.profile["positions"], ["AML"])
        self.assertEqual((profile.oldest_seen_on, profile.latest_seen_on),
                         ("2019-09-08", "2019-09-08"))

    def test_a_later_unknown_keeps_the_last_value_and_records_that_it_faded(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        self.store.record(capture("2019-10-01", player(attributes={"pace": UNKNOWN})))
        faded = self.store.best_known_profile("club:1", "1", "2019-10-01")

        pace = faded.attributes["pace"]
        self.assertEqual(pace.best_known.observation, known(14))
        self.assertEqual((pace.best_known.observed_on, pace.best_known.source),
                         ("2019-09-08", "current"))
        self.assertEqual(pace.latest.observation, UNKNOWN)
        self.assertEqual(pace.latest.observed_on, "2019-10-01")
        self.assertEqual((faded.oldest_seen_on, faded.latest_seen_on),
                         ("2019-09-08", "2019-10-01"))

    def test_a_captured_unknown_is_not_never_captured_and_neither_gains_a_value(self) -> None:
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(14), "vision": UNKNOWN}))
        )
        profile = self.store.best_known_profile("club:1", "1", "2019-09-08")

        vision = profile.attributes["vision"]
        self.assertIsNone(vision.best_known)          # captured, never learned
        self.assertEqual(vision.latest.observation, UNKNOWN)
        self.assertIsNone(vision.latest.observation.value)
        self.assertEqual(profile.attributes["pace"].best_known.observation, known(14))
        self.assertNotIn("finishing", profile.attributes)  # never captured at all

    def test_the_newest_reading_wins_when_two_ingests_share_a_date(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": spread(8, 14)})))
        self.store.record(capture("2019-09-08", player(attributes={"pace": spread(10, 12)})))
        profile = self.store.best_known_profile("club:1", "1", "2019-09-08")
        self.assertEqual(profile.attributes["pace"].best_known.observation, spread(10, 12))
        history = self.store.attribute_history("club:1", "1", "pace")
        self.assertEqual(len(history), 2)
        # The same order the history reports: its last entry is what is selected.
        self.assertEqual(profile.attributes["pace"].latest.observation, history[-1].observation)

    def test_as_of_excludes_everything_recorded_later(self) -> None:
        self.store.record(
            capture("2019-09-08",
                    player(profile={"transfer_status": "not_set"}, attributes={"pace": known(14)}))
        )
        listed = player(
            profile={"transfer_status": "transfer_listed"}, attributes={"pace": UNKNOWN}
        )
        self.store.record(capture("2019-10-01", listed))

        middle = self.store.best_known_profile("club:1", "1", "2019-09-15")
        self.assertEqual(middle.profile["transfer_status"], "not_set")
        self.assertEqual(middle.attributes["pace"].best_known.observation, known(14))
        self.assertEqual(middle.attributes["pace"].latest.observation, known(14))
        self.assertEqual(middle.latest_seen_on, "2019-09-08")

        self.assertEqual(
            self.store.best_known_profile("club:1", "1", "2019-09-08").profile["observed_on"],
            "2019-09-08",
        )
        latest = self.store.best_known_profile("club:1", "1", "2019-10-01")
        self.assertEqual(latest.profile["transfer_status"], "transfer_listed")
        self.assertEqual(latest.attributes["pace"].latest.observation, UNKNOWN)

    def test_a_player_first_seen_after_the_date_is_absent_rather_than_empty(self) -> None:
        self.store.record(capture("2019-10-01", player(attributes={"pace": known(14)})))
        self.assertIsNone(self.store.best_known_profile("club:1", "1", "2019-09-08"))
        self.assertEqual(self.store.best_known_profiles("club:1", "2019-09-08"), {})
        self.assertIsNone(self.store.best_known_profile("club:1", "no-such-player", "2019-10-01"))

    def test_profiles_never_cross_save_identity(self) -> None:
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(14)}), key="club:1")
        )
        self.store.record(
            capture("2019-09-08", player(attributes={"pace": known(9)}), key="save-b")
        )

        mine = self.store.best_known_profile("club:1", "1", "2019-09-08")
        theirs = self.store.best_known_profile("save-b", "1", "2019-09-08")
        self.assertEqual(mine.attributes["pace"].best_known.observation, known(14))
        self.assertEqual(theirs.attributes["pace"].best_known.observation, known(9))
        self.assertEqual(
            self.store.best_known_profiles("save-b", "2019-09-08")["1"]
            .attributes["pace"].best_known.observation,
            known(9),
        )
        self.assertIsNone(self.store.best_known_profile("save-b", "2", "2019-09-08"))

    def test_an_unrecorded_save_is_absent_rather_than_empty(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        self.assertIsNone(self.store.best_known_profile("no-such-save", "1", "2019-09-08"))
        self.assertEqual(self.store.best_known_profiles("no-such-save", "2019-09-08"), {})

    def test_a_rewound_reading_does_not_beat_a_newer_one(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        self.store.record(
            capture("2019-09-01", player(attributes={"pace": known(13)})), allow_rewind=True
        )
        self.assertEqual(
            self.store.best_known_profile("club:1", "1", "2019-09-08")
            .attributes["pace"].best_known.observation,
            known(14),
        )
        self.assertEqual(
            self.store.best_known_profile("club:1", "1", "2019-09-01")
            .attributes["pace"].best_known.observation,
            known(13),
        )

    def test_backdated_last_known_readings_show_without_a_profile_row(self) -> None:
        self.store.record(
            capture(
                "2019-09-08",
                player(attributes={}, last_known_attributes={"pace": spread(8, 12)},
                       last_known_observed_on="2019-07-21"),
            )
        )
        early = self.store.best_known_profile("club:1", "1", "2019-08-01")

        self.assertIsNone(early.profile)             # no profile row that early
        self.assertEqual(early.name, "Ada Winger")
        self.assertEqual(early.attributes["pace"].best_known.observation, spread(8, 12))
        self.assertEqual(early.attributes["pace"].best_known.source, "last_known")
        self.assertEqual((early.oldest_seen_on, early.latest_seen_on),
                         ("2019-07-21", "2019-07-21"))
        self.assertEqual(self.store.best_known_profile("club:1", "1", "2019-07-20"), None)

    def test_the_batched_read_returns_every_recorded_player_once(self) -> None:
        self.store.record(
            capture("2019-09-08", player("1", attributes={"pace": known(14)}), player("2", "Bob"))
        )
        profiles = self.store.best_known_profiles("club:1", "2019-09-08")

        self.assertEqual(list(profiles), ["1", "2"])
        self.assertEqual(set(profiles["1"].attributes), {"pace"})
        self.assertEqual(profiles["2"].attributes, {})       # profile facts only
        self.assertEqual(profiles["2"].profile["observed_on"], "2019-09-08")
        self.assertEqual((profiles["2"].oldest_seen_on, profiles["2"].latest_seen_on),
                         ("2019-09-08", "2019-09-08"))

    def test_an_unusable_date_is_refused_before_anything_is_read(self) -> None:
        with self.assertRaisesRegex(ValueError, "ISO date"):
            self.store.best_known_profile("club:1", "1", "08/09/2019")
        with self.assertRaisesRegex(ValueError, "ISO date"):
            self.store.best_known_profiles("club:1", "September")
        # Python accepts these as ISO dates, but as text "20190701" sorts after
        # every 2019-xx-xx and would admit September readings.
        for compact in ("20190701", "2019-W27-1"):
            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                self.store.best_known_profiles("club:1", compact)
        self.assertFalse(self.path.exists())

    def test_the_batched_read_costs_the_same_queries_whatever_the_squad(self) -> None:
        self.store.record(capture("2019-09-08", player("1", attributes={"pace": known(14)})))
        crowded = PlayerKnowledgeStore(self.path.parent / "crowded.sqlite3")
        five_players = (
            player(str(number), attributes={"pace": known(14)}) for number in range(1, 6)
        )
        crowded.record(capture("2019-09-08", *five_players))

        one = self.statements_used(self.store, "club:1", "2019-09-08")
        five = self.statements_used(crowded, "club:1", "2019-09-08")

        self.assertEqual(len(one), len(five))
        self.assertLessEqual(len(one), 10)

    def statements_used(self, store, save_key: str, as_of: str) -> list[str]:
        statements: list[str] = []
        original = PlayerKnowledgeStore._connect

        def counting(_store):
            connection = original(_store)
            connection.set_trace_callback(statements.append)
            return connection

        with patch.object(PlayerKnowledgeStore, "_connect", counting):
            store.best_known_profiles(save_key, as_of)
        return statements


class LastSeenTests(StoreCase):
    """Observation rows are change-only; ages run from the last sighting."""

    def seen_monthly(self, *dates: str, attributes=None) -> None:
        for when in dates:
            self.store.record(capture(when, player(attributes=attributes or {"pace": known(14)})))

    def test_an_unchanged_reading_ages_from_its_last_sighting_not_its_first(self) -> None:
        self.seen_monthly("2019-07-01", "2019-08-01", "2019-09-01", "2019-10-01", "2019-11-01")
        profile = self.store.best_known_profile("club:1", "1", "2019-11-01")

        pace = profile.attributes["pace"].best_known
        self.assertEqual((pace.observed_on, pace.last_seen_on), ("2019-07-01", "2019-11-01"))
        self.assertEqual((profile.profile["observed_on"], profile.profile_last_seen_on),
                         ("2019-07-01", "2019-11-01"))
        self.assertEqual((profile.oldest_seen_on, profile.latest_seen_on),
                         ("2019-11-01", "2019-11-01"))
        self.assertEqual(len(self.store.attribute_history("club:1", "1", "pace")), 1)

    def test_sightings_after_as_of_are_not_read(self) -> None:
        self.seen_monthly("2019-07-01", "2019-08-01", "2019-09-01", "2019-10-01")
        profile = self.store.best_known_profile("club:1", "1", "2019-09-15")
        self.assertEqual(profile.attributes["pace"].best_known.last_seen_on, "2019-09-01")
        self.assertEqual(profile.profile_last_seen_on, "2019-09-01")

    def test_the_feeds_last_known_date_survives_an_unchanged_reading(self) -> None:
        self.seen_monthly("2019-07-01")
        self.store.record(
            capture(
                "2019-11-08",
                player(attributes={}, last_known_attributes={"pace": known(14)},
                       last_known_observed_on="2019-11-01"),
            )
        )
        profile = self.store.best_known_profile("club:1", "1", "2019-11-08")

        pace = profile.attributes["pace"].best_known
        self.assertEqual((pace.observed_on, pace.last_seen_on), ("2019-07-01", "2019-11-01"))
        self.assertEqual((profile.oldest_seen_on, profile.latest_seen_on),
                         ("2019-11-01", "2019-11-08"))
        earlier = self.store.best_known_profile("club:1", "1", "2019-10-15")
        self.assertEqual(earlier.attributes["pace"].best_known.last_seen_on, "2019-07-01")

    def test_a_faded_value_was_last_seen_before_it_faded(self) -> None:
        self.seen_monthly("2019-07-01", "2019-08-01")
        self.seen_monthly("2019-09-01", "2019-10-01", attributes={"pace": UNKNOWN})
        pace = self.store.best_known_profile("club:1", "1", "2019-10-01").attributes["pace"]

        self.assertEqual((pace.best_known.observation, pace.best_known.last_seen_on),
                         (known(14), "2019-08-01"))
        self.assertEqual((pace.latest.observed_on, pace.latest.last_seen_on),
                         ("2019-09-01", "2019-10-01"))

    def test_a_capture_without_his_attribute_sheet_does_not_refresh_it(self) -> None:
        self.seen_monthly("2019-07-01")
        self.store.record(capture("2019-08-01", player(attributes={})))
        profile = self.store.best_known_profile("club:1", "1", "2019-08-01")

        self.assertEqual(profile.attributes["pace"].best_known.last_seen_on, "2019-07-01")
        self.assertEqual(profile.profile_last_seen_on, "2019-08-01")
        self.assertEqual((profile.oldest_seen_on, profile.latest_seen_on),
                         ("2019-07-01", "2019-08-01"))

    def test_a_last_known_sheet_vouches_only_for_the_attributes_it_lists(self) -> None:
        # Last-known sheets hold only the attributes FM shows for his position,
        # so an outfielder's sheet says nothing about his handling.
        self.seen_monthly("2019-07-01", attributes={"pace": known(14), "handling": spread(3, 7)})
        self.store.record(
            capture(
                "2019-09-08",
                player(attributes={}, last_known_attributes={"pace": known(14)},
                       last_known_observed_on="2019-09-01"),
            )
        )
        attributes = self.store.best_known_profile("club:1", "1", "2019-09-08").attributes

        self.assertEqual(attributes["pace"].best_known.last_seen_on, "2019-09-01")
        self.assertEqual(attributes["handling"].best_known.last_seen_on, "2019-07-01")

    def test_sightings_never_cross_save_identity(self) -> None:
        self.store.record(capture("2019-07-01", player(attributes={"pace": known(14)})))
        for when in ("2019-07-01", "2019-10-01"):
            self.store.record(capture(when, player(attributes={"pace": known(14)}), key="save-b"))

        mine = self.store.best_known_profile("club:1", "1", "2019-10-01")
        self.assertEqual(mine.attributes["pace"].best_known.last_seen_on, "2019-07-01")
        self.assertEqual(mine.profile_last_seen_on, "2019-07-01")


class AtomicityAndValidationTests(StoreCase):
    def test_a_failure_part_way_through_records_nothing(self) -> None:
        with patch.object(
            PlayerKnowledgeStore, "_record_attributes", side_effect=RuntimeError("disk full")
        ):
            with self.assertRaises(RuntimeError):
                self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        for table in ("saves", "ingests", "players", "profile_observations", "attribute_observations"):
            self.assertEqual(self.count(table), 0, table)

    def test_unknown_profile_fields_are_rejected_rather_than_dropped(self) -> None:
        with self.assertRaisesRegex(ValueError, "current_ability"):
            PlayerKnowledge("1", "A", {"current_ability": 150})

    def test_a_capture_cannot_list_a_player_twice(self) -> None:
        with self.assertRaisesRegex(ValueError, "twice"):
            capture("2019-09-08", player("1"), player("1"))

    def test_dates_must_be_iso(self) -> None:
        with self.assertRaisesRegex(ValueError, "ISO date"):
            capture("08/09/2019", player())
        with self.assertRaisesRegex(ValueError, "ISO date"):
            player(attributes_observed_on="yesterday")

    def test_a_date_that_would_sort_as_another_day_is_refused(self) -> None:
        # Stored dates are compared as text, so only YYYY-MM-DD orders correctly
        # and a history cannot be repaired once a compact date is in it.
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            capture("20190908", player())
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            player(last_known_attributes={"pace": known(9)}, last_known_observed_on="2019-W36-7")

    def test_last_known_attributes_need_a_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "date"):
            player(last_known_attributes={"pace": known(9)})

    def test_the_database_itself_rejects_an_inconsistent_attribute_row(self) -> None:
        self.store.record(capture("2019-09-08", player()))
        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO attribute_observations (save_id, player_id, attribute, "
                    "observed_on, ingest_id, source, visibility, value) "
                    "VALUES (1, '1', 'pace', '2019-09-08', 1, 'current', 'range', 5)"
                )


class VerdictTests(StoreCase):
    def test_a_decision_names_one_player_in_one_save(self) -> None:
        saved = self.store.set_verdict(
            "club:1", "7", "target", note="  fast winger, worth a look  ", decided_on="2019-09-08"
        )
        self.assertEqual(saved.verdict, Verdict.TARGET)
        self.assertEqual(saved.note, "fast winger, worth a look")
        self.assertEqual(saved.decided_on, "2019-09-08")
        self.assertEqual(self.store.get_verdict("club:1", "7"), saved)

    def test_verdicts_of_two_saves_and_two_players_stay_apart(self) -> None:
        self.store.set_verdict("club:1", "7", "target", decided_on="2019-09-08")
        self.store.set_verdict("club:1", "8", "watch", decided_on="2019-09-08")
        self.store.set_verdict("club:2", "7", "reject", decided_on="2019-09-08")

        self.assertEqual(self.store.get_verdict("club:1", "7").verdict, Verdict.TARGET)
        self.assertEqual(self.store.get_verdict("club:1", "8").verdict, Verdict.WATCH)
        self.assertEqual(self.store.get_verdict("club:2", "7").verdict, Verdict.REJECT)
        self.assertIsNone(self.store.get_verdict("club:3", "7"))
        self.assertEqual(set(self.store.current_verdicts("club:1")), {"7", "8"})

    def test_a_later_decision_is_the_current_one_and_the_earlier_survives(self) -> None:
        self.store.set_verdict("club:1", "7", "watch", note="raw", decided_on="2019-09-08")
        self.store.set_verdict("club:1", "7", "target", note="scouted since", decided_on="2019-12-01")

        current = self.store.get_verdict("club:1", "7")
        self.assertEqual((current.verdict, current.note), (Verdict.TARGET, "scouted since"))
        with closing(sqlite3.connect(self.path)) as connection:
            history = connection.execute(
                "SELECT verdict, note FROM verdict_events WHERE player_id = '7' ORDER BY id"
            ).fetchall()
        self.assertEqual(history, [("watch", "raw"), ("target", "scouted since")])

    def test_clearing_forgets_the_current_decision_but_not_the_history(self) -> None:
        self.store.set_verdict("club:1", "7", "reject", decided_on="2019-09-08")
        self.store.clear_verdict("club:1", "7", decided_on="2019-10-01")

        self.assertIsNone(self.store.get_verdict("club:1", "7"))
        self.assertEqual(self.store.current_verdicts("club:1"), {})
        self.assertEqual(self.count("verdict_events"), 2)

    def test_clearing_an_untouched_player_records_nothing(self) -> None:
        self.assertFalse(self.store.clear_verdict("club:1", "7", decided_on="2019-10-01"))
        self.assertEqual(self.count("verdict_events"), 0)

    def test_resubmitting_what_is_current_adds_no_row(self) -> None:
        self.store.set_verdict(
            "club:1", "7", "target", note="keep", decided_on="2019-09-08"
        )
        self.store.set_verdict(
            "club:1", "7", "target", note="  keep  ", decided_on="2019-09-08"
        )
        self.assertEqual(self.count("verdict_events"), 1)

    def test_an_unusable_decision_is_refused_before_anything_is_written(self) -> None:
        self.store.initialize()
        with self.assertRaisesRegex(ValueError, "not a valid Verdict", msg="an unknown name"):
            self.store.set_verdict("club:1", "7", "maybe", decided_on="2019-09-08")
        with self.assertRaisesRegex(ValueError, "limited to"):
            self.store.set_verdict(
                "club:1", "7", "target", note="x" * (MAX_VERDICT_NOTE_LENGTH + 1),
                decided_on="2019-09-08",
            )
        with self.assertRaisesRegex(ValueError, "ISO date"):
            self.store.set_verdict("club:1", "7", "target", decided_on="September")
        with self.assertRaisesRegex(ValueError, "save key"):
            self.store.set_verdict("", "7", "target", decided_on="2019-09-08")
        with self.assertRaisesRegex(ValueError, "player id"):
            self.store.set_verdict("club:1", "", "target", decided_on="2019-09-08")
        with self.assertRaisesRegex(ValueError, "save key"):
            self.store.clear_verdict("", "7", decided_on="2019-09-08")
        self.assertEqual(self.count("verdict_events"), 0)
        self.assertIsNone(self.store.get_verdict("club:1", "7"))

    def test_a_verdict_needs_no_capture_of_its_own(self) -> None:
        self.store.set_verdict("club:9", "7", "target", note="heard of him", decided_on="2019-09-08")
        self.assertEqual(self.store.get_verdict("club:9", "7").note, "heard of him")

    def test_the_batched_read_agrees_with_the_single_reads(self) -> None:
        self.store.set_verdict("club:1", "7", "target", decided_on="2019-09-08")
        self.store.set_verdict("club:1", "8", "watch", decided_on="2019-09-08")
        self.store.set_verdict("club:1", "9", "reject", decided_on="2019-09-08")
        self.store.clear_verdict("club:1", "9", decided_on="2019-10-01")

        current = self.store.current_verdicts("club:1")
        self.assertEqual(set(current), {"7", "8"})
        for player_id, record in current.items():
            self.assertEqual(record, self.store.get_verdict("club:1", player_id))

    def test_the_database_itself_bounds_a_verdict(self) -> None:
        self.store.initialize()
        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO verdict_events (save_key, player_id, verdict, note, decided_on) "
                    "VALUES ('club:1', '7', 'maybe', '', '2019-09-08')"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO verdict_events (save_key, player_id, verdict, note, decided_on) "
                    "VALUES ('club:1', '7', 'target', ?, '2019-09-08')",
                    ("x" * (MAX_VERDICT_NOTE_LENGTH + 1),),
                )


class MigrationTests(StoreCase):
    ADD_NOTE = "ALTER TABLE saves ADD COLUMN note TEXT;"

    def user_version(self, path: Path | None = None) -> int:
        with closing(sqlite3.connect(path or self.path)) as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def test_a_new_file_is_created_at_the_latest_version(self) -> None:
        self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS))

    def test_initialising_twice_changes_nothing(self) -> None:
        self.store.initialize()
        self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS))
        self.assertFalse(list(self.path.parent.glob("*.bak-*")))

    def test_an_older_file_is_backed_up_then_upgraded_with_its_data_intact(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        upgraded = PlayerKnowledgeStore(self.path, migrations=(*MIGRATIONS, self.ADD_NOTE))

        upgraded.initialize()

        self.assertEqual(self.user_version(), len(MIGRATIONS) + 1)
        backup = self.path.with_name(self.path.name + f".bak-v{len(MIGRATIONS)}")
        self.assertTrue(backup.exists())
        self.assertEqual(self.user_version(backup), len(MIGRATIONS))
        self.assertEqual(upgraded.attribute_history("club:1", "1")[0].observation, known(14))
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("SELECT note FROM saves")  # the new column exists

    def test_a_failing_migration_is_rolled_back_and_the_data_left_usable(self) -> None:
        self.store.record(capture("2019-09-08", player(attributes={"pace": known(14)})))
        broken = PlayerKnowledgeStore(
            self.path, migrations=(*MIGRATIONS, "CREATE TABLE half_done (x); THIS IS NOT SQL;")
        )
        with self.assertRaisesRegex(KnowledgeStoreError, "rolled back"):
            broken.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS))
        with closing(sqlite3.connect(self.path)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        self.assertNotIn("half_done", tables)
        self.assertEqual(self.store.attribute_history("club:1", "1")[0].observation, known(14))

    def test_a_file_from_a_newer_program_is_refused_not_touched(self) -> None:
        PlayerKnowledgeStore(self.path, migrations=(*MIGRATIONS, self.ADD_NOTE)).initialize()
        with self.assertRaisesRegex(KnowledgeStoreError, "newer than this program"):
            self.store.initialize()
        self.assertEqual(self.user_version(), len(MIGRATIONS) + 1)

    def test_some_other_sqlite_file_is_refused(self) -> None:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TABLE unrelated (x)")
        with self.assertRaisesRegex(KnowledgeStoreError, "not a player-knowledge database"):
            self.store.initialize()


if __name__ == "__main__":
    unittest.main()
