from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_comparison import (
    CandidateRoleScore,
    RoleComparison,
    compare_role_scores,
)
from fm_analytics.analytics.role_scoring import (
    RoleScore,
    RoleScoreCache,
    ScoringPolicy,
    is_position_eligible,
    score_role,
)
from fm_analytics.analytics.xi_selection import PlayerSelectionInput


@dataclass(frozen=True)
class PlayerRoleFit:
    """One player's score in one role they are position-eligible to play."""

    role_key: str
    role_name: str
    role_score: RoleScore


@dataclass(frozen=True)
class PlayerRoleProfile:
    """Every eligible role for one player, ranked by central score."""

    player_id: str
    player_name: str
    fits: tuple[PlayerRoleFit, ...]

    @property
    def best(self) -> PlayerRoleFit | None:
        return self.fits[0] if self.fits else None


@dataclass(frozen=True)
class RoleMatrix:
    """Every squad member scored in every role they are position-eligible for.

    This answers two of the manager's own questions from the same pass: "who
    is my best left-back" is `role_rankings[role_key]`, and "what is this
    player's best role" is `player_profiles[player_id].best`. Both reuse
    `score_role` and `compare_role_scores` exactly as tactic/XI selection
    does, so a role fit shown here and a role fit shown in a starting XI are
    the same number computed the same way -- this module adds no scoring
    logic of its own, only the cross-product and two lookup shapes over it.

    Eligibility here is position-only, matching `is_position_eligible`
    elsewhere in this codebase: it does not fold in readiness or position
    familiarity, so a listed fit is an intrinsic-quality estimate, not a
    prediction that the player would start there today.
    """

    catalogue_version: str
    scoring_version: str
    role_rankings: Mapping[str, RoleComparison]
    uncovered_roles: tuple[str, ...]
    player_profiles: Mapping[str, PlayerRoleProfile]

    def best_for_role(self, role_key: str) -> CandidateRoleScore | None:
        """The squad's best-fitting player for a role, or None if nobody is eligible."""
        comparison = self.role_rankings.get(role_key)
        return comparison.selected if comparison is not None else None

    def best_role_for_player(self, player_id: str) -> PlayerRoleFit | None:
        """A player's best-fitting eligible role, or None if they have none."""
        profile = self.player_profiles.get(player_id)
        return profile.best if profile is not None else None


def build_role_matrix(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    scoring_policy: ScoringPolicy = ScoringPolicy(),
    role_score_cache: RoleScoreCache | None = None,
) -> RoleMatrix:
    player_ids = [player.id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("role matrix player ids must be unique")

    role_rankings: dict[str, RoleComparison] = {}
    uncovered_roles: list[str] = []
    fits_by_player: dict[str, list[PlayerRoleFit]] = {player.id: [] for player in players}

    for role_key, role in catalogue.roles.items():
        candidates: list[CandidateRoleScore] = []
        for player in players:
            if not is_position_eligible(role, player.positions):
                continue
            role_score = score_role(
                role, player.attributes, policy=scoring_policy, cache=role_score_cache
            )
            candidates.append(
                CandidateRoleScore(
                    player_id=player.id, player_name=player.name, role_score=role_score
                )
            )
            fits_by_player[player.id].append(
                PlayerRoleFit(role_key=role_key, role_name=role.name, role_score=role_score)
            )
        if candidates:
            role_rankings[role_key] = compare_role_scores(candidates)
        else:
            uncovered_roles.append(role_key)

    player_profiles = {
        player.id: PlayerRoleProfile(
            player_id=player.id,
            player_name=player.name,
            fits=tuple(
                sorted(
                    fits_by_player[player.id],
                    key=lambda fit: (
                        -fit.role_score.score.central,
                        -fit.role_score.score.lower,
                        fit.role_name,
                    ),
                )
            ),
        )
        for player in players
    }

    return RoleMatrix(
        catalogue_version=catalogue.version,
        scoring_version=scoring_policy.version,
        role_rankings=role_rankings,
        uncovered_roles=tuple(sorted(uncovered_roles)),
        player_profiles=player_profiles,
    )
