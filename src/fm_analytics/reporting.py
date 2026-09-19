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
    MVP_CATALOGUE,
    FootballCatalogue,
    PlayerSelectionInput,
    RecruitmentBrief,
    RoleMatrix,
    SquadDepthReport,
    SubstitutionBoard,
    TacticRecommendation,
    TrainingTarget,
    WeaknessReport,
    assess_squad_depth,
    assess_weaknesses,
    build_recruitment_briefs,
    build_role_matrix,
    best_position_adjusted_role,
    best_selection_adjusted_role,
    build_substitution_board,
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
    squad: Squad, *, catalogue: FootballCatalogue = MVP_CATALOGUE
) -> RoleMatrix:
    """Build the player-by-role view without evaluating tactics or XIs.

    The Squad and Roles pages need this small, independent calculation. It is
    intentionally separate from ``build_recommendation_bundle`` so opening a
    roster does not also optimise every tactic.
    """
    selection_players = tuple(
        PlayerSelectionInput.from_player(player) for player in squad.players
    )
    return build_role_matrix(selection_players, catalogue)


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
    effective_and_potential = recommend_tactic_effective_and_potential(
        selection_players, catalogue
    )
    recommendation = effective_and_potential.effective
    bench = select_bench(recommendation.selected, selection_players, catalogue)
    substitution_board = build_substitution_board(
        recommendation.selected, bench, selection_players, catalogue
    )
    weakness_report = assess_weaknesses(recommendation.selected, selection_players, catalogue)
    squad_depth = assess_squad_depth(recommendation.evaluations, selection_players, catalogue)
    role_matrix = build_squad_role_matrix(squad, catalogue=catalogue)
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
    )
