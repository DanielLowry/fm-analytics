from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence

from fm_analytics.analytics.catalogue import (
    FootballCatalogue,
    TacticDefinition,
    TacticSlot,
)
from fm_analytics.analytics.role_scoring import RoleScore, ScoreBand, score_role
from fm_analytics.domain import AttributeObservation, Player


@dataclass(frozen=True)
class PlayerSelectionInput:
    id: str
    name: str
    positions: tuple[str, ...]
    attributes: Mapping[str, AttributeObservation]
    availability: str
    injured: bool | None
    suspended: bool | None
    condition_percent: int | None
    match_fitness_percent: int | None

    @classmethod
    def from_player(cls, player: Player) -> PlayerSelectionInput:
        return cls(
            id=player.id,
            name=player.name,
            positions=player.positions,
            attributes=player.attributes,
            availability=player.availability,
            injured=player.injured,
            suspended=player.suspended,
            condition_percent=player.condition_percent,
            match_fitness_percent=player.match_fitness_percent,
        )


@dataclass(frozen=True)
class ReadinessPolicy:
    version: str = "readiness-v1"
    minimum_condition: int = 65
    minimum_match_fitness: int = 50
    unknown_percent: int = 70
    condition_penalty_weight: float = 0.25
    match_fitness_penalty_weight: float = 0.10

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("readiness policy version is required")
        for name, value in (
            ("minimum_condition", self.minimum_condition),
            ("minimum_match_fitness", self.minimum_match_fitness),
            ("unknown_percent", self.unknown_percent),
        ):
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.condition_penalty_weight < 0 or self.match_fitness_penalty_weight < 0:
            raise ValueError("readiness penalty weights cannot be negative")


@dataclass(frozen=True)
class TacticFitPolicy:
    """Balance whole-XI quality against the weakest starting slot."""

    version: str = "tactic-fit-v1"
    weakest_slot_weight: float = 0.35

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("tactic-fit policy version is required")
        if not isfinite(self.weakest_slot_weight) or not 0 <= self.weakest_slot_weight <= 1:
            raise ValueError("weakest-slot weight must be finite and between 0 and 1")


@dataclass(frozen=True)
class SlotAssignment:
    slot: TacticSlot
    player_id: str
    player_name: str
    intrinsic_role_score: RoleScore
    readiness_penalty: float
    readiness_warnings: tuple[str, ...]
    selection_score: ScoreBand


@dataclass(frozen=True)
class TacticEvaluation:
    tactic: TacticDefinition
    readiness_version: str
    fit_version: str
    assignments: tuple[SlotAssignment, ...]
    unfilled_slots: tuple[TacticSlot, ...]
    mean_score: ScoreBand
    weakest_score: ScoreBand
    weakest_slot_keys: tuple[str, ...]
    score: ScoreBand

    @property
    def has_legal_xi(self) -> bool:
        return not self.unfilled_slots and len(self.assignments) == 11


@dataclass(frozen=True)
class TacticRecommendation:
    evaluations: tuple[TacticEvaluation, ...]

    @property
    def selected(self) -> TacticEvaluation:
        return self.evaluations[0]


@dataclass(frozen=True)
class _CandidateAssignment:
    slot_index: int
    player_index: int
    assignment: SlotAssignment


@dataclass(frozen=True)
class _AssignmentState:
    total: float
    assignments: tuple[_CandidateAssignment, ...]


def evaluate_tactic(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> TacticEvaluation:
    if tactic.key not in catalogue.tactics or catalogue.tactics[tactic.key] != tactic:
        raise ValueError("tactic must belong to the supplied football catalogue")
    player_ids = [player.id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("selection player ids must be unique")

    ordered_players = tuple(sorted(players, key=lambda item: (item.name.casefold(), item.id)))
    choices = _build_choices(tactic, ordered_players, catalogue, readiness_policy)
    states = _assignment_states(choices)
    best_mask, best = min(
        states.items(),
        key=lambda item: (
            -item[0].bit_count(),
            -item[1].total,
            _state_signature(item[1]),
        ),
    )
    full_mask = (1 << len(tactic.slots)) - 1
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
    mean_score, weakest_score, fit_score = _tactic_fit(
        ordered_assignments, len(tactic.slots), fit_policy
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
        fit_version=fit_policy.version,
        assignments=ordered_assignments,
        unfilled_slots=unfilled,
        mean_score=mean_score,
        weakest_score=weakest_score,
        weakest_slot_keys=weakest_slot_keys,
        score=fit_score,
    )


def recommend_tactic(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> TacticRecommendation:
    evaluations = tuple(
        evaluate_tactic(
            tactic,
            players,
            catalogue,
            readiness_policy=readiness_policy,
            fit_policy=fit_policy,
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
) -> SlotAssignment | None:
    """Score one legal, selectable player/slot pairing."""
    if slot.role_key not in catalogue.roles:
        raise ValueError(f"unknown role {slot.role_key!r}")
    if not _is_available(player, readiness_policy):
        return None
    if slot.position not in player.positions:
        return None
    intrinsic = score_role(catalogue.roles[slot.role_key], player.attributes)
    penalty, warnings = _readiness(player, readiness_policy)
    return SlotAssignment(
        slot=slot,
        player_id=player.id,
        player_name=player.name,
        intrinsic_role_score=intrinsic,
        readiness_penalty=penalty,
        readiness_warnings=warnings,
        selection_score=ScoreBand(
            lower=max(0, round(intrinsic.score.lower - penalty, 6)),
            central=max(0, round(intrinsic.score.central - penalty, 6)),
            upper=max(0, round(intrinsic.score.upper - penalty, 6)),
        ),
    )


def _build_choices(
    tactic: TacticDefinition,
    players: tuple[PlayerSelectionInput, ...],
    catalogue: FootballCatalogue,
    policy: ReadinessPolicy,
) -> tuple[tuple[_CandidateAssignment, ...], ...]:
    choices: list[tuple[_CandidateAssignment, ...]] = []
    for player_index, player in enumerate(players):
        if not _is_available(player, policy):
            choices.append(())
            continue
        player_choices: list[_CandidateAssignment] = []
        for slot_index, slot in enumerate(tactic.slots):
            assignment = score_player_for_slot(
                player,
                slot,
                catalogue,
                readiness_policy=policy,
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


def _state_is_better(candidate: _AssignmentState, current: _AssignmentState) -> bool:
    if candidate.total != current.total:
        return candidate.total > current.total
    return _state_signature(candidate) < _state_signature(current)


def _state_signature(state: _AssignmentState) -> tuple[tuple[int, str], ...]:
    return tuple(
        (choice.slot_index, choice.assignment.player_id)
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

    def key(state: _AssignmentState) -> tuple[float, float, tuple[tuple[int, str], ...]]:
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
    return tuple(
        ScoreBand(lower[index], central[index], upper[index])
        for index in range(3)
    )  # type: ignore[return-value]
