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
from itertools import product
from math import inf, sqrt
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticDefinition
from fm_analytics.analytics.opponent import (
    OpponentProfile,
    attribute_emphasis as opponent_attribute_emphasis,
)
from fm_analytics.analytics.xi_models import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    TacticFitPolicy,
    _CandidateAssignment,
)
from fm_analytics.analytics.xi_selection import (
    _apply_balance_multiplier,
    _build_choices,
    _role_structure_checks,
    _tactic_balance_multiplier,
    _tactic_fit,
)
from fm_analytics.analytics.tactical_system import (
    assess_coherence,
    assess_instruction_suitability,
)


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


def optimise_tactic_jointly(
    tactic: TacticDefinition,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
    fit_policy: TacticFitPolicy = TacticFitPolicy(),
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

    # Select one complete legal role version. These constraints also stop the
    # joint model from assembling an unlisted mixture of slot alternatives.
    role_versions: list[tuple[tuple[str, ...], float, int]] = []
    role_options = tuple(derived.role_keys_for_slot(slot) for slot in tactic.slots)
    for role_keys in product(*role_options):
        if not derived.role_version_is_legal(tactic, role_keys):
            continue
        roles = tuple(derived.roles[role_key] for role_key in role_keys)
        balance_multiplier = _tactic_balance_multiplier(
            assess_coherence(tactic, roles),
            assess_instruction_suitability(roles, tactic.instructions),
        )
        role_versions.append(
            (role_keys, balance_multiplier, model.variable(upper=1.0, binary=True))
        )
    if not role_versions:
        return None
    model.constraint(
        {version_variable: 1.0 for _, _, version_variable in role_versions},
        lower=1.0,
        upper=1.0,
    )
    for role_keys, _balance, version_variable in role_versions:
        for slot_index, role_key in enumerate(role_keys):
            matching = {
                variable: 1.0
                for candidate, variable in candidate_variables
                if candidate.slot_index == slot_index
                and candidate.assignment.intrinsic_role_score.role_key == role_key
            }
            matching[version_variable] = -1.0
            model.constraint(matching, lower=0.0)

    # Let U be the mean square-root player utility. For each role version,
    # version_utility is U when that version is selected and zero otherwise.
    # Maximising sqrt(balance) * U is exactly equivalent to maximising the final
    # balance * U² score, while keeping the model linear.
    utility_coefficients = {
        variable: sqrt(candidate.assignment.selection_score.central)
        / len(tactic.slots)
        for candidate, variable in candidate_variables
    }
    utility_bound = 10.0  # sqrt(100), the maximum possible mean utility.
    objective_coefficients: dict[int, float] = {}
    for _role_keys, balance_multiplier, version_variable in role_versions:
        version_utility = model.variable(lower=0.0, upper=utility_bound)
        model.constraint(
            {version_utility: 1.0, version_variable: -utility_bound},
            upper=0.0,
        )
        model.constraint(
            {version_utility: 1.0}
            | {index: -value for index, value in utility_coefficients.items()},
            upper=0.0,
        )
        model.constraint(
            {version_utility: 1.0, version_variable: -utility_bound}
            | {index: -value for index, value in utility_coefficients.items()},
            lower=-utility_bound,
        )
        objective_coefficients[version_utility] = sqrt(balance_multiplier)
    model.maximise(_Expression(objective_coefficients))
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
    _, _, exact_xi = _tactic_fit(assignments, len(tactic.slots))
    exact_coherence, exact_instruction, exact_opponent = _role_structure_checks(
        tactic, assignments, derived, opponent
    )
    balance_multiplier = _tactic_balance_multiplier(
        exact_coherence, exact_instruction
    )
    exact_score = _apply_balance_multiplier(exact_xi, balance_multiplier)
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
