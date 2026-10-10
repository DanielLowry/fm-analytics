import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import required_role_attributes
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "src/fm_analytics/fixtures/sample-game.json"
CAPTURE = ROOT / "tests/fixtures/hungerford-vertical-442-2020-10-20.json"


def _complete_fixture(directory: Path) -> Path:
    game, squad = load_fixture(FIXTURE)
    original = squad.players[0]
    required = required_role_attributes()
    players = tuple(
        replace(
            original,
            id=f"player-{index}",
            name=f"Player {index}",
            positions=(slot.position,),
            attributes={
                name: AttributeObservation(Visibility.KNOWN, value=10)
                for name in required
            },
        )
        for index, slot in enumerate(
            MVP_CATALOGUE.tactics["balanced_442"].slots, start=1
        )
    )
    path = directory / "complete.json"
    path.write_text(
        json.dumps({"game": game.to_dict(), "squad": replace(squad, players=players).to_dict()}),
        encoding="utf-8",
    )
    return path


class SetPiecePageTests(unittest.TestCase):
    def _serve(self, fixture_path: Path) -> int:
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(fixture_path),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server.server_address[1]

    def _get(self, port: int, path: str) -> tuple[int, str]:
        connection = HTTPConnection("127.0.0.1", port)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, body

    def test_partial_data_builds_a_squad_wide_plan(self) -> None:
        status, body = self._get(self._serve(FIXTURE), "/set-pieces")

        self.assertEqual(status, 200)
        self.assertIn("Left-side Corners (prefer Right foot)", body)
        self.assertIn("Free Kick Taking is not captured", body)
        self.assertIn("Long throws", body)
        self.assertIn("Match-day assignments", body)
        self.assertIn("Direct (small chance of shot)", body)
        self.assertIn("Indirect (wide)", body)
        self.assertIn("Indirect (deep)", body)
        self.assertIn("Routines", body)
        self.assertIn("Incomplete role data", body)
        self.assertIn("provisional squad-wide plan", body)
        self.assertIn("Chris Centreback", body)
        self.assertIn("Provisional — dedicated taker evidence is missing", body)
        self.assertNotIn("No rated taker", body)
        self.assertIn("id='selected-routine'>Left attacking corner", body)
        self.assertNotIn("id='selected-routine'>Right attacking corner", body)

    def test_routine_selector_renders_only_the_requested_plan(self) -> None:
        port = self._serve(FIXTURE)
        status, body = self._get(
            port,
            "/set-pieces?routine=defending_wide_free_kick&delivery=outswinging&risk=secure",
        )

        self.assertEqual(status, 200)
        self.assertIn(
            "id='selected-routine'>Defending indirect free kicks (wide)", body
        )
        self.assertNotIn("id='selected-routine'>Left attacking corner", body)
        self.assertIn("routine=defending_corner", body)
        self.assertIn("delivery=outswinging", body)
        self.assertIn("risk=secure", body)

    def test_unknown_routine_falls_back_to_left_attacking_corner(self) -> None:
        status, body = self._get(
            self._serve(FIXTURE), "/set-pieces?routine=not-a-routine"
        )

        self.assertEqual(status, 200)
        self.assertIn("id='selected-routine'>Left attacking corner", body)

    def test_defending_corner_uses_the_fm_instruction_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            port = self._serve(_complete_fixture(Path(directory)))
            status, body = self._get(
                port,
                "/set-pieces?tactic=balanced_442&routine=defending_corner",
            )

        self.assertEqual(status, 200)
        for instruction in (
            "Mark near post",
            "Mark far post",
            "Zonally mark 6 yard box near post",
            "Zonally mark 6 yard box centre",
            "Zonally mark 6 yard box far post",
            "Go back",
            "Man mark",
            "Mark tall player",
            "Edge of area",
            "Stay forward",
        ):
            self.assertIn(instruction, body)
        self.assertNotIn("Close down short", body)
        self.assertNotIn("Mark edge of area", body)
        self.assertEqual(body.count("class='routine-assignment-note'"), 11)
        self.assertIn("Strongest visible inputs", body)
        self.assertIn("every player can fill only one job", body)

    def test_captured_xi_displays_revised_corner_assignments_and_responsibility_weights(self) -> None:
        status, body = self._get(
            self._serve(CAPTURE),
            "/set-pieces?tactic=vertical_442&routine=defending_corner",
        )

        self.assertEqual(status, 200)
        self.assertIn("Vertical 4-4-2 match XI", body)
        # Check the actual assignment cards, rather than names appearing
        # elsewhere in specialist rankings or the explanation table.
        self.assertIn("<b>Ejiro Okosieme</b><span><strong>Mark tall player</strong>", body)
        self.assertIn("<b>Jamie Bradley-Green</b><span><strong>Zonally mark 6 yard box near post</strong>", body)
        self.assertIn("<b>Ross Holden</b><span><strong>Mark near post</strong>", body)
        self.assertIn("<b>Terrance Saydee</b><span><strong>Mark far post</strong>", body)
        self.assertIn("<dt>Responsibility weight</dt><dd>1.5×</dd>", body)
        self.assertIn("<dt>Responsibility weight</dt><dd>0.7×</dd>", body)
        self.assertEqual(body.count("class='routine-assignment-note'"), 11)

    def test_defending_free_kick_uses_the_fm_instruction_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            port = self._serve(_complete_fixture(Path(directory)))
            status, body = self._get(
                port,
                "/set-pieces?tactic=balanced_442&routine=defending_indirect_wide",
            )

        self.assertEqual(status, 200)
        for instruction in (
            "Man mark",
            "Go back",
            "Edge of area",
            "Wall",
            "Stay forward",
        ):
            self.assertIn(instruction, body)
        for old_instruction in (
            "Mark near post",
            "Mark far post",
            "Mark tall player",
            "Close down short",
            "Mark edge of area",
        ):
            self.assertNotIn(old_instruction, body)
        self.assertEqual(body.count("class='routine-assignment-note'"), 11)

    def test_attacking_free_kick_uses_the_fm_instruction_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            port = self._serve(_complete_fixture(Path(directory)))
            status, body = self._get(
                port,
                "/set-pieces?tactic=balanced_442&routine=attacking_indirect_wide_left",
            )

        self.assertEqual(status, 200)
        for instruction in (
            "Stay back",
            "Attack ball from edge",
            "Stand with taker",
            "Go forward",
            "Attack near post",
            "Attack far post",
        ):
            self.assertIn(instruction, body)
        for old_instruction in (
            "Stay back if needed",
            "Attack ball from centre",
            "Lurk outside area",
            "Come short",
            "Mark keeper",
        ):
            self.assertNotIn(old_instruction, body)
        self.assertEqual(body.count("class='routine-assignment-note'"), 10)

    def test_free_kick_routine_selector_lists_all_four_types_by_phase(self) -> None:
        port = self._serve(FIXTURE)
        attacking_status, attacking_body = self._get(
            port, "/set-pieces?routine=attacking_direct_free_kick_left"
        )
        defending_status, defending_body = self._get(
            port, "/set-pieces?routine=defending_direct_free_kick"
        )

        self.assertEqual((attacking_status, defending_status), (200, 200))
        for label in (
            "Direct",
            "Direct (small chance of shot)",
            "Indirect (wide)",
            "Indirect (deep)",
        ):
            self.assertIn(label, attacking_body)
            self.assertIn(label, defending_body)
        self.assertIn("id='selected-routine'>Left direct free kick", attacking_body)
        self.assertIn("id='selected-routine'>Defending direct free kicks", defending_body)

    def test_complete_data_uses_the_selected_match_xi_and_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            port = self._serve(_complete_fixture(Path(directory)))
            status, body = self._get(
                port,
                "/set-pieces?tactic=balanced_442&delivery=outswinging&risk=secure",
            )

        self.assertEqual(status, 200)
        self.assertIn("Balanced 4-4-2 match XI", body)
        self.assertIn("Optimized against the selected tactic&#x27;s exact XI", body)
        self.assertIn("Secure template", body)
        self.assertIn("3 held back", body)
        self.assertIn("Attack near post", body)
        self.assertIn("Lurk near post", body)
        self.assertIn("Come short", body)
        self.assertIn("Attack ball from edge of area", body)
        self.assertIn("Lurk outside edge of area", body)
        self.assertIn("Stay back", body)
        self.assertIn("Why these takers? View specialist rankings and backups", body)
        self.assertIn("Why this plan?", body)
        self.assertEqual(body.count("class='routine-assignment-note'"), 10)
        self.assertIn("Delivery-side fit", body)
        self.assertIn("Strongest visible inputs", body)


if __name__ == "__main__":
    unittest.main()
