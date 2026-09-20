"""Manager-facing eligibility checks shared by selection views."""

from __future__ import annotations

from fm_analytics.analytics.xi_models import PlayerSelectionInput, ReadinessPolicy


def selection_unavailability_reasons(
    player: PlayerSelectionInput, policy: ReadinessPolicy
) -> tuple[str, ...]:
    """Return why a player cannot be selected today, if anything."""
    reasons: list[str] = []
    if player.availability != "available":
        reasons.append(f"availability is {player.availability}")
    if player.injured is True:
        reasons.append("injured")
    if player.suspended is True:
        reasons.append("suspended")
    if player.condition_percent is not None and player.condition_percent < policy.minimum_condition:
        reasons.append(f"condition {player.condition_percent}% is below {policy.minimum_condition}%")
    if (
        player.match_fitness_percent is not None
        and player.match_fitness_percent < policy.minimum_match_fitness
    ):
        reasons.append(
            f"match fitness {player.match_fitness_percent}% is below "
            f"{policy.minimum_match_fitness}%"
        )
    return tuple(reasons)
