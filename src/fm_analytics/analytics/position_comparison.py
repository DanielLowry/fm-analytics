"""Compare every eligible squad member at one specific position and role."""

from __future__ import annotations

from dataclasses import dataclass

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticSlot
from fm_analytics.analytics.selection_status import selection_unavailability_reasons
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
)
from fm_analytics.analytics.xi_selection import score_player_for_slot


@dataclass(frozen=True)
class PositionComparisonEntry:
    """One player's estimate in the selected position."""

    player_id: str
    player_name: str
    assignment: SlotAssignment
    familiarity_rating: int
    familiarity_known: bool
    condition_percent: int | None
    match_fitness_percent: int | None
    unavailability_reasons: tuple[str, ...]

    @property
    def selectable_today(self) -> bool:
        return not self.unavailability_reasons


@dataclass(frozen=True)
class PositionComparison:
    """A like-for-like ranking of players captured for one position."""

    position: str
    requested_role_key: str | None
    requested_role_name: str | None
    available_role_keys: tuple[str, ...]
    entries: tuple[PositionComparisonEntry, ...]
    players_not_captured_for_position: int


def compare_players_at_position(
    players: tuple[PlayerSelectionInput, ...],
    position: str,
    catalogue: FootballCatalogue,
    *,
    role_key: str | None = None,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
) -> PositionComparison:
    """Score each player recorded for ``position`` against the same role choice.

    Without a pinned role, each player is shown in their strongest compatible
    role at the chosen position. Players unavailable today remain visible,
    marked separately so their longer-term position estimate is not hidden.
    """
    compatible_roles = tuple(
        key for key, role in catalogue.roles.items() if position in role.eligible_positions
    )
    if not compatible_roles:
        raise ValueError(f"position {position!r} has no compatible roles")
    if role_key is not None and role_key not in compatible_roles:
        raise ValueError(f"role {role_key!r} is not compatible with position {position!r}")

    comparison_players = tuple(player for player in players if position in player.positions)
    entries = tuple(
        _comparison_entry(
            player,
            position,
            (role_key,) if role_key is not None else compatible_roles,
            catalogue,
            readiness_policy,
            familiarity_policy,
        )
        for player in comparison_players
    )
    return PositionComparison(
        position=position,
        requested_role_key=role_key,
        requested_role_name=catalogue.roles[role_key].name if role_key else None,
        available_role_keys=compatible_roles,
        entries=tuple(
            sorted(
                entries,
                key=lambda entry: (
                    -entry.assignment.in_position_score.central,
                    -entry.assignment.in_position_score.lower,
                    entry.player_name.casefold(),
                ),
            )
        ),
        players_not_captured_for_position=len(players) - len(comparison_players),
    )


def _comparison_entry(
    player: PlayerSelectionInput,
    position: str,
    role_keys: tuple[str, ...],
    catalogue: FootballCatalogue,
    readiness_policy: ReadinessPolicy,
    familiarity_policy: FamiliarityPolicy,
) -> PositionComparisonEntry:
    assignments = []
    for role_key in role_keys:
        assignment = score_player_for_slot(
            player,
            TacticSlot(
                key=f"position-comparison-{position}", position=position, role_key=role_key
            ),
            catalogue,
            readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
            require_selectable=False,
        )
        if assignment is not None:
            assignments.append(assignment)
    if not assignments:
        raise ValueError(f"player {player.id!r} cannot be scored at {position!r}")
    best = min(
        assignments,
        key=lambda item: (
            -item.in_position_score.central,
            -item.in_position_score.lower,
            item.intrinsic_role_score.role_key,
        ),
    )
    return PositionComparisonEntry(
        player_id=player.id,
        player_name=player.name,
        assignment=best,
        familiarity_rating=player.position_familiarity.get(
            position, familiarity_policy.unknown_rating
        ),
        familiarity_known=position in player.position_familiarity,
        condition_percent=player.condition_percent,
        match_fitness_percent=player.match_fitness_percent,
        unavailability_reasons=selection_unavailability_reasons(player, readiness_policy),
    )
