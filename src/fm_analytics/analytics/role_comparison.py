from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fm_analytics.analytics.role_scoring import RoleScore


@dataclass(frozen=True)
class CandidateRoleScore:
    player_id: str
    player_name: str
    role_score: RoleScore

    def __post_init__(self) -> None:
        if not self.player_id or not self.player_name:
            raise ValueError("candidate player id and name are required")


@dataclass(frozen=True)
class ScoutingPriority:
    player_id: str
    player_name: str
    attribute: str
    visibility: str
    supplied: bool
    maximum_score_swing: float


@dataclass(frozen=True)
class RoleComparison:
    role_key: str
    catalogue_version: str
    scoring_version: str
    candidates: tuple[CandidateRoleScore, ...]
    decision_certain: bool
    scouting_priorities: tuple[ScoutingPriority, ...]

    @property
    def selected(self) -> CandidateRoleScore:
        return self.candidates[0]


def compare_role_scores(
    candidates: Sequence[CandidateRoleScore],
) -> RoleComparison:
    """Rank candidates and identify knowledge that could affect the winner.

    Ordering uses the conservative central estimate, then lower and upper
    bounds, followed by stable identity tie-breakers. A decision is certain
    only when the selected candidate's lower bound beats every alternative's
    upper bound. This is interval certainty, not a claim of football truth.
    """

    if not candidates:
        raise ValueError("at least one role candidate is required")
    _validate_comparable(candidates)

    ordered = tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.role_score.score.central,
                -candidate.role_score.score.lower,
                -candidate.role_score.score.upper,
                candidate.player_name.casefold(),
                candidate.player_id,
            ),
        )
    )
    selected = ordered[0]
    alternatives = ordered[1:]
    decision_certain = not alternatives or selected.role_score.score.lower > max(
        candidate.role_score.score.upper for candidate in alternatives
    )

    relevant = (
        ()
        if decision_certain
        else (selected,)
        + tuple(
            candidate
            for candidate in alternatives
            if candidate.role_score.score.upper >= selected.role_score.score.lower
        )
    )
    priorities = tuple(
        sorted(
            (
                ScoutingPriority(
                    player_id=candidate.player_id,
                    player_name=candidate.player_name,
                    attribute=gap.attribute,
                    visibility=gap.observation.visibility.value,
                    supplied=gap.supplied,
                    maximum_score_swing=round(gap.uncertainty_span, 6),
                )
                for candidate in relevant
                for gap in candidate.role_score.information_gaps
            ),
            key=lambda priority: (
                -priority.maximum_score_swing,
                priority.player_name.casefold(),
                priority.attribute,
                priority.player_id,
            ),
        )
    )

    reference = selected.role_score
    return RoleComparison(
        role_key=reference.role_key,
        catalogue_version=reference.catalogue_version,
        scoring_version=reference.scoring_version,
        candidates=ordered,
        decision_certain=decision_certain,
        scouting_priorities=priorities,
    )


def _validate_comparable(candidates: Sequence[CandidateRoleScore]) -> None:
    first = candidates[0].role_score
    expected = (
        first.role_key,
        first.catalogue_version,
        first.scoring_version,
    )
    player_ids: set[str] = set()
    for candidate in candidates:
        actual = (
            candidate.role_score.role_key,
            candidate.role_score.catalogue_version,
            candidate.role_score.scoring_version,
        )
        if actual != expected:
            raise ValueError("role candidates must use the same role and versions")
        if candidate.player_id in player_ids:
            raise ValueError("role candidate player ids must be unique")
        player_ids.add(candidate.player_id)
