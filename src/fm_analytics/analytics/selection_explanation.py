"""Evidence for the player allocations made by the XI optimiser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import ScoreBand
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    SystemFitPolicy,
    TacticEvaluation,
    TacticFitPolicy,
)
from fm_analytics.analytics.forced_selection import evaluate_tactic_with_forced_assignment
from fm_analytics.analytics.xi_selection import score_player_for_slot


@dataclass(frozen=True)
class SelectionAlternative:
    """What happens if one other eligible player is locked into this slot."""

    player_id: str
    player_name: str
    assignment: SlotAssignment
    current_slot_key: str | None
    counterfactual_score: ScoreBand
    counterfactual_has_legal_xi: bool
    tactic_score_change: float


@dataclass(frozen=True)
class SlotSelectionExplanation:
    """The chosen player and the strongest alternatives for one exact job."""

    starter: SlotAssignment
    readiness_score_cost: float
    alternatives: tuple[SelectionAlternative, ...]


@dataclass(frozen=True)
class TacticSelectionExplanation:
    slots: tuple[SlotSelectionExplanation, ...]


def explain_tactic_selection(
    evaluation: TacticEvaluation,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    alternative_limit: int = 3,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    system_policy: SystemFitPolicy = SystemFitPolicy(),
) -> TacticSelectionExplanation:
    """Explain each starter with like-for-like and whole-XI comparisons.

    Alternatives are scored in the starter's exact slot and selected role.
    Each of the strongest alternatives is then forced into that job while the
    normal optimiser reallocates every other player.  This distinguishes
    "weaker in this job" from "stronger here, but needed elsewhere".
    """
    if alternative_limit < 0:
        raise ValueError("alternative limit cannot be negative")
    current_slots = {
        assignment.player_id: assignment.slot.key for assignment in evaluation.assignments
    }
    explanations = []
    for starter in evaluation.assignments:
        candidates = []
        for player in players:
            if player.id == starter.player_id:
                continue
            assignment = score_player_for_slot(
                player,
                starter.slot,
                catalogue,
                readiness_policy=readiness_policy,
                familiarity_policy=familiarity_policy,
                role_key=starter.intrinsic_role_score.role_key,
            )
            if assignment is not None:
                candidates.append(assignment)
        candidates.sort(
            key=lambda item: (
                -item.selection_score.central,
                -item.selection_score.lower,
                item.player_name.casefold(),
                item.player_id,
            )
        )
        alternatives = []
        for assignment in candidates[:alternative_limit]:
            counterfactual = evaluate_tactic_with_forced_assignment(
                evaluation.tactic,
                players,
                catalogue,
                slot_key=starter.slot.key,
                player_id=assignment.player_id,
                role_key=starter.intrinsic_role_score.role_key,
                readiness_policy=readiness_policy,
                familiarity_policy=familiarity_policy,
                fit_policy=fit_policy,
                system_policy=system_policy,
            )
            alternatives.append(
                SelectionAlternative(
                    player_id=assignment.player_id,
                    player_name=assignment.player_name,
                    assignment=assignment,
                    current_slot_key=current_slots.get(assignment.player_id),
                    counterfactual_score=counterfactual.score,
                    counterfactual_has_legal_xi=counterfactual.has_legal_xi,
                    tactic_score_change=round(
                        counterfactual.score.central - evaluation.score.central, 6
                    ),
                )
            )
        explanations.append(
            SlotSelectionExplanation(
                starter=starter,
                readiness_score_cost=round(
                    starter.in_position_score.central
                    - starter.selection_score.central,
                    6,
                ),
                alternatives=tuple(alternatives),
            )
        )
    return TacticSelectionExplanation(slots=tuple(explanations))
