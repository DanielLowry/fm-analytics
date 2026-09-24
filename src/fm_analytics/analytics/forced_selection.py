"""Public constrained XI evaluation used for selection explanations."""

from __future__ import annotations

from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticDefinition
from fm_analytics.analytics.opponent import OpponentProfile
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    TacticEvaluation,
    TacticFitPolicy,
)
from fm_analytics.analytics.xi_selection import _evaluate_tactic


def evaluate_tactic_with_forced_assignment(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    slot_key: str,
    player_id: str,
    role_key: str,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
) -> TacticEvaluation:
    """Re-optimise the other ten slots with one player locked into one role."""
    slot_indexes = [
        index for index, slot in enumerate(tactic.slots) if slot.key == slot_key
    ]
    if not slot_indexes:
        raise ValueError(f"unknown tactic slot {slot_key!r}")
    slot_index = slot_indexes[0]
    if role_key not in catalogue.role_keys_for_slot(tactic.slots[slot_index]):
        raise ValueError(f"role {role_key!r} is not allowed for slot {slot_key!r}")
    return _evaluate_tactic(
        tactic,
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy,
        fit_policy=fit_policy,
        opponent=opponent,
        forced_assignment=(slot_index, player_id, role_key),
    )
