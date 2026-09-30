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
class BenchPolicy:
    """Define when an eligible substitute counts as credible slot cover.

    Eligibility alone is too weak for bench planning: a utility player with a
    very low score in six positions should not make all six look safely
    covered.  A candidate therefore provides credible cover when today's
    selection score is at least this fraction of the selected starter's score.
    The default matches the existing weak-backup threshold.
    """

    version: str = "bench-coverage-v3"
    credible_cover_ratio: float = 0.80

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("bench policy version is required")
        if not 0 < self.credible_cover_ratio <= 1:
            raise ValueError(
                "credible cover ratio must be greater than 0 and at most 1"
            )


@dataclass(frozen=True)
class BenchEntry:
    player_id: str
    player_name: str
    primary_assignment: SlotAssignment
    covered_slots: tuple[str, ...]
    credible_slots: tuple[str, ...]
    newly_covered_slots: tuple[str, ...]
    newly_credible_slots: tuple[str, ...]
    improved_slots: tuple[str, ...]


@dataclass(frozen=True)
class BenchSelection:
    policy_version: str
    credible_cover_ratio: float
    entries: tuple[BenchEntry, ...]
    covered_slots: tuple[str, ...]
    credible_covered_slots: tuple[str, ...]
    weakly_covered_slots: tuple[str, ...]
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
    bench_policy: BenchPolicy = BenchPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
    role_score_cache: RoleScoreCache | None = None,
) -> BenchSelection:
    """Choose non-starters for credible slot cover, then cover quality.

    The configured bench is planned as a complete unit: reserve goalkeeper
    first; each later choice preserves the widest formation-position spread
    still achievable with the places left, then prefers newly credible cover,
    nominally uncovered slots, and improvements to the best cover already on
    the bench. Playing quality and stable player identity break remaining
    ties. A different bench size is recalculated rather than obtained by
    truncating this result.
    """
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

    starter_scores = {
        assignment.slot.key: assignment.selection_score.central
        for assignment in evaluation.assignments
    }
    covered: set[str] = set()
    credible_covered: set[str] = set()
    best_cover_ratios: dict[str, float] = {}
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
                covered,
                credible_covered,
                best_cover_ratios,
                starter_scores,
                bench_policy,
                primary_slot_keys=goalkeeper_slot_keys,
            )
            entries.append(entry)
            _record_cover(
                entry,
                chosen,
                covered,
                credible_covered,
                best_cover_ratios,
                starter_scores,
            )
            candidates.remove(chosen)

    while candidates and len(entries) < bench_size:
        projected_position_coverage = _projected_position_coverage(
            candidates,
            covered,
            evaluation,
            remaining_picks=bench_size - len(entries) - 1,
        )
        chosen = min(
            candidates,
            key=lambda candidate: _candidate_order(
                candidate,
                projected_position_coverage[candidate.player.id],
                covered,
                credible_covered,
                best_cover_ratios,
                starter_scores,
                bench_policy,
            ),
        )
        entry = _bench_entry(
            chosen,
            covered,
            credible_covered,
            best_cover_ratios,
            starter_scores,
            bench_policy,
        )
        entries.append(entry)
        _record_cover(
            entry,
            chosen,
            covered,
            credible_covered,
            best_cover_ratios,
            starter_scores,
        )
        candidates.remove(chosen)

    ordered_slots = tuple(slot.key for slot in evaluation.tactic.slots)
    return BenchSelection(
        policy_version=bench_policy.version,
        credible_cover_ratio=bench_policy.credible_cover_ratio,
        entries=tuple(entries),
        covered_slots=tuple(slot for slot in ordered_slots if slot in covered),
        credible_covered_slots=tuple(
            slot for slot in ordered_slots if slot in credible_covered
        ),
        weakly_covered_slots=tuple(
            slot
            for slot in ordered_slots
            if slot in covered and slot not in credible_covered
        ),
        uncovered_slots=tuple(slot for slot in ordered_slots if slot not in covered),
    )


def _bench_entry(
    candidate: _BenchCandidate,
    covered_so_far: set[str],
    credible_covered: set[str],
    best_cover_ratios: dict[str, float],
    starter_scores: dict[str, float],
    policy: BenchPolicy,
    *,
    primary_slot_keys: frozenset[str] = frozenset(),
) -> BenchEntry:
    covered_slots = tuple(
        assignment.slot.key for assignment in candidate.assignments
    )
    credible = tuple(
        assignment.slot.key
        for assignment in candidate.assignments
        if _cover_ratio(assignment, starter_scores) >= policy.credible_cover_ratio
    )
    newly_covered = tuple(
        slot for slot in covered_slots if slot not in covered_so_far
    )
    newly_credible = tuple(
        slot for slot in credible if slot not in credible_covered
    )
    improved = tuple(
        assignment.slot.key
        for assignment in candidate.assignments
        if _cover_ratio(assignment, starter_scores)
        > best_cover_ratios.get(assignment.slot.key, 0.0)
    )
    focus_slot_keys = (
        primary_slot_keys
        or frozenset(newly_credible)
        or frozenset(newly_covered)
        or frozenset(improved)
    )
    primary_options = tuple(
        assignment
        for assignment in candidate.assignments
        if assignment.slot.key in focus_slot_keys
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
        covered_slots=covered_slots,
        credible_slots=credible,
        newly_covered_slots=newly_covered,
        newly_credible_slots=newly_credible,
        improved_slots=improved,
    )


def _record_cover(
    entry: BenchEntry,
    candidate: _BenchCandidate,
    covered: set[str],
    credible_covered: set[str],
    best_cover_ratios: dict[str, float],
    starter_scores: dict[str, float],
) -> None:
    covered.update(entry.covered_slots)
    credible_covered.update(entry.credible_slots)
    for assignment in candidate.assignments:
        slot_key = assignment.slot.key
        best_cover_ratios[slot_key] = max(
            best_cover_ratios.get(slot_key, 0.0),
            _cover_ratio(assignment, starter_scores),
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
    projected_position_coverage: int,
    covered: set[str],
    credible_covered: set[str],
    best_cover_ratios: dict[str, float],
    starter_scores: dict[str, float],
    policy: BenchPolicy,
) -> tuple[int, int, int, float, float, float, float, str, str]:
    assignment_ratios = tuple(
        (assignment, _cover_ratio(assignment, starter_scores))
        for assignment in candidate.assignments
    )
    newly_credible = sum(
        assignment.slot.key not in credible_covered
        and ratio >= policy.credible_cover_ratio
        for assignment, ratio in assignment_ratios
    )
    newly_covered = sum(
        assignment.slot.key not in covered
        for assignment in candidate.assignments
    )
    cover_quality_gain = sum(
        max(0.0, ratio - best_cover_ratios.get(assignment.slot.key, 0.0))
        for assignment, ratio in assignment_ratios
    )
    weak_cover_quality_gain = sum(
        max(
            0.0,
            min(ratio, policy.credible_cover_ratio)
            - min(
                best_cover_ratios.get(assignment.slot.key, 0.0),
                policy.credible_cover_ratio,
            ),
        )
        for assignment, ratio in assignment_ratios
    )
    best_central = max(
        assignment.selection_score.central for assignment in candidate.assignments
    )
    best_lower = max(
        assignment.selection_score.lower for assignment in candidate.assignments
    )
    return (
        -projected_position_coverage,
        -newly_credible,
        -newly_covered,
        -weak_cover_quality_gain,
        -cover_quality_gain,
        -best_central,
        -best_lower,
        candidate.player.name.casefold(),
        candidate.player.id,
    )


def _projected_position_coverage(
    candidates: Sequence[_BenchCandidate],
    covered_slots: set[str],
    evaluation: TacticEvaluation,
    *,
    remaining_picks: int,
) -> dict[str, int]:
    """Return each next pick's best achievable final position spread.

    This small look-ahead stops locally attractive picks from using the last
    bench place needed for a position only one remaining player can fill. The
    pitch has at most eleven slots, so bit-mask dynamic programming keeps the
    search bounded without enumerating player combinations.
    """
    positions = tuple(dict.fromkeys(slot.position for slot in evaluation.tactic.slots))
    position_bits = {
        position: 1 << index for index, position in enumerate(positions)
    }
    slot_positions = {
        slot.key: slot.position for slot in evaluation.tactic.slots
    }
    covered_mask = 0
    for slot_key in covered_slots:
        covered_mask |= position_bits[slot_positions[slot_key]]
    candidate_masks = {
        candidate.player.id: _candidate_position_mask(candidate, position_bits)
        for candidate in candidates
    }
    future_unions = _coverage_unions(
        tuple(candidate_masks.values()), remaining_picks
    )
    return {
        candidate.player.id: max(
            (covered_mask | candidate_masks[candidate.player.id] | future).bit_count()
            for future in future_unions
        )
        for candidate in candidates
    }


def _candidate_position_mask(
    candidate: _BenchCandidate,
    position_bits: dict[str, int],
) -> int:
    mask = 0
    for assignment in candidate.assignments:
        mask |= position_bits[assignment.slot.position]
    return mask


def _coverage_unions(candidate_masks: tuple[int, ...], picks: int) -> set[int]:
    unions = {0}
    for _ in range(picks):
        unions |= {
            existing | candidate
            for existing in unions
            for candidate in candidate_masks
        }
    return unions


def _cover_ratio(
    assignment: SlotAssignment,
    starter_scores: dict[str, float],
) -> float:
    starter_score = starter_scores.get(assignment.slot.key, 0.0)
    if starter_score <= 0:
        return 1.0
    return assignment.selection_score.central / starter_score
