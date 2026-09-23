"""Shared "compute everything for a squad recommendation" path.

The CLI and the read-only web view (`fm_analytics.web`) both need the same
answer to "given this squad, what should the manager do", and they must
compute it the same way or their numbers can silently disagree. This module
is that one computation; each surface is responsible only for turning its
result into text or HTML. It does not read game memory, bridge JSON, or FM
screens -- it consumes the same domain objects analytics always has.
"""

from __future__ import annotations

from dataclasses import dataclass

from fm_analytics.analytics import (
    BenchSelection,
    PlayerRoleFit,
    PositionAdjustedRoleFit,
    PositionComparison,
    MVP_CATALOGUE,
    FootballCatalogue,
    FamiliarityPolicy,
    OpponentProfile,
    PlayerSelectionInput,
    ReadinessPolicy,
    RecruitmentBrief,
    RoleMatrix,
    RoleScoreCache,
    SquadDepthReport,
    SubstitutionBoard,
    TacticEvaluation,
    TacticFitPolicy,
    TacticRecommendation,
    TacticSelectionExplanation,
    SystemFitPolicy,
    TrainingTarget,
    WeaknessReport,
    assess_squad_depth,
    assess_weaknesses,
    build_recruitment_briefs,
    build_role_matrix,
    compare_players_at_position,
    best_position_adjusted_role,
    best_selection_adjusted_role,
    build_substitution_board,
    explain_tactic_selection,
    recommend_tactic_effective_and_potential,
    select_bench,
)
from fm_analytics.domain import GameState, Player, Squad


@dataclass(frozen=True)
class RecommendationBundle:
    game: GameState
    squad: Squad
    recommendation: TacticRecommendation
    training_targets: tuple[TrainingTarget, ...]
    bench: BenchSelection
    substitution_board: SubstitutionBoard
    weakness_report: WeaknessReport
    squad_depth: SquadDepthReport
    role_matrix: RoleMatrix
    briefs: tuple[RecruitmentBrief, ...]
    policy: RecommendationPolicy


@dataclass(frozen=True)
class RecommendationPolicy:
    """All adjustable recommendation priorities carried as one profile.

    The browser uses these defaults today.  Keeping the policies together and
    on the resulting bundle gives future controls one input to change while
    ensuring every explanation and matchday calculation uses the same values.
    """

    readiness: ReadinessPolicy = ReadinessPolicy()
    familiarity: FamiliarityPolicy = FamiliarityPolicy()
    tactic_fit: TacticFitPolicy = TacticFitPolicy()
    system_fit: SystemFitPolicy = SystemFitPolicy()
    # The manager's own read of the opposition; neutral by default, which
    # leaves every score exactly as it was before this existed.
    opponent: OpponentProfile = OpponentProfile.neutral()
    bench_size: int = 7

    def __post_init__(self) -> None:
        if self.bench_size < 0:
            raise ValueError("bench size cannot be negative")


@dataclass(frozen=True)
class TacticMatchdayReport:
    """Drill-down data for one tactic, computed through the shared analytics."""

    evaluation: TacticEvaluation
    bench: BenchSelection
    substitution_board: SubstitutionBoard
    selection_explanation: TacticSelectionExplanation


def required_role_attributes(catalogue: FootballCatalogue = MVP_CATALOGUE) -> frozenset[str]:
    return frozenset(
        attribute.name for role in catalogue.roles.values() for attribute in role.attributes
    )


def has_complete_role_attributes(
    squad: Squad, catalogue: FootballCatalogue = MVP_CATALOGUE
) -> bool:
    required = required_role_attributes(catalogue)
    return bool(squad.players) and all(
        required.issubset(player.attributes) for player in squad.players
    )


def build_squad_role_matrix(
    squad: Squad,
    *,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
    role_score_cache: RoleScoreCache | None = None,
) -> RoleMatrix:
    """Build the player-by-role view without evaluating tactics or XIs.

    The Squad and Roles pages need this small, independent calculation. It is
    intentionally separate from ``build_recommendation_bundle`` so opening a
    roster does not also optimise every tactic.
    """
    selection_players = tuple(
        PlayerSelectionInput.from_player(player) for player in squad.players
    )
    return build_role_matrix(selection_players, catalogue, role_score_cache=role_score_cache)


def build_squad_position_comparison(
    squad: Squad,
    position: str,
    *,
    role_key: str | None = None,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
    policy: RecommendationPolicy = RecommendationPolicy(),
) -> PositionComparison:
    """Compare a squad at one position using the shared recommendation policy."""
    return compare_players_at_position(
        tuple(PlayerSelectionInput.from_player(player) for player in squad.players),
        position,
        catalogue,
        role_key=role_key,
        readiness_policy=policy.readiness,
        familiarity_policy=policy.familiarity,
    )


@dataclass(frozen=True)
class PlayerRoleScores:
    """A player's strongest role under each of the three score definitions."""

    attribute_based: PlayerRoleFit | None
    in_position: PositionAdjustedRoleFit | None
    selection: PositionAdjustedRoleFit | None


def build_player_role_scores(
    player: Player,
    role_matrix: RoleMatrix | None = None,
    *,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
) -> PlayerRoleScores:
    """The three scores the Squad roster and a player's own page both show.

    Pass the squad's ``role_matrix`` when scoring many players so the
    attribute-based pass is not repeated; otherwise it is built for this
    player alone (role scoring is independent per player).
    """
    selection_input = PlayerSelectionInput.from_player(player)
    if role_matrix is None:
        role_matrix = build_role_matrix((selection_input,), catalogue)
    profile = role_matrix.player_profiles.get(player.id)
    return PlayerRoleScores(
        attribute_based=profile.best if profile else None,
        in_position=best_position_adjusted_role(selection_input, catalogue),
        selection=best_selection_adjusted_role(selection_input, catalogue),
    )


def validate_recommendation_snapshot(game: GameState, squad: Squad) -> None:
    if game.game_date != squad.as_of_date:
        raise ValueError("game and squad observations have different in-game dates")
    if game.controlled_club is None or squad.club is None:
        raise ValueError("recommendation requires an active managed club")
    if game.controlled_club.id != squad.club.id:
        raise ValueError("game and squad observations have different managed clubs")


def build_recommendation_bundle(
    game: GameState,
    squad: Squad,
    *,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
    policy: RecommendationPolicy = RecommendationPolicy(),
) -> RecommendationBundle:
    """Run every analytics pass a squad recommendation needs, once.

    Callers are responsible for resolving the squad's data source (live
    probe, fixture, HTML overlay) and for `validate_recommendation_snapshot`
    and completeness checks beforehand; this function assumes a squad that is
    already coherent and attribute-complete enough to score.
    """
    selection_players = tuple(
        PlayerSelectionInput.from_player(player) for player in squad.players
    )
    role_score_cache = RoleScoreCache()
    effective_and_potential = recommend_tactic_effective_and_potential(
        selection_players,
        catalogue,
        readiness_policy=policy.readiness,
        familiarity_policy=policy.familiarity,
        fit_policy=policy.tactic_fit,
        system_policy=policy.system_fit,
        opponent=policy.opponent,
        role_score_cache=role_score_cache,
    )
    recommendation = effective_and_potential.effective
    bench = select_bench(
        recommendation.selected,
        selection_players,
        catalogue,
        bench_size=policy.bench_size,
        readiness_policy=policy.readiness,
        familiarity_policy=policy.familiarity,
        opponent=policy.opponent,
        role_score_cache=role_score_cache,
    )
    substitution_board = build_substitution_board(
        recommendation.selected,
        bench,
        selection_players,
        catalogue,
        readiness_policy=policy.readiness,
        familiarity_policy=policy.familiarity,
        opponent=policy.opponent,
        role_score_cache=role_score_cache,
    )
    weakness_report = assess_weaknesses(
        recommendation.selected, selection_players, catalogue,
        opponent=policy.opponent, role_score_cache=role_score_cache,
    )
    squad_depth = assess_squad_depth(
        recommendation.evaluations, selection_players, catalogue,
        opponent=policy.opponent, role_score_cache=role_score_cache,
    )
    role_matrix = build_squad_role_matrix(
        squad, catalogue=catalogue, role_score_cache=role_score_cache
    )
    briefs = build_recruitment_briefs(weakness_report, catalogue)
    return RecommendationBundle(
        game=game,
        squad=squad,
        recommendation=recommendation,
        training_targets=effective_and_potential.training_targets(),
        bench=bench,
        substitution_board=substitution_board,
        weakness_report=weakness_report,
        squad_depth=squad_depth,
        role_matrix=role_matrix,
        briefs=briefs,
        policy=policy,
    )


def build_tactic_matchday_report(
    bundle: RecommendationBundle,
    tactic_key: str,
    *,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
    bench_size: int | None = None,
) -> TacticMatchdayReport:
    """Build the XI explanation and tactic-specific matchday bench."""
    try:
        evaluation = bundle.recommendation.by_tactic_key(tactic_key)
    except StopIteration as exc:
        raise ValueError(f"unknown evaluated tactic {tactic_key!r}") from exc
    selection_players = tuple(
        PlayerSelectionInput.from_player(player) for player in bundle.squad.players
    )
    resolved_bench_size = bundle.policy.bench_size if bench_size is None else bench_size
    bench = select_bench(
        evaluation,
        selection_players,
        catalogue,
        bench_size=resolved_bench_size,
        readiness_policy=bundle.policy.readiness,
        familiarity_policy=bundle.policy.familiarity,
        opponent=bundle.policy.opponent,
    )
    substitution_board = build_substitution_board(
        evaluation,
        bench,
        selection_players,
        catalogue,
        readiness_policy=bundle.policy.readiness,
        familiarity_policy=bundle.policy.familiarity,
        opponent=bundle.policy.opponent,
    )
    selection_explanation = explain_tactic_selection(
        evaluation,
        selection_players,
        catalogue,
        readiness_policy=bundle.policy.readiness,
        familiarity_policy=bundle.policy.familiarity,
        fit_policy=bundle.policy.tactic_fit,
        system_policy=bundle.policy.system_fit,
        opponent=bundle.policy.opponent,
    )
    return TacticMatchdayReport(
        evaluation=evaluation,
        bench=bench,
        substitution_board=substitution_board,
        selection_explanation=selection_explanation,
    )
