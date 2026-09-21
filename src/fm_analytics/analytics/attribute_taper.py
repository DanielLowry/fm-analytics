"""Taper a player's slot score where he falls short of a tactic's attribute level.

A weighted average cannot say "this tactic does not work without passing": a
midfielder on passing 4 in a role that gives passing a tenth of its weight loses
about 8% of his score. A tactic can instead name a level (`taperBelow`) for an
attribute; below it the slot score is multiplied by a factor that falls smoothly
with the shortfall.

    factor = max(floor, 1 - penalty_per_point * (level - value))     if value < level
    factor = 1                                                        otherwise

This is a taper, not a cut-off. There is no cliff at the level, and nobody is
ruled out: a player who is short on one attribute but far stronger elsewhere can
still be the best available. Several tapers multiply, and the product never goes
below `combined_floor`, so no player is scored to nothing.

Everything is computed per player and slot, independent of the other ten
selected, which keeps the exact one-player-per-slot assignment in
`xi_selection` exact. (A rule about the group, such as "at least one midfielder
with passing 12", would couple players to each other and would not.)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from fm_analytics.analytics.catalogue import AttributeTaper
from fm_analytics.analytics.role_scoring import (
    RoleScore,
    ScoreBand,
    ScoringPolicy,
    observation_band,
)
from fm_analytics.domain import AttributeObservation
from fm_analytics.domain.models import Visibility


@dataclass(frozen=True)
class AttributeTaperPolicy:
    """How steeply fit tapers away below a tactic's attribute level.

    The defaults were chosen so the penalty is heavy relative to what the
    weighted average already costs a player (a midfielder on passing 4 against a
    level of 12 loses about half his score, where the weights alone cost 8%),
    while a single shortfall never costs more than half.
    """

    version: str = "attribute-taper-v1"
    penalty_per_point: float = 0.06
    single_floor: float = 0.5
    combined_floor: float = 0.35

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("attribute taper policy version is required")
        if not 0 < self.penalty_per_point <= 1:
            raise ValueError("penalty per point must be above 0 and at most 1")
        if not 0 < self.combined_floor <= self.single_floor <= 1:
            raise ValueError(
                "floors must satisfy 0 < combined floor <= single floor <= 1"
            )

    def factor(self, value: float, level: int) -> float:
        """The multiplier for one attribute value against one taper level."""
        shortfall = max(0.0, level - value)
        return max(self.single_floor, 1.0 - self.penalty_per_point * shortfall)


NO_TAPER = ScoreBand(1.0, 1.0, 1.0)


@dataclass(frozen=True)
class TaperAssessment:
    """The combined multiplier (as a band) and what caused it, for explanation."""

    multiplier: ScoreBand = NO_TAPER
    notes: tuple[str, ...] = ()

    @property
    def applies(self) -> bool:
        return self.multiplier.central < 1.0 or self.multiplier.lower < 1.0


def assess_tapers(
    tapers: Sequence[AttributeTaper],
    observations: Mapping[str, AttributeObservation],
    policy: AttributeTaperPolicy = AttributeTaperPolicy(),
    scoring: ScoringPolicy = ScoringPolicy(),
) -> TaperAssessment:
    """Combine every applicable taper into one multiplier band.

    The band follows the observation's band: a scouted range gives a lower
    multiplier at the pessimistic end of the range and none at the optimistic
    end, and an unknown attribute is treated as the scale minimum centrally, as
    everywhere else in scoring.
    """
    if not tapers:
        return TaperAssessment()
    lower = central = upper = 1.0
    notes: list[str] = []
    for taper in tapers:
        observation = observations.get(
            taper.attribute, AttributeObservation(visibility=Visibility.UNKNOWN)
        )
        band = observation_band(observation, scoring)
        lower *= policy.factor(band.lower, taper.below)
        central_factor = policy.factor(band.central, taper.below)
        central *= central_factor
        upper *= policy.factor(band.upper, taper.below)
        if central_factor < 1.0:
            notes.append(_note(taper, observation, band.central, central_factor))
    combined = ScoreBand(
        lower=max(policy.combined_floor, lower),
        central=max(policy.combined_floor, central),
        upper=max(policy.combined_floor, upper),
    )
    return TaperAssessment(multiplier=combined, notes=tuple(notes))


def _note(
    taper: AttributeTaper,
    observation: AttributeObservation,
    central: float,
    factor: float,
) -> str:
    name = _readable(taper.attribute)
    if observation.visibility is Visibility.UNKNOWN:
        seen = f"{name} not known"
    elif observation.visibility is Visibility.RANGE:
        seen = f"{name} scouted as {observation.minimum}-{observation.maximum}"
    else:
        seen = f"{name} {central:g}"
    return f"{seen}, below this tactic's {taper.below} (fit ×{factor:.2f})"


def _readable(attribute: str) -> str:
    out = []
    for index, char in enumerate(attribute):
        if char.isupper() and index:
            out.append(" ")
        out.append(char.lower())
    return "".join(out)


def taper_score_band(score: ScoreBand, multiplier: ScoreBand) -> ScoreBand:
    """A score band with each end scaled by its own multiplier."""
    return ScoreBand(
        lower=round(score.lower * multiplier.lower, 6),
        central=round(score.central * multiplier.central, 6),
        upper=round(score.upper * multiplier.upper, 6),
    )


def taper_role_score(role_score: RoleScore, assessment: TaperAssessment) -> RoleScore:
    """A role score with the tactic's taper applied, for depth and weakness checks."""
    if not assessment.applies:
        return role_score
    return replace(
        role_score, score=taper_score_band(role_score.score, assessment.multiplier)
    )
