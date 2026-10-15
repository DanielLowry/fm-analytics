"""Shared player-job model for set-piece routine builders."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from fm_analytics.analytics.role_scoring import RoleAttribute, RoleDefinition, RoleScore, score_role
from fm_analytics.analytics.set_piece_config import JobWeights, SET_PIECE_WEIGHTS
from fm_analytics.domain import Player

SET_PIECE_SCORING_VERSION = SET_PIECE_WEIGHTS.version


@dataclass(frozen=True)
class RoutineRole:
    """One mutually exclusive player job inside a set-piece routine."""

    key: str
    name: str
    unit: str
    zone: str
    instruction: str
    explanation: str
    attributes: tuple[RoleAttribute, ...]
    priority: int = 50
    goalkeeper: bool = False
    taker_task_key: str | None = None
    # Multiplies the job's contribution to the whole-routine objective. This
    # is separate from priority, which selects jobs on a partial player feed.
    importance: float = 1.0

    def __post_init__(self) -> None:
        if not isfinite(self.importance) or self.importance <= 0:
            raise ValueError("routine role importance must be finite and positive")

    def score(self, player: Player) -> RoleScore:
        profile = RoleDefinition(
            key=f"set_piece_routine_{self.key}",
            name=self.name,
            eligible_positions=("set-piece",),
            attributes=self.attributes,
            catalogue_version=SET_PIECE_SCORING_VERSION,
        )
        return score_role(profile, player.attributes)


def _role(
    key: str, name: str, unit: str, zone: str, instruction: str,
    explanation: str, weights: JobWeights, *,
    priority: int = 50, goalkeeper: bool = False,
    taker_task_key: str | None = None,
) -> RoutineRole:
    return RoutineRole(
        key, name, unit, zone, instruction, explanation, weights.attributes,
        priority, goalkeeper, taker_task_key, weights.importance,
    )
