"""Transparent POC scoring for interactions between selected roles.

This is deliberately not a claim to reproduce Football Manager's hidden
tactical engine.  It turns an explicit, reviewable description of role
contributions into two separate answers: whether the eleven form a balanced
system, and whether they can support the template's instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from fm_analytics.analytics.catalogue import TacticDefinition
from fm_analytics.analytics.role_scoring import RoleDefinition


SYSTEM_DIMENSIONS = (
    "width",
    "defensiveCover",
    "ballProgression",
    "creativity",
    "runners",
    "penetration",
    "aerialOutlet",
    "boxPresence",
    "restDefence",
    "pressing",
)


@dataclass(frozen=True)
class SystemAssessment:
    score: float
    contributions: Mapping[str, float]
    shortfalls: tuple[str, ...]
    attack_duties: int
    creators: int
    active: bool


# What each instruction asks of the eleven, in the same units a role's
# `system` traits supply (see data/roles/*.json).  The two are one scale:
# a demand is only meaningful if some legal XI can reach it, and
# tests/test_tactical_calibration.py fails any tactic whose instructions
# demand more than its role versions can supply.  Every instruction a tactic
# uses must appear here (also tested), or it silently costs nothing.
# These are declared football hypotheses, not fitted numbers.
_INSTRUCTION_REQUIREMENTS: Mapping[str, Mapping[str, float]] = {
    "Fairly Narrow": {"creativity": 1.0, "ballProgression": 1.5},
    "Fairly Wide": {"width": 3.0},
    "Narrower": {"defensiveCover": 2.0, "ballProgression": 1.0},
    "Shorter Passing": {"ballProgression": 2.0},
    "Slightly Shorter Passing": {"ballProgression": 1.5},
    "Slightly More Direct Passing": {"aerialOutlet": 0.8, "runners": 1.5},
    "More Direct Passing": {"aerialOutlet": 1.0, "runners": 1.5},
    "Much More Direct Passing": {"aerialOutlet": 2.0, "runners": 2.0},
    "Pass Into Space": {"runners": 2.0, "penetration": 1.5},
    "Play Out Of Defence": {"ballProgression": 3.0, "restDefence": 2.5},
    "Prevent Short GK Distribution": {"pressing": 3.0},
    "Work Ball Into Box": {"creativity": 2.0, "boxPresence": 1.5},
    "Hit Early Crosses": {"width": 2.0, "aerialOutlet": 1.5, "boxPresence": 1.5},
    "Overlap Left": {"width": 2.5, "restDefence": 2.0},
    "Overlap Right": {"width": 2.5, "restDefence": 2.0},
    "Higher Tempo": {"runners": 1.5, "pressing": 1.0},
    "Lower Tempo": {"ballProgression": 1.5, "restDefence": 2.0},
    "Slower Tempo": {"defensiveCover": 2.0, "restDefence": 2.0},
    "Hold Shape": {"defensiveCover": 2.5, "restDefence": 3.0},
    "Counter": {"runners": 1.5, "penetration": 1.5},
    "Counter-Press": {"pressing": 2.5, "restDefence": 2.5},
    "Much More Urgent Pressing": {"pressing": 3.5},
    "Standard Line of Engagement": {"defensiveCover": 2.0},
    "Higher Line of Engagement": {"pressing": 2.0, "restDefence": 2.5},
    "Much Higher Line of Engagement": {"pressing": 3.0, "restDefence": 3.0},
    "Lower Line of Engagement": {"defensiveCover": 2.5, "restDefence": 2.5},
    "Drop Deeper Line of Engagement": {"defensiveCover": 3.0, "restDefence": 3.0},
    "Much Lower Line of Engagement": {"defensiveCover": 3.5, "restDefence": 3.5},
    "Standard Defensive Line": {"restDefence": 2.0},
    "Higher Defensive Line": {"pressing": 1.0, "restDefence": 3.0},
    "Drop Off More Defensive Line": {"defensiveCover": 3.0, "restDefence": 3.0},
    "Much Deeper Defensive Line": {"defensiveCover": 3.5, "restDefence": 3.5},
    "Regroup": {"defensiveCover": 3.0, "restDefence": 3.0},
}


def role_traits(role: RoleDefinition) -> Mapping[str, float]:
    return role.system_traits


def assess_coherence(
    tactic: TacticDefinition,
    roles: Sequence[RoleDefinition],
) -> SystemAssessment:
    contributions = _contributions(roles)
    requirements = tactic.system_requirements
    active = bool(
        requirements.minimums
        or requirements.maximum_attack_duties is not None
        or requirements.maximum_creators is not None
    )
    attack_duties = round(contributions.pop("attackDuty", 0.0))
    creators = sum(role_traits(role).get("creativity", 0) >= 1.2 for role in roles)
    if not active:
        return SystemAssessment(100.0, contributions, (), attack_duties, creators, False)

    components: list[float] = []
    shortfalls: list[str] = []
    for dimension, minimum in requirements.minimums.items():
        actual = contributions.get(dimension, 0.0)
        components.append(min(1.0, actual / minimum) if minimum else 1.0)
        if actual < minimum:
            shortfalls.append(f"{dimension} {actual:.1f}/{minimum:.1f}")
    if requirements.maximum_attack_duties is not None:
        limit = requirements.maximum_attack_duties
        components.append(min(1.0, limit / attack_duties) if attack_duties else 1.0)
        if attack_duties > limit:
            shortfalls.append(f"attack duties {attack_duties}/{limit}")
    if requirements.maximum_creators is not None:
        limit = requirements.maximum_creators
        components.append(min(1.0, limit / creators) if creators else 1.0)
        if creators > limit:
            shortfalls.append(f"creators {creators}/{limit}")
    score = round(100 * sum(components) / len(components), 6) if components else 100.0
    return SystemAssessment(score, contributions, tuple(shortfalls), attack_duties, creators, True)


def assess_instruction_suitability(roles: Sequence[RoleDefinition], instructions: Sequence[str]) -> SystemAssessment:
    demands: dict[str, float] = {}
    for instruction in instructions:
        for dimension, minimum in _INSTRUCTION_REQUIREMENTS.get(instruction, {}).items():
            demands[dimension] = max(demands.get(dimension, 0.0), minimum)
    return assess_demands(roles, demands)


def assess_demands(roles: Sequence[RoleDefinition], demands: Mapping[str, float]) -> SystemAssessment:
    """How fully the eleven's combined traits meet a set of minimums.

    Inactive (and 100) when nothing is demanded, which is what lets a component
    built on it drop out of a blend entirely rather than dilute it.
    """
    contributions = _contributions(roles)
    attack_duties = round(contributions.pop("attackDuty", 0.0))
    creators = sum(role_traits(role).get("creativity", 0) >= 1.2 for role in roles)
    if not demands:
        return SystemAssessment(100.0, contributions, (), attack_duties, creators, False)
    components = []
    shortfalls = []
    for dimension, minimum in demands.items():
        actual = contributions.get(dimension, 0.0)
        components.append(min(1.0, actual / minimum))
        if actual < minimum:
            shortfalls.append(f"{dimension} {actual:.1f}/{minimum:.1f}")
    return SystemAssessment(
        round(100 * sum(components) / len(components), 6),
        contributions,
        tuple(shortfalls),
        attack_duties,
        creators,
        True,
    )


def _contributions(roles: Sequence[RoleDefinition]) -> dict[str, float]:
    totals = {dimension: 0.0 for dimension in SYSTEM_DIMENSIONS}
    totals["attackDuty"] = 0.0
    for role in roles:
        for dimension, value in role_traits(role).items():
            totals[dimension] = round(totals.get(dimension, 0.0) + value, 6)
    return totals
