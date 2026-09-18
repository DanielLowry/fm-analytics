import json
import tempfile
import unittest
from pathlib import Path

import contextlib
from types import SimpleNamespace
from unittest import mock

from tools import fm20_scouting_feed as feed
from tools.fm20_scouting_feed import ScoutingFeedError, feed_document, load_prior_visibility


class ScoutingFeedTests(unittest.TestCase):
    def test_builds_an_identity_only_feed_without_claiming_unread_fields(self) -> None:
        document = feed_document(
            [30, 10], {10: "One Player", 30: "Two Player"},
            game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=22,
            excluded_own_ids=[1, 2],
        )

        self.assertEqual([player["id"] for player in document["players"]], ["10", "30"])
        self.assertEqual(document["players"][0]["positions"], [])
        self.assertEqual(document["players"][0]["attributes"], {})
        self.assertEqual(document["source"]["excludedOwnContractedCount"], 2)
        self.assertIn("not yet", document["source"]["fieldCoverage"]["attributes"])

    def test_refuses_to_publish_an_unlabelled_discovered_player(self) -> None:
        with self.assertRaisesRegex(ScoutingFeedError, "identity lookup failed"):
            feed_document(
                [10], {}, game_date="2020-08-14",
                managed_club={"id": "club-1", "name": "Hungerford Town"},
                source_count=1, excluded_own_ids=[],
            )

    def test_includes_only_verified_visible_attributes_for_hydrated_players(self) -> None:
        document = feed_document(
            [10, 30], {10: "One Player", 30: "Two Player"},
            game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=22,
            excluded_own_ids=[],
            attributes_by_id={
                10: {"finishing": {"visibility": "range", "minimum": 8, "maximum": 14}}
            },
            footedness_by_id={10: "Right"},
            hydrated_count=1,
        )

        self.assertEqual(document["players"][0]["attributes"]["finishing"]["maximum"], 14)
        self.assertEqual(document["players"][1]["attributes"], {})
        self.assertEqual(document["players"][0]["footedness"], "Right")
        self.assertNotIn("footedness", document["players"][1])
        self.assertIn("1/2", document["source"]["fieldCoverage"]["attributes"])

    def test_marks_raw_external_positions_as_the_accepted_visibility_gap(self) -> None:
        document = feed_document(
            [10], {10: "One Player"},
            game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=22,
            excluded_own_ids=[],
            raw_positions_by_id={10: ("ST", "AMC")},
        )

        self.assertEqual(document["players"][0]["positions"], [])
        self.assertEqual(document["players"][0]["rawPositions"], ["ST", "AMC"])
        self.assertIn("accepted", document["source"]["fieldCoverage"]["positions"])

    def test_loads_only_existing_visible_fields_from_a_prior_feed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps({
                "gameDate": "2020-08-14",
                "players": [{
                    "id": "10", "attributes": {"pace": {"visibility": "unknown"}},
                    "footedness": "Right",
                }],
            }), encoding="utf-8")

            prior = load_prior_visibility(path)

        self.assertEqual(prior.game_date, "2020-08-14")
        self.assertEqual(prior.attributes[10]["pace"]["visibility"], "unknown")
        self.assertEqual(prior.footedness, {10: "Right"})
        self.assertEqual(prior.raw_positions, {})

    def test_observed_at_falls_back_to_the_capture_date_for_older_files(self) -> None:
        """A file written before per-field dating existed has only the one date."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps({
                "gameDate": "2020-08-14",
                "players": [{
                    "id": "10", "attributes": {"pace": {"visibility": "unknown"}},
                    "footedness": "Right",
                }],
            }), encoding="utf-8")

            prior = load_prior_visibility(path)

        self.assertEqual(prior.attributes_observed_at, {10: "2020-08-14"})
        self.assertEqual(prior.footedness_observed_at, {10: "2020-08-14"})

    def test_observed_at_is_read_when_present_and_older_than_the_capture(self) -> None:
        """A newer file's per-field date survives even after the file itself refreshes."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps({
                "gameDate": "2020-09-01",
                "players": [{
                    "id": "10", "attributes": {"pace": {"visibility": "unknown"}},
                    "attributesObservedAt": "2020-08-14",
                    "footedness": "Right",
                    "footednessObservedAt": "2020-08-20",
                }],
            }), encoding="utf-8")

            prior = load_prior_visibility(path)

        self.assertEqual(prior.game_date, "2020-09-01")
        self.assertEqual(prior.attributes_observed_at, {10: "2020-08-14"})
        self.assertEqual(prior.footedness_observed_at, {10: "2020-08-20"})

    def test_feed_document_includes_age_and_club_when_resolved(self) -> None:
        """Age/club are basic identity facts, visible with no scouting needed --
        they must appear unconditionally, unlike attributes/raw positions."""
        document = feed_document(
            [10, 30], {10: "One Player", 30: "Two Player"},
            game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=22,
            excluded_own_ids=[],
            identity_facts_by_id={10: {"age": 27, "club": "Weymouth", "transferStatus": "transfer_listed"}},
        )

        self.assertEqual(document["players"][0]["age"], 27)
        self.assertEqual(document["players"][0]["club"], "Weymouth")
        self.assertEqual(document["players"][0]["transferStatus"], "transfer_listed")
        self.assertNotIn("age", document["players"][1])
        self.assertNotIn("club", document["players"][1])
        self.assertIn("age 1/2", document["source"]["fieldCoverage"]["identity"])
        self.assertIn("club/transfer status 1/2", document["source"]["fieldCoverage"]["identity"])

    def test_feed_document_defaults_observed_at_to_the_capture_date(self) -> None:
        document = feed_document(
            [10], {10: "One Player"}, game_date="2020-09-01",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=1, excluded_own_ids=[],
            attributes_by_id={10: {"pace": {"visibility": "unknown"}}},
            footedness_by_id={10: "Right"},
        )

        self.assertEqual(document["players"][0]["attributesObservedAt"], "2020-09-01")
        self.assertEqual(document["players"][0]["footednessObservedAt"], "2020-09-01")

    def test_feed_document_keeps_an_older_observed_at_per_player(self) -> None:
        document = feed_document(
            [10], {10: "One Player"}, game_date="2020-09-01",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=1, excluded_own_ids=[],
            attributes_by_id={10: {"pace": {"visibility": "unknown"}}},
            attributes_observed_at={10: "2020-08-14"},
            footedness_by_id={10: "Right"},
            footedness_observed_at={10: "2020-08-20"},
        )

        self.assertEqual(document["gameDate"], "2020-09-01")
        self.assertEqual(document["players"][0]["attributesObservedAt"], "2020-08-14")
        self.assertEqual(document["players"][0]["footednessObservedAt"], "2020-08-20")


if __name__ == "__main__":
    unittest.main()


class CapturePoolSafetyGateTests(unittest.TestCase):
    """The pool must be read, not rebuilt, unless rebuilding is explicitly allowed."""

    def _patch(self, pool_ids, scouted_players=None):
        state = SimpleNamespace(module_base="0x140000000", game_date="2019-06-24")
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        return (
            mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), pool_ids)),
            mock.patch.object(feed, "_active_manager", return_value=manager),
            mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}),
            mock.patch.object(feed, "connect_to_fm", side_effect=AssertionError("must not attach to FM")),
            mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999),
            mock.patch.object(
                feed, "capture_scouted_attributes", return_value=(scouted_players or {}, {})
            ),
        )

    def test_unbuilt_pool_refuses_rather_than_calling_into_fm(self) -> None:
        with contextlib.ExitStack() as stack:
            for patch in self._patch([]):
                stack.enter_context(patch)
            with self.assertRaises(feed.PoolNotBuiltError) as caught:
                feed.capture_pool(1234, remote_address="127.0.0.1:27042")
        self.assertIn("Open Player Search in FM", str(caught.exception))

    def test_rebuild_still_needs_a_frida_address(self) -> None:
        """Consent alone is not enough; an unreachable server must fail closed."""
        with contextlib.ExitStack() as stack:
            for patch in self._patch([]):
                stack.enter_context(patch)
            with self.assertRaises(ScoutingFeedError) as caught:
                feed.capture_pool(1234, remote_address=None, allow_rebuild=True)
        self.assertIn("Frida server address is required", str(caught.exception))

    def test_pool_not_built_is_a_scouting_feed_error(self) -> None:
        """Existing callers that catch the base class keep failing closed."""
        self.assertTrue(issubclass(feed.PoolNotBuiltError, ScoutingFeedError))


class RefreshLoggingTests(unittest.TestCase):
    """Every decision point must land in the log without a live game to check."""

    def _patch(self, pool_ids, scouted_players=None):
        state = SimpleNamespace(module_base="0x140000000", game_date="2019-06-24")
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        return (
            mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), pool_ids)),
            mock.patch.object(feed, "_active_manager", return_value=manager),
            mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}),
            mock.patch.object(feed, "connect_to_fm", side_effect=AssertionError("must not attach to FM")),
            mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999),
            mock.patch.object(
                feed, "capture_scouted_attributes", return_value=(scouted_players or {}, {})
            ),
        )

    def test_refused_pool_has_a_distinct_log_event_before_the_generic_failure(self) -> None:
        with contextlib.ExitStack() as stack:
            for patch in self._patch([]):
                stack.enter_context(patch)
            logged = stack.enter_context(mock.patch.object(feed, "log_event"))
            with self.assertRaises(feed.PoolNotBuiltError):
                feed.capture_pool(1234, remote_address="127.0.0.1:27042")

        # The specific, diagnosable event fires, and the generic failure
        # handler still fires around it too -- belt and suspenders, not
        # either/or.
        events = [call.args[0] for call in logged.call_args_list]
        self.assertEqual(
            events,
            [
                "scouting_refresh_started",
                "scouting_pool_read",
                "scouting_knowledge_read",
                "scouting_refresh_refused_pool_not_built",
                "scouting_refresh_failed",
            ],
        )

    def test_every_call_carries_the_same_call_number_for_correlation(self) -> None:
        """A crash mid-refresh must be traceable to one call, like the ptrace log."""
        with contextlib.ExitStack() as stack:
            for patch in self._patch([]):
                stack.enter_context(patch)
            logged = stack.enter_context(mock.patch.object(feed, "log_event"))
            with self.assertRaises(feed.PoolNotBuiltError):
                feed.capture_pool(1234, remote_address="127.0.0.1:27042")

        call_numbers = {call.kwargs["call_number"] for call in logged.call_args_list}
        self.assertEqual(len(call_numbers), 1)


class IdentityFactsTests(unittest.TestCase):
    """Age/club/transfer status degrade per player and per field, never
    fail the whole refresh -- mirrors the owned-squad reader's own
    behaviour when one of these reads does not come back cleanly."""

    def test_a_failed_field_for_one_player_does_not_lose_another_players_facts(self) -> None:
        import os
        from datetime import date

        from fm_analytics.domain import Visibility  # noqa: F401  (import used only to confirm module loads)
        from tools.fm20_linux_probe import PlayerContractResult, ClubResult, ProbeError

        contract = PlayerContractResult(
            contract_type="full_time", start_date=None, end_date=None, joined_date=None,
            squad_status=None, transfer_status="transfer_listed",
            contracted_club=ClubResult(id="5100145", name="Weymouth"),
        )

        def fake_read_exact(fd, address, size):
            if address == 20 + 0x28 + 0x1C:  # player 2's DOB bytes
                raise ProbeError("simulated bad DOB read")
            return b"\x00\x00\x00\x00"

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(feed, "read_exact", side_effect=fake_read_exact))
            stack.enter_context(mock.patch.object(
                feed, "decode_fm_date", return_value=date(1991, 8, 8)
            ))
            stack.enter_context(mock.patch.object(feed, "calculate_age", return_value=27))
            stack.enter_context(mock.patch.object(feed, "read_player_contract", return_value=contract))

            facts = feed.resolve_source_identity_facts(
                os.getpid(), {1: 10, 2: 20}, "2019-07-04"
            )

        # Player 1: everything resolved.
        self.assertEqual(facts[1]["age"], 27)
        self.assertEqual(facts[1]["club"], "Weymouth")
        self.assertEqual(facts[1]["transferStatus"], "transfer_listed")
        # Player 2: DOB read failed, but club/transfer status still made it in --
        # a genuine per-field degrade, not an all-or-nothing loss.
        self.assertNotIn("age", facts[2])
        self.assertEqual(facts[2]["club"], "Weymouth")

    def test_a_player_with_no_contract_and_no_dob_is_simply_absent(self) -> None:
        import os

        from tools.fm20_linux_probe import ProbeError

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                feed, "read_exact", side_effect=ProbeError("no DOB")
            ))
            stack.enter_context(mock.patch.object(feed, "read_player_contract", return_value=None))

            facts = feed.resolve_source_identity_facts(os.getpid(), {1: 10}, "2019-07-04")

        self.assertNotIn(1, facts)


class DateDriftTests(unittest.TestCase):
    """Reproduces the reported failure: base feed older than the live game date."""

    def test_refresh_succeeds_across_a_date_change_and_logs_the_drift(self) -> None:
        import os

        state = SimpleNamespace(
            module_base="0x140000000", game_date="2019-07-04", first_team_squad=(),
        )
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        pool_ids = [10, 20]
        records = {10: 0x1000, 20: 0x2000}
        names = {10: "A Player", 20: "B Player"}

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                feed, "_live_context", return_value=(state, (1, 2, 3), pool_ids)
            ))
            stack.enter_context(mock.patch.object(feed, "_active_manager", return_value=manager))
            stack.enter_context(mock.patch.object(
                feed, "preflight", return_value={"moduleBase": "0x140000000"}
            ))
            stack.enter_context(mock.patch.object(feed, "process_alive", return_value=True))
            stack.enter_context(mock.patch.object(feed, "_source_records", return_value=records))
            stack.enter_context(mock.patch.object(feed, "resolve_source_player_names", return_value=names))
            stack.enter_context(mock.patch.object(feed, "read_raw_external_positions", return_value={}))
            stack.enter_context(mock.patch.object(
                feed, "connect_to_fm", side_effect=AssertionError("must not attach to FM")
            ))
            stack.enter_context(mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999))
            stack.enter_context(mock.patch.object(feed, "capture_scouted_attributes", return_value=({}, {})))
            logged = stack.enter_context(mock.patch.object(feed, "log_event"))

            document = feed.capture_pool(
                os.getpid(),  # a real /proc/<pid>/mem must be openable
                remote_address=None,
                allow_rebuild=False,
                prior_game_date="2019-06-24",
                prior_attributes_by_id={10: {"pace": {"visibility": "unknown"}}},
                prior_attributes_observed_at={10: "2019-06-24"},
                prior_footedness_by_id={10: "Right"},
                prior_footedness_observed_at={10: "2019-06-24"},
            )

        # The refresh must succeed -- no more hard failure on date drift -- and
        # the file's own date always advances to today's live read.
        self.assertEqual(document["gameDate"], "2019-07-04")
        by_id = {player["id"]: player for player in document["players"]}
        self.assertEqual(by_id["10"]["attributes"]["pace"]["visibility"], "unknown")
        # The carried-forward fact keeps the date it was actually observed,
        # not today's date -- this is "keep the old dates" from the request.
        self.assertEqual(by_id["10"]["attributesObservedAt"], "2019-06-24")
        self.assertEqual(by_id["10"]["footednessObservedAt"], "2019-06-24")

        # The drift must be visible in the log without needing to read the
        # live game by hand to diagnose a future failure.
        events = [call.args[0] for call in logged.call_args_list]
        self.assertIn("scouting_refresh_date_drift", events)
        drift_call = next(
            call for call in logged.call_args_list if call.args[0] == "scouting_refresh_date_drift"
        )
        self.assertEqual(drift_call.kwargs["prior_game_date"], "2019-06-24")
        self.assertEqual(drift_call.kwargs["live_game_date"], "2019-07-04")
        self.assertIn("scouting_refresh_completed", events)
        self.assertNotIn("scouting_refresh_failed", events)


class FeedProvenanceTests(unittest.TestCase):
    def test_document_records_whether_fm_was_asked_to_rebuild(self) -> None:
        read_only = feed.feed_document(
            [1], {1: "A Player"}, game_date="2019-06-24",
            managed_club={"id": "c1", "name": "Example FC"},
            source_count=1, excluded_own_ids=[],
        )
        rebuilt = feed.feed_document(
            [1], {1: "A Player"}, game_date="2019-06-24",
            managed_club={"id": "c1", "name": "Example FC"},
            source_count=1, excluded_own_ids=[], rebuilt=True,
        )

        self.assertFalse(read_only["source"]["poolRebuiltByCapture"])
        self.assertEqual(read_only["source"]["transport"], "read-only-process-memory")
        self.assertTrue(rebuilt["source"]["poolRebuiltByCapture"])
        self.assertEqual(rebuilt["source"]["transport"], "windows-frida-server")
