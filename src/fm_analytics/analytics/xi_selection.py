from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Sequence

from fm_analytics.analytics.catalogue import (
    FootballCatalogue,
    TacticDefinition,
    TacticSlot,
)
from fm_analytics.analytics.assignment_solver import (
    best_assignment_for_role_version,
    state_signature,
)
from fm_analytics.analytics.attribute_taper import AttributeTaperPolicy, assess_tapers
from fm_analytics.analytics.opponent import (
    OpponentProfile,
    assess_opponent_fit,
    attribute_emphasis as opponent_attribute_emphasis,
)
from fm_analytics.analytics.role_scoring import RoleScore, RoleScoreCache, ScoreBand, score_role
from fm_analytics.analytics.selection_status import selection_unavailability_reasons
from fm_analytics.analytics.tactical_system import (
    SystemAssessment,
    assess_coherence,
    assess_instruction_suitability,
)
from fm_analytics.analytics.tactic_ranking import TacticRankingExecutor, rank_evaluations
from fm_analytics.analytics.selection_constraints import apply_forced_assignment_choices
from fm_analytics.domain import Player
from fm_analytics.analytics.xi_models import (
    EffectiveAndPotentialRecommendation,
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    TacticEvaluation,
    TacticFitPolicy,
    TacticRecommendation,
    TrainingTarget,
    _AssignmentState,
    _CandidateAssignment,
)


def evaluate_tactic(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
    role_score_cache: RoleScoreCache | None = None,
) -> TacticEvaluation:
    return _evaluate_tactic(
        tactic,
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy,
        fit_policy=fit_policy,
        opponent=opponent,
        role_score_cache=role_score_cache,
    )


def _evaluate_tactic(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy,
    familiarity_policy: FamiliarityPolicy,
    fit_policy: TacticFitPolicy,
    # Required, like the policies above: a silent neutral default here would
    # hide a caller that forgot to thread the opponent through.
    opponent: OpponentProfile,
    role_score_cache: RoleScoreCache | None = None,
    forced_assignment: tuple[int, str, str] | None = None,
) -> TacticEvaluation:
    if tactic.key not in catalogue.tactics or catalogue.tactics[tactic.key] != tactic:
        raise ValueError("tactic must belong to the supplied football catalogue")
    # Score every player through this tactic's own attribute emphasis, plus
    # whatever this opponent adds to it -- a neutral opponent adds nothing and
    # this is exactly `catalogue.for_tactic(tactic.key)`.
    catalogue = catalogue.for_context(
        tactic.key, extra_emphasis=opponent_attribute_emphasis(opponent)
    )
    player_ids = [player.id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("selection player ids must be unique")

    ordered_players = tuple(sorted(players, key=lambda item: (item.name.casefold(), item.id)))
    choices = _build_choices(
        tactic, ordered_players, catalogue, readiness_policy, familiarity_policy, role_score_cache
    )
    forced_roles: dict[int, str] = {}
    if forced_assignment is not None:
        choices, forced_roles = apply_forced_assignment_choices(
            choices, ordered_players, forced_assignment
        )
    full_mask = (1 << len(tactic.slots)) - 1
    (
        best_mask,
        _best_state,
        ordered_assignments,
        mean_score,
        weakest_score,
        xi_score,
        coherence,
        instruction_suitability,
        opponent_fit,
        fit_score,
    ) = _best_role_version(
        tactic,
        choices,
        catalogue,
        fit_policy,
        opponent,
        forced_roles=forced_roles,
    )
    unfilled = tuple(
        slot
        for index, slot in enumerate(tactic.slots)
        if not best_mask & (1 << index)
    )
    weakest_value = weakest_score.central
    weakest_slot_keys = tuple(
        slot.key for slot in unfilled
    ) if unfilled else tuple(
        assignment.slot.key
        for assignment in ordered_assignments
        if assignment.selection_score.central == weakest_value
    )
    return TacticEvaluation(
        tactic=tactic,
        readiness_version=readiness_policy.version,
        familiarity_version=familiarity_policy.version,
        familiarity_floor=familiarity_policy.floor_multiplier,
        fit_version=fit_policy.version,
        fit_weakest_weight=fit_policy.weakest_slot_weight,
        assignments=ordered_assignments,
        unfilled_slots=unfilled,
        mean_score=mean_score,
        weakest_score=weakest_score,
        weakest_slot_keys=weakest_slot_keys,
        xi_score=xi_score,
        coherence=coherence,
        instruction_suitability=instruction_suitability,
        opponent_fit=opponent_fit,
        score=fit_score,
    )


def recommend_tactic(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
    role_score_cache: RoleScoreCache | None = None,
) -> TacticRecommendation:
    evaluations = tuple(
        evaluate_tactic(
            tactic,
            players,
            catalogue,
            readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
            fit_policy=fit_policy,
            opponent=opponent,
            role_score_cache=role_score_cache,
        )
        for tactic in catalogue.tactics.values()
    )
    return rank_evaluations(evaluations)


def recommend_tactic_effective_and_potential(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
    role_score_cache: RoleScoreCache | None = None,
    ranking_executor: TacticRankingExecutor | None = None,
) -> EffectiveAndPotentialRecommendation:
    """Answer both "what to play now" and "what to aim for" from one call.

    *Effective* applies the familiarity penalty as configured -- what the
    squad can safely play this weekend. *Potential* forces that same
    policy's penalty to zero -- what the squad could be if fully retrained
    into position, with every other input unchanged. The two runs share
    every other policy, so a difference in ranking or score is attributable
    to position familiarity and nothing else.

    This says nothing about *tactic* familiarity (the squad's fluency with a
    shape as a whole), which is a distinct, currently unavailable input --
    see Phase 05. A tactic ranked far higher in potential than in effective
    is one where retraining individual players into their slots would help;
    it is not evidence the squad already knows how to play that shape.
    """
    if ranking_executor is not None:
        # A parent-process score cache is keyed by object identity, so it
        # cannot safely cross process boundaries. Workers use their own
        # request-local caches; callers can still retain the supplied cache
        # for downstream reports built in this process.
        return ranking_executor.rank(
            players,
            catalogue,
            readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
            fit_policy=fit_policy,
            opponent=opponent,
        )
    effective = recommend_tactic(
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy,
        fit_policy=fit_policy,
        opponent=opponent,
        role_score_cache=role_score_cache,
    )
    potential = recommend_tactic(
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy.potential(),
        fit_policy=fit_policy,
        opponent=opponent,
        role_score_cache=role_score_cache,
    )
    return EffectiveAndPotentialRecommendation(effective=effective, potential=potential)


def is_player_selectable(
    player: PlayerSelectionInput,
    *,
    policy: ReadinessPolicy = ReadinessPolicy(),
) -> bool:
    return _is_available(player, policy)


@dataclass(frozen=True)
class PositionAdjustedRoleFit:
    """One role's scores at the player's most familiar eligible position.

    It has no tactic slot: the Squad page uses it for each player's strongest
    attribute-only, in-position, and available-today role. The calculation of
    ``selection_score`` is deliberately the same as ``SlotAssignment`` so the
    Squad and Tactics pages stay comparable.
    """

    role_key: str
    role_name: str
    position: str
    familiarity_rating: int
    familiarity_known: bool
    familiarity_multiplier: float
    intrinsic_role_score: RoleScore
    position_adjusted_score: ScoreBand
    readiness_penalty: float
    readiness_warnings: tuple[str, ...]
    selection_score: ScoreBand


def best_position_adjusted_role(
    player: PlayerSelectionInput,
    catalogue: FootballCatalogue,
    *,
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
) -> PositionAdjustedRoleFit | None:
    """Return a player's strongest eligible role after position familiarity.

    A role can be used at multiple positions. For this squad-level summary we
    use the player's most familiar eligible position for that role; a missing
    reading follows the Tactics policy's neutral ``unknown_rating`` and is
    marked on the returned fit rather than treated as evidence of familiarity.
    """
    return max(
        _position_role_fits(
            player, catalogue, readiness_policy=ReadinessPolicy(),
            familiarity_policy=familiarity_policy,
        ),
        key=lambda item: (
            item.position_adjusted_score.central,
            item.position_adjusted_score.lower,
            item.role_key,
            item.position,
        ),
        default=None,
    )


def best_selection_adjusted_role(
    player: PlayerSelectionInput,
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
) -> PositionAdjustedRoleFit | None:
    """Return the player's strongest legal role for selection today.

    This is the Squad-page counterpart to a Tactics assignment. It does not
    choose a formation or reserve the player for a particular slot, but it
    applies the same availability, readiness and position-familiarity rules.
    """
    if not _is_available(player, readiness_policy):
        return None
    return max(
        _position_role_fits(
            player, catalogue, readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
        ),
        key=lambda item: (
            item.selection_score.central,
            item.selection_score.lower,
            item.role_key,
            item.position,
        ),
        default=None,
    )


def _position_role_fits(
    player: PlayerSelectionInput,
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy,
    familiarity_policy: FamiliarityPolicy,
) -> list[PositionAdjustedRoleFit]:
    """Score every eligible role once for the Squad-page summaries."""
    player_positions = set(player.positions)
    readiness_penalty, readiness_warnings = _readiness(player, readiness_policy)
    fits: list[PositionAdjustedRoleFit] = []
    for role in catalogue.roles.values():
        eligible_positions = sorted(player_positions.intersection(role.eligible_positions))
        if not eligible_positions:
            continue
        position = max(
            eligible_positions,
            key=lambda item: (
                familiarity_policy.multiplier(
                    player.position_familiarity.get(item, familiarity_policy.unknown_rating)
                ),
                item,
            ),
        )
        familiarity_known = position in player.position_familiarity
        rating = player.position_familiarity.get(position, familiarity_policy.unknown_rating)
        multiplier = familiarity_policy.multiplier(rating)
        intrinsic = score_role(role, player.attributes)
        position_adjusted = ScoreBand(
            lower=round(intrinsic.score.lower * multiplier, 6),
            central=round(intrinsic.score.central * multiplier, 6),
            upper=round(intrinsic.score.upper * multiplier, 6),
        )
        fits.append(
            PositionAdjustedRoleFit(
                role_key=role.key,
                role_name=role.name,
                position=position,
                familiarity_rating=rating,
                familiarity_known=familiarity_known,
                familiarity_multiplier=multiplier,
                intrinsic_role_score=intrinsic,
                position_adjusted_score=position_adjusted,
                readiness_penalty=readiness_penalty,
                readiness_warnings=readiness_warnings,
                selection_score=ScoreBand(
                    lower=_selection_adjust(intrinsic.score.lower, readiness_penalty, multiplier),
                    central=_selection_adjust(intrinsic.score.central, readiness_penalty, multiplier),
                    upper=_selection_adjust(intrinsic.score.upper, readiness_penalty, multiplier),
                ),
            )
        )
    return fits


def score_player_for_slot(
    player: PlayerSelectionInput,
    slot: TacticSlot,
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    role_key: str | None = None,
    require_selectable: bool = True,
    taper_policy: AttributeTaperPolicy = AttributeTaperPolicy(),
    role_score_cache: RoleScoreCache | None = None,
) -> SlotAssignment | None:
    """Score a legal player/slot pairing for one allowed role.

    With no `role_key`, return the player's strongest permitted role for this
    slot.  The joint optimiser passes every permitted role explicitly so it
    can trade a little individual quality for a materially better XI system.
    """
    if require_selectable and not _is_available(player, readiness_policy):
        return None
    if slot.position not in player.positions:
        return None
    candidate_roles = (
        (role_key,)
        if role_key is not None
        else catalogue.role_keys_for_slot(slot)
    )
    if not candidate_roles:
        raise ValueError(f"slot {slot.key!r} has no known compatible roles")
    if any(candidate not in catalogue.role_keys_for_slot(slot) for candidate in candidate_roles):
        raise ValueError(f"role {role_key!r} is not allowed for slot {slot.key!r}")
    readiness_penalty, readiness_warnings = _readiness(player, readiness_policy)
    familiarity_multiplier, familiarity_warnings = _familiarity(
        player, slot, familiarity_policy
    )
    assignments = []
    for candidate_role in candidate_roles:
        taper = assess_tapers(
            catalogue.tapers_for_slot(slot, candidate_role),
            player.attributes,
            taper_policy,
        )
        intrinsic = score_role(
            catalogue.role_for_slot(slot, candidate_role), player.attributes,
            cache=role_score_cache,
        )
        assignments.append(
            SlotAssignment(
                slot=slot,
                player_id=player.id,
                player_name=player.name,
                intrinsic_role_score=intrinsic,
                readiness_penalty=readiness_penalty,
                readiness_warnings=readiness_warnings,
                familiarity_multiplier=familiarity_multiplier,
                familiarity_warnings=familiarity_warnings,
                selection_score=ScoreBand(
                    lower=_selection_adjust(
                        intrinsic.score.lower, readiness_penalty, familiarity_multiplier,
                        taper.multiplier.lower,
                    ),
                    central=_selection_adjust(
                        intrinsic.score.central, readiness_penalty, familiarity_multiplier,
                        taper.multiplier.central,
                    ),
                    upper=_selection_adjust(
                        intrinsic.score.upper, readiness_penalty, familiarity_multiplier,
                        taper.multiplier.upper,
                    ),
                ),
                taper_multiplier=taper.multiplier,
                taper_notes=taper.notes,
            )
        )
    return min(
        assignments,
        key=lambda item: (
            -item.selection_score.central,
            -item.selection_score.lower,
            item.intrinsic_role_score.role_key,
        ),
    )


def _build_choices(
    tactic: TacticDefinition,
    players: tuple[PlayerSelectionInput, ...],
    catalogue: FootballCatalogue,
    policy: ReadinessPolicy,
    familiarity_policy: FamiliarityPolicy,
    role_score_cache: RoleScoreCache | None = None,
) -> tuple[tuple[_CandidateAssignment, ...], ...]:
    choices: list[tuple[_CandidateAssignment, ...]] = []
    for player_index, player in enumerate(players):
        if not _is_available(player, policy):
            choices.append(())
            continue
        player_choices: list[_CandidateAssignment] = []
        for slot_index, slot in enumerate(tactic.slots):
            for role_key in catalogue.role_keys_for_slot(slot):
                assignment = score_player_for_slot(
                    player,
                    slot,
                    catalogue,
                    readiness_policy=policy,
                    familiarity_policy=familiarity_policy,
                    role_key=role_key,
                    role_score_cache=role_score_cache,
                )
                if assignment is None:
                    continue
                player_choices.append(
                    _CandidateAssignment(
                        slot_index=slot_index,
                        player_index=player_index,
                        assignment=assignment,
                    )
                )
        choices.append(tuple(player_choices))
    return tuple(choices)


def _is_available(player: PlayerSelectionInput, policy: ReadinessPolicy) -> bool:
    return not selection_unavailability_reasons(player, policy)


def _readiness(
    player: PlayerSelectionInput, policy: ReadinessPolicy
) -> tuple[float, tuple[str, ...]]:
    warnings: list[str] = []
    condition = player.condition_percent
    if condition is None:
        condition = policy.unknown_percent
        warnings.append("condition unknown")
    match_fitness = player.match_fitness_percent
    if match_fitness is None:
        match_fitness = policy.unknown_percent
        warnings.append("match fitness unknown")
    penalty = (
        (100 - condition) * policy.condition_penalty_weight
        + (100 - match_fitness) * policy.match_fitness_penalty_weight
    )
    return round(penalty, 6), tuple(warnings)


def _selection_adjust(
    raw: float,
    readiness_penalty: float,
    familiarity_multiplier: float,
    taper_multiplier: float = 1.0,
) -> float:
    """The shared Tactics/Squad adjustment from intrinsic score to today score.

    `taper_multiplier` is 1.0 wherever there is no tactic (the Squad page), so
    the tactic-free scores are exactly what they were.
    """
    return round(
        max(0, round(raw - readiness_penalty, 6)) * familiarity_multiplier * taper_multiplier,
        6,
    )


def _familiarity(
    player: PlayerSelectionInput, slot: TacticSlot, policy: FamiliarityPolicy
) -> tuple[float, tuple[str, ...]]:
    warnings: list[str] = []
    rating = player.position_familiarity.get(slot.position)
    if rating is None:
        rating = policy.unknown_rating
        warnings.append(f"{slot.position} familiarity unknown")
    return policy.multiplier(rating), tuple(warnings)


@dataclass(frozen=True)
class _RoleVersionEvaluation:
    mask: int
    state: _AssignmentState
    assignments: tuple[SlotAssignment, ...]
    mean_score: ScoreBand
    weakest_score: ScoreBand
    xi_score: ScoreBand
    coherence: SystemAssessment
    instruction_suitability: SystemAssessment
    opponent_fit: SystemAssessment
    score: ScoreBand


def _best_role_version(
    tactic: TacticDefinition,
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    catalogue: FootballCatalogue,
    fit_policy: TacticFitPolicy,
    opponent: OpponentProfile,
    *,
    forced_roles: dict[int, str] | None = None,
) -> tuple[
    int,
    _AssignmentState,
    tuple[SlotAssignment, ...],
    ScoreBand,
    ScoreBand,
    ScoreBand,
    SystemAssessment,
    SystemAssessment,
    SystemAssessment,
    ScoreBand,
]:
    """Evaluate every permitted role version, then solve its XI exactly.

    A tactic's system and instruction scores are determined by its roles, not
    by the identities of the players filling those roles.  We can therefore
    enumerate the small set of explicitly permitted role versions first. For
    each one, player selection is a standard one-player-per-slot assignment:
    no partial XI is discarded just because its individual score is lower
    before its complete role system has been assessed.
    """
    full_mask = (1 << len(tactic.slots)) - 1
    best: _RoleVersionEvaluation | None = None
    forced_roles = forced_roles or {}
    role_options = tuple(
        (forced_roles[index],)
        if index in forced_roles
        else catalogue.role_keys_for_slot(slot)
        for index, slot in enumerate(tactic.slots)
    )
    for role_keys in product(*role_options):
        if not catalogue.role_version_is_legal(tactic, role_keys):
            continue
        version_choices = _choices_for_role_version(choices, role_keys)
        state = best_assignment_for_role_version(
            version_choices, full_mask, fit_policy
        )
        mask = sum(1 << choice.slot_index for choice in state.assignments)
        assignments = tuple(
            choice.assignment
            for choice in sorted(state.assignments, key=lambda item: item.slot_index)
        )
        mean_score, weakest_score, xi_score = _tactic_fit(
            assignments, len(tactic.slots), fit_policy
        )
        coherence, instruction_suitability, opponent_fit = _role_structure_checks(
            tactic, assignments, catalogue, opponent
        )
        candidate = _RoleVersionEvaluation(
            mask=mask,
            state=state,
            assignments=assignments,
            mean_score=mean_score,
            weakest_score=weakest_score,
            xi_score=xi_score,
            coherence=coherence,
            instruction_suitability=instruction_suitability,
            opponent_fit=opponent_fit,
            score=xi_score,
        )
        if (
            best is None
            or _role_version_key(candidate, full_mask)
            < _role_version_key(best, full_mask)
        ):
            best = candidate

    if best is None:  # A tactic must have at least one pinned role per slot.
        raise ValueError(f"tactic {tactic.key!r} has no permitted role versions")
    return (
        best.mask,
        best.state,
        best.assignments,
        best.mean_score,
        best.weakest_score,
        best.xi_score,
        best.coherence,
        best.instruction_suitability,
        best.opponent_fit,
        best.score,
    )


def _role_version_key(
    candidate: _RoleVersionEvaluation,
    full_mask: int,
) -> tuple[bool, int, float, float, tuple[tuple[int, str, str], ...]]:
    return (
        candidate.mask != full_mask,
        -candidate.mask.bit_count(),
        -candidate.score.central,
        -candidate.xi_score.central,
        state_signature(candidate.state),
    )


def _choices_for_role_version(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    role_keys: tuple[str, ...],
) -> tuple[tuple[_CandidateAssignment, ...], ...]:
    return tuple(
        tuple(
            choice
            for choice in player_choices
            if choice.assignment.intrinsic_role_score.role_key == role_keys[choice.slot_index]
        )
        for player_choices in choices
    )


def _role_structure_checks(
    tactic: TacticDefinition,
    assignments: tuple[SlotAssignment, ...],
    catalogue: FootballCatalogue,
    opponent: OpponentProfile,
) -> tuple[SystemAssessment, SystemAssessment, SystemAssessment]:
    """Run advisory checks on the selected roles.

    These checks are advisory because they use fixed values attached to roles,
    not the abilities of the selected players. They must not affect a ranking
    whose purpose is to say which tactic best suits the squad.
    """
    roles = tuple(
        catalogue.roles[assignment.intrinsic_role_score.role_key]
        for assignment in assignments
    )
    coherence = assess_coherence(tactic, roles)
    instruction = assess_instruction_suitability(roles, tactic.instructions)
    opponent_fit = assess_opponent_fit(roles, opponent)
    return coherence, instruction, opponent_fit


def _tactic_fit(
    assignments: tuple[SlotAssignment, ...],
    slot_count: int,
    policy: TacticFitPolicy,
) -> tuple[ScoreBand, ScoreBand, ScoreBand]:
    missing = slot_count - len(assignments)
    if missing < 0:
        raise ValueError("more assignments than tactic slots")

    def component(field: str) -> tuple[float, float, float]:
        values = [getattr(item.selection_score, field) for item in assignments]
        mean = round(sum(values) / slot_count, 6)
        weakest = min(values) if values and not missing else 0.0
        fit = round(
            (1 - policy.weakest_slot_weight) * mean
            + policy.weakest_slot_weight * weakest,
            6,
        )
        return mean, weakest, fit

    lower = component("lower")
    central = component("central")
    upper = component("upper")
    mean = ScoreBand(lower[0], central[0], upper[0])
    weakest = ScoreBand(lower[1], central[1], upper[1])
    fit = ScoreBand(lower[2], central[2], upper[2])
    return mean, weakest, fit
