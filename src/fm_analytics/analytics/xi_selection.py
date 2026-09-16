from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Mapping, Sequence

from fm_analytics.analytics.catalogue import (
    FootballCatalogue,
    TacticDefinition,
    TacticSlot,
)
from fm_analytics.analytics.role_scoring import RoleScore, ScoreBand, score_role
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
    """Balance whole-XI quality against the weakest starting slot."""

    version: str = "tactic-fit-v1"
    weakest_slot_weight: float = 0.35

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("tactic-fit policy version is required")
        if not isfinite(self.weakest_slot_weight) or not 0 <= self.weakest_slot_weight <= 1:
            raise ValueError("weakest-slot weight must be finite and between 0 and 1")


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


@dataclass(frozen=True)
class TacticEvaluation:
    tactic: TacticDefinition
    readiness_version: str
    familiarity_version: str
    familiarity_floor: float
    fit_version: str
    fit_weakest_weight: float
    assignments: tuple[SlotAssignment, ...]
    unfilled_slots: tuple[TacticSlot, ...]
    mean_score: ScoreBand
    weakest_score: ScoreBand
    weakest_slot_keys: tuple[str, ...]
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


def evaluate_tactic(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> TacticEvaluation:
    if tactic.key not in catalogue.tactics or catalogue.tactics[tactic.key] != tactic:
        raise ValueError("tactic must belong to the supplied football catalogue")
    player_ids = [player.id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("selection player ids must be unique")

    ordered_players = tuple(sorted(players, key=lambda item: (item.name.casefold(), item.id)))
    choices = _build_choices(
        tactic, ordered_players, catalogue, readiness_policy, familiarity_policy
    )
    states = _assignment_states(choices)
    best_mask, best = min(
        states.items(),
        key=lambda item: (
            -item[0].bit_count(),
            -item[1].total,
            _state_signature(item[1]),
        ),
    )
    full_mask = (1 << len(tactic.slots)) - 1
    if best_mask == full_mask and fit_policy.weakest_slot_weight:
        best = _best_fit_state(choices, full_mask, fit_policy, best)
    ordered_assignments = tuple(
        choice.assignment
        for choice in sorted(best.assignments, key=lambda item: item.slot_index)
    )
    unfilled = tuple(
        slot
        for index, slot in enumerate(tactic.slots)
        if not best_mask & (1 << index)
    )
    mean_score, weakest_score, fit_score = _tactic_fit(
        ordered_assignments, len(tactic.slots), fit_policy
    )
    weakest_value = weakest_score.central
    weakest_slot_keys = tuple(
        slot.key for slot in unfilled
    ) if unfilled else tuple(
        assignment.slot.key
        for assignment in ordered_assignments
        if assignment.selection_score.central == weakest_value
    )
    return TacticEvaluation(
        tactic=tactic,
        readiness_version=readiness_policy.version,
        familiarity_version=familiarity_policy.version,
        familiarity_floor=familiarity_policy.floor_multiplier,
        fit_version=fit_policy.version,
        fit_weakest_weight=fit_policy.weakest_slot_weight,
        assignments=ordered_assignments,
        unfilled_slots=unfilled,
        mean_score=mean_score,
        weakest_score=weakest_score,
        weakest_slot_keys=weakest_slot_keys,
        score=fit_score,
    )


def recommend_tactic(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> TacticRecommendation:
    evaluations = tuple(
        evaluate_tactic(
            tactic,
            players,
            catalogue,
            readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
            fit_policy=fit_policy,
        )
        for tactic in catalogue.tactics.values()
    )
    return TacticRecommendation(
        evaluations=tuple(
            sorted(
                evaluations,
                key=lambda item: (
                    not item.has_legal_xi,
                    -len(item.assignments),
                    -item.score.central,
                    -item.score.lower,
                    item.tactic.key,
                ),
            )
        )
    )


def recommend_tactic_effective_and_potential(
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
) -> EffectiveAndPotentialRecommendation:
    """Answer both "what to play now" and "what to aim for" from one call.

    *Effective* applies the familiarity penalty as configured -- what the
    squad can safely play this weekend. *Potential* forces that same
    policy's penalty to zero -- what the squad could be if fully retrained
    into position, with every other input unchanged. The two runs share
    every other policy, so a difference in ranking or score is attributable
    to position familiarity and nothing else.

    This says nothing about *tactic* familiarity (the squad's fluency with a
    shape as a whole), which is a distinct, currently unavailable input --
    see Phase 05. A tactic ranked far higher in potential than in effective
    is one where retraining individual players into their slots would help;
    it is not evidence the squad already knows how to play that shape.
    """
    effective = recommend_tactic(
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy,
        fit_policy=fit_policy,
    )
    potential = recommend_tactic(
        players,
        catalogue,
        readiness_policy=readiness_policy,
        familiarity_policy=familiarity_policy.potential(),
        fit_policy=fit_policy,
    )
    return EffectiveAndPotentialRecommendation(effective=effective, potential=potential)


def is_player_selectable(
    player: PlayerSelectionInput,
    *,
    policy: ReadinessPolicy = ReadinessPolicy(),
) -> bool:
    return _is_available(player, policy)


def score_player_for_slot(
    player: PlayerSelectionInput,
    slot: TacticSlot,
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
) -> SlotAssignment | None:
    """Score one legal, selectable player/slot pairing."""
    if slot.role_key not in catalogue.roles:
        raise ValueError(f"unknown role {slot.role_key!r}")
    if not _is_available(player, readiness_policy):
        return None
    if slot.position not in player.positions:
        return None
    intrinsic = score_role(catalogue.roles[slot.role_key], player.attributes)
    readiness_penalty, readiness_warnings = _readiness(player, readiness_policy)
    familiarity_multiplier, familiarity_warnings = _familiarity(
        player, slot, familiarity_policy
    )

    def _adjust(raw: float) -> float:
        return round(max(0, round(raw - readiness_penalty, 6)) * familiarity_multiplier, 6)

    return SlotAssignment(
        slot=slot,
        player_id=player.id,
        player_name=player.name,
        intrinsic_role_score=intrinsic,
        readiness_penalty=readiness_penalty,
        readiness_warnings=readiness_warnings,
        familiarity_multiplier=familiarity_multiplier,
        familiarity_warnings=familiarity_warnings,
        selection_score=ScoreBand(
            lower=_adjust(intrinsic.score.lower),
            central=_adjust(intrinsic.score.central),
            upper=_adjust(intrinsic.score.upper),
        ),
    )


def _build_choices(
    tactic: TacticDefinition,
    players: tuple[PlayerSelectionInput, ...],
    catalogue: FootballCatalogue,
    policy: ReadinessPolicy,
    familiarity_policy: FamiliarityPolicy,
) -> tuple[tuple[_CandidateAssignment, ...], ...]:
    choices: list[tuple[_CandidateAssignment, ...]] = []
    for player_index, player in enumerate(players):
        if not _is_available(player, policy):
            choices.append(())
            continue
        player_choices: list[_CandidateAssignment] = []
        for slot_index, slot in enumerate(tactic.slots):
            assignment = score_player_for_slot(
                player,
                slot,
                catalogue,
                readiness_policy=policy,
                familiarity_policy=familiarity_policy,
            )
            if assignment is None:
                continue
            player_choices.append(
                _CandidateAssignment(
                    slot_index=slot_index,
                    player_index=player_index,
                    assignment=assignment,
                )
            )
        choices.append(tuple(player_choices))
    return tuple(choices)


def _is_available(player: PlayerSelectionInput, policy: ReadinessPolicy) -> bool:
    if player.availability != "available" or player.injured is True or player.suspended is True:
        return False
    if (
        player.condition_percent is not None
        and player.condition_percent < policy.minimum_condition
    ):
        return False
    if (
        player.match_fitness_percent is not None
        and player.match_fitness_percent < policy.minimum_match_fitness
    ):
        return False
    return True


def _readiness(
    player: PlayerSelectionInput, policy: ReadinessPolicy
) -> tuple[float, tuple[str, ...]]:
    warnings: list[str] = []
    condition = player.condition_percent
    if condition is None:
        condition = policy.unknown_percent
        warnings.append("condition unknown")
    match_fitness = player.match_fitness_percent
    if match_fitness is None:
        match_fitness = policy.unknown_percent
        warnings.append("match fitness unknown")
    penalty = (
        (100 - condition) * policy.condition_penalty_weight
        + (100 - match_fitness) * policy.match_fitness_penalty_weight
    )
    return round(penalty, 6), tuple(warnings)


def _familiarity(
    player: PlayerSelectionInput, slot: TacticSlot, policy: FamiliarityPolicy
) -> tuple[float, tuple[str, ...]]:
    warnings: list[str] = []
    rating = player.position_familiarity.get(slot.position)
    if rating is None:
        rating = policy.unknown_rating
        warnings.append(f"{slot.position} familiarity unknown")
    return policy.multiplier(rating), tuple(warnings)


def _state_is_better(candidate: _AssignmentState, current: _AssignmentState) -> bool:
    if candidate.total != current.total:
        return candidate.total > current.total
    return _state_signature(candidate) < _state_signature(current)


def _state_signature(state: _AssignmentState) -> tuple[tuple[int, str], ...]:
    return tuple(
        (choice.slot_index, choice.assignment.player_id)
        for choice in sorted(state.assignments, key=lambda item: item.slot_index)
    )


def _assignment_states(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    *,
    minimum_score: float = 0,
) -> dict[int, _AssignmentState]:
    states: dict[int, _AssignmentState] = {0: _AssignmentState(0, ())}
    for player_choices in choices:
        next_states = dict(states)
        for mask, state in states.items():
            for choice in player_choices:
                score = choice.assignment.selection_score.central
                if score < minimum_score:
                    continue
                bit = 1 << choice.slot_index
                if mask & bit:
                    continue
                candidate = _AssignmentState(
                    total=round(state.total + score, 6),
                    assignments=state.assignments + (choice,),
                )
                next_mask = mask | bit
                current = next_states.get(next_mask)
                if current is None or _state_is_better(candidate, current):
                    next_states[next_mask] = candidate
        states = next_states
    return states


def _best_fit_state(
    choices: tuple[tuple[_CandidateAssignment, ...], ...],
    full_mask: int,
    policy: TacticFitPolicy,
    mean_best: _AssignmentState,
) -> _AssignmentState:
    """Optimize the central mean/weakest blend over every feasible XI.

    For each distinct candidate score as a possible minimum, the max-total
    assignment under that floor dominates all other assignments with that
    minimum or higher. This is exact for the linear mean/weakest objective.
    """
    best = mean_best
    slot_count = full_mask.bit_count()

    def key(state: _AssignmentState) -> tuple[float, float, tuple[tuple[int, str], ...]]:
        weakest = min(
            choice.assignment.selection_score.central for choice in state.assignments
        )
        fit = round(
            (1 - policy.weakest_slot_weight) * state.total / slot_count
            + policy.weakest_slot_weight * weakest,
            6,
        )
        return -fit, -state.total, _state_signature(state)

    best_key = key(best)
    thresholds = sorted({
        choice.assignment.selection_score.central
        for player_choices in choices
        for choice in player_choices
        if choice.assignment.selection_score.central > 0
    })
    for threshold in thresholds:
        candidate = _assignment_states(choices, minimum_score=threshold).get(full_mask)
        if candidate is None:
            break
        candidate_key = key(candidate)
        if candidate_key < best_key:
            best, best_key = candidate, candidate_key
    return best


def _tactic_fit(
    assignments: tuple[SlotAssignment, ...],
    slot_count: int,
    policy: TacticFitPolicy,
) -> tuple[ScoreBand, ScoreBand, ScoreBand]:
    missing = slot_count - len(assignments)
    if missing < 0:
        raise ValueError("more assignments than tactic slots")

    def component(field: str) -> tuple[float, float, float]:
        values = [getattr(item.selection_score, field) for item in assignments]
        mean = round(sum(values) / slot_count, 6)
        weakest = min(values) if values and not missing else 0.0
        fit = round(
            (1 - policy.weakest_slot_weight) * mean
            + policy.weakest_slot_weight * weakest,
            6,
        )
        return mean, weakest, fit

    lower = component("lower")
    central = component("central")
    upper = component("upper")
    mean = ScoreBand(lower[0], central[0], upper[0])
    weakest = ScoreBand(lower[1], central[1], upper[1])
    fit = ScoreBand(lower[2], central[2], upper[2])
    return mean, weakest, fit
