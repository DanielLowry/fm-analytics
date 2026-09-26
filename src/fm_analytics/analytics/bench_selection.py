from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.opponent import OpponentProfile, attribute_emphasis
from fm_analytics.analytics.xi_selection import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    TacticEvaluation,
    score_player_for_slot,
)
from fm_analytics.analytics.role_scoring import RoleScoreCache


@dataclass(frozen=True)
class BenchEntry:
    player_id: str
    player_name: str
    primary_assignment: SlotAssignment
    covered_slots: tuple[str, ...]
    newly_covered_slots: tuple[str, ...]


@dataclass(frozen=True)
class BenchSelection:
    policy_version: str
    entries: tuple[BenchEntry, ...]
    covered_slots: tuple[str, ...]
    uncovered_slots: tuple[str, ...]


@dataclass(frozen=True)
class _BenchCandidate:
    player: PlayerSelectionInput
    assignments: tuple[SlotAssignment, ...]


def select_bench(
    evaluation: TacticEvaluation,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    bench_size: int = 7,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
    role_score_cache: RoleScoreCache | None = None,
) -> BenchSelection:
    """Choose selectable non-starters for slot coverage, then playing quality."""
    if bench_size < 0:
        raise ValueError("bench size cannot be negative")
    if (
        evaluation.tactic.key not in catalogue.tactics
        or catalogue.tactics[evaluation.tactic.key] != evaluation.tactic
    ):
        raise ValueError("evaluated tactic must belong to the supplied catalogue")
    catalogue = catalogue.for_context(
        evaluation.tactic.key, extra_emphasis=attribute_emphasis(opponent)
    )
    player_ids = [player.id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("bench player ids must be unique")

    starter_ids = frozenset(item.player_id for item in evaluation.assignments)
    candidates: list[_BenchCandidate] = []
    for player in players:
        if player.id in starter_ids:
            continue
        assignments = tuple(
            assignment
            for slot in evaluation.tactic.slots
            if (
                assignment := score_player_for_slot(
                    player,
                    slot,
                    catalogue,
                    readiness_policy=readiness_policy,
                    familiarity_policy=familiarity_policy,
                    role_score_cache=role_score_cache,
                )
            )
            is not None
        )
        if assignments:
            candidates.append(_BenchCandidate(player, assignments))

    uncovered = {slot.key for slot in evaluation.tactic.slots}
    entries: list[BenchEntry] = []
    goalkeeper_slot_keys = frozenset(
        slot.key for slot in evaluation.tactic.slots if slot.position == "GK"
    )
    if bench_size and goalkeeper_slot_keys:
        goalkeeper_candidates = tuple(
            candidate
            for candidate in candidates
            if any(
                assignment.slot.key in goalkeeper_slot_keys
                for assignment in candidate.assignments
            )
        )
        if goalkeeper_candidates:
            chosen = min(
                goalkeeper_candidates,
                key=lambda candidate: _goalkeeper_order(
                    candidate, goalkeeper_slot_keys
                ),
            )
            entry = _bench_entry(
                chosen,
                uncovered,
                primary_slot_keys=goalkeeper_slot_keys,
            )
            entries.append(entry)
            uncovered.difference_update(entry.covered_slots)
            candidates.remove(chosen)

    while candidates and len(entries) < bench_size:
        chosen = min(
            candidates,
            key=lambda candidate: _candidate_order(candidate, uncovered),
        )
        entry = _bench_entry(chosen, uncovered)
        entries.append(entry)
        uncovered.difference_update(entry.covered_slots)
        candidates.remove(chosen)

    ordered_slots = tuple(slot.key for slot in evaluation.tactic.slots)
    return BenchSelection(
        policy_version="bench-coverage-v2",
        entries=tuple(entries),
        covered_slots=tuple(slot for slot in ordered_slots if slot not in uncovered),
        uncovered_slots=tuple(slot for slot in ordered_slots if slot in uncovered),
    )


def _bench_entry(
    candidate: _BenchCandidate,
    uncovered: set[str],
    *,
    primary_slot_keys: frozenset[str] = frozenset(),
) -> BenchEntry:
    covered = tuple(assignment.slot.key for assignment in candidate.assignments)
    newly_covered = tuple(slot for slot in covered if slot in uncovered)
    primary_options = tuple(
        assignment
        for assignment in candidate.assignments
        if assignment.slot.key in primary_slot_keys
    ) or candidate.assignments
    primary = min(
        primary_options,
        key=lambda assignment: (
            -assignment.selection_score.central,
            -assignment.selection_score.lower,
            assignment.slot.key,
        ),
    )
    return BenchEntry(
        player_id=candidate.player.id,
        player_name=candidate.player.name,
        primary_assignment=primary,
        covered_slots=covered,
        newly_covered_slots=newly_covered,
    )


def _goalkeeper_order(
    candidate: _BenchCandidate,
    goalkeeper_slot_keys: frozenset[str],
) -> tuple[float, float, str, str]:
    best = min(
        (
            assignment
            for assignment in candidate.assignments
            if assignment.slot.key in goalkeeper_slot_keys
        ),
        key=lambda assignment: (
            -assignment.selection_score.central,
            -assignment.selection_score.lower,
            assignment.slot.key,
        ),
    )
    return (
        -best.selection_score.central,
        -best.selection_score.lower,
        candidate.player.name.casefold(),
        candidate.player.id,
    )


def _candidate_order(
    candidate: _BenchCandidate,
    uncovered: set[str],
) -> tuple[int, float, float, str, str]:
    newly_covered = sum(
        assignment.slot.key in uncovered for assignment in candidate.assignments
    )
    best_central = max(
        assignment.selection_score.central for assignment in candidate.assignments
    )
    best_lower = max(
        assignment.selection_score.lower for assignment in candidate.assignments
    )
    return (
        -newly_covered,
        -best_central,
        -best_lower,
        candidate.player.name.casefold(),
        candidate.player.id,
    )
