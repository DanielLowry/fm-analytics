import subprocess
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.fm20_league_inventory import capture_inventory, inventory, read_roster_ids
from tools.fm20_research import _adapter_command, _adapter_passed, plan_recipe


class LeagueInventoryTests(unittest.TestCase):
    def setUp(self):
        self.memory = Mock(fd=7, module_base=0x140000000)
        self.rows = {
            1: dict(home_team=1, away_team=2, fixture_name=10, date=date(2019, 9, 1)),
            2: dict(home_team=2, away_team=1, fixture_name=10, date=date(2019, 9, 3)),
        }
        self.markers = SimpleNamespace(game_date="2019-09-04", manager_id="manager-1", club_id="1")
        self.clubs = lambda _fd, team: SimpleNamespace(id=str(team), name=f"Club {team}")

    def read(self, roster_reader=None):
        with (
            patch("tools.fm20_league_inventory.first_team_address", return_value=1),
            patch("tools.fm20_league_inventory.played_results", return_value=self.rows),
            patch("tools.fm20_league_inventory.competition", return_value={"id": "148", "name": "League"}),
            patch("tools.fm20_match_probe.probe.read_club_from_team", side_effect=self.clubs),
            patch("tools.fm20_league_inventory.read_roster_ids",
                  side_effect=roster_reader or (lambda memory, team: (f"player-{team}",))),
        ):
            return inventory(self.memory)

    def test_stable_roster_ids_are_research_evidence_without_completeness_claims(self):
        report = self.read()
        self.assertTrue(report["researchOnly"])
        self.assertTrue(report["stable"])
        self.assertEqual(report["rostersRead"], 2)
        self.assertFalse(report["membershipComplete"])
        self.assertFalse(report["rosterVisibilityVerified"])
        self.assertFalse(report["positionsVisibilityVerified"])
        league, = report["leagues"]
        self.assertFalse(league["membershipComplete"])
        self.assertEqual([team["playerIds"] for team in league["teams"]],
                         [["player-1"], ["player-2"]])

    def test_identity_reader_does_not_use_owned_squad_field_reader(self):
        with (
            patch("tools.fm20_league_inventory.probe.read_first_team_ids", return_value={"2", "1"}) as ids,
            patch("tools.fm20_league_inventory.probe._read_team_squad_players") as full,
        ):
            self.assertEqual(read_roster_ids(self.memory, 2), ("1", "2"))
        ids.assert_called_once_with(7, 0x140000000, 2)
        full.assert_not_called()

    def test_a_same_date_rival_roster_change_is_detected(self):
        seen = {1: 0, 2: 0}

        def changing(memory, team):
            seen[team] += 1
            return ("new-player",) if team == 2 and seen[team] > 1 else (f"player-{team}",)

        self.assertFalse(self.read(changing)["stable"])

    def test_one_unreadable_roster_keeps_the_other_and_records_the_gap(self):
        def incomplete(memory, team):
            if team == 2:
                raise OSError("cannot read vector")
            return ("player-1",)

        report = self.read(incomplete)
        self.assertEqual(report["rostersRead"], 1)
        self.assertEqual(report["errors"][0]["club"]["id"], "2")
        self.assertIsNone(report["leagues"][0]["teams"][1]["playerIds"])

    def test_preseason_without_played_results_does_not_invent_membership(self):
        self.rows = {}
        report = self.read()
        self.assertEqual(report["candidateLeagueCount"], 0)
        self.assertFalse(report["membershipComplete"])

    def test_capture_detects_changed_manager_or_date_and_closes_memory(self):
        for second in (self.markers, SimpleNamespace(game_date="2019-09-05", manager_id="manager-1", club_id="1")):
            with (
                patch("tools.fm20_league_inventory.snapshot_marker", side_effect=(self.markers, second)),
                patch("tools.fm20_league_inventory.Memory", return_value=self.memory),
                patch("tools.fm20_league_inventory.inventory", return_value={"stable": True}),
            ):
                result = capture_inventory(123)
            self.assertEqual(result["stable"], second == self.markers)
            self.memory.close.assert_called()

    def test_controller_recipe_uses_only_read_only_adapter_and_refuses_promoted_claims(self):
        recipe, plan = plan_recipe("league-roster-inventory")
        self.assertEqual(plan["safety"], "passive-live")
        self.assertEqual(plan["operator_interaction"], "none")
        command = _adapter_command(recipe, 123, Path("/games/fm.exe"), "0x140000000", Path("/tmp/report.json"))
        self.assertTrue(command[1].endswith("fm20_league_inventory.py"))
        self.assertNotIn("--remote-address", command)
        report = {"status": "complete", "researchOnly": True, "stable": True, "rostersRead": 22,
                  "membershipComplete": False, "rosterVisibilityVerified": False,
                  "positionsVisibilityVerified": False}
        completed = subprocess.CompletedProcess(command, 0)
        self.assertTrue(_adapter_passed(recipe, completed, report)[0])
        for change in ({"stable": False}, {"rostersRead": 0}, {"membershipComplete": True},
                       {"rosterVisibilityVerified": True}, {"positionsVisibilityVerified": True}):
            self.assertFalse(_adapter_passed(recipe, completed, {**report, **change})[0])


if __name__ == "__main__":
    unittest.main()
