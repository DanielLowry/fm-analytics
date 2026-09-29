import unittest
import json
from dataclasses import asdict, replace
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    PlayerSelectionInput,
    RoleScoreCache,
    SquadDepthReport,
    TacticRankingExecutor,
    TacticRecommendation,
    assess_weaknesses,
    evaluate_tactic,
    recommend_tactic_effective_and_potential,
)
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.reporting import (
    RecommendationBundle,
    RecommendationPolicy,
    WeakSlot,
    build_recommendation_bundle,
    build_squad_role_matrix,
    build_tactic_matchday_report,
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
    weakest_slots,
)
from tests.test_xi_selection import (
    CATALOGUE as WEAK_SLOT_CATALOGUE,
    TACTIC as WEAK_SLOT_TACTIC,
    legal_squad,
    player,
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


def _canonical_bundle_json(bundle) -> str:
    """A stable, human-inspectable companion to direct dataclass equality."""
    def encode(value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, frozenset):
            return sorted(value)
        raise TypeError(f"cannot canonically encode {type(value).__name__}")

    return json.dumps(asdict(bundle), sort_keys=True, separators=(",", ":"), default=encode)


def _bundle_from_weakness_report(report, evaluation, *, pinned_tactics=()) -> RecommendationBundle:
    """The minimal bundle `weakest_slots` needs: pins, the evaluated tactic(s),
    and a squad-depth report keyed by tactic. Every other field is untouched by
    `weakest_slots`, so it is left as an honest placeholder rather than built
    for real -- building a genuine `Squad`/`GameState` for a test-only tactic
    and catalogue would test the fixture, not the function.
    """
    return RecommendationBundle(
        game=None,
        squad=None,
        recommendation=TacticRecommendation((evaluation,)),
        training_targets=(),
        bench=None,
        substitution_board=None,
        weakness_report=report,
        squad_depth=SquadDepthReport(
            policy_version=report.policy_version,
            tactic_keys=(evaluation.tactic.key,),
            per_tactic={evaluation.tactic.key: report},
            positions={},
        ),
        role_matrix=None,
        briefs=(),
        policy=RecommendationPolicy(pinned_tactics=pinned_tactics),
    )


class WeakestSlotsTests(unittest.TestCase):
    def test_weak_starter_is_ranked_first_and_ties_break_by_slot_key(self) -> None:
        squad = legal_squad()
        squad[0] = player(1, "GK", 6)
        evaluation = evaluate_tactic(WEAK_SLOT_TACTIC, squad, WEAK_SLOT_CATALOGUE)
        report = assess_weaknesses(evaluation, squad, WEAK_SLOT_CATALOGUE)
        bundle = _bundle_from_weakness_report(report, evaluation)

        result = weakest_slots(bundle, catalogue=WEAK_SLOT_CATALOGUE)

        self.assertEqual(len(result), 8)  # the default limit
        self.assertEqual(result[0].concern, "starter")
        self.assertEqual(result[0].slot_key, "slot-0")
        self.assertEqual(result[0].starter_name, "Player 01")
        self.assertEqual(result[0].role_name, "Generic")
        # The test role weights a single attribute; the alerts brief reads
        # this list to decide which unknowns matter for a weak slot.
        self.assertEqual(result[0].role_attributes, (("quality", 1),))
        self.assertTrue(all(item.concern == "cover" for item in result[1:]))
        # slot-0's weak starter also has no backup, so it is flagged both
        # ways -- once under each concern -- and every slot (including
        # slot-0 again, this time as a cover concern) has no backup at all,
        # so ties there break by slot key.
        self.assertEqual(
            [item.slot_key for item in result[1:]],
            sorted(slot.key for slot in WEAK_SLOT_TACTIC.slots)[:7],
        )

    def test_pinned_and_unpinned_bundles_agree_on_the_same_tactic(self) -> None:
        squad = legal_squad()
        squad[0] = player(1, "GK", 6)
        evaluation = evaluate_tactic(WEAK_SLOT_TACTIC, squad, WEAK_SLOT_CATALOGUE)
        report = assess_weaknesses(evaluation, squad, WEAK_SLOT_CATALOGUE)
        unpinned = _bundle_from_weakness_report(report, evaluation)
        pinned = _bundle_from_weakness_report(
            report, evaluation, pinned_tactics=(WEAK_SLOT_TACTIC.key,)
        )

        self.assertEqual(
            weakest_slots(unpinned, catalogue=WEAK_SLOT_CATALOGUE),
            weakest_slots(pinned, catalogue=WEAK_SLOT_CATALOGUE),
        )

    def test_limit_bounds_the_result_without_dropping_the_worst_item_first(self) -> None:
        squad = legal_squad()
        squad[0] = player(1, "GK", 6)
        evaluation = evaluate_tactic(WEAK_SLOT_TACTIC, squad, WEAK_SLOT_CATALOGUE)
        report = assess_weaknesses(evaluation, squad, WEAK_SLOT_CATALOGUE)
        bundle = _bundle_from_weakness_report(report, evaluation)

        result = weakest_slots(bundle, catalogue=WEAK_SLOT_CATALOGUE, limit=3)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].concern, "starter")

    def test_a_real_backup_ranks_below_every_slot_with_no_backup_at_all(self) -> None:
        # A weak-but-real backup at GK; every other slot still has none.
        squad = legal_squad() + [player(40, "GK", 4)]
        evaluation = evaluate_tactic(WEAK_SLOT_TACTIC, squad, WEAK_SLOT_CATALOGUE)
        report = assess_weaknesses(evaluation, squad, WEAK_SLOT_CATALOGUE)
        bundle = _bundle_from_weakness_report(report, evaluation)

        result = weakest_slots(bundle, catalogue=WEAK_SLOT_CATALOGUE, limit=20)

        by_slot = {item.slot_key: item for item in result}
        self.assertEqual(by_slot["slot-0"].concern, "cover")
        self.assertIsNotNone(by_slot["slot-0"].cover_score)
        self.assertEqual(by_slot["slot-0"].cover_name, "Player 40")
        no_cover_at_all = [item for item in result if item.cover_score is None]
        self.assertTrue(no_cover_at_all)
        self.assertLess(
            max(result.index(item) for item in no_cover_at_all),
            result.index(by_slot["slot-0"]),
        )

    def test_no_weaknesses_gives_an_empty_result(self) -> None:
        squad = legal_squad()
        evaluation = evaluate_tactic(WEAK_SLOT_TACTIC, squad, WEAK_SLOT_CATALOGUE)
        report = assess_weaknesses(evaluation, squad, WEAK_SLOT_CATALOGUE)
        bundle = _bundle_from_weakness_report(report, evaluation)

        # An evenly matched, exactly-filled 11 has 11 NO_BACKUP weaknesses
        # (see tests.test_weaknesses), so exercise a report with none of the
        # three concerning kinds by dropping them by hand.
        from dataclasses import replace

        clean_report = replace(
            report,
            weaknesses=tuple(
                weakness for weakness in report.weaknesses
                if weakness.kind.value not in {"weak_starter", "no_backup", "weak_backup"}
            ),
        )
        bundle = _bundle_from_weakness_report(clean_report, evaluation)

        self.assertEqual(weakest_slots(bundle, catalogue=WEAK_SLOT_CATALOGUE), ())


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

    def test_parallel_ranking_preserves_the_complete_recommendation_bundle(self) -> None:
        game, squad = _complete_owned_snapshot()
        expected = build_recommendation_bundle(game, squad)
        executor = TacticRankingExecutor(workers=2)
        try:
            actual = build_recommendation_bundle(
                game, squad, ranking_executor=executor
            )
        finally:
            executor.shutdown()

        self.assertEqual(actual, expected)
        self.assertEqual(_canonical_bundle_json(actual), _canonical_bundle_json(expected))

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
            bundle.training_targets,
            bundle.squad_depth,
        )

        self.assertIn(bundle.recommendation.selected.tactic.name, rendered)


if __name__ == "__main__":
    unittest.main()
