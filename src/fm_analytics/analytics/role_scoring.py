from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Mapping

from fm_analytics.domain import AttributeObservation
from fm_analytics.domain.models import Visibility


class AttributePriority(StrEnum):
    REQUIRED = "required"
    DESIRABLE = "desirable"


@dataclass(frozen=True)
class RoleAttribute:
    name: str
    weight: float
    priority: AttributePriority

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("role attribute name must not be empty")
        if not isfinite(self.weight) or self.weight <= 0:
            raise ValueError("role attribute weight must be finite and positive")


@dataclass(frozen=True)
class RoleDefinition:
    key: str
    name: str
    eligible_positions: tuple[str, ...]
    attributes: tuple[RoleAttribute, ...]
    catalogue_version: str

    def __post_init__(self) -> None:
        if not self.key or not self.name or not self.catalogue_version:
            raise ValueError("role key, name, and catalogue version are required")
        if not self.eligible_positions:
            raise ValueError("a role requires at least one eligible position")
        if not self.attributes:
            raise ValueError("a role requires at least one weighted attribute")
        attribute_names = [attribute.name for attribute in self.attributes]
        if len(attribute_names) != len(set(attribute_names)):
            raise ValueError("role attribute names must be unique")


@dataclass(frozen=True)
class ScoringPolicy:
    version: str = "role-score-v1"
    scale_minimum: int = 1
    scale_maximum: int = 20
    unknown_central: int = 1

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("scoring policy version is required")
        if self.scale_minimum >= self.scale_maximum:
            raise ValueError("scoring scale minimum must be below maximum")
        if not self.scale_minimum <= self.unknown_central <= self.scale_maximum:
            raise ValueError("unknown central value must be within the scoring scale")


@dataclass(frozen=True)
class ScoreBand:
    lower: float
    central: float
    upper: float

    def __post_init__(self) -> None:
        if not self.lower <= self.central <= self.upper:
            raise ValueError("score band must be ordered lower, central, upper")


@dataclass(frozen=True)
class AttributeContribution:
    attribute: str
    priority: AttributePriority
    weight: float
    supplied: bool
    observation: AttributeObservation
    raw: ScoreBand
    points: ScoreBand

    @property
    def uncertainty_span(self) -> float:
        return self.points.upper - self.points.lower


@dataclass(frozen=True)
class RoleScore:
    role_key: str
    role_name: str
    catalogue_version: str
    scoring_version: str
    score: ScoreBand
    contributions: tuple[AttributeContribution, ...]

    @property
    def information_gaps(self) -> tuple[AttributeContribution, ...]:
        """Return uncertain inputs ordered by potential effect on this score."""

        gaps = (
            contribution
            for contribution in self.contributions
            if contribution.observation.visibility is not Visibility.KNOWN
        )
        return tuple(
            sorted(
                gaps,
                key=lambda item: (-item.uncertainty_span, item.attribute),
            )
        )


def is_position_eligible(
    role: RoleDefinition, player_positions: tuple[str, ...]
) -> bool:
    """Check eligibility without folding familiarity into intrinsic quality."""

    return bool(set(role.eligible_positions).intersection(player_positions))


def score_role(
    role: RoleDefinition,
    observations: Mapping[str, AttributeObservation],
    *,
    policy: ScoringPolicy = ScoringPolicy(),
) -> RoleScore:
    """Score manager-visible observations while retaining their uncertainty.

    Ranged observations use their midpoint only for the central estimate.
    Unknown or absent observations receive the scale minimum centrally, so a
    less-observed player cannot gain an artificial ranking advantage. Their
    upper bound remains the scale maximum to show where more scouting could
    still change a decision.
    """

    total_weight = sum(attribute.weight for attribute in role.attributes)
    contributions: list[AttributeContribution] = []

    for weighted_attribute in role.attributes:
        supplied = weighted_attribute.name in observations
        observation = observations.get(
            weighted_attribute.name,
            AttributeObservation(visibility=Visibility.UNKNOWN),
        )
        raw = _raw_band(observation, policy)
        weight_share = weighted_attribute.weight / total_weight
        points = ScoreBand(
            lower=_score_points(raw.lower, weight_share, policy),
            central=_score_points(raw.central, weight_share, policy),
            upper=_score_points(raw.upper, weight_share, policy),
        )
        contributions.append(
            AttributeContribution(
                attribute=weighted_attribute.name,
                priority=weighted_attribute.priority,
                weight=weighted_attribute.weight,
                supplied=supplied,
                observation=observation,
                raw=raw,
                points=points,
            )
        )

    return RoleScore(
        role_key=role.key,
        role_name=role.name,
        catalogue_version=role.catalogue_version,
        scoring_version=policy.version,
        score=ScoreBand(
            lower=_sum_points(contributions, "lower"),
            central=_sum_points(contributions, "central"),
            upper=_sum_points(contributions, "upper"),
        ),
        contributions=tuple(contributions),
    )


def _raw_band(
    observation: AttributeObservation, policy: ScoringPolicy
) -> ScoreBand:
    if observation.visibility is Visibility.KNOWN:
        assert observation.value is not None
        band = ScoreBand(
            lower=float(observation.value),
            central=float(observation.value),
            upper=float(observation.value),
        )
    elif observation.visibility is Visibility.RANGE:
        assert observation.minimum is not None
        assert observation.maximum is not None
        band = ScoreBand(
            lower=float(observation.minimum),
            central=(observation.minimum + observation.maximum) / 2,
            upper=float(observation.maximum),
        )
    else:
        band = ScoreBand(
            lower=float(policy.scale_minimum),
            central=float(policy.unknown_central),
            upper=float(policy.scale_maximum),
        )

    if band.lower < policy.scale_minimum or band.upper > policy.scale_maximum:
        raise ValueError(
            "attribute observation lies outside the configured scoring scale"
        )
    return band


def _score_points(
    raw_value: float, weight_share: float, policy: ScoringPolicy
) -> float:
    scale_span = policy.scale_maximum - policy.scale_minimum
    normalized = (raw_value - policy.scale_minimum) / scale_span
    return round(normalized * weight_share * 100, 6)


def _sum_points(
    contributions: list[AttributeContribution], field: str
) -> float:
    return round(sum(getattr(item.points, field) for item in contributions), 6)
