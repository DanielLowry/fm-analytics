"""Low-level candidate restrictions for constrained XI comparisons."""

from __future__ import annotations

from fm_analytics.analytics.xi_models import PlayerSelectionInput, _CandidateAssignment


def apply_forced_assignment_choices(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    players: tuple[PlayerSelectionInput, ...],
    forced_assignment: tuple[int, str, str],
) -> tuple[tuple[tuple[_CandidateAssignment, ...], ...], dict[int, str]]:
    """Reserve one slot for one player's exact role in an existing choice table."""
    forced_slot_index, forced_player_id, forced_role_key = forced_assignment
    player_index = next(
        (index for index, player in enumerate(players) if player.id == forced_player_id),
        None,
    )
    if player_index is None:
        raise ValueError(f"unknown selection player {forced_player_id!r}")
    forced_choice = next(
        (
            choice
            for choice in choices[player_index]
            if choice.slot_index == forced_slot_index
            and choice.assignment.intrinsic_role_score.role_key == forced_role_key
        ),
        None,
    )
    if forced_choice is None:
        raise ValueError("forced player is not selectable in the requested slot and role")
    constrained = tuple(
        (forced_choice,)
        if index == player_index
        else tuple(
            choice for choice in player_choices if choice.slot_index != forced_slot_index
        )
        for index, player_choices in enumerate(choices)
    )
    return constrained, {forced_slot_index: forced_role_key}
