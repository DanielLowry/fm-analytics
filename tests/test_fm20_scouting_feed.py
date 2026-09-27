import json
import tempfile
import unittest
from pathlib import Path

import contextlib
from types import SimpleNamespace
from unittest import mock

from tools import fm20_scouting_feed as feed
from tools import fm20_scouting_identity as identity
from tools.fm20_sandbox_queries import SandboxQueryError
from tools.fm20_scouting_feed import ScoutingFeedError, feed_document, load_prior_visibility

# Building the Player Search list in the sandbox needs a real FM process; every
# capture_pool test here gets a build that fails, i.e. the fallback to FM's own
# live list that predates it. PoolBuiltInSandboxTests replaces this per test.
_SANDBOX_POOL = mock.patch.object(
    feed, "build_pool_in_sandbox", side_effect=SandboxQueryError("no FM in unit tests")
)


def setUpModule() -> None:
    _SANDBOX_POOL.start()


def tearDownModule() -> None:
    _SANDBOX_POOL.stop()


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
            sandboxed_count=1,
        )

        self.assertEqual(document["players"][0]["attributes"]["finishing"]["maximum"], 14)
        self.assertEqual(document["players"][1]["attributes"], {})
        self.assertEqual(document["players"][0]["footedness"], "Right")
        self.assertNotIn("footedness", document["players"][1])
        self.assertIn("1/2", document["source"]["fieldCoverage"]["attributes"])

    def test_current_and_last_known_attributes_are_separate_dated_fields(self) -> None:
        document = feed_document(
            [10], {10: "One Player"}, game_date="2020-09-01",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=1, excluded_own_ids=[],
            attributes_by_id={10: {}},
            last_known_attributes_by_id={
                10: {"pace": {"visibility": "range", "minimum": 8, "maximum": 14}}
            },
            last_known_attributes_observed_at={10: "2020-08-14"},
        )

        player = document["players"][0]
        self.assertEqual(player["attributes"], {})
        self.assertEqual(player["lastKnownAttributes"]["pace"]["maximum"], 14)
        self.assertEqual(player["lastKnownAttributesObservedAt"], "2020-08-14")

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

    def test_scout_report_is_written_for_every_known_player_and_read_back(self) -> None:
        document = feed_document(
            [10, 20, 30], {10: "Reported", 20: "Known", 30: "Pool"}, game_date="2020-08-14",
            managed_club={"id": "1", "name": "Club"}, source_count=3, excluded_own_ids=(),
            scouting_knowledge_by_id={10: 0, 20: 40}, scout_report_ids={10},
        )
        rows = {row["id"]: row for row in document["players"]}
        self.assertIs(rows["10"]["scoutReport"], True)
        self.assertIs(rows["20"]["scoutReport"], False)
        self.assertNotIn("scoutReport", rows["30"])  # not known at all: nothing to say

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(load_prior_visibility(path).scout_reports, frozenset({10}))

    def test_a_feed_from_before_scout_reports_were_recorded_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps({
                "gameDate": "2020-08-14", "players": [{"id": "10", "scoutingKnowledge": 30}],
            }), encoding="utf-8")

            self.assertIsNone(load_prior_visibility(path).scout_reports)

    def test_load_migrates_a_legacy_dropped_players_attributes_to_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.json"
            path.write_text(json.dumps({
                "schemaVersion": 1,
                "gameDate": "2020-08-14",
                "players": [{
                    "id": "10", "name": "Past Player",
                    "scoutingKnowledge": 6,
                    "droppedFromScoutReports": True,
                    "attributes": {
                        "pace": {"visibility": "range", "minimum": 8, "maximum": 14}
                    },
                    "attributesObservedAt": "2020-07-21",
                }],
            }), encoding="utf-8")

            prior = load_prior_visibility(path)

        self.assertNotIn(10, prior.attributes)
        self.assertEqual(prior.last_known_attributes[10]["pace"]["maximum"], 14)
        self.assertEqual(
            prior.last_known_attributes_observed_at[10], "2020-07-21"
        )

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
                "scouting_sandbox_pool_failed",
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


class SandboxCaptureWiringTests(unittest.TestCase):
    """capture_pool merges the sandbox's answer over the scouted baseline,
    and degrades gracefully (never fails the refresh) when the sandbox
    could not be set up at all -- the same posture a Frida failure used to
    have, now for a read-only step that cannot touch FM."""

    def test_sandbox_attributes_and_interest_override_the_scouted_baseline(self) -> None:
        import os

        from fm_analytics.domain import AttributeObservation, Visibility
        from tools.fm20_sandbox_queries import InterestVerdict, PlayerCapture
        from tools.fm20_scouted_attributes import ScoutedPlayer

        state = SimpleNamespace(module_base="0x140000000", game_date="2019-07-04", first_team_squad=())
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        records = {10: 0x1000}
        names = {10: "A Player"}
        scouted = ScoutedPlayer(
            row_id=1, player_id=10, name="A Player", age=21, person=0x1000, knowledge=15,
            observations={"pace": AttributeObservation(Visibility.RANGE, minimum=8, maximum=14)},
        )
        sandbox_result = {
            10: PlayerCapture(
                attributes={"pace": AttributeObservation(Visibility.KNOWN, value=12)},
                interest=InterestVerdict(transfer="yes", loan=None),
            )
        }

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), [10])))
            stack.enter_context(mock.patch.object(feed, "_active_manager", return_value=manager))
            stack.enter_context(mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}))
            stack.enter_context(mock.patch.object(feed, "process_alive", return_value=True))
            stack.enter_context(mock.patch.object(feed, "_source_records", return_value=records))
            stack.enter_context(mock.patch.object(feed, "resolve_source_player_names", return_value=names))
            stack.enter_context(mock.patch.object(feed, "read_raw_external_positions", return_value={}))
            stack.enter_context(mock.patch.object(feed, "read_raw_position_familiarity", return_value={}))
            stack.enter_context(mock.patch.object(feed, "resolve_source_identity_facts", return_value={}))
            stack.enter_context(mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999))
            stack.enter_context(mock.patch.object(
                feed, "capture_scouted_attributes", return_value=({10: scouted}, {})
            ))
            stack.enter_context(mock.patch.object(
                feed, "resolve_sandbox_context",
                return_value=SimpleNamespace(module_base=0x140000000, knowledge_context=0x999),
            ))
            stack.enter_context(mock.patch.object(feed, "resolve_player_interfaces", return_value={10: 0x1000}))
            stack.enter_context(mock.patch.object(feed, "resolve_scout_persons", return_value={}))
            capture_players_mock = stack.enter_context(
                mock.patch.object(feed, "capture_players", return_value=sandbox_result)
            )
            stack.enter_context(mock.patch.object(feed, "log_event"))

            document = feed.capture_pool(os.getpid(), remote_address=None)

        capture_players_mock.assert_called_once()
        row = document["players"][0]
        # The sandbox's answer (exact) overrides the scouted-only calculation
        # (a range) for the same attribute, and interest is a new field the
        # scouted-only calculation could never have supplied.
        self.assertEqual(row["attributes"]["pace"], {"visibility": "known", "value": 12})
        self.assertEqual(row["transferInterest"], "yes")
        self.assertNotIn("loanInterest", row)
        self.assertEqual(document["source"]["sandboxedCount"], 1)
        self.assertIsNone(document["source"]["sandboxError"])

    def test_an_unresolvable_sandbox_context_degrades_the_refresh_rather_than_failing_it(self) -> None:
        import os

        from tools.fm20_sandbox_queries import SandboxQueryError

        state = SimpleNamespace(module_base="0x140000000", game_date="2019-07-04", first_team_squad=())
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        records = {10: 0x1000}
        names = {10: "A Player"}

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), [10])))
            stack.enter_context(mock.patch.object(feed, "_active_manager", return_value=manager))
            stack.enter_context(mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}))
            stack.enter_context(mock.patch.object(feed, "process_alive", return_value=True))
            stack.enter_context(mock.patch.object(feed, "_source_records", return_value=records))
            stack.enter_context(mock.patch.object(feed, "resolve_source_player_names", return_value=names))
            stack.enter_context(mock.patch.object(feed, "read_raw_external_positions", return_value={}))
            stack.enter_context(mock.patch.object(feed, "read_raw_position_familiarity", return_value={}))
            stack.enter_context(mock.patch.object(feed, "resolve_source_identity_facts", return_value={}))
            stack.enter_context(mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999))
            stack.enter_context(mock.patch.object(feed, "capture_scouted_attributes", return_value=({}, {})))
            stack.enter_context(mock.patch.object(
                feed, "resolve_sandbox_context",
                side_effect=SandboxQueryError("the manager's search source has no filter object"),
            ))
            events = stack.enter_context(mock.patch.object(feed, "log_event"))

            document = feed.capture_pool(os.getpid(), remote_address=None)

        self.assertEqual(document["players"][0]["attributes"], {})
        self.assertEqual(document["source"]["sandboxedCount"], 0)
        self.assertIn("filter object", document["source"]["sandboxError"])
        events.assert_any_call(
            "scouting_sandbox_capture_failed", call_number=mock.ANY, pid=os.getpid(),
            exception_type="SandboxQueryError",
            exception="the manager's search source has no filter object",
        )


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
            stack.enter_context(mock.patch.object(identity, "read_exact", side_effect=fake_read_exact))
            stack.enter_context(mock.patch.object(
                identity, "decode_fm_date", return_value=date(1991, 8, 8)
            ))
            stack.enter_context(mock.patch.object(identity, "calculate_age", return_value=27))
            stack.enter_context(mock.patch.object(identity, "read_player_contract", return_value=contract))

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

    def test_a_player_with_no_contract_is_recorded_as_unattached(self) -> None:
        import os

        from tools.fm20_linux_probe import ProbeError

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                identity, "read_exact", side_effect=ProbeError("no DOB")
            ))
            stack.enter_context(mock.patch.object(identity, "read_player_contract", return_value=None))

            facts = feed.resolve_source_identity_facts(os.getpid(), {1: 10}, "2019-07-04")

        self.assertEqual(facts[1], {"hasContract": False})


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
                prior_attributes_by_id={
                    10: {"pace": {"visibility": "range", "minimum": 8, "maximum": 14}}
                },
                prior_attributes_observed_at={10: "2019-06-24"},
                prior_footedness_by_id={10: "Right"},
                prior_footedness_observed_at={10: "2019-06-24"},
                prior_scouting_knowledge={10: 6},
                prior_names={10: "A Player"},
            )

        # The refresh must succeed -- no more hard failure on date drift -- and
        # the file's own date always advances to today's live read.
        self.assertEqual(document["gameDate"], "2019-07-04")
        by_id = {player["id"]: player for player in document["players"]}
        self.assertEqual(by_id["10"]["attributes"], {})
        self.assertEqual(
            by_id["10"]["lastKnownAttributes"]["pace"]["visibility"], "range"
        )
        # The historical fact keeps the date it was actually observed and is
        # no longer presented as a current scoring input.
        self.assertEqual(
            by_id["10"]["lastKnownAttributesObservedAt"], "2019-06-24"
        )
        self.assertTrue(by_id["10"]["droppedFromScoutReports"])
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


class ScoutedOnlyIdentityTests(unittest.TestCase):
    """The Scouted tab must have positions and a club without Player Search."""

    def test_scouted_players_outside_the_pool_get_positions_and_club(self) -> None:
        import os
        from tools.fm20_scouted_attributes import ScoutedPlayer

        state = SimpleNamespace(module_base="0x140000000", game_date="2019-07-04", first_team_squad=())
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        player = ScoutedPlayer(
            row_id=7, player_id=42, name="Scouted Player", age=21, person=0x5000,
            knowledge=15, observations={},
        )
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), [])))
            stack.enter_context(mock.patch.object(feed, "_active_manager", return_value=manager))
            stack.enter_context(mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}))
            stack.enter_context(mock.patch.object(feed, "process_alive", return_value=True))
            stack.enter_context(mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999))
            stack.enter_context(mock.patch.object(feed, "capture_scouted_attributes", return_value=({42: player}, {})))
            positions = stack.enter_context(mock.patch.object(
                feed, "read_raw_external_positions", return_value={42: ("DR", "MR")}))
            stack.enter_context(mock.patch.object(
                feed, "resolve_source_identity_facts",
                return_value={42: {"age": 21, "club": "Weymouth", "transferStatus": "transfer_listed"}}))
            stack.enter_context(mock.patch.object(feed, "log_event"))

            document = feed.capture_pool(os.getpid(), remote_address=None)

        row = document["players"][0]
        self.assertEqual(row["rawPositions"], ["DR", "MR"])
        self.assertEqual(row["club"], "Weymouth")
        self.assertEqual(row["transferStatus"], "transfer_listed")
        self.assertFalse(document["source"]["poolAvailable"])
        positions.assert_called_once()

    def test_one_unreadable_scouted_player_does_not_fail_the_refresh(self) -> None:
        import os
        from tools.fm20_scouted_attributes import ScoutedPlayer

        state = SimpleNamespace(module_base="0x140000000", game_date="2019-07-04", first_team_squad=())
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        player = ScoutedPlayer(row_id=7, player_id=42, name="P", age=21, person=0x5000, knowledge=15, observations={})
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), [])))
            stack.enter_context(mock.patch.object(feed, "_active_manager", return_value=manager))
            stack.enter_context(mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}))
            stack.enter_context(mock.patch.object(feed, "process_alive", return_value=True))
            stack.enter_context(mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999))
            stack.enter_context(mock.patch.object(feed, "capture_scouted_attributes", return_value=({42: player}, {})))
            stack.enter_context(mock.patch.object(
                feed, "read_raw_external_positions", side_effect=ScoutingFeedError("unreadable")))
            stack.enter_context(mock.patch.object(feed, "resolve_source_identity_facts", return_value={}))
            stack.enter_context(mock.patch.object(feed, "log_event"))

            document = feed.capture_pool(os.getpid(), remote_address=None)

        self.assertEqual(document["players"][0]["name"], "P")
        self.assertNotIn("rawPositions", document["players"][0])


class ScoutedListAlignmentTests(unittest.TestCase):
    """27 September 2026: the feed's counts had drifted from FM's own lists.

    Own-club reserves and youth were published as candidates (FM's Player
    Search leaves out the whole club, not just the first team), and every
    knowledge level counted as "scouted" where FM's Scouted list is the
    players with a report.
    """

    def _capture(self, scouted_players, *, own_club_members, prior=None):
        import os

        from tools.fm20_sandbox_queries import SandboxQueryError

        state = SimpleNamespace(module_base="0x140000000", game_date="2019-07-04", first_team_squad=())
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        records = {10: 0x1000, 11: 0x1100}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(feed, "_live_context", return_value=(state, (1, 2, 3), [10, 11])))
            stack.enter_context(mock.patch.object(feed, "_active_manager", return_value=manager))
            stack.enter_context(mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}))
            stack.enter_context(mock.patch.object(feed, "process_alive", return_value=True))
            stack.enter_context(mock.patch.object(feed, "_source_records", return_value=records))
            stack.enter_context(mock.patch.object(
                feed, "resolve_source_player_names", side_effect=lambda pid, wanted: {i: f"P{i}" for i in wanted}))
            stack.enter_context(mock.patch.object(feed, "read_raw_external_positions", return_value={}))
            stack.enter_context(mock.patch.object(feed, "read_raw_position_familiarity", return_value={}))
            stack.enter_context(mock.patch.object(feed, "resolve_source_identity_facts", return_value={}))
            stack.enter_context(mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999))
            stack.enter_context(mock.patch.object(
                feed, "capture_scouted_attributes", return_value=(scouted_players, {})))
            own = stack.enter_context(mock.patch.object(
                feed, "read_own_club_members", return_value=own_club_members))
            stack.enter_context(mock.patch.object(
                feed, "resolve_sandbox_context", side_effect=SandboxQueryError("not under test")))
            stack.enter_context(mock.patch.object(feed, "log_event"))
            document = feed.capture_pool(os.getpid(), remote_address=None, **(prior or {}))
        return document, own

    def test_everyone_contracted_to_the_managed_club_is_left_out(self) -> None:
        from tools.fm20_scouted_attributes import ScoutedPlayer

        own_youth = ScoutedPlayer(
            row_id=5, player_id=42, name="Own Youth", age=17, person=0x4200, knowledge=60,
            observations={}, has_report=True,
        )
        document, own = self._capture({42: own_youth}, own_club_members={11, 42})

        self.assertEqual([row["id"] for row in document["players"]], ["10"])
        self.assertEqual(document["source"]["excludedOwnContractedCount"], 1)
        # Checked against the managed club, for pool records and scouted players alike.
        pid, persons, club_id = own.call_args.args
        self.assertEqual(club_id, "c1")
        self.assertEqual(persons, {42: 0x4200, 10: 0x1000, 11: 0x1100})

    def test_scouted_means_a_report_and_a_dropped_player_keeps_his_last_answer(self) -> None:
        from tools.fm20_scouted_attributes import ScoutedPlayer

        reported = ScoutedPlayer(
            row_id=1, player_id=50, name="Reported", age=20, person=0x5000, knowledge=0,
            observations={}, has_report=True,
        )
        trialist = ScoutedPlayer(
            row_id=2, player_id=51, name="Trialist", age=20, person=0x5100, knowledge=45,
            observations={},
        )
        document, _own = self._capture(
            {50: reported, 51: trialist}, own_club_members=set(),
            prior={
                "prior_scouting_knowledge": {60: 30, 61: 30},
                "prior_scout_reports": {60},
                "prior_names": {60: "Gone Reported", 61: "Gone Known"},
            },
        )

        rows = {row["id"]: row for row in document["players"]}
        self.assertIs(rows["50"]["scoutReport"], True)
        self.assertIs(rows["51"]["scoutReport"], False)
        self.assertIs(rows["60"]["scoutReport"], True)
        self.assertIs(rows["61"]["scoutReport"], False)
        self.assertNotIn("scoutReport", rows["10"])
        # Who FM's Player Search lists this run, for every player: what keeps a
        # player who dropped off the scouting list under All players.
        self.assertEqual(
            {row_id: row["inPlayerSearch"] for row_id, row in rows.items()},
            {"10": True, "11": True, "50": False, "51": False, "60": False, "61": False},
        )


class PoolBuiltInSandboxTests(unittest.TestCase):
    """27 September 2026: the refresh builds Player Search's list itself, on a
    copy of FM's memory, so FM's own list (empty after every launch until the
    manager opens Player Search) is only the fallback."""

    def _capture(self, live_pool_ids, sandbox):
        import os

        state = SimpleNamespace(module_base="0x140000000", game_date="2019-07-04", first_team_squad=())
        manager = SimpleNamespace(id="m1", club=SimpleNamespace(id="c1", name="Example FC"))
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                feed, "_live_context", return_value=(state, (1, 2, 3), live_pool_ids)))
            stack.enter_context(mock.patch.object(feed, "_active_manager", return_value=manager))
            stack.enter_context(mock.patch.object(feed, "preflight", return_value={"moduleBase": "0x140000000"}))
            stack.enter_context(mock.patch.object(feed, "process_alive", return_value=True))
            live_records = stack.enter_context(mock.patch.object(
                feed, "_source_records", return_value={pid: 0x1000 + pid for pid in live_pool_ids}))
            stack.enter_context(mock.patch.object(
                feed, "resolve_source_player_names", side_effect=lambda pid, wanted: {i: f"P{i}" for i in wanted}))
            stack.enter_context(mock.patch.object(feed, "read_raw_external_positions", return_value={}))
            stack.enter_context(mock.patch.object(feed, "read_raw_position_familiarity", return_value={}))
            stack.enter_context(mock.patch.object(feed, "resolve_source_identity_facts", return_value={}))
            stack.enter_context(mock.patch.object(feed, "read_own_club_members", return_value=set()))
            stack.enter_context(mock.patch.object(feed, "_resolve_knowledge_context", return_value=0x999))
            stack.enter_context(mock.patch.object(feed, "capture_scouted_attributes", return_value=({}, {})))
            stack.enter_context(mock.patch.object(
                feed, "resolve_sandbox_context", side_effect=SandboxQueryError("not under test")))
            build = stack.enter_context(mock.patch.object(feed, "build_pool_in_sandbox", **sandbox))
            events = stack.enter_context(mock.patch.object(feed, "log_event"))
            document = feed.capture_pool(os.getpid(), remote_address=None)
        return document, build, live_records, events

    def test_an_unopened_player_search_no_longer_matters(self) -> None:
        document, build, live_records, events = self._capture(
            [], {"return_value": {10: 0x2010, 11: 0x2011}}
        )

        self.assertEqual(build.call_args.args[2], (1, 2, 3))
        self.assertEqual(sorted(row["id"] for row in document["players"]), ["10", "11"])
        self.assertTrue(document["source"]["poolAvailable"])
        self.assertTrue(document["source"]["poolBuiltInSandbox"])
        self.assertFalse(document["source"]["poolRebuiltByCapture"])
        self.assertEqual(document["source"]["transport"], "read-only-process-memory")
        live_records.assert_not_called()
        events.assert_any_call(
            "scouting_sandbox_pool_built", call_number=mock.ANY, pid=mock.ANY,
            pool_count=2, live_pool_count=0,
        )

    def test_the_sandbox_list_is_preferred_even_when_fm_has_its_own(self) -> None:
        # FM's own list is only as fresh as the last time Player Search was opened.
        document, _build, live_records, _events = self._capture(
            [10], {"return_value": {10: 0x2010, 12: 0x2012}}
        )

        self.assertEqual(sorted(row["id"] for row in document["players"]), ["10", "12"])
        live_records.assert_not_called()

    def test_a_failed_sandbox_build_falls_back_to_fms_own_list(self) -> None:
        document, _build, live_records, events = self._capture(
            [10, 11], {"side_effect": SandboxQueryError("builder stopped")}
        )

        self.assertEqual(sorted(row["id"] for row in document["players"]), ["10", "11"])
        self.assertFalse(document["source"]["poolBuiltInSandbox"])
        live_records.assert_called_once()
        events.assert_any_call(
            "scouting_sandbox_pool_failed", call_number=mock.ANY, pid=mock.ANY,
            exception_type="SandboxQueryError", exception="builder stopped", live_pool_count=2,
        )


class PositionFamiliarityFeedTests(unittest.TestCase):
    def test_ratings_are_stored_apart_from_the_verified_positions(self) -> None:
        document = feed_document(
            [10, 30], {10: "One", 30: "Two"}, game_date="2020-08-14",
            managed_club={"id": "club-1", "name": "Hungerford Town"},
            source_count=2, excluded_own_ids=[],
            raw_positions_by_id={10: ("DC",)},
            position_familiarity_by_id={10: {"DC": 17, "DR": 3}},
        )

        self.assertEqual(document["players"][0]["rawPositionFamiliarity"], {"DC": 17, "DR": 3})
        self.assertEqual(document["players"][0]["positions"], [])
        self.assertNotIn("rawPositionFamiliarity", document["players"][1])
        self.assertIn("individual position ratings for 1/2", document["source"]["fieldCoverage"]["positions"])

    def test_the_reader_keeps_all_fifteen_ratings_and_refuses_a_non_rating_array(self) -> None:
        import os
        from tools.fm20_linux_probe import POSITION_CODES

        good = bytes(range(len(POSITION_CODES)))
        noise = bytes([200] + [0] * (len(POSITION_CODES) - 1))
        reads = {0x1000 - 0x5C: good, 0x2000 - 0x5C: noise}
        with mock.patch.object(identity, "read_exact", side_effect=lambda fd, address, size: reads[address]):
            ratings = feed.read_raw_position_familiarity(os.getpid(), {1: 0x1000, 2: 0x2000})

        self.assertEqual(ratings, {1: dict(zip(POSITION_CODES, good))})



class NoPlayerIdTests(unittest.TestCase):
    def test_source_records_skip_a_player_fm_gave_no_id(self) -> None:
        import struct as _struct

        from tools.fm20_discoverability_cold_filter import _source_records

        memory = {
            (0x1000 + 0xD0, 16): _struct.pack("<QQ", 0x2000, 0x2010),
            (0x2000, 16): _struct.pack("<QQ", 0x3000, 0x3010),
            (0x3000, 8): _struct.pack("<Q", 0x4000),
            (0x3010, 8): _struct.pack("<Q", 0x4010),
            (0x4000 + 0xC, 4): _struct.pack("<i", 42),
            (0x4010 + 0xC, 4): _struct.pack("<i", -1),
        }
        records = _source_records(lambda address, size: memory[(address, size)], 0x1000)
        self.assertEqual(records, {42: 0x4000})
