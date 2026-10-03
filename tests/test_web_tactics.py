import html
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from fm_analytics.analytics import AXIS_DEFINITIONS, MVP_CATALOGUE
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
        self.assertIn("When possession has been lost</span><b>Regroup", section)
        self.assertIn("When possession has been won</span><b>Counter", section)
        self.assertIn("Goalkeeper in possession</span><b>Distribute Quickly", section)
        self.assertIn("Distribute To Flanks", section)
        self.assertIn("Take Long Kicks", section)
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
