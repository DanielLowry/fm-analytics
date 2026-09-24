"""Advisory checks for player-independent tactic role combinations."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticDefinition
from fm_analytics.analytics.tactical_system import (
    SystemAssessment,
    assess_coherence,
    assess_instruction_suitability,
)


@dataclass(frozen=True)
class StructuralCombinationFailure:
    role_keys: tuple[str, ...]
    balance: SystemAssessment
    instructions: SystemAssessment


@dataclass(frozen=True)
class TacticStructureCheck:
    tactic: TacticDefinition
    combination_count: int
    failures: tuple[StructuralCombinationFailure, ...]


def check_tactic_structure(
    tactic: TacticDefinition,
    catalogue: FootballCatalogue,
) -> TacticStructureCheck:
    """Check every permitted role combination without looking at any players."""
    failures = []
    combination_count = 0
    options = tuple(catalogue.role_keys_for_slot(slot) for slot in tactic.slots)
    for role_keys in product(*options):
        if not catalogue.role_version_is_legal(tactic, role_keys):
            continue
        combination_count += 1
        roles = tuple(catalogue.roles[key] for key in role_keys)
        balance = assess_coherence(tactic, roles)
        instructions = assess_instruction_suitability(roles, tactic.instructions)
        if balance.shortfalls or instructions.shortfalls:
            failures.append(
                StructuralCombinationFailure(role_keys, balance, instructions)
            )
    return TacticStructureCheck(tactic, combination_count, tuple(failures))


def check_catalogue_structure(
    catalogue: FootballCatalogue,
) -> tuple[TacticStructureCheck, ...]:
    return tuple(
        check_tactic_structure(tactic, catalogue)
        for tactic in catalogue.tactics.values()
    )
