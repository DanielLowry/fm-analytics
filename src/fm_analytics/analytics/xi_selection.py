from __future__ import annotations

from dataclasses import dataclass
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
    assignments: tuple[SlotAssignment, ...]
    unfilled_slots: tuple[TacticSlot, ...]
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
) -> TacticEvaluation:
    if tactic.key not in catalogue.tactics or catalogue.tactics[tactic.key] != tactic:
        raise ValueError("tactic must belong to the supplied football catalogue")
    player_ids = [player.id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("selection player ids must be unique")

    ordered_players = tuple(sorted(players, key=lambda item: (item.name.casefold(), item.id)))
    choices = _build_choices(tactic, ordered_players, catalogue, readiness_policy)
    states: dict[int, _AssignmentState] = {0: _AssignmentState(0, ())}
    for player_index in range(len(ordered_players)):
        next_states = dict(states)
        for mask, state in states.items():
            for choice in choices[player_index]:
                bit = 1 << choice.slot_index
                if mask & bit:
                    continue
                candidate = _AssignmentState(
                    total=round(state.total + choice.assignment.selection_score.central, 6),
                    assignments=state.assignments + (choice,),
                )
                next_mask = mask | bit
                current = next_states.get(next_mask)
                if current is None or _state_is_better(candidate, current):
                    next_states[next_mask] = candidate
        states = next_states

    best_mask, best = min(
        states.items(),
        key=lambda item: (
            -item[0].bit_count(),
            -item[1].total,
            _state_signature(item[1]),
        ),
    )
    ordered_assignments = tuple(
        choice.assignment
        for choice in sorted(best.assignments, key=lambda item: item.slot_index)
    )
    unfilled = tuple(
        slot
        for index, slot in enumerate(tactic.slots)
        if not best_mask & (1 << index)
    )
    return TacticEvaluation(
        tactic=tactic,
        readiness_version=readiness_policy.version,
        assignments=ordered_assignments,
        unfilled_slots=unfilled,
        score=_tactic_score(ordered_assignments),
    )


def recommend_tactic(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
) -> TacticRecommendation:
    evaluations = tuple(
        evaluate_tactic(
            tactic,
            players,
            catalogue,
            readiness_policy=readiness_policy,
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


def _tactic_score(assignments: tuple[SlotAssignment, ...]) -> ScoreBand:
    divisor = 11
    return ScoreBand(
        lower=round(sum(item.selection_score.lower for item in assignments) / divisor, 6),
        central=round(
            sum(item.selection_score.central for item in assignments) / divisor,
            6,
        ),
        upper=round(sum(item.selection_score.upper for item in assignments) / divisor, 6),
    )
