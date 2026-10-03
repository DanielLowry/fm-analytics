"""Best-XI bounds for one roster, using the shared player and tactic scorer.

Bounds are conditional on supplied eligibility and selection policies. Roster
and position evidence must be supplied by the caller; player-search membership
alone cannot establish either. This module never acquires player knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleScoreCache, ScoreBand
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SelectionObjective,
    TacticFitPolicy,
    TacticRecommendation,
)
from fm_analytics.analytics.xi_selection import recommend_tactic


class TeamComparisonStatus(StrEnum):
    READY = "ready"
    ROSTER_INCOMPLETE = "roster_incomplete"
    POSITIONS_INCOMPLETE = "positions_incomplete"
    NO_LEGAL_XI = "no_legal_xi"


@dataclass(frozen=True)
class TeamXIComparison:
    status: TeamComparisonStatus
    catalogue_version: str
    tactic_keys: tuple[str, ...]
    lower: TacticRecommendation
    central: TacticRecommendation
    upper: TacticRecommendation

    @property
    def score(self) -> ScoreBand | None:
        """The team's band, rather than the band of its displayed central XI."""
        if self.status is not TeamComparisonStatus.READY:
            return None
        return ScoreBand(
            lower=self.lower.selected.score.lower,
            central=self.central.selected.score.central,
            upper=self.upper.selected.score.upper,
        )


def compare_team_xi(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    roster_complete: bool,
    positions_complete: bool,
    tactic_keys: Sequence[str] | None = None,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> TeamXIComparison:
    """Reselect players, roles, and tactics at each end of the observed bands.

    A neutral opponent is used for all scenarios. Partial rosters and unknown
    positions still yield explainable selections, but never a comparable team
    score. Missing attributes are handled by the existing broad score bands.
    """
    if not isinstance(roster_complete, bool) or not isinstance(positions_complete, bool):
        raise ValueError("roster and position completeness must be explicit booleans")
    keys = tuple(catalogue.tactics) if tactic_keys is None else tuple(tactic_keys)
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("comparison requires a non-empty set of unique tactic keys")
    unknown = set(keys) - catalogue.tactics.keys()
    if unknown:
        raise ValueError(f"unknown comparison tactics: {', '.join(sorted(unknown))}")
    comparison_catalogue = replace(catalogue, tactics={key: catalogue.tactics[key] for key in keys})
    players = tuple(players)
    cache = RoleScoreCache()
    recommendations = {
        objective: recommend_tactic(
            players,
            comparison_catalogue,
            readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
            fit_policy=fit_policy,
            role_score_cache=cache,
            objective=objective,
        )
        for objective in SelectionObjective
    }
    if not roster_complete:
        status = TeamComparisonStatus.ROSTER_INCOMPLETE
    elif not positions_complete or any(not player.positions for player in players):
        status = TeamComparisonStatus.POSITIONS_INCOMPLETE
    elif not all(item.selected.has_legal_xi for item in recommendations.values()):
        status = TeamComparisonStatus.NO_LEGAL_XI
    else:
        status = TeamComparisonStatus.READY
    return TeamXIComparison(
        status=status,
        catalogue_version=catalogue.version,
        tactic_keys=keys,
        lower=recommendations[SelectionObjective.LOWER],
        central=recommendations[SelectionObjective.CENTRAL],
        upper=recommendations[SelectionObjective.UPPER],
    )
