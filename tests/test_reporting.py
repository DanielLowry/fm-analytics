import unittest
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    PlayerSelectionInput,
    RoleScoreCache,
    recommend_tactic_effective_and_potential,
)
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import (
    RecommendationPolicy,
    build_recommendation_bundle,
    build_squad_role_matrix,
    build_tactic_matchday_report,
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
)


def _complete_owned_snapshot():
    fixture = Path(__file__).parent.parent / "src/fm_analytics/fixtures/sample-game.json"
    game, squad = load_fixture(fixture)
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


class ReportingTests(unittest.TestCase):
    def test_validate_recommendation_snapshot_rejects_mismatched_dates(self) -> None:
        game, squad = _complete_owned_snapshot()
        mismatched = replace(squad, as_of_date=game.game_date.replace(day=1))

        with self.assertRaisesRegex(ValueError, "different in-game dates"):
            validate_recommendation_snapshot(game, mismatched)

    def test_has_complete_role_attributes_detects_a_missing_attribute(self) -> None:
        game, squad = _complete_owned_snapshot()
        thinned = replace(
            squad,
            players=tuple(
                replace(player, attributes={k: v for k, v in player.attributes.items() if k != "passing"})
                if "passing" in player.attributes
                else player
                for player in squad.players
            ),
        )

        self.assertTrue(has_complete_role_attributes(squad))
        self.assertFalse(has_complete_role_attributes(thinned))

    def test_build_recommendation_bundle_computes_every_report_together(self) -> None:
        game, squad = _complete_owned_snapshot()

        bundle = build_recommendation_bundle(game, squad)

        self.assertIs(bundle.game, game)
        self.assertTrue(bundle.recommendation.selected.has_legal_xi)
        self.assertEqual(bundle.recommendation.selected.tactic.key, "balanced_442")
        # The role matrix and squad depth reports are genuinely computed, not
        # placeholder-empty, for this complete synthetic squad.
        self.assertTrue(bundle.role_matrix.role_rankings)
        self.assertTrue(bundle.squad_depth.positions)
        self.assertEqual(bundle.squad_depth.tactic_keys, tuple(
            evaluation.tactic.key for evaluation in bundle.recommendation.evaluations
        ))

    def test_role_score_cache_preserves_effective_and_potential_recommendation(self) -> None:
        _game, squad = _complete_owned_snapshot()
        players = tuple(PlayerSelectionInput.from_player(player) for player in squad.players)

        uncached = recommend_tactic_effective_and_potential(players, MVP_CATALOGUE)
        cached = recommend_tactic_effective_and_potential(
            players, MVP_CATALOGUE, role_score_cache=RoleScoreCache()
        )

        self.assertEqual(cached, uncached)

    def test_matchday_detail_reuses_the_bundle_policy_profile(self) -> None:
        game, squad = _complete_owned_snapshot()
        policy = RecommendationPolicy(bench_size=0)
        bundle = build_recommendation_bundle(game, squad, policy=policy)

        report = build_tactic_matchday_report(
            bundle, bundle.recommendation.selected.tactic.key
        )

        self.assertIs(bundle.policy, policy)
        self.assertEqual(report.bench.entries, ())

    def test_squad_role_matrix_does_not_evaluate_tactics(self) -> None:
        from unittest.mock import patch

        _game, squad = _complete_owned_snapshot()
        with patch(
            "fm_analytics.reporting.recommend_tactic_effective_and_potential",
            side_effect=AssertionError("the roster must not optimise tactics"),
        ):
            matrix = build_squad_role_matrix(squad)

        self.assertTrue(matrix.role_rankings)
        self.assertEqual(set(matrix.player_profiles), {player.id for player in squad.players})

    def test_build_recommendation_bundle_and_cli_agree_on_the_selected_tactic(self) -> None:
        # Guards against the CLI and a future web view silently drifting:
        # both now call the same function, so this is really a smoke test
        # that the refactor didn't fork the computation path.
        from fm_analytics.cli import render_recommendation

        game, squad = _complete_owned_snapshot()
        bundle = build_recommendation_bundle(game, squad)

        rendered = render_recommendation(
            game,
            squad,
            bundle.recommendation,
            bundle.bench,
            bundle.weakness_report,
            bundle.briefs,
            (),
            bundle.training_targets,
            bundle.squad_depth,
        )

        self.assertIn(bundle.recommendation.selected.tactic.name, rendered)


if __name__ == "__main__":
    unittest.main()
