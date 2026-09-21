"""Exact player-to-slot assignment for one fixed role version.

For a fixed set of roles (one per slot) a player's score in a slot does not
depend on the other ten selected, so choosing the XI is a standard one-player-per-
slot assignment problem, solved exactly here rather than by enumerating XIs or
keeping a beam of partial ones. `best_assignment_for_role_version` is the entry
point; `xi_selection` calls it once per permitted role version and then scores
that version's team system.

This is exact only while a slot's score is independent of who fills the others.
A feature that couples players (a rule about the group, such as "at least one
midfielder with passing 12") would break that, and the solver would need
revisiting rather than being quietly treated as independent.
"""

from __future__ import annotations

from typing import Sequence

from fm_analytics.analytics.xi_models import (
    TacticFitPolicy,
    _AssignmentState,
    _CandidateAssignment,
)


def state_signature(state: _AssignmentState) -> tuple[tuple[int, str, str], ...]:
    return tuple(
        (
            choice.slot_index,
            choice.assignment.player_id,
            choice.assignment.intrinsic_role_score.role_key,
        )
        for choice in sorted(state.assignments, key=lambda item: item.slot_index)
    )


def best_assignment_for_role_version(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    full_mask: int,
    policy: TacticFitPolicy,
) -> _AssignmentState:
    """Return the exact best full XI, or the best explainable partial XI."""
    full = _best_full_fit_assignment(choices, full_mask, policy)
    if full is not None:
        return full
    return _best_partial_assignment(
        choices, slot_count=full_mask.bit_count()
    )[1]


def _best_full_fit_assignment(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    full_mask: int,
    policy: TacticFitPolicy,
) -> _AssignmentState | None:
    """Optimize the mean/weakest blend without enumerating full XIs.

    For each possible weakest score, an exact assignment solver finds the
    highest-total XI that clears it. That candidate dominates every other XI
    with the same or a higher weakest score, so this covers the full objective
    without listing player combinations.
    """
    slot_count = full_mask.bit_count()
    best = _maximum_total_assignment(
        choices, slot_count=slot_count, minimum_score=0
    )
    if best is None:
        return None

    def key(state: _AssignmentState) -> tuple[float, float, tuple[tuple[int, str, str], ...]]:
        weakest = min(
            choice.assignment.selection_score.central for choice in state.assignments
        )
        fit = round(
            (1 - policy.weakest_slot_weight) * state.total / slot_count
            + policy.weakest_slot_weight * weakest,
            6,
        )
        return -fit, -state.total, state_signature(state)

    best_key = key(best)
    thresholds = sorted({
        choice.assignment.selection_score.central
        for player_choices in choices
        for choice in player_choices
        if choice.assignment.selection_score.central > 0
    })
    for threshold in thresholds:
        candidate = _maximum_total_assignment(
            choices, slot_count=slot_count, minimum_score=threshold
        )
        if candidate is None:
            break
        candidate_key = key(candidate)
        if candidate_key < best_key:
            best, best_key = candidate, candidate_key
    return best


def _maximum_total_assignment(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    *,
    slot_count: int,
    minimum_score: float,
) -> _AssignmentState | None:
    """Find the highest-total legal full XI above a score floor.

    The Hungarian assignment algorithm solves the fixed-role problem directly:
    every slot gets one player, and no player can be selected twice.  It is
    polynomial in the small player/slot score table rather than exponential in
    the number of possible XIs.
    """
    if slot_count == 0 or len(choices) < slot_count:
        return None
    by_slot = _choices_by_slot(
        choices, slot_count=slot_count, minimum_score=minimum_score
    )
    if any(not candidates for candidates in by_slot):
        return None

    highest_score = max(
        choice.assignment.selection_score.central
        for candidates in by_slot
        for choice in candidates.values()
    )
    costs: list[list[float | None]] = [
        [
            (
                round(
                    highest_score
                    - candidates[player_index].assignment.selection_score.central,
                    6,
                )
                if player_index in candidates
                else None
            )
            for player_index in range(len(choices))
        ]
        for candidates in by_slot
    ]
    player_indexes = _minimum_cost_full_assignment(costs)
    if player_indexes is None:
        return None
    assignments = tuple(
        by_slot[slot_index][player_index]
        for slot_index, player_index in enumerate(player_indexes)
    )
    return _AssignmentState(
        total=round(
            sum(choice.assignment.selection_score.central for choice in assignments), 6
        ),
        assignments=assignments,
    )


def _best_partial_assignment(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    *,
    slot_count: int,
) -> tuple[int, _AssignmentState]:
    """Find the best incomplete XI when a legal XI cannot be filled.

    Empty dummy assignments let the same solver maximize filled slots first,
    then player score. This keeps incomplete tactic results useful without
    returning to exponential partial-XI enumeration.
    """
    by_slot = _choices_by_slot(choices, slot_count=slot_count, minimum_score=0)
    player_count = len(choices)
    best_possible_total = sum(
        max(
            (choice.assignment.selection_score.central for choice in candidates.values()),
            default=0.0,
        )
        for candidates in by_slot
    )
    filled_slot_bonus = best_possible_total + 1
    highest_weight = filled_slot_bonus + max(
        (
            choice.assignment.selection_score.central
            for candidates in by_slot
            for choice in candidates.values()
        ),
        default=0.0,
    )
    # Every row can use any dummy column. The number of dummies is the number
    # of slots, so each unfilled slot can remain distinct in the assignment.
    costs: list[list[float | None]] = [
        [
            (
                round(
                    highest_weight
                    - filled_slot_bonus
                    - candidates[player_index].assignment.selection_score.central,
                    6,
                )
                if player_index in candidates
                else None
            )
            for player_index in range(player_count)
        ]
        + [highest_weight] * slot_count
        for candidates in by_slot
    ]
    selected_indexes = _minimum_cost_full_assignment(costs)
    if selected_indexes is None:  # Dummy columns make this defensive only.
        return 0, _AssignmentState(0, ())
    assignments = tuple(
        by_slot[slot_index][player_index]
        for slot_index, player_index in enumerate(selected_indexes)
        if player_index < player_count and player_index in by_slot[slot_index]
    )
    mask = sum(1 << choice.slot_index for choice in assignments)
    return mask, _AssignmentState(
        total=round(
            sum(choice.assignment.selection_score.central for choice in assignments), 6
        ),
        assignments=assignments,
    )


def _choices_by_slot(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    *,
    slot_count: int,
    minimum_score: float,
) -> list[dict[int, _CandidateAssignment]]:
    by_slot: list[dict[int, _CandidateAssignment]] = [dict() for _ in range(slot_count)]
    for player_choices in choices:
        for choice in player_choices:
            if choice.assignment.selection_score.central >= minimum_score:
                by_slot[choice.slot_index][choice.player_index] = choice
    return by_slot


def _minimum_cost_full_assignment(
    costs: Sequence[Sequence[float | None]],
) -> tuple[int, ...] | None:
    """Return one minimum-cost distinct-column choice for every row.

    ``None`` represents an illegal player/slot pairing. Rows are tactic slots
    and columns are players; tactics have eleven rows, so this stays tiny even
    for a large squad.
    """
    row_count = len(costs)
    column_count = len(costs[0]) if costs else 0
    if row_count > column_count or any(len(row) != column_count for row in costs):
        return None
    infinity = float("inf")
    potential_rows = [0.0] * (row_count + 1)
    potential_columns = [0.0] * (column_count + 1)
    matched_row_for_column = [0] * (column_count + 1)
    predecessor = [0] * (column_count + 1)

    for row in range(1, row_count + 1):
        matched_row_for_column[0] = row
        column = 0
        minimum = [infinity] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[column] = True
            current_row = matched_row_for_column[column]
            delta = infinity
            next_column = 0
            for candidate_column in range(1, column_count + 1):
                if used[candidate_column]:
                    continue
                cost = costs[current_row - 1][candidate_column - 1]
                if cost is not None:
                    reduced = (
                        cost
                        - potential_rows[current_row]
                        - potential_columns[candidate_column]
                    )
                    if reduced < minimum[candidate_column]:
                        minimum[candidate_column] = reduced
                        predecessor[candidate_column] = column
                if minimum[candidate_column] < delta:
                    delta = minimum[candidate_column]
                    next_column = candidate_column
            if delta == infinity:
                return None
            for candidate_column in range(column_count + 1):
                if used[candidate_column]:
                    potential_rows[matched_row_for_column[candidate_column]] += delta
                    potential_columns[candidate_column] -= delta
                else:
                    minimum[candidate_column] -= delta
            column = next_column
            if matched_row_for_column[column] == 0:
                break
        while True:
            previous_column = predecessor[column]
            matched_row_for_column[column] = matched_row_for_column[previous_column]
            column = previous_column
            if column == 0:
                break

    assignment = [-1] * row_count
    for column in range(1, column_count + 1):
        if matched_row_for_column[column]:
            assignment[matched_row_for_column[column] - 1] = column - 1
    if any(
        column < 0 or costs[row][column] is None
        for row, column in enumerate(assignment)
    ):
        return None
    return tuple(assignment)
