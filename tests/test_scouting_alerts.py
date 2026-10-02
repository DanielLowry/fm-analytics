import unittest
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import ScoutingCandidate, build_scouting_alerts
from fm_analytics.analytics.scouting_candidate import CandidateHistory
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence import (
    KnowledgeCapture, PlayerKnowledge, PlayerKnowledgeStore, Verdict, VerdictRecord,
)
from fm_analytics.reporting import WeakSlot
from fm_analytics.web.scouting_render import scouting_alerts_panel
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer
from tests.web_support import FIXTURE, WebServerHelpers


def verdict(player_id: str, value: Verdict) -> VerdictRecord:
    return VerdictRecord("save:1", player_id, value, "", "2019-10-01")


def weak_slot() -> WeakSlot:
    return WeakSlot(
        "tactic", "Tactic <One>", "st", "ST", "af", "Forward",
        (("pace", 5.0), ("finishing", 5.0), ("flair", 1.0)),
        "starter", "Starter", 30.0, "Cover", 20.0, "Weak starter",
    )


class ScoutingAlertTests(unittest.TestCase):
    def test_rendered_alerts_escape_player_and_reason_text(self):
        from fm_analytics.analytics import ScoutingAlert, ScoutingAlerts

        body = scouting_alerts_panel(ScoutingAlerts(now_gettable=(
            ScoutingAlert("id/1", "<Player>", "became_free", "Free & clear"),
        )))

        self.assertIn("/scouting/player/id%2F1", body)
        self.assertIn("&lt;Player&gt;", body)
        self.assertIn("Free &amp; clear", body)
        self.assertNotIn("<Player>", body)

    def test_market_transitions_have_specific_reasons_and_no_previous_means_no_alert(self):
        players = (
            ScoutingCandidate("free", "Free", ("ST",), {}, has_contract=False),
            ScoutingCandidate("listed", "Listed", ("ST",), {}, transfer_status="transfer_listed"),
            ScoutingCandidate(
                "ending", "Ending", ("ST",), {}, has_contract=True,
                contract_end="2020-02-01", captured_game_date="2019-10-01",
            ),
            ScoutingCandidate("new", "New", ("ST",), {}, has_contract=False),
        )
        previous = {
            "free": {"has_contract": True, "observed_on": "2019-09-01"},
            "listed": {"transfer_status": None, "observed_on": "2019-09-01"},
            "ending": {"contract_end": "2021-01-01", "observed_on": "2019-09-01"},
        }

        alerts = build_scouting_alerts(players, previous, {}, ())

        self.assertEqual(
            [(item.player_id, item.reason_code) for item in alerts.now_gettable],
            [("free", "became_free"), ("listed", "became_listed"), ("ending", "contract_near_end")],
        )

    def test_continuous_gettable_and_reject_do_not_alert(self):
        players = (
            ScoutingCandidate("same", "Same", ("ST",), {}, has_contract=False),
            ScoutingCandidate("reject", "Reject", ("ST",), {}, has_contract=False),
        )
        previous = {
            "same": {"has_contract": False, "observed_on": "2019-09-01"},
            "reject": {"has_contract": True, "observed_on": "2019-09-01"},
        }
        alerts = build_scouting_alerts(
            players, previous, {"reject": verdict("reject", Verdict.REJECT)}, ()
        )
        self.assertEqual(alerts.now_gettable, ())

    def test_target_and_watch_keep_market_alerts_and_history_only_players_do_not(self):
        players = tuple(
            ScoutingCandidate(key, key, ("ST",), {}, has_contract=False)
            for key in ("target", "watch", "history")
        )
        players = (*players[:2], replace(players[2], history=CandidateHistory(
            "2019-10-01", False, "2019-04-01"
        )))
        alerts = build_scouting_alerts(
            players, {item.id: {"has_contract": True} for item in players},
            {"target": verdict("target", Verdict.TARGET), "watch": verdict("watch", Verdict.WATCH)}, (),
        )
        self.assertEqual([item.player_id for item in alerts.now_gettable], ["target", "watch"])

    def test_contract_window_crosses_without_changed_contract_facts(self):
        candidate = ScoutingCandidate(
            "ending", "Ending", ("ST",), {}, contract_end="2020-04-01",
            captured_game_date="2019-10-01",
        )
        prior = {"ending": {"contract_end": "2020-04-01", "observed_on": "2019-09-01"}}
        self.assertEqual(
            build_scouting_alerts((candidate,), prior, {}, ()).now_gettable[0].reason_code,
            "contract_near_end",
        )
        self.assertEqual(
            build_scouting_alerts((candidate,), prior, {}, (), near_contract_months=3).now_gettable, ()
        )

    def test_stale_cutoff_and_unknown_important_attributes_are_respected(self):
        candidate = ScoutingCandidate("watch", "Watch", ("ST",), {
            "pace": AttributeObservation(Visibility.UNKNOWN),
            "finishing": AttributeObservation(Visibility.KNOWN, value=12),
        }, history=CandidateHistory(
            "2019-10-01", True, "2019-04-01", profile_last_seen_on="2019-04-01"
        ))
        watches = {"watch": verdict("watch", Verdict.WATCH)}
        alerts = build_scouting_alerts((candidate,), {}, watches, (weak_slot(),))
        self.assertEqual([item.reason_code for item in alerts.rescout_due], ["weak_role_missing"])
        self.assertEqual(alerts.rescout_due[0].attributes, ("pace",))
        stricter = replace(candidate, history=replace(candidate.history, out_of_date_before="2019-07-01"))
        self.assertEqual(
            build_scouting_alerts((stricter,), {}, watches, ()).rescout_due[0].reason_code, "stale"
        )

    def test_watch_is_due_only_for_stale_or_important_missing_information(self):
        stale = ScoutingCandidate(
            "stale", "Stale", ("DC",), {}, history=CandidateHistory(
                "2019-10-01", True, "2019-04-01", profile_last_seen_on="2019-03-01"
            )
        )
        missing = ScoutingCandidate(
            "missing", "Missing", ("ST",),
            {"flair": AttributeObservation(Visibility.UNKNOWN)},
        )
        complete = ScoutingCandidate(
            "complete", "Complete", ("ST",), {
                "pace": AttributeObservation(Visibility.KNOWN, value=12),
                "finishing": AttributeObservation(Visibility.RANGE, minimum=10, maximum=14),
                "flair": AttributeObservation(Visibility.UNKNOWN),
            }
        )
        watches = {item.id: verdict(item.id, Verdict.WATCH) for item in (stale, missing, complete)}

        alerts = build_scouting_alerts((stale, missing, complete), {}, watches, (weak_slot(),))

        self.assertEqual(
            [(item.player_id, item.reason_code) for item in alerts.rescout_due],
            [("stale", "stale"), ("missing", "weak_role_missing")],
        )
        self.assertEqual(alerts.rescout_due[1].attributes, ("pace", "finishing"))


class ScoutingAlertPageTests(WebServerHelpers, unittest.TestCase):
    def test_refresh_updates_alerts_and_later_unchanged_sightings_clear_the_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PlayerKnowledgeStore(Path(directory) / "knowledge.sqlite3")
            store.record(KnowledgeCapture("save:1", "2019-09-01", "first", (
                PlayerKnowledge("known", "Known Striker", {"has_contract": True}),
            )))
            current = [ScoutingCandidate(
                "known", "Known Striker", ("ST",), {}, has_contract=True,
                captured_game_date="2019-09-01",
            )]

            def refresh(**_kwargs):
                current[0] = replace(current[0], has_contract=False, captured_game_date="2019-10-01")
                return "captured"

            def record():
                item = current[0]
                return store.record(KnowledgeCapture("save:1", item.captured_game_date, "capture", (
                    PlayerKnowledge(item.id, item.name, {"has_contract": item.has_contract}),
                )))

            server = SquadWebServer(
                ("127.0.0.1", 0), fixture_provider(FIXTURE),
                scouting_provider=lambda: tuple(current), scouting_refresh=refresh,
                knowledge_store=store, knowledge_save_key="save:1", knowledge_recorder=record,
            )
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            port = server.server_address[1]
            self._post(port, "/scouting/refresh")
            for _ in range(100):
                if server.scouting_refresh_job.status != "running":
                    break
                time.sleep(0.01)
            status, page = self._get(port, "/scouting")
            self.assertEqual(status, 200)
            self.assertIn("Became a free agent", page)
            self.assertIn("/scouting/player/known", page)

            current[0] = replace(current[0], captured_game_date="2019-10-02")
            server.record_knowledge()
            _, page = self._get(port, "/scouting")
            self.assertNotIn("Became a free agent", page)
            self.assertIn("No new gettable players or re-scout reminders", page)


if __name__ == "__main__":
    unittest.main()
