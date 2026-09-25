"""Data models used by the XI selection and tactic recommendation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from fm_analytics.analytics.catalogue import TacticDefinition, TacticSlot
from fm_analytics.analytics.role_scoring import RoleScore, ScoreBand
from fm_analytics.analytics.tactical_system import SystemAssessment
from fm_analytics.domain import AttributeObservation, Player


@dataclass(frozen=True)
class PlayerSelectionInput:
    id: str
    name: str
    positions: tuple[str, ...]
    attributes: Mapping[str, AttributeObservation]
    availability: str
    injured: bool | None
    suspended: bool | None
    condition_percent: int | None
    match_fitness_percent: int | None
    position_familiarity: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def from_player(cls, player: Player) -> PlayerSelectionInput:
        return cls(
            id=player.id,
            name=player.name,
            positions=player.positions,
            attributes=player.attributes,
            availability=player.availability,
            injured=player.injured,
            suspended=player.suspended,
            condition_percent=player.condition_percent,
            match_fitness_percent=player.match_fitness_percent,
            position_familiarity=player.position_familiarity,
        )


@dataclass(frozen=True)
class ReadinessPolicy:
    version: str = "readiness-v1"
    minimum_condition: int = 65
    minimum_match_fitness: int = 50
    unknown_percent: int = 70
    condition_penalty_weight: float = 0.25
    match_fitness_penalty_weight: float = 0.10

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("readiness policy version is required")
        for name, value in (
            ("minimum_condition", self.minimum_condition),
            ("minimum_match_fitness", self.minimum_match_fitness),
            ("unknown_percent", self.unknown_percent),
        ):
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.condition_penalty_weight < 0 or self.match_fitness_penalty_weight < 0:
            raise ValueError("readiness penalty weights cannot be negative")


@dataclass(frozen=True)
class FamiliarityPolicy:
    """Scale a slot's role score by how familiar the player is with the position.

    Uses FM's own raw 1-20 position rating directly as a continuous signal
    rather than mapping it onto the game's Natural/Accomplished/.../
    Ineffectual labels first: those labels are themselves believed to be a
    projection of this same number, so reproducing them exactly is not
    required to use the information, only to describe it the way the UI does.

    The rating maps onto a *multiplier* applied to the role score, not a
    flat points deduction: `floor_multiplier` at the worst rating (1), 1.0
    at the best (20), linear in between. Multiplying keeps the discount
    proportionate to the player's underlying quality -- an excellent player
    playing out of position still loses a fixed *fraction* of a large score,
    rather than the same handful of points as a mediocre one -- and it makes
    the single `selection_score` a fair one-number comparison across
    players, which an additive penalty on wildly different base scores does
    not. `floor_multiplier` exists (rather than letting a rating of 1 zero a
    player out) because attributes like decisions, strength, or passing
    still count for something in an unfamiliar position; it is a judgment
    call, not a measured constant.

    `unknown_rating` is the value assumed when no reading exists for a
    position a player is otherwise eligible for -- for example a squad
    assembled from HTML import, which cannot supply this field. It defaults
    to `tools/fm20_linux_probe.POSITION_ELIGIBILITY_MINIMUM` (10) because
    that is the same threshold used to decide whether a position appears in
    `positions` at all; treating a missing reading as anything below that
    would penalize an eligible player beyond what the rest of this codebase
    already assumes about them. The two are duplicated rather than imported
    across the tools/src boundary; keep them in step if either changes.

    A `floor_multiplier` of 1.0 disables the discount entirely without
    deleting the policy, which is what distinguishes an *effective*
    recommendation (this policy as configured) from a *potential* one
    (multiplier forced to 1.0) -- see `recommend_tactic_effective_and_potential`.
    """

    version: str = "familiarity-v2"
    scale_minimum: int = 1
    scale_maximum: int = 20
    unknown_rating: int = 10
    floor_multiplier: float = 0.5

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("familiarity policy version is required")
        if self.scale_minimum >= self.scale_maximum:
            raise ValueError("familiarity scale minimum must be below maximum")
        if not self.scale_minimum <= self.unknown_rating <= self.scale_maximum:
            raise ValueError("unknown rating must be within the familiarity scale")
        if not 0 <= self.floor_multiplier <= 1:
            raise ValueError("familiarity floor multiplier must be between 0 and 1")

    def multiplier(self, rating: int) -> float:
        """The fraction of role score retained at this raw 1-20 rating."""
        span = self.scale_maximum - self.scale_minimum
        normalized = (rating - self.scale_minimum) / span
        return round(
            self.floor_multiplier + normalized * (1 - self.floor_multiplier), 6
        )

    def potential(self) -> FamiliarityPolicy:
        """Return the same policy with its discount disabled.

        Evaluating with this instead of `self` answers "what could this
        tactic be, once the squad is trained into position", rather than
        "what is safe to play today".
        """
        return FamiliarityPolicy(
            version=self.version,
            scale_minimum=self.scale_minimum,
            scale_maximum=self.scale_maximum,
            unknown_rating=self.unknown_rating,
            floor_multiplier=1.0,
        )


@dataclass(frozen=True)
class TacticFitPolicy:
    """Version the deliberately parameter-free whole-XI scoring method.

    Player scores are combined with the square-root mean in ``_tactic_fit``.
    Keeping the policy object preserves the public call signatures and records
    which scoring semantics produced an evaluation without exposing another
    tuning knob.
    """

    version: str = "tactic-fit-v2"

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("tactic-fit policy version is required")


@dataclass(frozen=True)
class SlotAssignment:
    slot: TacticSlot
    player_id: str
    player_name: str
    intrinsic_role_score: RoleScore
    readiness_penalty: float
    readiness_warnings: tuple[str, ...]
    familiarity_multiplier: float
    familiarity_warnings: tuple[str, ...]
    selection_score: ScoreBand
    # How far this player falls short of the tactic's attribute levels, as a
    # multiplier band (1.0 = no shortfall), and why. See `attribute_taper`.
    taper_multiplier: ScoreBand = ScoreBand(1.0, 1.0, 1.0)
    taper_notes: tuple[str, ...] = ()

    @property
    def tapered_attribute_score(self) -> ScoreBand:
        """The attribute-based role score after this tactic's taper.

        This, not `intrinsic_role_score`, is the like-for-like figure to compare
        a starter with his cover: both have the taper applied.
        """
        score, taper = self.intrinsic_role_score.score, self.taper_multiplier
        return ScoreBand(
            lower=round(score.lower * taper.lower, 6),
            central=round(score.central * taper.central, 6),
            upper=round(score.upper * taper.upper, 6),
        )

    @property
    def tapered_score(self) -> ScoreBand:
        """After position familiarity and the taper, before readiness."""
        base, taper = self.in_position_score, self.taper_multiplier
        return ScoreBand(
            lower=round(base.lower * taper.lower, 6),
            central=round(base.central * taper.central, 6),
            upper=round(base.upper * taper.upper, 6),
        )

    @property
    def in_position_score(self) -> ScoreBand:
        """Attribute-based role score after position familiarity, before readiness."""
        return ScoreBand(
            lower=round(self.intrinsic_role_score.score.lower * self.familiarity_multiplier, 6),
            central=round(self.intrinsic_role_score.score.central * self.familiarity_multiplier, 6),
            upper=round(self.intrinsic_role_score.score.upper * self.familiarity_multiplier, 6),
        )


@dataclass(frozen=True)
class TacticEvaluation:
    tactic: TacticDefinition
    readiness_version: str
    familiarity_version: str
    familiarity_floor: float
    fit_version: str
    assignments: tuple[SlotAssignment, ...]
    unfilled_slots: tuple[TacticSlot, ...]
    mean_score: ScoreBand
    weakest_score: ScoreBand
    weakest_slot_keys: tuple[str, ...]
    xi_score: ScoreBand
    coherence: SystemAssessment
    instruction_suitability: SystemAssessment
    tactic_balance_multiplier: float
    # Whether the eleven's roles meet this opponent's system floors (see
    # `analytics/opponent.py`). Inactive, and scored 100, under a neutral
    # profile -- the default for every evaluation that does not ask for one.
    opponent_fit: SystemAssessment
    score: ScoreBand

    @property
    def has_legal_xi(self) -> bool:
        return not self.unfilled_slots and len(self.assignments) == 11


@dataclass(frozen=True)
class TacticRecommendation:
    evaluations: tuple[TacticEvaluation, ...]

    @property
    def selected(self) -> TacticEvaluation:
        return self.evaluations[0]

    def by_tactic_key(self, tactic_key: str) -> TacticEvaluation:
        return next(
            evaluation
            for evaluation in self.evaluations
            if evaluation.tactic.key == tactic_key
        )


@dataclass(frozen=True)
class TrainingTarget:
    """A tactic worth training towards: its potential materially beats today.

    `score_gap` is the potential fit score's central estimate minus the
    effective one, for the same tactic; it is the retraining upside, not a
    prediction of when the squad will realize it.
    """

    tactic_key: str
    tactic_name: str
    effective_score: ScoreBand
    potential_score: ScoreBand
    score_gap: float


@dataclass(frozen=True)
class EffectiveAndPotentialRecommendation:
    effective: TacticRecommendation
    potential: TacticRecommendation

    def training_targets(self, *, minimum_gap_ratio: float = 0.08) -> tuple[TrainingTarget, ...]:
        """Tactics whose potential fit clears its effective fit by a margin.

        Ordered by the largest gap first, since that is the tactic where
        training individual players into position would move the needle
        the most. The bar is a *fraction* of the tactic's effective fit
        (default 8%) rather than a fixed number of points: fit magnitudes
        move with the catalogue and scoring policy in use -- multiplicative
        familiarity discounts produce smaller absolute gaps than the old
        additive penalty did, and a fixed points threshold tuned for one
        would quietly stop firing under the other. A tactic with no legal
        XI today (effective fit of 0 or less) counts any positive gap as
        material, since a relative comparison is meaningless there.
        """
        targets = []
        for potential_evaluation in self.potential.evaluations:
            effective_evaluation = self.effective.by_tactic_key(
                potential_evaluation.tactic.key
            )
            gap = round(
                potential_evaluation.score.central - effective_evaluation.score.central,
                6,
            )
            baseline = effective_evaluation.score.central
            material = gap > 0 and (baseline <= 0 or gap / baseline >= minimum_gap_ratio)
            if material:
                targets.append(
                    TrainingTarget(
                        tactic_key=potential_evaluation.tactic.key,
                        tactic_name=potential_evaluation.tactic.name,
                        effective_score=effective_evaluation.score,
                        potential_score=potential_evaluation.score,
                        score_gap=gap,
                    )
                )
        return tuple(sorted(targets, key=lambda item: (-item.score_gap, item.tactic_key)))


@dataclass(frozen=True)
class _CandidateAssignment:
    slot_index: int
    player_index: int
    assignment: SlotAssignment


@dataclass(frozen=True)
class _AssignmentState:
    total: float
    assignments: tuple[_CandidateAssignment, ...]
