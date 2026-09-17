from __future__ import annotations

from typing import Sequence

from fm_analytics.analytics.catalogue import (
    FootballCatalogue,
    TacticDefinition,
    TacticSlot,
)
from fm_analytics.analytics.role_scoring import RoleScore, ScoreBand, score_role
from fm_analytics.analytics.tactical_system import (
    SystemAssessment,
    assess_coherence,
    assess_instruction_suitability,
)
from fm_analytics.domain import Player
from fm_analytics.analytics.xi_models import (
    EffectiveAndPotentialRecommendation,
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    SystemFitPolicy,
    TacticEvaluation,
    TacticFitPolicy,
    TacticRecommendation,
    TrainingTarget,
    _AssignmentState,
    _CandidateAssignment,
    _JointAssignmentState,
)




def evaluate_tactic(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    system_policy: SystemFitPolicy = SystemFitPolicy(),
) -> TacticEvaluation:
    if tactic.key not in catalogue.tactics or catalogue.tactics[tactic.key] != tactic:
        raise ValueError("tactic must belong to the supplied football catalogue")
    player_ids = [player.id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("selection player ids must be unique")

    ordered_players = tuple(sorted(players, key=lambda item: (item.name.casefold(), item.id)))
    choices = _build_choices(
        tactic, ordered_players, catalogue, readiness_policy, familiarity_policy
    )
    full_mask = (1 << len(tactic.slots)) - 1
    has_role_choices = any(
        len(catalogue.role_keys_for_slot(slot)) > 1 for slot in tactic.slots
    )
    if has_role_choices:
        best = _best_joint_role_state(
            tactic, choices, catalogue, fit_policy, system_policy
        )
        best_mask = sum(1 << choice.slot_index for choice in best.assignments)
    else:
        states = _assignment_states(choices)
        best_mask, best = min(
            states.items(),
            key=lambda item: (
                -item[0].bit_count(),
                -item[1].total,
                _state_signature(item[1]),
            ),
        )
        if best_mask == full_mask and fit_policy.weakest_slot_weight:
            best = _best_fit_state(choices, full_mask, fit_policy, best)
    ordered_assignments = tuple(
        choice.assignment
        for choice in sorted(best.assignments, key=lambda item: item.slot_index)
    )
    unfilled = tuple(
        slot
        for index, slot in enumerate(tactic.slots)
        if not best_mask & (1 << index)
    )
    mean_score, weakest_score, xi_score = _tactic_fit(
        ordered_assignments, len(tactic.slots), fit_policy
    )
    coherence, instruction_suitability, fit_score = _system_fit(
        tactic, ordered_assignments, catalogue, xi_score, system_policy
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
        system_version=system_policy.version,
        system_weakest_component_weight=system_policy.weakest_component_weight,
        assignments=ordered_assignments,
        unfilled_slots=unfilled,
        mean_score=mean_score,
        weakest_score=weakest_score,
        weakest_slot_keys=weakest_slot_keys,
        xi_score=xi_score,
        coherence=coherence,
        instruction_suitability=instruction_suitability,
        score=fit_score,
    )


def recommend_tactic(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    system_policy: SystemFitPolicy = SystemFitPolicy(),
) -> TacticRecommendation:
    evaluations = tuple(
        evaluate_tactic(
            tactic,
            players,
            catalogue,
            readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
            fit_policy=fit_policy,
            system_policy=system_policy,
        )
        for tactic in catalogue.tactics.values()
    )
    return TacticRecommendation(
        evaluations=tuple(
            sorted(
                evaluations,
                key=lambda item: (
                    not item.has_legal_xi,
                    -len(item.assignments),
                    -item.score.central,
                    -item.score.lower,
                    item.tactic.key,
                ),
            )
        )
    )


def recommend_tactic_effective_and_potential(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    system_policy: SystemFitPolicy = SystemFitPolicy(),
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
    effective = recommend_tactic(
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy,
        fit_policy=fit_policy,
        system_policy=system_policy,
    )
    potential = recommend_tactic(
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy.potential(),
        fit_policy=fit_policy,
        system_policy=system_policy,
    )
    return EffectiveAndPotentialRecommendation(effective=effective, potential=potential)


def is_player_selectable(
    player: PlayerSelectionInput,
    *,
    policy: ReadinessPolicy = ReadinessPolicy(),
) -> bool:
    return _is_available(player, policy)


def score_player_for_slot(
    player: PlayerSelectionInput,
    slot: TacticSlot,
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    role_key: str | None = None,
) -> SlotAssignment | None:
    """Score a legal player/slot pairing for one allowed role.

    With no `role_key`, return the player's strongest permitted role for this
    slot.  The joint optimiser passes every permitted role explicitly so it
    can trade a little individual quality for a materially better XI system.
    """
    if not _is_available(player, readiness_policy):
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

    def _adjust(raw: float) -> float:
        return round(max(0, round(raw - readiness_penalty, 6)) * familiarity_multiplier, 6)

    assignments = []
    for candidate_role in candidate_roles:
        intrinsic = score_role(catalogue.roles[candidate_role], player.attributes)
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
                    lower=_adjust(intrinsic.score.lower),
                    central=_adjust(intrinsic.score.central),
                    upper=_adjust(intrinsic.score.upper),
                ),
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
    if player.availability != "available" or player.injured is True or player.suspended is True:
        return False
    if (
        player.condition_percent is not None
        and player.condition_percent < policy.minimum_condition
    ):
        return False
    if (
        player.match_fitness_percent is not None
        and player.match_fitness_percent < policy.minimum_match_fitness
    ):
        return False
    return True


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


def _familiarity(
    player: PlayerSelectionInput, slot: TacticSlot, policy: FamiliarityPolicy
) -> tuple[float, tuple[str, ...]]:
    warnings: list[str] = []
    rating = player.position_familiarity.get(slot.position)
    if rating is None:
        rating = policy.unknown_rating
        warnings.append(f"{slot.position} familiarity unknown")
    return policy.multiplier(rating), tuple(warnings)


def _state_is_better(candidate: _AssignmentState, current: _AssignmentState) -> bool:
    if candidate.total != current.total:
        return candidate.total > current.total
    return _state_signature(candidate) < _state_signature(current)


def _state_signature(state: _AssignmentState) -> tuple[tuple[int, str, str], ...]:
    return tuple(
        (
            choice.slot_index,
            choice.assignment.player_id,
            choice.assignment.intrinsic_role_score.role_key,
        )
        for choice in sorted(state.assignments, key=lambda item: item.slot_index)
    )


def _assignment_states(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    *,
    minimum_score: float = 0,
) -> dict[int, _AssignmentState]:
    states: dict[int, _AssignmentState] = {0: _AssignmentState(0, ())}
    for player_choices in choices:
        next_states = dict(states)
        for mask, state in states.items():
            for choice in player_choices:
                score = choice.assignment.selection_score.central
                if score < minimum_score:
                    continue
                bit = 1 << choice.slot_index
                if mask & bit:
                    continue
                candidate = _AssignmentState(
                    total=round(state.total + score, 6),
                    assignments=state.assignments + (choice,),
                )
                next_mask = mask | bit
                current = next_states.get(next_mask)
                if current is None or _state_is_better(candidate, current):
                    next_states[next_mask] = candidate
        states = next_states
    return states


def _best_fit_state(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    full_mask: int,
    policy: TacticFitPolicy,
    mean_best: _AssignmentState,
) -> _AssignmentState:
    """Optimize the central mean/weakest blend over every feasible XI.

    For each distinct candidate score as a possible minimum, the max-total
    assignment under that floor dominates all other assignments with that
    minimum or higher. This is exact for the linear mean/weakest objective.
    """
    best = mean_best
    slot_count = full_mask.bit_count()

    def key(state: _AssignmentState) -> tuple[float, float, tuple[tuple[int, str, str], ...]]:
        weakest = min(
            choice.assignment.selection_score.central for choice in state.assignments
        )
        fit = round(
            (1 - policy.weakest_slot_weight) * state.total / slot_count
            + policy.weakest_slot_weight * weakest,
            6,
        )
        return -fit, -state.total, _state_signature(state)

    best_key = key(best)
    thresholds = sorted({
        choice.assignment.selection_score.central
        for player_choices in choices
        for choice in player_choices
        if choice.assignment.selection_score.central > 0
    })
    for threshold in thresholds:
        candidate = _assignment_states(choices, minimum_score=threshold).get(full_mask)
        if candidate is None:
            break
        candidate_key = key(candidate)
        if candidate_key < best_key:
            best, best_key = candidate, candidate_key
    return best


def _best_joint_role_state(
    tactic: TacticDefinition,
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    catalogue: FootballCatalogue,
    fit_policy: TacticFitPolicy,
    system_policy: SystemFitPolicy,
) -> _AssignmentState:
    """Bounded joint search across slots, players, and allowed roles.

    The old dynamic programme could retain only one state for a slot mask,
    which is valid when every slot has one role but throws away meaningful
    alternatives once role interactions matter.  This deterministic beam
    keeps complete player/role combinations alive until their system score can
    be evaluated.  The bound is explicit in the policy and should be measured
    again before catalogue breadth grows materially.
    """

    by_slot: list[tuple[_CandidateAssignment, ...]] = []
    for slot_index in range(len(tactic.slots)):
        candidates = tuple(
            choice
            for player_choices in choices
            for choice in player_choices
            if choice.slot_index == slot_index
        )
        by_slot.append(candidates)
    slot_order = tuple(sorted(range(len(tactic.slots)), key=lambda index: (len(by_slot[index]), index)))
    states = (_JointAssignmentState(0.0, frozenset(), ()),)
    for step, slot_index in enumerate(slot_order):
        expanded: list[_JointAssignmentState] = list(states)  # Allow an explainable partial XI.
        for state in states:
            for choice in by_slot[slot_index]:
                if choice.player_index in state.player_indexes:
                    continue
                expanded.append(
                    _JointAssignmentState(
                        total=round(state.total + choice.assignment.selection_score.central, 6),
                        player_indexes=state.player_indexes | {choice.player_index},
                        assignments=state.assignments + (choice,),
                    )
                )
        ranked = sorted(
            expanded,
            key=lambda state: (
                -len(state.assignments),
                -state.total,
                -min(
                    (choice.assignment.selection_score.central for choice in state.assignments),
                    default=0.0,
                ),
                _joint_state_signature(state),
            ),
        )
        if step == len(slot_order) - 1:
            # A flat top-K cut here would keep only whichever role scores
            # best on individual fit, discarding an alternate role for this
            # same slot that a downstream coherence/instruction check might
            # actually prefer (e.g. a "runner" over a "creator" up front).
            # Keep the best few states for *each* role choice at this slot
            # instead, so that trade-off is still visible when we score
            # coherence below, without carrying forward every combination.
            grouped: dict[str | None, list[_JointAssignmentState]] = {}
            for state in ranked:
                role_key = next(
                    (
                        choice.assignment.intrinsic_role_score.role_key
                        for choice in state.assignments
                        if choice.slot_index == slot_index
                    ),
                    None,
                )
                grouped.setdefault(role_key, []).append(state)
            states = tuple(
                state
                for group in grouped.values()
                for state in group[: system_policy.role_assignment_beam_width]
            )
        else:
            states = tuple(ranked[: system_policy.role_assignment_beam_width])

    def key(state: _JointAssignmentState) -> tuple[bool, int, float, float, tuple[tuple[int, str, str], ...]]:
        assignments = tuple(
            choice.assignment
            for choice in sorted(state.assignments, key=lambda item: item.slot_index)
        )
        _, _, xi_score = _tactic_fit(assignments, len(tactic.slots), fit_policy)
        _, _, overall = _system_fit(tactic, assignments, catalogue, xi_score, system_policy)
        return (
            len(assignments) != len(tactic.slots),
            -len(assignments),
            -overall.central,
            -xi_score.central,
            _joint_state_signature(state),
        )

    best = min(states, key=key)
    return _AssignmentState(best.total, best.assignments)


def _joint_state_signature(
    state: _JointAssignmentState,
) -> tuple[tuple[int, str, str], ...]:
    return tuple(
        (
            choice.slot_index,
            choice.assignment.player_id,
            choice.assignment.intrinsic_role_score.role_key,
        )
        for choice in sorted(state.assignments, key=lambda item: item.slot_index)
    )


def _system_fit(
    tactic: TacticDefinition,
    assignments: tuple[SlotAssignment, ...],
    catalogue: FootballCatalogue,
    xi_score: ScoreBand,
    policy: SystemFitPolicy,
) -> tuple[SystemAssessment, SystemAssessment, ScoreBand]:
    roles = tuple(
        catalogue.roles[assignment.intrinsic_role_score.role_key]
        for assignment in assignments
    )
    coherence = assess_coherence(tactic, roles)
    instruction = assess_instruction_suitability(roles, tactic.instructions)

    def component(xi_value: float) -> float:
        weighted: list[tuple[float, float]] = [(xi_value, policy.xi_weight)]
        if coherence.active:
            weighted.append((coherence.score, policy.coherence_weight))
        if instruction.active:
            weighted.append((instruction.score, policy.instruction_weight))
        total_weight = sum(weight for _, weight in weighted)
        mean = sum(value * weight for value, weight in weighted) / total_weight
        weakest = min(value for value, _ in weighted)
        return round(
            (1 - policy.weakest_component_weight) * mean
            + policy.weakest_component_weight * weakest,
            6,
        )

    return coherence, instruction, ScoreBand(
        component(xi_score.lower),
        component(xi_score.central),
        component(xi_score.upper),
    )


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
