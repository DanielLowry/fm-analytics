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
from typing import TYPE_CHECKING

from fm_analytics.analytics.match_analysis import (
    MatchReport,
    MatchReview,
    ReviewFilters,
    report_match,
    review_matches,
)
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
    TacticRankingExecutor,
    TacticRecommendation,
    TacticSelectionExplanation,
    TrainingTarget,
    WeaknessKind,
    WeaknessReport,
    assess_squad_depth,
    opponent_attribute_emphasis,
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

if TYPE_CHECKING:
    from fm_analytics.persistence.match_history import MatchHistory


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

    @property
    def primary(self) -> TacticEvaluation:
        """The tactic the manager actually plays, else the top-ranked one.

        `recommendation.selected` stays "highest fit of all 42"; this is what
        every page defaults to. With no pins it is the same object.
        """
        pins = self.policy.pinned_tactics
        return self.recommendation.by_tactic_key(pins[0]) if pins else self.recommendation.selected

    @property
    def pinned(self) -> tuple[TacticEvaluation, ...]:
        """The pinned tactics in the manager's order; empty when none are set."""
        return tuple(
            self.recommendation.by_tactic_key(key) for key in self.policy.pinned_tactics
        )

    @property
    def planning_depth(self) -> SquadDepthReport:
        """Depth over the tactics actually in play, or every tactic with no pins.

        `squad_depth` always covers the whole catalogue because the tactic
        drill-down needs every per-tactic report; this is the persistent and
        occasional view a manager should plan recruitment from.
        """
        pins = self.policy.pinned_tactics
        return self.squad_depth.restricted_to(pins) if pins else self.squad_depth


@dataclass(frozen=True)
class WeakSlot:
    """One slot a pinned tactic (or the top-ranked tactic, with no pins) needs help at.

    Read entirely from an already-computed `WeaknessReport`; see
    `weakest_slots`. `starter_score`/`cover_score` are the same tapered
    central figure `/depth` itself shows for the starter and first available
    backup, so this can never disagree with that page about who they are.
    """

    tactic_key: str
    tactic_name: str
    slot_key: str
    position: str
    role_key: str
    role_name: str
    # The role's attribute weights in this slot, heaviest first (ties by
    # name), as this tactic and the bundle's opponent profile weight them --
    # the same weighting the weakness report scored the starter and cover
    # with. Which of these matter enough to trigger re-scouting is the
    # caller's threshold, not this list's.
    role_attributes: tuple[tuple[str, float], ...]
    # "starter": the starter himself is the weak link. "cover": the starter is
    # fine, but there is no backup, or the backup drops off sharply.
    concern: str
    starter_name: str | None
    starter_score: float | None
    cover_name: str | None
    cover_score: float | None
    message: str


# Which weakness kinds name a slot worth surfacing here, and as which concern.
# Structural/simultaneous/temporary gaps and shared cover describe a squad-wide
# shortage or a scheduling clash, not a single slot's role being weak, so they
# are deliberately left out -- see docs/archive/tasks/medium-weakest-slot-service.md.
_WEAK_SLOT_CONCERNS = {
    WeaknessKind.WEAK_STARTER: "starter",
    WeaknessKind.NO_BACKUP: "cover",
    WeaknessKind.WEAK_BACKUP: "cover",
}


def weakest_slots(
    bundle: RecommendationBundle,
    *,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
    limit: int = 8,
) -> tuple[WeakSlot, ...]:
    """Where the manager's own tactics need help, for scouting and trial priority.

    Covers the pinned tactics in their configured order, or just the
    top-ranked tactic with no pins -- the same tactics `bundle.pinned`/
    `bundle.primary` already default to. Reads only the weakness reports
    `build_recommendation_bundle` already computed; this calculates no new
    score, so `/scouting`'s navigation and trial-priority sort cannot
    disagree with `/depth` about where a tactic is weak.

    Worst starters first (lowest starter score), then worst cover (lowest
    cover score, with no cover at all ranked worse than any real backup), each
    group in tactic-then-slot order for ties. `limit` bounds the combined
    result, applied after that ordering, so the most severe items are the ones
    trimmed away last, never first.
    """
    tactics = bundle.pinned or (bundle.recommendation.selected,)
    starters: list[WeakSlot] = []
    covers: list[WeakSlot] = []
    seen: set[tuple[str, str, str]] = set()
    extra_emphasis = opponent_attribute_emphasis(bundle.policy.opponent)
    for evaluation in tactics:
        report = bundle.squad_depth.per_tactic[evaluation.tactic.key]
        depth_by_slot = {slot_depth.slot.key: slot_depth for slot_depth in report.depth}
        derived = catalogue.for_context(evaluation.tactic.key, extra_emphasis=extra_emphasis)
        for weakness in report.weaknesses:
            concern = _WEAK_SLOT_CONCERNS.get(weakness.kind)
            if concern is None:
                continue
            for slot_key in weakness.slot_keys:
                identity = (evaluation.tactic.key, slot_key, concern)
                if identity in seen:
                    continue
                seen.add(identity)
                slot_depth = depth_by_slot.get(slot_key)
                if slot_depth is None or slot_depth.starter is None:
                    continue
                role_key = slot_depth.starter.intrinsic_role_score.role_key
                cover = slot_depth.available_backups[0] if slot_depth.available_backups else None
                item = WeakSlot(
                    tactic_key=evaluation.tactic.key,
                    tactic_name=evaluation.tactic.name,
                    slot_key=slot_key,
                    position=slot_depth.slot.position,
                    role_key=role_key,
                    role_name=catalogue.roles[role_key].name,
                    role_attributes=tuple(
                        (attribute.name, attribute.weight)
                        for attribute in sorted(
                            derived.role_for_slot(slot_depth.slot, role_key).attributes,
                            key=lambda attribute: (-attribute.weight, attribute.name),
                        )
                    ),
                    concern=concern,
                    starter_name=slot_depth.starter.player_name,
                    starter_score=slot_depth.starter.tapered_attribute_score.central,
                    cover_name=cover.player_name if cover else None,
                    cover_score=cover.role_score.score.central if cover else None,
                    message=weakness.message,
                )
                (starters if concern == "starter" else covers).append(item)
    starters.sort(key=lambda item: (item.starter_score, item.tactic_key, item.slot_key))
    covers.sort(
        key=lambda item: (
            item.cover_score if item.cover_score is not None else -1.0,
            item.tactic_key,
            item.slot_key,
        )
    )
    return tuple((starters + covers)[:limit])


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
    # The manager's own read of the opposition; neutral by default, which
    # leaves every score exactly as it was before this existed.
    opponent: OpponentProfile = OpponentProfile.neutral()
    bench_size: int = 7
    # The tactics the manager actually plays, primary first. Empty means "no
    # opinion": every default falls back to the top-ranked tactic, exactly as
    # before pins existed.
    pinned_tactics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.bench_size < 0:
            raise ValueError("bench size cannot be negative")
        if len(set(self.pinned_tactics)) != len(self.pinned_tactics):
            raise ValueError("pinned tactics must be distinct")


def parse_pinned_tactics(
    text: str | None, catalogue: FootballCatalogue = MVP_CATALOGUE
) -> tuple[str, ...]:
    """Turn a comma-separated `--my-tactics` value into validated tactic keys.

    Raises `ValueError` naming every unknown key, so a typo is a start-up error
    rather than a page that quietly falls back to the wrong tactic.
    """
    if not text:
        return ()
    keys = tuple(part.strip() for part in text.split(",") if part.strip())
    unknown = [key for key in keys if key not in catalogue.tactics]
    if unknown:
        raise ValueError(
            "unknown tactic key(s) in --my-tactics: " + ", ".join(unknown)
            + ". Tactic keys are the file names under analytics/data/tactics/."
        )
    if len(set(keys)) != len(keys):
        raise ValueError("--my-tactics lists the same tactic more than once")
    return keys


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
    ranking_executor: TacticRankingExecutor | None = None,
) -> RecommendationBundle:
    """Run every analytics pass a squad recommendation needs, once.

    Callers are responsible for resolving the squad's data source (live
    probe, fixture, HTML overlay) and for `validate_recommendation_snapshot`
    and completeness checks beforehand; this function assumes a squad that is
    already coherent and attribute-complete enough to score.
    """
    unknown_pins = [key for key in policy.pinned_tactics if key not in catalogue.tactics]
    if unknown_pins:
        raise ValueError("unknown pinned tactic(s): " + ", ".join(unknown_pins))
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
        opponent=policy.opponent,
        role_score_cache=role_score_cache,
        ranking_executor=ranking_executor,
    )
    recommendation = effective_and_potential.effective
    # Bench, substitutions and weaknesses describe the tactic actually played.
    primary = (
        recommendation.by_tactic_key(policy.pinned_tactics[0])
        if policy.pinned_tactics
        else recommendation.selected
    )
    bench = select_bench(
        primary,
        selection_players,
        catalogue,
        bench_size=policy.bench_size,
        readiness_policy=policy.readiness,
        familiarity_policy=policy.familiarity,
        opponent=policy.opponent,
        role_score_cache=role_score_cache,
    )
    substitution_board = build_substitution_board(
        primary,
        bench,
        selection_players,
        catalogue,
        readiness_policy=policy.readiness,
        familiarity_policy=policy.familiarity,
        opponent=policy.opponent,
        role_score_cache=role_score_cache,
    )
    weakness_report = assess_weaknesses(
        primary, selection_players, catalogue,
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
        opponent=bundle.policy.opponent,
    )
    return TacticMatchdayReport(
        evaluation=evaluation,
        bench=bench,
        substitution_board=substitution_board,
        selection_explanation=selection_explanation,
    )


def build_match_review(
    history: MatchHistory,
    *,
    filters: ReviewFilters = ReviewFilters(),
    catalogue: FootballCatalogue = MVP_CATALOGUE,
) -> MatchReview:
    """The one match-review computation, shared by `fm-matches review` and the Matches page."""
    return review_matches(
        history.matches,
        history.league_results,
        history.club,
        catalogue=catalogue,
        notes=history.notes,
        confirmed_role_codes=history.role_codes,
        filters=filters,
    )


def build_match_report(
    history: MatchHistory, match_key: str, *, catalogue: FootballCatalogue = MVP_CATALOGUE
) -> MatchReport | None:
    """One match as `fm-matches show` and the match page present it."""
    return report_match(
        match_key,
        history.matches,
        history.league_results,
        history.club,
        catalogue=catalogue,
        notes=history.notes,
        confirmed_role_codes=history.role_codes,
    )
