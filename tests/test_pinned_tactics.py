"""Pinned tactics: the tactics the manager actually plays.

Pins change which tactic every page and report *defaults* to. They must never
change a score, so most of these tests compare a pinned run against the same
computation done directly.
"""

import io
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    PlayerSelectionInput,
    assess_squad_depth,
    assess_weaknesses,
)
from fm_analytics.cli import load_fixture, main as cli_main
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import (
    RecommendationPolicy,
    build_recommendation_bundle,
    build_tactic_matchday_report,
    parse_pinned_tactics,
    required_role_attributes,
)
from fm_analytics.web.providers import fixture_provider
from fm_analytics.web.server import SquadWebServer, main as web_main

FIXTURE = Path(__file__).resolve().parent.parent / "src/fm_analytics/fixtures/sample-game.json"


def _complete_snapshot():
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
                name: AttributeObservation(Visibility.KNOWN, value=10) for name in required
            },
        )
        for index, slot in enumerate(MVP_CATALOGUE.tactics["balanced_442"].slots, start=1)
    )
    return game, replace(squad, players=players)


def _write_fixture(directory: Path) -> Path:
    game, squad = _complete_snapshot()
    path = directory / "complete.json"
    path.write_text(
        json.dumps({"game": game.to_dict(), "squad": squad.to_dict()}), encoding="utf-8"
    )
    return path


class ParsePinnedTacticsTests(unittest.TestCase):
    def test_empty_means_no_opinion(self) -> None:
        self.assertEqual(parse_pinned_tactics(None), ())
        self.assertEqual(parse_pinned_tactics(""), ())

    def test_keeps_the_order_given_and_tolerates_spaces(self) -> None:
        self.assertEqual(
            parse_pinned_tactics("wing_play_442, vertical_442"),
            ("wing_play_442", "vertical_442"),
        )

    def test_the_manager_s_three_tactics_exist_in_the_catalogue(self) -> None:
        keys = ("vertical_442", "wing_play_442", "positive_433dm")
        self.assertEqual(parse_pinned_tactics(",".join(keys)), keys)

    def test_names_every_unknown_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "nope.*also_nope"):
            parse_pinned_tactics("vertical_442,nope,also_nope")

    def test_rejects_a_repeated_tactic(self) -> None:
        with self.assertRaisesRegex(ValueError, "more than once"):
            parse_pinned_tactics("vertical_442,vertical_442")

    def test_policy_rejects_duplicates_too(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct"):
            RecommendationPolicy(pinned_tactics=("vertical_442", "vertical_442"))


class PinnedBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.game, cls.squad = _complete_snapshot()
        cls.plain = build_recommendation_bundle(cls.game, cls.squad)
        top = cls.plain.recommendation.selected.tactic.key
        legal = [
            item.tactic.key
            for item in cls.plain.recommendation.evaluations
            if item.has_legal_xi and item.tactic.key != top
        ]
        # A pinned tactic that is deliberately not the top-ranked one, or the
        # tests below could pass without pins doing anything.
        cls.primary_key, cls.second_key = legal[0], legal[1]
        cls.pins = (cls.primary_key, cls.second_key)
        cls.pinned = build_recommendation_bundle(
            cls.game, cls.squad, policy=RecommendationPolicy(pinned_tactics=cls.pins)
        )

    def test_without_pins_primary_is_the_top_ranked_tactic(self) -> None:
        self.assertIs(self.plain.primary, self.plain.recommendation.selected)
        self.assertEqual(self.plain.pinned, ())
        self.assertIs(self.plain.planning_depth, self.plain.squad_depth)

    def test_with_pins_primary_is_the_first_pin_not_the_top_ranked(self) -> None:
        self.assertEqual(self.pinned.primary.tactic.key, self.primary_key)
        self.assertNotEqual(
            self.pinned.primary.tactic.key, self.pinned.recommendation.selected.tactic.key
        )
        self.assertEqual(
            tuple(item.tactic.key for item in self.pinned.pinned), self.pins
        )

    def test_pins_change_no_score(self) -> None:
        self.assertEqual(self.pinned.recommendation, self.plain.recommendation)
        self.assertEqual(self.pinned.squad_depth, self.plain.squad_depth)
        self.assertEqual(self.pinned.role_matrix, self.plain.role_matrix)
        self.assertEqual(self.pinned.training_targets, self.plain.training_targets)

    def test_weaknesses_and_briefs_describe_the_primary_tactic(self) -> None:
        self.assertEqual(self.pinned.weakness_report.tactic_key, self.primary_key)
        self.assertEqual(self.plain.weakness_report.tactic_key, self.plain.primary.tactic.key)
        direct = assess_weaknesses(
            self.pinned.primary,
            tuple(PlayerSelectionInput.from_player(p) for p in self.squad.players),
            MVP_CATALOGUE,
        )
        self.assertEqual(self.pinned.weakness_report, direct)

    def test_bench_and_substitutions_describe_the_primary_tactic(self) -> None:
        report = build_tactic_matchday_report(self.pinned, self.primary_key)
        self.assertEqual(self.pinned.bench, report.bench)
        self.assertEqual(self.pinned.substitution_board, report.substitution_board)

    def test_planning_depth_equals_evaluating_only_the_pinned_tactics(self) -> None:
        players = tuple(PlayerSelectionInput.from_player(p) for p in self.squad.players)
        recomputed = assess_squad_depth(self.pinned.pinned, players, MVP_CATALOGUE)
        self.assertEqual(self.pinned.planning_depth, recomputed)

    def test_planning_depth_keeps_the_full_report_untouched(self) -> None:
        self.assertEqual(
            len(self.pinned.squad_depth.tactic_keys), len(self.pinned.recommendation.evaluations)
        )
        self.assertEqual(self.pinned.planning_depth.tactic_keys, self.pins)

    def test_unknown_pin_is_rejected_when_building(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown pinned tactic"):
            build_recommendation_bundle(
                self.game, self.squad, policy=RecommendationPolicy(pinned_tactics=("nope",))
            )


class RestrictedDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        game, squad = _complete_snapshot()
        cls.bundle = build_recommendation_bundle(game, squad)

    def test_rejects_an_unknown_tactic(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in this depth report"):
            self.bundle.squad_depth.restricted_to(("nope",))

    def test_rejects_an_empty_selection(self) -> None:
        with self.assertRaises(ValueError):
            self.bundle.squad_depth.restricted_to(())

    def test_restricting_to_everything_is_the_identity_up_to_order(self) -> None:
        full = self.bundle.squad_depth
        same = full.restricted_to(full.tactic_keys)
        self.assertEqual(same, full)

    def test_only_positions_the_kept_tactics_field_survive(self) -> None:
        key = self.bundle.recommendation.selected.tactic.key
        narrowed = self.bundle.squad_depth.restricted_to((key,))
        fielded = {slot.position for slot in MVP_CATALOGUE.tactics[key].slots}
        self.assertEqual(set(narrowed.positions), fielded)
        for depth in narrowed.positions.values():
            self.assertEqual(depth.tactics_with_this_position, (key,))


class PinnedCliTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.fixture = _write_fixture(Path(directory.name))

    def _run(self, *extra: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(["--fixture", str(self.fixture), "--recommend", *extra])
        return code, output.getvalue()

    def test_names_the_pinned_primary_and_marks_pinned_rows(self) -> None:
        code, text = self._run("--my-tactics", "balanced_442,balanced_433dm")
        self.assertEqual(code, 0)
        self.assertIn("Primary (pinned): Balanced 4-4-2", text)
        self.assertIn("* Balanced 4-4-2", text)
        self.assertIn("* Balanced 4-3-3 DM", text)
        self.assertNotIn("Selected:", text)
        self.assertIn("Squad depth across your 2 pinned tactic(s)", text)

    def test_without_pins_the_output_is_unchanged(self) -> None:
        code, text = self._run()
        self.assertEqual(code, 0)
        self.assertIn("Selected:", text)
        self.assertNotIn("Primary (pinned)", text)
        self.assertNotIn("pinned with --my-tactics", text)

    def test_says_when_the_primary_is_not_the_highest_fit(self) -> None:
        plain_bundle_top = build_recommendation_bundle(*_complete_snapshot()).recommendation
        other = next(
            item.tactic.key
            for item in plain_bundle_top.evaluations
            if item.has_legal_xi and item.tactic.key != plain_bundle_top.selected.tactic.key
        )
        _, text = self._run("--my-tactics", other)
        self.assertIn("Highest fit overall:", text)

    def test_unknown_key_is_an_error_not_a_silent_fallback(self) -> None:
        code, text = self._run("--my-tactics", "nope")
        self.assertEqual(code, 1)
        self.assertIn("unknown tactic key", text)

    def test_requires_recommend(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli_main(["--fixture", str(self.fixture), "--my-tactics", "balanced_442"])
        self.assertEqual(code, 1)
        self.assertIn("requires --recommend", output.getvalue())


class PinnedWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls.fixture = _write_fixture(Path(cls._directory.name))
        plain = build_recommendation_bundle(*_complete_snapshot()).recommendation
        legal = [
            item.tactic for item in plain.evaluations
            if item.has_legal_xi and item.tactic.key != plain.selected.tactic.key
        ]
        cls.primary, cls.second = legal[0], legal[1]
        cls.pinned_server = cls._serve((cls.primary.key, cls.second.key))
        cls.plain_server = cls._serve(())

    @classmethod
    def _serve(cls, pins):
        server = SquadWebServer(
            ("127.0.0.1", 0), fixture_provider(cls.fixture), pinned_tactics=pins
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    @classmethod
    def tearDownClass(cls) -> None:
        for server in (cls.pinned_server, cls.plain_server):
            server.shutdown()
            server.server_close()
        cls._directory.cleanup()

    @staticmethod
    def _get(server, path: str) -> tuple[int, str]:
        connection = HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, body

    def test_tactics_page_lists_your_tactics_with_ranks(self) -> None:
        status, body = self._get(self.pinned_server, "/tactics")
        self.assertEqual(status, 200)
        self.assertIn("Your tactics", body)
        self.assertIn(self.primary.name, body)
        self.assertIn(self.second.name, body)
        self.assertIn(">Primary<", body)
        self.assertIn(">Pinned<", body)
        self.assertIn("Recommended for today", body)

    def test_tactics_page_without_pins_is_unchanged(self) -> None:
        _, body = self._get(self.plain_server, "/tactics")
        self.assertNotIn("Your tactics", body)
        self.assertNotIn(">Primary<", body)

    def test_depth_defaults_to_the_pinned_tactics_and_can_show_all(self) -> None:
        _, pinned = self._get(self.pinned_server, "/depth")
        self.assertIn("your pinned tactics", pinned)
        self.assertIn("Show every tactic", pinned)
        _, everything = self._get(self.pinned_server, "/depth?scope=all")
        self.assertIn("Show pinned tactics only", everything)
        _, plain = self._get(self.plain_server, "/depth")
        self.assertNotIn("Show every tactic", plain)

    def test_set_pieces_defaults_to_the_primary_tactic_s_xi(self) -> None:
        status, body = self._get(self.pinned_server, "/set-pieces")
        self.assertEqual(status, 200)
        self.assertIn(f"{self.primary.name} match XI", body)
        self.assertIn(f"★ {self.primary.name}", body)

    def test_an_explicit_tactic_still_overrides_the_default(self) -> None:
        _, body = self._get(self.pinned_server, f"/set-pieces?tactic={self.second.key}")
        self.assertIn(f"{self.second.name} match XI", body)

    def test_scouting_selector_lists_pinned_tactics_first(self) -> None:
        _, body = self._get(self.pinned_server, "/scouting")
        self.assertLess(body.index(f"★ {self.primary.name}"), body.index(f"★ {self.second.name}"))
        _, plain = self._get(self.plain_server, "/scouting")
        self.assertNotIn("★", plain)

    def test_dashboard_shows_the_pins_without_needing_a_bundle(self) -> None:
        _, body = self._get(self.pinned_server, "/")
        self.assertIn("My tactics", body)
        self.assertIn(self.primary.name, body)
        _, plain = self._get(self.plain_server, "/")
        self.assertNotIn("My tactics", plain)

    def test_starting_the_server_with_a_typo_fails_before_serving(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            web_main(["--fixture", str(self.fixture), "--my-tactics", "nope"])
        self.assertIn("unknown tactic key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
