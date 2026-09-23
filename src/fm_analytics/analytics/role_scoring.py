from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping

from fm_analytics.domain import AttributeObservation
from fm_analytics.domain.models import Visibility


@dataclass(frozen=True)
class RoleAttribute:
    name: str
    weight: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("role attribute name must not be empty")
        if not isfinite(self.weight) or self.weight < 0:
            raise ValueError("role attribute weight must be finite and non-negative")


@dataclass(frozen=True)
class RoleDefinition:
    key: str
    name: str
    eligible_positions: tuple[str, ...]
    attributes: tuple[RoleAttribute, ...]
    catalogue_version: str
    # A compact, explainable description of what the role contributes to a
    # team system (width, cover, progression, ...).  The first catalogue uses
    # a POC fallback profile for its existing roles, but keeping this on the
    # role model lets future catalogue versions declare the contribution as
    # data rather than burying tactical judgement in the optimiser.
    system_traits: Mapping[str, float] = field(default_factory=dict)

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
        for name, value in self.system_traits.items():
            if not isinstance(name, str) or not name:
                raise ValueError("system trait names must be non-empty strings")
            if not isfinite(value) or value < 0:
                raise ValueError("system trait values must be finite and non-negative")


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
    # The score if every unknown attribute were mid-scale and every range sat at
    # its midpoint. ``score.central`` deliberately treats an unknown as the scale
    # minimum, so a barely-scouted player cannot outrank a well-known one; this
    # is the neutral counterpart used to rank *what to scout next*, where the
    # question is "what could this player be worth?" rather than "what do we
    # know he is worth?". Always between ``score.lower`` and ``score.upper``.
    median: float = 0.0

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


class RoleScoreCache:
    """Short-lived cache for immutable role-score inputs.

    A score contains detailed evidence as well as its numeric band, so sharing
    it is safe only when the scoring-relevant role fields and exact observation
    mapping are unchanged.  Callers create this per recommendation build; it
    intentionally has no cross-request lifetime.
    """

    def __init__(self) -> None:
        self._scores: dict[
            tuple[tuple[str, str, str, tuple[RoleAttribute, ...]], int, ScoringPolicy],
            tuple[Mapping[str, AttributeObservation], RoleScore],
        ] = {}

    @staticmethod
    def _role_key(role: RoleDefinition) -> tuple[str, str, str, tuple[RoleAttribute, ...]]:
        # System traits do not influence `score_role`; including them would
        # prevent safe reuse of two independently-derived but identically
        # weighted views of the same role.
        return role.key, role.name, role.catalogue_version, role.attributes

    def get(
        self,
        role: RoleDefinition,
        observations: Mapping[str, AttributeObservation],
        policy: ScoringPolicy,
    ) -> RoleScore | None:
        entry = self._scores.get((self._role_key(role), id(observations), policy))
        if entry is None:
            return None
        cached_observations, score = entry
        return score if cached_observations is observations else None

    def put(
        self,
        role: RoleDefinition,
        observations: Mapping[str, AttributeObservation],
        policy: ScoringPolicy,
        score: RoleScore,
    ) -> RoleScore:
        self._scores[(self._role_key(role), id(observations), policy)] = (observations, score)
        return score


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
    cache: RoleScoreCache | None = None,
) -> RoleScore:
    """Score manager-visible observations while retaining their uncertainty.

    Ranged observations use their midpoint only for the central estimate.
    Unknown or absent observations receive the scale minimum centrally, so a
    less-observed player cannot gain an artificial ranking advantage. Their
    upper bound remains the scale maximum to show where more scouting could
    still change a decision.
    """

    if cache is not None:
        cached = cache.get(role, observations, policy)
        if cached is not None:
            return cached

    total_weight = sum(attribute.weight for attribute in role.attributes)
    contributions: list[AttributeContribution] = []
    # Each contribution is rounded for display, but the totals below are summed
    # from these unrounded values and rounded once -- the same way `_median_score`
    # does it. Summing pre-rounded terms let the error accumulate, so a fully
    # known player's `lower` drifted off his `median`, and an all-unknown
    # player's `upper` came to 99.999999 instead of 100.
    exact_points: list[ScoreBand] = []

    for weighted_attribute in role.attributes:
        supplied = weighted_attribute.name in observations
        observation = observations.get(
            weighted_attribute.name,
            AttributeObservation(visibility=Visibility.UNKNOWN),
        )
        raw = _raw_band(observation, policy)
        weight_share = weighted_attribute.weight / total_weight
        exact = ScoreBand(
            lower=_score_points(raw.lower, weight_share, policy),
            central=_score_points(raw.central, weight_share, policy),
            upper=_score_points(raw.upper, weight_share, policy),
        )
        exact_points.append(exact)
        points = ScoreBand(
            lower=round(exact.lower, 6),
            central=round(exact.central, 6),
            upper=round(exact.upper, 6),
        )
        contributions.append(
            AttributeContribution(
                attribute=weighted_attribute.name,
                weight=weighted_attribute.weight,
                supplied=supplied,
                observation=observation,
                raw=raw,
                points=points,
            )
        )

    result = RoleScore(
        role_key=role.key,
        role_name=role.name,
        catalogue_version=role.catalogue_version,
        scoring_version=policy.version,
        score=ScoreBand(
            lower=round(sum(band.lower for band in exact_points), 6),
            central=round(sum(band.central for band in exact_points), 6),
            upper=round(sum(band.upper for band in exact_points), 6),
        ),
        contributions=tuple(contributions),
        median=_median_score(role, observations, total_weight, policy),
    )
    return cache.put(role, observations, policy, result) if cache is not None else result


def _median_score(
    role: RoleDefinition,
    observations: Mapping[str, AttributeObservation],
    total_weight: float,
    policy: ScoringPolicy,
) -> float:
    midpoint = (policy.scale_minimum + policy.scale_maximum) / 2
    total = 0.0
    for weighted_attribute in role.attributes:
        observation = observations.get(
            weighted_attribute.name, AttributeObservation(visibility=Visibility.UNKNOWN)
        )
        if observation.visibility is Visibility.KNOWN:
            assert observation.value is not None
            raw = float(observation.value)
        elif observation.visibility is Visibility.RANGE:
            assert observation.minimum is not None and observation.maximum is not None
            raw = (observation.minimum + observation.maximum) / 2
        else:
            raw = midpoint
        scale_span = policy.scale_maximum - policy.scale_minimum
        normalized = (raw - policy.scale_minimum) / scale_span
        total += normalized * (weighted_attribute.weight / total_weight) * 100
    # Rounded once, at the end: rounding each term first (as the banded scores
    # do) lets the error accumulate, giving 50.000001 for an all-unknown player.
    return round(total, 6)


def observation_band(
    observation: AttributeObservation, policy: ScoringPolicy = ScoringPolicy()
) -> ScoreBand:
    """An observation as (lower, central, upper) values on the attribute scale.

    A known value is all three; a scouted range spans its bounds with the
    midpoint central; an unknown value spans the whole scale with the policy's
    unknown-central (the minimum) as its central estimate, so a poorly known
    player cannot look better than a well known one.
    """

    return _raw_band(observation, policy)


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
    return normalized * weight_share * 100
