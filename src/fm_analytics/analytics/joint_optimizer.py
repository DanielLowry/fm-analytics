"""Prototype joint role/player MILP for one tactic.

This is intentionally not wired into :mod:`xi_selection` yet.  It exists to
measure the alternative formulation against the production exact solver: one
binary variable represents a player filling a slot in a permitted role, so
role selection and player assignment happen in one solve.

The model currently targets legal full XIs and the central score.  That is the
path which dominates normal tactic ranking; the production selector remains
responsible for explainable partial XIs and lower/upper score bands.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticDefinition
from fm_analytics.analytics.opponent import (
    OpponentProfile,
    attribute_emphasis as opponent_attribute_emphasis,
    system_floors,
)
from fm_analytics.analytics.tactical_system import _INSTRUCTION_REQUIREMENTS
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    SystemFitPolicy,
    TacticFitPolicy,
    _CandidateAssignment,
)
from fm_analytics.analytics.xi_selection import _build_choices, _system_fit, _tactic_fit


@dataclass(frozen=True)
class JointOptimisationResult:
    assignments: tuple[SlotAssignment, ...]
    objective: float
    xi_score: float
    coherence_score: float
    instruction_score: float
    opponent_score: float
    variable_count: int
    binary_variable_count: int
    constraint_count: int
    mip_node_count: int


@dataclass
class _Expression:
    coefficients: dict[int, float]
    constant: float = 0.0


class _Model:
    def __init__(self) -> None:
        self.lower: list[float] = []
        self.upper: list[float] = []
        self.integrality: list[int] = []
        self.objective: list[float] = []
        self.rows: list[dict[int, float]] = []
        self.row_lower: list[float] = []
        self.row_upper: list[float] = []

    def variable(self, *, lower: float = 0.0, upper: float = inf, binary: bool = False) -> int:
        index = len(self.lower)
        self.lower.append(lower)
        self.upper.append(upper)
        self.integrality.append(1 if binary else 0)
        self.objective.append(0.0)
        return index

    def constraint(
        self,
        coefficients: Mapping[int, float],
        *,
        lower: float = -inf,
        upper: float = inf,
    ) -> None:
        self.rows.append({index: value for index, value in coefficients.items() if value})
        self.row_lower.append(lower)
        self.row_upper.append(upper)

    def maximise(self, expression: _Expression) -> None:
        for index, coefficient in expression.coefficients.items():
            self.objective[index] -= coefficient

    def solve(self):
        row_indexes: list[int] = []
        column_indexes: list[int] = []
        values: list[float] = []
        for row_index, row in enumerate(self.rows):
            for column_index, value in row.items():
                row_indexes.append(row_index)
                column_indexes.append(column_index)
                values.append(value)
        matrix = coo_array(
            (values, (row_indexes, column_indexes)),
            shape=(len(self.rows), len(self.lower)),
        ).tocsc()
        return milp(
            c=np.asarray(self.objective),
            integrality=np.asarray(self.integrality),
            bounds=Bounds(np.asarray(self.lower), np.asarray(self.upper)),
            constraints=LinearConstraint(
                matrix,
                np.asarray(self.row_lower),
                np.asarray(self.row_upper),
            ),
            options={"presolve": True},
        )


def _add(left: _Expression, right: _Expression, scale: float = 1.0) -> _Expression:
    coefficients = dict(left.coefficients)
    for index, value in right.coefficients.items():
        coefficients[index] = coefficients.get(index, 0.0) + scale * value
    return _Expression(coefficients, left.constant + scale * right.constant)


def _scale(expression: _Expression, factor: float) -> _Expression:
    return _Expression(
        {index: factor * value for index, value in expression.coefficients.items()},
        factor * expression.constant,
    )


def _role_count_expression(
    candidate_variables: Sequence[tuple[_CandidateAssignment, int]],
    catalogue: FootballCatalogue,
    value,
) -> _Expression:
    coefficients: dict[int, float] = {}
    for candidate, variable in candidate_variables:
        role = catalogue.roles[candidate.assignment.intrinsic_role_score.role_key]
        coefficients[variable] = float(value(role))
    return _Expression(coefficients)


def _demand_score(
    model: _Model,
    candidate_variables: Sequence[tuple[_CandidateAssignment, int]],
    catalogue: FootballCatalogue,
    demands: Mapping[str, float],
) -> _Expression:
    if not demands:
        return _Expression({}, 100.0)
    component_expressions: list[_Expression] = []
    for dimension, minimum in demands.items():
        if not minimum:
            component_expressions.append(_Expression({}, 1.0))
            continue
        by_slot: dict[int, set[float]] = {}
        for candidate, _ in candidate_variables:
            role = catalogue.roles[candidate.assignment.intrinsic_role_score.role_key]
            by_slot.setdefault(candidate.slot_index, set()).add(
                role.system_traits.get(dimension, 0.0)
            )
        guaranteed = sum(min(values) for values in by_slot.values())
        if guaranteed >= minimum:
            component_expressions.append(_Expression({}, 1.0))
            continue
        supplied = _role_count_expression(
            candidate_variables,
            catalogue,
            lambda role, dimension=dimension: role.system_traits.get(dimension, 0.0),
        )
        fraction = model.variable(lower=0.0, upper=1.0)
        row = {fraction: minimum}
        for index, coefficient in supplied.coefficients.items():
            row[index] = row.get(index, 0.0) - coefficient
        model.constraint(row, upper=0.0)
        component_expressions.append(_Expression({fraction: 1.0}))
    total = _Expression({})
    for component in component_expressions:
        total = _add(total, component)
    return _scale(total, 100.0 / len(component_expressions))


def _discrete_cap_score(
    model: _Model,
    count: _Expression,
    limit: int,
    slot_count: int,
) -> _Expression:
    selectors = [model.variable(lower=0.0, upper=1.0, binary=True) for _ in range(slot_count + 1)]
    model.constraint({index: 1.0 for index in selectors}, lower=1.0, upper=1.0)
    row = {index: float(number) for number, index in enumerate(selectors)}
    for index, coefficient in count.coefficients.items():
        row[index] = row.get(index, 0.0) - coefficient
    model.constraint(row, lower=0.0, upper=0.0)
    return _Expression(
        {
            index: 1.0 if number == 0 else min(1.0, limit / number)
            for number, index in enumerate(selectors)
        }
    )


def _maximum_count(
    candidate_variables: Sequence[tuple[_CandidateAssignment, int]],
    catalogue: FootballCatalogue,
    value,
) -> float:
    by_slot: dict[int, set[float]] = {}
    for candidate, _ in candidate_variables:
        role = catalogue.roles[candidate.assignment.intrinsic_role_score.role_key]
        by_slot.setdefault(candidate.slot_index, set()).add(float(value(role)))
    return sum(max(values) for values in by_slot.values())


def _coherence_score(
    model: _Model,
    tactic: TacticDefinition,
    candidate_variables: Sequence[tuple[_CandidateAssignment, int]],
    catalogue: FootballCatalogue,
) -> tuple[_Expression, bool]:
    requirements = tactic.system_requirements
    active = bool(
        requirements.minimums
        or requirements.maximum_attack_duties is not None
        or requirements.maximum_creators is not None
    )
    if not active:
        return _Expression({}, 100.0), False

    components: list[_Expression] = []
    for dimension, minimum in requirements.minimums.items():
        components.append(
            _scale(
                _demand_score(
                    model, candidate_variables, catalogue, {dimension: minimum}
                ),
                0.01,
            )
        )
    if requirements.maximum_attack_duties is not None:
        attack_value = lambda role: role.system_traits.get("attackDuty", 0.0)
        if _maximum_count(candidate_variables, catalogue, attack_value) <= requirements.maximum_attack_duties:
            components.append(_Expression({}, 1.0))
        else:
            attack_count = _role_count_expression(
                candidate_variables, catalogue, attack_value
            )
            components.append(
                _discrete_cap_score(
                    model,
                    attack_count,
                    requirements.maximum_attack_duties,
                    len(tactic.slots),
                )
            )
    if requirements.maximum_creators is not None:
        creator_value = lambda role: role.system_traits.get("creativity", 0.0) >= 1.2
        if _maximum_count(candidate_variables, catalogue, creator_value) <= requirements.maximum_creators:
            components.append(_Expression({}, 1.0))
        else:
            creator_count = _role_count_expression(
                candidate_variables, catalogue, creator_value
            )
            components.append(
                _discrete_cap_score(
                    model,
                    creator_count,
                    requirements.maximum_creators,
                    len(tactic.slots),
                )
            )
    total = _Expression({})
    for component in components:
        total = _add(total, component)
    return _scale(total, 100.0 / len(components)), True


def _instruction_demands(tactic: TacticDefinition) -> dict[str, float]:
    demands: dict[str, float] = {}
    for instruction in tactic.instructions:
        for dimension, minimum in _INSTRUCTION_REQUIREMENTS.get(instruction, {}).items():
            demands[dimension] = max(demands.get(dimension, 0.0), minimum)
    return demands


def optimise_tactic_jointly(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
    system_policy: SystemFitPolicy = SystemFitPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
) -> JointOptimisationResult | None:
    """Solve role choice and full-XI assignment in one mixed-integer model."""
    derived = catalogue.for_context(
        tactic.key, extra_emphasis=opponent_attribute_emphasis(opponent)
    )
    ordered_players = tuple(sorted(players, key=lambda item: (item.name.casefold(), item.id)))
    choices = _build_choices(
        tactic, ordered_players, derived, readiness_policy, familiarity_policy
    )

    model = _Model()
    candidate_variables: list[tuple[_CandidateAssignment, int]] = [
        (candidate, model.variable(lower=0.0, upper=1.0, binary=True))
        for player_choices in choices
        for candidate in player_choices
    ]
    if not candidate_variables:
        return None

    for slot_index in range(len(tactic.slots)):
        variables = {
            variable: 1.0
            for candidate, variable in candidate_variables
            if candidate.slot_index == slot_index
        }
        if not variables:
            return None
        model.constraint(variables, lower=1.0, upper=1.0)
    for player_index in range(len(ordered_players)):
        variables = {
            variable: 1.0
            for candidate, variable in candidate_variables
            if candidate.player_index == player_index
        }
        if variables:
            model.constraint(variables, upper=1.0)

    for group in derived.exclusive_role_groups:
        variables = {
            variable: 1.0
            for candidate, variable in candidate_variables
            if candidate.assignment.intrinsic_role_score.role_key in group.role_keys
            and (
                group.position is None
                or tactic.slots[candidate.slot_index].position == group.position
            )
        }
        if variables:
            model.constraint(variables, upper=1.0)

    weakest = model.variable(lower=0.0, upper=100.0)
    for candidate, variable in candidate_variables:
        score = candidate.assignment.selection_score.central
        model.constraint({weakest: 1.0, variable: 100.0}, upper=score + 100.0)

    mean = _Expression(
        {
            variable: candidate.assignment.selection_score.central / len(tactic.slots)
            for candidate, variable in candidate_variables
        }
    )
    xi = _add(
        _scale(mean, 1.0 - fit_policy.weakest_slot_weight),
        _Expression({weakest: fit_policy.weakest_slot_weight}),
    )
    coherence, coherence_active = _coherence_score(
        model, tactic, candidate_variables, derived
    )
    instruction_demands = _instruction_demands(tactic)
    instruction = _demand_score(
        model, candidate_variables, derived, instruction_demands
    )
    instruction_active = bool(instruction_demands)
    floors = system_floors(opponent)
    opponent_fit = _demand_score(model, candidate_variables, derived, floors)
    opponent_active = bool(floors)

    weighted = [(xi, system_policy.xi_weight)]
    components = [xi]
    if coherence_active:
        weighted.append((coherence, system_policy.coherence_weight))
        components.append(coherence)
    if instruction_active:
        weighted.append((instruction, system_policy.instruction_weight))
        components.append(instruction)
    if opponent_active:
        weighted.append((opponent_fit, system_policy.opponent_weight))
        components.append(opponent_fit)
    total_weight = sum(weight for _, weight in weighted)
    weighted_mean = _Expression({})
    for expression, weight in weighted:
        weighted_mean = _add(weighted_mean, _scale(expression, weight / total_weight))

    weakest_component = model.variable(lower=0.0, upper=100.0)
    for component in components:
        row = {weakest_component: 1.0}
        for index, coefficient in component.coefficients.items():
            row[index] = row.get(index, 0.0) - coefficient
        model.constraint(row, upper=component.constant)
    final = _add(
        _scale(weighted_mean, 1.0 - system_policy.weakest_component_weight),
        _Expression({weakest_component: system_policy.weakest_component_weight}),
    )
    model.maximise(final)
    solved = model.solve()
    if not solved.success or solved.x is None:
        return None

    selected_candidates = [
        candidate
        for candidate, variable in candidate_variables
        if solved.x[variable] > 0.5
    ]
    assignments = tuple(
        candidate.assignment
        for candidate in sorted(selected_candidates, key=lambda item: item.slot_index)
    )
    _, _, exact_xi = _tactic_fit(assignments, len(tactic.slots), fit_policy)
    exact_coherence, exact_instruction, exact_opponent, exact_score = _system_fit(
        tactic, assignments, derived, exact_xi, system_policy, opponent
    )
    return JointOptimisationResult(
        assignments=assignments,
        objective=exact_score.central,
        xi_score=exact_xi.central,
        coherence_score=exact_coherence.score,
        instruction_score=exact_instruction.score,
        opponent_score=exact_opponent.score,
        variable_count=len(model.lower),
        binary_variable_count=sum(model.integrality),
        constraint_count=len(model.rows),
        mip_node_count=int(getattr(solved, "mip_node_count", 0) or 0),
    )
