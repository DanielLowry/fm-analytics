import html
import json
import re
import tempfile
import threading
import unittest
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from fm_analytics.analytics import AXIS_DEFINITIONS, MVP_CATALOGUE
from fm_analytics.analytics.player_form import FormLookup, FormPolicy, FormRating, JobForm
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.rendering import (
    _slot_reasoning,
)
from fm_analytics.web.server import SquadWebServer
from tests.web_support import write_complete_fixture


class TacticsAndDepthPageTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.fixture_path = write_complete_fixture(Path(directory.name))
        server = SquadWebServer(("127.0.0.1", 0), fixture_provider(self.fixture_path))
        self.server = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        self.port = server.server_address[1]

    def _get(self, path: str) -> tuple[int, str]:
        connection = HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, body

    def test_tactics_overview_is_compact_and_links_to_drill_down(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        self.assertIn("Recommended for today", body)
        self.assertIn("Key issue", body)
        self.assertIn("View tactic", body)
        self.assertNotIn("Starting XI", body)
        self.assertNotIn("Matchday bench", body)
        # Owned players' attributes are exact, so scores collapse to one number.
        self.assertNotIn(" / ", body.split("Compare tactics")[1].split("</table>")[0])

    def test_tactics_page_renders_every_opponent_slider(self) -> None:
        status, body = self._get("/tactics")
        self.assertEqual(status, 200)
        self.assertIn("Opponent profile", body)
        self.assertIn("name='opp_formation'", body)
        self.assertIn(">4-4-2</option>", body)
        self.assertEqual(body.count("type='range'"), len(AXIS_DEFINITIONS))
        for axis in AXIS_DEFINITIONS:
            self.assertIn(f"name='opp_{axis.key}'", body)
            self.assertIn(html.escape(axis.label), body)
        self.assertIn("min='-2' max='2' step='1' value='0'", body)

    def test_opponent_profile_shows_neutral_deltas_and_survives_drill_down(self) -> None:
        query = "opp_formation=442&opp_chance_creation=2&opp_dribbling_quality=-2&opp_finishing_quality=-1&opp_pos_DR=2&opp_attr_leadership=-1"
        status, body = self._get(f"/tactics?{query}")
        self.assertEqual(status, 200)
        self.assertIn("Active opponent assumptions", body)
        for expected in ("Likely formation: 4-4-2", "Chance creation: Creates many chances", "Dribbling: Poor dribblers", "Finishing: Leans wasteful finishers"):
            self.assertIn(expected, body)
        self.assertIn("Strong positions: Right-back", body)
        self.assertIn("Attribute weaknesses: Leadership", body)
        self.assertIn("Change vs neutral", body)
        self.assertIn("Opponent fit", body)
        self.assertIn("Recommended for this opponent", body)
        escaped_query = "opp_formation=442&amp;opp_chance_creation=2&amp;opp_dribbling_quality=-2&amp;opp_finishing_quality=-1&amp;opp_pos_DR=2&amp;opp_attr_leadership=-1"
        self.assertIn(escaped_query, body)
        status, detail = self._get(f"/tactics/balanced_442?{query}")
        self.assertEqual(status, 200)
        self.assertIn("Opponent profile:", detail)
        self.assertIn("Opponent fit", detail)
        self.assertIn(f"href='/tactics?{escaped_query}'", detail)
        self.assertEqual(detail.count("type='range'"), len(AXIS_DEFINITIONS))
        self.assertIn("action='/tactics/balanced_442'", detail)
        self.assertIn(
            "href='/tactics/balanced_442'>Reset to neutral</a>", detail
        )
        status, aerial_only = self._get("/tactics?opp_aerial_threat=2")

        self.assertEqual(status, 200)
        self.assertIn("Player emphasis only; no system check", aerial_only)

    def test_invalid_opponent_slider_is_a_bad_request(self) -> None:
        status, body = self._get("/tactics?opp_quality=3")

        self.assertEqual(status, 400)
        self.assertIn("between -2 and 2", body)

    def test_tactic_detail_explains_each_selection_and_score_layer(self) -> None:
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        self.assertEqual(body.count("Why Player"), 11)
        self.assertIn("attribute-based", body)
        self.assertIn("in-position", body)
        self.assertIn("readiness", body)
        self.assertIn("other ten slots are", body)
        self.assertIn("Tactic score", body)
        self.assertIn("Player scores", body)
        self.assertIn("Score details", body)
        self.assertIn("if every player score rises by 2%", body)
        self.assertIn("tactic-balance factor", body)

    def test_starting_xi_copy_contains_every_displayed_starter_and_selected_job(self) -> None:
        status, body = self._get("/tactics/balanced_442")
        self.assertEqual(status, 200)
        self.assertIn("Copy starting XI attributes to clipboard", body)
        text = json.loads(re.search(r"data-player-copy-text>(.*?)</script>", body, re.S).group(1))
        report = self.server.tactic_report("balanced_442")
        game, squad = self.server.read()
        self.assertIn(f"Game date: {game.game_date.isoformat()}", text)
        self.assertIn(f"Tactic: {report.evaluation.tactic.name}", text)
        self.assertIn("Starting XI: 11 / 11", text)
        self.assertEqual(text.count("\nName: "), 11)
        for assignment in report.evaluation.assignments:
            role, duty = assignment.intrinsic_role_score.role_name.rsplit(" (", 1)
            self.assertIn(
                f"Slot: {assignment.slot.key}\nPosition: {assignment.slot.position}\n"
                f"Role: {role}\nDuty: {duty.removesuffix(')')}\nName: {assignment.player_name}", text,
            )
        self.assertEqual(text.count(f"Club: {squad.club.name}"), 11)
        self.assertEqual(text.count("\nPhysical\n"), 11)
        self.assertEqual(text.count("\nMental\n"), 11)
        self.assertIn("\nGoalkeeping\n", text)
        self.assertIn("Long Throws: ?", text)

    def test_all_four_selection_modes_reoptimize_the_xi_and_clipboard(self) -> None:
        game, squad = load_fixture(self.fixture_path)
        original = squad.players[0]
        keepers = tuple(replace(
            original, id=key, name="Keeper " + key, positions=("GK",), availability="available",
            condition_percent=100 if key in ("A", "B") else 60, match_fitness_percent=100,
            injured=False, suspended=False, position_familiarity={"GK": 20},
            attributes={key_name: AttributeObservation(Visibility.KNOWN,
                value=(12 if key in ("A", "B") else 13) + int(key_name == "handling" and key in ("B", "D")))
                for key_name in original.attributes},
        ) for key in ("A", "B", "C", "D"))
        squad = replace(squad, players=keepers + squad.players[1:])
        self.fixture_path.write_text(json.dumps({"game": game.to_dict(), "squad": squad.to_dict()}))
        before = self.fixture_path.read_bytes()
        rating = FormRating("test-match", game.game_date, "Opponent", 7.0, 90, 1.0)
        jobs = {(player.id, "balanced_442", "GK", role): JobForm(
            player.id, player.name, "balanced_442", "GK", role, (rating,), 7.0, 1.0,
            1.03 if player.id in ("A", "C") else .97,
        ) for player in keepers for role, definition in MVP_CATALOGUE.roles.items() if "GK" in definition.eligible_positions}
        form = FormLookup(FormPolicy(), game.game_date, jobs)
        self.enterContext(patch.object(self.server, "recent_form", return_value=form))
        reports = []
        for ignore_form, ignore_condition, expected in ((False, False, "A"), (True, False, "B"),
                                                       (False, True, "C"), (True, True, "D")):
            with self.subTest(ignore_form=ignore_form, ignore_condition=ignore_condition):
                query = f"?ignoreForm={int(ignore_form)}&ignoreCondition={int(ignore_condition)}"
                status, body = self._get("/tactics/balanced_442" + query)
                self.assertEqual(status, 200)
                options = {"ignore_form": ignore_form, "ignore_condition": ignore_condition}
                report = self.server.tactic_report("balanced_442", **options)
                reports.append(report)
                keeper = next(item for item in report.evaluation.assignments if item.slot.position == "GK")
                self.assertEqual(keeper.player_id, expected)
                row = re.findall(r"<tr class='fm-xi-row'>(.*?)</tr>", body, re.S)[0]
                self.assertIn("Keeper " + expected, row)
                text = json.loads(re.search(r"data-player-copy-text>(.*?)</script>", body, re.S).group(1))
                self.assertIn("Name: Keeper " + expected, text)
                self.assertEqual(text.count("\nName: "), 11)
                for other in {"A", "B", "C", "D"} - {expected}:
                    self.assertNotIn("Name: Keeper " + other, text)
                controls = re.search(r"data-xi-options>(.*?)</form>", body, re.S).group(1)
                for name, active in (("ignoreForm", ignore_form), ("ignoreCondition", ignore_condition)):
                    self.assertIn(f"name='{name}' value='1'" + (" checked" if active else "") + ">", controls)
                ignored = [label for label, active in (("form", ignore_form), ("condition", ignore_condition)) if active]
                if ignored:
                    self.assertIn("Ignored during selection: " + ", ".join(ignored), text)
                if ignore_form:
                    self.assertEqual(keeper.form_multiplier, 1.0)
                    self.assertIn("Recent form is ignored for this XI", body)
                    self.assertIsNone(self.server.bundle(**options).form)
                if ignore_condition:
                    self.assertEqual(keeper.readiness_penalty, 0)
                    self.assertIn("match fitness only", body)
        self.assertEqual(len({id(report) for report in reports}), 4)
        self.assertIs(self.server.tactic_report("balanced_442"), reports[0])
        self.assertEqual(self.fixture_path.read_bytes(), before)
        self.assertEqual(self.server.read()[1].players[2].condition_percent, 60)

    def test_selection_switches_survive_opponent_forms_and_tactic_navigation(self) -> None:
        query = "opp_aerial_threat=2&ignoreForm=1&ignoreCondition=1"
        for path in ("/tactics", "/tactics/balanced_442"):
            status, body = self._get(path + "?" + query)
            self.assertEqual(status, 200)
            self.assertIn("opp_aerial_threat=2&amp;ignoreForm=1&amp;ignoreCondition=1", body)
            controls = re.search(r"data-xi-options>(.*?)</form>", body, re.S).group(1)
            self.assertIn("type='hidden' name='opp_aerial_threat' value='2'", controls)
            opponent_form = re.search(r"<form class='opponent-form'.*?</form>", body, re.S).group(0)
            self.assertIn("type='hidden' name='ignoreForm' value='1'", opponent_form)
            self.assertIn("type='hidden' name='ignoreCondition' value='1'", opponent_form)
            self.assertIn(f"href='{path}?ignoreForm=1&amp;ignoreCondition=1'>Reset to neutral", body)

    def test_excluding_a_player_repicks_this_xi_and_each_can_be_restored(self) -> None:
        game, squad = load_fixture(self.fixture_path)
        starter = squad.players[0]
        backup = replace(starter, id="backup", name="Backup Keeper", attributes={
            key: AttributeObservation(Visibility.KNOWN, value=9) for key in starter.attributes
        })
        squad = replace(squad, players=squad.players + (backup,))
        self.fixture_path.write_text(json.dumps({"game": game.to_dict(), "squad": squad.to_dict()}))

        status, full = self._get("/tactics/balanced_442?ignoreForm=1")
        self.assertEqual(status, 200)
        self.assertNotIn("fm-xi-excluded", full)
        self.assertIn(
            "href='/tactics/balanced_442?ignoreForm=1&amp;exclude=player-1#starting-xi' data-xi-exclusion", full
        )
        self.assertIn("href='/tactics/balanced_442?ignoreForm=1&amp;exclude=backup#matchday-bench'", full)

        # A player no longer in the squad is dropped rather than failing the page.
        status, body = self._get("/tactics/balanced_442?ignoreForm=1&exclude=player-1,nobody")
        self.assertEqual(status, 200)
        xi = "".join(re.findall(r"<tr class='fm-xi-row'>(.*?)</tr>", body, re.S))
        self.assertNotIn("/squad/player/player-1'", xi)
        self.assertIn("Backup Keeper</a><small class='fm-xi-in-for'>in for Player 1</small>", xi)
        self.assertIn("Selection comparison", body)
        self.assertIn("Excluded (1)", body)
        restore = "href='/tactics/balanced_442?ignoreForm=1#starting-xi' data-xi-exclusion"
        self.assertIn(restore + " aria-label='Restore Player 1'>Restore</a>", body)
        self.assertIn(restore + ">Restore all</a>", body)
        self.assertIn(
            "href='/tactics/balanced_442?ignoreForm=1&amp;exclude=player-1,player-2#starting-xi'", body
        )
        report = self.server.tactic_report("balanced_442", ignore_form=True, excluded_player_ids=frozenset({"player-1"}))
        full_score = self.server.tactic_report("balanced_442", ignore_form=True).evaluation.score.central
        self.assertIn(
            f"Tactic score <b>{report.evaluation.score.central:.1f}</b> without them "
            f"({report.evaluation.score.central - full_score:+.1f} against the full-squad XI)", body,
        )
        text = json.loads(re.search(r"data-player-copy-text>(.*?)</script>", body, re.S).group(1))
        self.assertIn("Excluded players: Player 1\n", text)
        self.assertNotIn("Name: Player 1\n", text)
        # Toggling form/condition or the opponent keeps the exclusion; leaving the tactic drops it.
        hidden = "type='hidden' name='exclude' value='player-1'"
        self.assertIn(hidden, re.search(r"data-xi-options>(.*?)</form>", body, re.S).group(1))
        self.assertIn(hidden, re.search(r"<form class='opponent-form'.*?</form>", body, re.S).group(0))
        self.assertIn("href='/tactics?ignoreForm=1'>← All tactics", body)

        status, both = self._get("/tactics/balanced_442?exclude=player-1,backup")
        self.assertEqual(status, 200)
        self.assertIn("Excluded (2)", both)
        self.assertIn("href='/tactics/balanced_442?exclude=backup#starting-xi' data-xi-exclusion aria-label='Restore Player 1'", both)
        self.assertIn("href='/tactics/balanced_442?exclude=player-1#starting-xi' data-xi-exclusion aria-label='Restore Backup Keeper'", both)
        self.assertIn("href='/tactics/balanced_442#starting-xi' data-xi-exclusion>Restore all", both)
        self.assertIn("Unfilled: GK", both)

    def test_invalid_selection_switches_are_rejected(self) -> None:
        for path in ("/tactics", "/tactics/balanced_442"):
            for parameter in ("ignoreForm", "ignoreCondition"):
                status, body = self._get(path + "?" + parameter + "=unexpected")
                self.assertEqual(status, 400)
                self.assertIn("must be 0 or 1", body)

    def test_tactic_checks_page_lists_player_independent_failures(self) -> None:
        status, body = self._get("/tactic-checks")

        self.assertEqual(status, 200)
        self.assertIn("Experimental, player-independent checks", body)
        self.assertIn("does affect tactic rankings", body)
        self.assertIn("Fluid Counter 4-1-4-1", body)
        self.assertIn("Failing combination", body)
        self.assertIn("Forward threat: roles provide 1.4; standard is 1.5", body)

    def test_tactic_detail_warns_when_its_selected_roles_fail_a_check(self) -> None:
        evaluation = next(
            item
            for item in self.server.bundle().recommendation.evaluations
            if item.coherence.shortfalls or item.instruction_suitability.shortfalls
        )

        status, body = self._get(f"/tactics/{evaluation.tactic.key}")

        self.assertEqual(status, 200)
        self.assertIn("Selected roles miss a structural check", body)
        self.assertIn("reduces the tactic-balance factor", body)
        self.assertIn(f"/tactic-checks#{evaluation.tactic.key}", body)

    def test_tactic_detail_justifies_the_shape_and_every_slot(self) -> None:
        tactic = MVP_CATALOGUE.tactics["balanced_442"]
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        self.assertIn("Why this shape:", body)
        self.assertIn("When to use it:", body)
        self.assertIn("When to avoid it:", body)
        self.assertIn("Why these instructions", body)
        self.assertEqual(body.count("Why this role here:"), 11)
        for slot in tactic.slots:
            self.assertIn(html.escape(slot.why), body)

    def test_tactic_detail_flags_missing_in_possession_settings(self) -> None:
        # lowblock_442 has not been given an inPossession block yet.
        status, body = self._get("/tactics/lowblock_442")

        self.assertEqual(status, 200)
        self.assertIn("In possession", body)
        self.assertIn("Not yet set:", body)
        self.assertIn("Not set</b>", body)

    def test_tactic_detail_shows_specified_in_possession_settings(self) -> None:
        for key in ("vertical_442", "balanced_442", "attacking_424"):
            with self.subTest(key=key):
                tactic = MVP_CATALOGUE.tactics[key]
                self.assertEqual(tactic.in_possession_missing_fields, ())
                status, body = self._get(f"/tactics/{key}")

                self.assertEqual(status, 200)
                self.assertNotIn("Not yet set:", body)
                self.assertIn("Every fixed in-possession setting is specified.", body)
                self.assertIn(html.escape(tactic.in_possession.attacking_width), body)
                self.assertEqual(tactic.in_transition_missing_fields, ())
                self.assertEqual(tactic.out_of_possession_missing_fields, ())
                self.assertIn("Every in-transition setting is specified.", body)
                self.assertIn("Every out-of-possession setting is specified.", body)
                self.assertNotIn("Not set</b>", body)

    def test_tactic_detail_says_which_attributes_the_tactic_leans_on(self) -> None:
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        self.assertIn("Leans on:", body)
        # Rendered for a manager, not as the JSON key.
        self.assertIn("off the ball +2", body)
        self.assertNotIn("offTheBall", body)

    def test_tactic_detail_shows_transition_choices_and_distribution(self) -> None:
        status, body = self._get("/tactics/vertical_442")
        self.assertEqual(status, 200)
        section = body.split("<section class='in-transition-section'>", 1)[1].split("</section>", 1)[0]
        for selected in ("Regroup", "Counter", "Distribute quickly", "Distribute to flanks", "Take long kicks"):
            self.assertIn(f"<span>{selected}</span><b>Selected</b>", section)
        self.assertIn(
            "<span>Counter-press</span><b>Unavailable</b><small>Regroup is selected</small>", section
        )
        self.assertIn(
            "<span>Distribute to full backs</span><b>Unavailable</b>"
            "<small>Distribute To Flanks is selected</small>", section,
        )
        self.assertEqual(section.count("<b>Selected</b>"), 5)
        self.assertEqual(section.count("<b>Unavailable</b>"), 11)
        self.assertIn("Every in-transition setting is specified.", section)

    def test_tactic_detail_shows_complete_defensive_settings(self) -> None:
        status, body = self._get("/tactics/vertical_442")
        self.assertEqual(status, 200)
        section = body.split("<section class='out-of-possession-section'>", 1)[1].split("</section>", 1)[0]
        self.assertIn("Line of engagement</span><b>Standard", section)
        self.assertIn("Defensive line</span><b>Standard", section)
        self.assertIn("Use tighter marking</span><b>Neutral", section)
        self.assertIn("Pressing intensity</span><b>Standard", section)
        self.assertIn("Prevent short GK distribution</span><b>No", section)
        self.assertIn("Every out-of-possession setting is specified.", section)

    def test_tactic_detail_labels_an_introduced_role_requirement(self) -> None:
        status, body = self._get("/tactics/pressing_442")

        self.assertEqual(status, 200)
        self.assertIn("aggression +1", body)
        self.assertIn("new requirement", body)

    def test_tactics_overview_hints_when_each_tactic_suits(self) -> None:
        status, body = self._get("/tactics")

        self.assertEqual(status, 200)
        for tactic in MVP_CATALOGUE.tactics.values():
            self.assertIn(html.escape(tactic.when_to_use), body)

    def test_an_alternate_role_choice_does_not_borrow_the_default_roles_reasoning(self) -> None:
        slot = MVP_CATALOGUE.tactics["balanced_442"].slots[-1]
        default = _slot_reasoning(slot, slot.role_key, "Advanced Forward (Attack)")
        alternate = _slot_reasoning(slot, slot.alternate_role_keys[0], "Poacher (Attack)")

        self.assertNotIn("suits", default)
        self.assertIn("Your squad suits Poacher (Attack)", alternate)
        self.assertIn(html.escape(slot.why), alternate)

    def test_xi_rows_follow_formation_order_from_goalkeeper_to_attack(self) -> None:
        status, body = self._get("/tactics/balanced_442")

        self.assertEqual(status, 200)
        assignment_table = body.split("<h2>Starting XI</h2>", 1)[1].split(
            "<h2>Matchday bench</h2>", 1
        )[0]
        self.assertLess(
            assignment_table.index("<td>GK</td>"),
            assignment_table.index("<td>ST</td>"),
        )

    def test_depth_page_leads_with_conclusions_and_a_compact_table(self) -> None:
        status, body = self._get("/depth")

        self.assertEqual(status, 200)
        self.assertIn("Conclusions", body)
        self.assertIn("By position", body)
        # No per-weakness sentence dump: reasons are short kind codes.
        self.assertNotIn("is below the starter role-fit threshold", body)
