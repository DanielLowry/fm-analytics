"""Rank external scouting candidates by their effect on one tactic's best XI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
from typing import Sequence

from fm_analytics.analytics.assignment_solver import (
    best_assignment_for_role_version,
)
from fm_analytics.analytics.catalogue import FootballCatalogue, TacticDefinition
from fm_analytics.analytics.opponent import OpponentProfile, attribute_emphasis
from fm_analytics.analytics.role_scoring import RoleScoreCache, ScoreBand
from fm_analytics.analytics.scouting import ScoutingCandidate
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    TacticEvaluation,
    _AssignmentState,
    _CandidateAssignment,
)
from fm_analytics.analytics.xi_selection import (
    _apply_balance_multiplier,
    _build_choices,
    _role_structure_checks,
    _tactic_balance_multiplier,
    _tactic_fit,
    score_player_for_slot,
)
from fm_analytics.domain.models import Visibility


@dataclass(frozen=True)
class ScenarioScores:
    """Floor, conservative estimate, and ceiling as separate scenarios."""

    floor: float
    estimate: float
    ceiling: float


@dataclass(frozen=True)
class TacticScoutingAssessment:
    candidate: ScoutingCandidate
    tactic_key: str
    best_slot_key: str
    best_position: str
    best_role_key: str
    best_role_name: str
    player_fit: ScoreBand
    baseline_score: ScoreBand
    projected_score: ScenarioScores
    score_gain: ScenarioScores
    starts_at_estimate: bool
    replaced_player_names: tuple[str, ...]
    known_attributes: int
    ranged_attributes: int
    unknown_attributes: int


@dataclass(frozen=True)
class _Remainder:
    role_keys: tuple[str, ...]
    forced_slot_index: int
    state: _AssignmentState


@dataclass(frozen=True)
class _ProjectedLineup:
    assignments: tuple[SlotAssignment, ...]
    candidate_assignment: SlotAssignment
    xi_score: ScoreBand
    score: ScoreBand
    signature: tuple[tuple[int, str, str], ...]

    @property
    def filled_slots(self) -> int:
        return len(self.assignments)


def rank_candidates_for_tactic(
    candidates: Sequence[ScoutingCandidate],
    owned_players: Sequence[PlayerSelectionInput],
    tactic: TacticDefinition,
    catalogue: FootballCatalogue,
    baseline: TacticEvaluation,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
    include_raw_external_positions: bool = False,
    position: str | None = None,
    role_key: str | None = None,
) -> tuple[TacticScoutingAssessment, ...]:
    """Assess each candidate as one possible addition to the current squad.

    The candidate is assumed available, fully fit, and match fit. The owned
    players retain the exact readiness used by the current tactic score. A
    candidate can be ignored by the projected XI, so signing one can never
    reduce the projection.

    For every legal role version and possible candidate slot, the best
    allocation of the other ten slots is solved once and reused across the
    entire candidate pool. This is exactly equivalent to adding candidates one
    at a time and re-optimising, but avoids repeating the owned-player work.
    """
    if tactic.key not in catalogue.tactics or catalogue.tactics[tactic.key] != tactic:
        raise ValueError("tactic must belong to the supplied football catalogue")
    if baseline.tactic != tactic:
        raise ValueError("baseline evaluation must be for the selected tactic")

    derived = catalogue.for_context(
        tactic.key, extra_emphasis=attribute_emphasis(opponent)
    )
    ordered_owned = tuple(
        sorted(owned_players, key=lambda item: (item.name.casefold(), item.id))
    )
    owned_choices = _build_choices(
        tactic,
        ordered_owned,
        derived,
        readiness_policy,
        familiarity_policy,
        RoleScoreCache(),
    )
    remainders = _build_remainders(tactic, derived, owned_choices)
    slot_indexes = {slot.key: index for index, slot in enumerate(tactic.slots)}
    baseline_signature = tuple(
        (
            slot_indexes[assignment.slot.key],
            assignment.player_id,
            assignment.intrinsic_role_score.role_key,
        )
        for assignment in baseline.assignments
    )
    baseline_ids = {assignment.player_id for assignment in baseline.assignments}
    owned_names = {player.id: player.name for player in ordered_owned}
    role_score_cache = RoleScoreCache()

    assessments = []
    for candidate in candidates:
        candidate_input = _candidate_input(
            candidate,
            include_raw_external_positions=include_raw_external_positions,
        )
        projected: list[_ProjectedLineup] = []
        personal_assignments: list[SlotAssignment] = []
        for remainder in remainders:
            slot_index = remainder.forced_slot_index
            slot = tactic.slots[slot_index]
            candidate_role = remainder.role_keys[slot_index]
            if position is not None and slot.position != position:
                continue
            if role_key is not None and candidate_role != role_key:
                continue
            assignment = score_player_for_slot(
                candidate_input,
                slot,
                derived,
                readiness_policy=readiness_policy,
                familiarity_policy=familiarity_policy,
                role_key=candidate_role,
                role_score_cache=role_score_cache,
            )
            if assignment is None:
                continue
            personal_assignments.append(assignment)
            assignments = tuple(
                sorted(
                    (
                        *(choice.assignment for choice in remainder.state.assignments),
                        assignment,
                    ),
                    key=lambda item: slot_indexes[item.slot.key],
                )
            )
            _, _, xi_score = _tactic_fit(assignments, len(tactic.slots))
            coherence, instruction, _opponent_fit = _role_structure_checks(
                tactic, assignments, derived, opponent
            )
            score = _apply_balance_multiplier(
                xi_score, _tactic_balance_multiplier(coherence, instruction)
            )
            projected.append(
                _ProjectedLineup(
                    assignments=assignments,
                    candidate_assignment=assignment,
                    xi_score=xi_score,
                    score=score,
                    signature=tuple(
                        (
                            slot_indexes[item.slot.key],
                            item.player_id,
                            item.intrinsic_role_score.role_key,
                        )
                        for item in assignments
                    ),
                )
            )
        if not personal_assignments:
            continue

        best_personal = min(
            personal_assignments,
            key=lambda item: (
                -item.selection_score.central,
                -item.selection_score.lower,
                slot_indexes[item.slot.key],
                item.intrinsic_role_score.role_key,
            ),
        )
        player_fit = ScoreBand(
            lower=max(item.selection_score.lower for item in personal_assignments),
            central=max(item.selection_score.central for item in personal_assignments),
            upper=max(item.selection_score.upper for item in personal_assignments),
        )
        best_by_field = {
            field: _best_projection(
                projected,
                baseline,
                baseline_signature,
                field,
                len(tactic.slots),
            )
            for field in ("lower", "central", "upper")
        }
        central_projection = best_by_field["central"]
        starts = central_projection is not None
        chosen_assignment = (
            central_projection.candidate_assignment if central_projection else best_personal
        )
        projected_scores = ScenarioScores(
            floor=_projection_value(best_by_field["lower"], baseline, "lower"),
            estimate=_projection_value(best_by_field["central"], baseline, "central"),
            ceiling=_projection_value(best_by_field["upper"], baseline, "upper"),
        )
        score_gain = ScenarioScores(
            floor=round(projected_scores.floor - baseline.score.lower, 6),
            estimate=round(projected_scores.estimate - baseline.score.central, 6),
            ceiling=round(projected_scores.ceiling - baseline.score.upper, 6),
        )
        selected_ids = (
            {item.player_id for item in central_projection.assignments}
            if central_projection
            else baseline_ids
        )
        replaced = tuple(
            owned_names[player_id]
            for player_id in sorted(baseline_ids - selected_ids)
            if player_id in owned_names
        )
        visibilities = tuple(
            item.observation.visibility
            for item in chosen_assignment.intrinsic_role_score.contributions
        )
        known = sum(item is Visibility.KNOWN for item in visibilities)
        ranged = sum(item is Visibility.RANGE for item in visibilities)
        assessments.append(
            TacticScoutingAssessment(
                candidate=candidate,
                tactic_key=tactic.key,
                best_slot_key=chosen_assignment.slot.key,
                best_position=chosen_assignment.slot.position,
                best_role_key=chosen_assignment.intrinsic_role_score.role_key,
                best_role_name=chosen_assignment.intrinsic_role_score.role_name,
                player_fit=player_fit,
                baseline_score=baseline.score,
                projected_score=projected_scores,
                score_gain=score_gain,
                starts_at_estimate=starts,
                replaced_player_names=replaced,
                known_attributes=known,
                ranged_attributes=ranged,
                unknown_attributes=len(visibilities) - known - ranged,
            )
        )
    return tuple(assessments)


def sort_tactic_assessments(
    assessments: Sequence[TacticScoutingAssessment],
    *,
    sort: str = "tactic_gain",
    descending: bool = True,
) -> tuple[TacticScoutingAssessment, ...]:
    values = {
        "tactic_gain": lambda item: item.score_gain.estimate,
        "tactic_floor_gain": lambda item: item.score_gain.floor,
        "tactic_ceiling_gain": lambda item: item.score_gain.ceiling,
        "tactic_score": lambda item: item.projected_score.estimate,
        "tactic_fit": lambda item: item.player_fit.central,
        "minimum": lambda item: item.player_fit.lower,
        "median": lambda item: item.player_fit.central,
        "ceiling": lambda item: item.player_fit.upper,
        "upside": lambda item: item.player_fit.upper - item.player_fit.central,
        "age": lambda item: item.candidate.age,
        "scouted": lambda item: item.candidate.scouting_knowledge,
        "known": lambda item: item.known_attributes + item.ranged_attributes,
        "name": lambda item: item.candidate.name.casefold(),
        "role": lambda item: item.best_role_name.casefold(),
        "familiarity": lambda item: (
            item.candidate.raw_position_familiarity or {}
        ).get(item.best_position),
        "value": lambda item: item.candidate.value,
    }
    if sort not in values:
        sort = "tactic_gain"
    value = values[sort]
    ordered = sorted(
        assessments,
        key=lambda item: (item.candidate.name.casefold(), item.candidate.id),
    )
    ordered.sort(key=lambda item: -item.score_gain.estimate)
    present = [item for item in ordered if value(item) is not None]
    missing = [item for item in ordered if value(item) is None]
    present.sort(key=value, reverse=descending)
    return tuple(present + missing)


def _candidate_input(
    candidate: ScoutingCandidate,
    *,
    include_raw_external_positions: bool,
) -> PlayerSelectionInput:
    return PlayerSelectionInput(
        id=f"scouting:{candidate.id}",
        name=candidate.name,
        positions=candidate.positions_for(
            include_raw_external_positions=include_raw_external_positions
        ),
        attributes=candidate.attributes,
        availability="available",
        injured=False,
        suspended=False,
        condition_percent=100,
        match_fitness_percent=100,
        position_familiarity=(
            dict(candidate.raw_position_familiarity or {})
            if include_raw_external_positions
            else {}
        ),
    )


def _build_remainders(
    tactic: TacticDefinition,
    catalogue: FootballCatalogue,
    owned_choices: tuple[tuple[_CandidateAssignment, ...], ...],
) -> tuple[_Remainder, ...]:
    remainders = []
    role_options = tuple(catalogue.role_keys_for_slot(slot) for slot in tactic.slots)
    for role_keys in product(*role_options):
        if not catalogue.role_version_is_legal(tactic, role_keys):
            continue
        for forced_slot_index in range(len(tactic.slots)):
            remaining_slots = tuple(
                index
                for index in range(len(tactic.slots))
                if index != forced_slot_index
            )
            remapped = {original: new for new, original in enumerate(remaining_slots)}
            choices = tuple(
                tuple(
                    replace(choice, slot_index=remapped[choice.slot_index])
                    for choice in player_choices
                    if choice.slot_index in remapped
                    and choice.assignment.intrinsic_role_score.role_key
                    == role_keys[choice.slot_index]
                )
                for player_choices in owned_choices
            )
            state = best_assignment_for_role_version(
                choices, (1 << len(remaining_slots)) - 1
            )
            remainders.append(_Remainder(role_keys, forced_slot_index, state))
    return tuple(remainders)


def _best_projection(
    projected: Sequence[_ProjectedLineup],
    baseline: TacticEvaluation,
    baseline_signature: tuple[tuple[int, str, str], ...],
    field: str,
    slot_count: int,
) -> _ProjectedLineup | None:
    def key(item: _ProjectedLineup):
        return (
            item.filled_slots != slot_count,
            -item.filled_slots,
            -getattr(item.score, field),
            -getattr(item.xi_score, field),
            item.signature,
        )

    baseline_key = (
        not baseline.has_legal_xi,
        -len(baseline.assignments),
        -getattr(baseline.score, field),
        -getattr(baseline.xi_score, field),
        baseline_signature,
    )
    best = min(projected, key=key)
    return best if key(best) < baseline_key else None


def _projection_value(
    projection: _ProjectedLineup | None,
    baseline: TacticEvaluation,
    field: str,
) -> float:
    return getattr(projection.score, field) if projection else getattr(baseline.score, field)
