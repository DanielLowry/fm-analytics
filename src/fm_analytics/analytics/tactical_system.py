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


# These are deliberately coarse starting hypotheses.  Catalogue authors can
# override them per RoleDefinition via `system_traits`; keeping this mapping
# central makes every current assumption reviewable during the POC.
_DEFAULT_ROLE_TRAITS: Mapping[str, Mapping[str, float]] = {
    "gk_defend": {"defensiveCover": 0.5, "restDefence": 1.0, "aerialOutlet": 0.4},
    "sk_defend": {"defensiveCover": 0.7, "restDefence": 1.0, "ballProgression": 0.8, "pressing": 0.4},
    "cd_defend": {"defensiveCover": 1.8, "restDefence": 1.8, "aerialOutlet": 0.8},
    "bpd_defend": {"defensiveCover": 1.5, "restDefence": 1.6, "ballProgression": 1.3, "aerialOutlet": 0.7},
    "cd_cover": {"defensiveCover": 1.8, "restDefence": 1.8, "pressing": 0.5},
    "fb_support": {"width": 1.0, "defensiveCover": 0.9, "ballProgression": 0.6, "restDefence": 0.8},
    "wb_dl_dr_support": {"width": 1.5, "defensiveCover": 0.5, "ballProgression": 1.0, "runners": 0.8, "pressing": 0.8},
    "wb_wbl_wbr_support": {"width": 1.5, "defensiveCover": 0.5, "ballProgression": 1.0, "runners": 0.8, "pressing": 0.8},
    "wb_dl_dr_attack": {"width": 1.8, "ballProgression": 1.2, "runners": 1.1, "penetration": 0.7, "boxPresence": 0.4, "attackDuty": 1.0},
    "wb_wbl_wbr_attack": {"width": 1.8, "ballProgression": 1.2, "runners": 1.1, "penetration": 0.7, "boxPresence": 0.4, "attackDuty": 1.0},
    "dm_defend": {"defensiveCover": 1.6, "ballProgression": 0.5, "restDefence": 1.6},
    "dm_support": {"defensiveCover": 1.1, "ballProgression": 1.0, "restDefence": 1.2},
    "bwm_dm_support": {"defensiveCover": 1.2, "pressing": 1.5, "ballProgression": 0.5, "restDefence": 0.8},
    "bwm_mc_support": {"defensiveCover": 1.2, "pressing": 1.5, "ballProgression": 0.5, "restDefence": 0.8},
    "dlp_dm_support": {"ballProgression": 1.5, "creativity": 1.4, "restDefence": 0.7},
    "dlp_mc_support": {"ballProgression": 1.5, "creativity": 1.4, "restDefence": 0.7},
    "cm_defend": {"defensiveCover": 1.0, "ballProgression": 0.6, "restDefence": 0.9},
    "cm_support": {"ballProgression": 1.0, "creativity": 0.7, "runners": 0.6, "pressing": 0.5},
    "b2b_support": {"defensiveCover": 0.7, "ballProgression": 0.8, "runners": 1.3, "boxPresence": 0.7, "pressing": 1.0},
    "mez_attack": {"width": 0.5, "ballProgression": 0.9, "creativity": 0.8, "runners": 1.1, "penetration": 0.7, "attackDuty": 1.0},
    "wm_support": {"width": 1.5, "defensiveCover": 0.5, "ballProgression": 0.7, "pressing": 0.6},
    "winger_ml_mr_support": {"width": 1.8, "ballProgression": 0.9, "creativity": 0.7, "runners": 0.6, "pressing": 0.5},
    "winger_aml_amr_support": {"width": 1.8, "ballProgression": 0.9, "creativity": 0.7, "runners": 0.6, "pressing": 0.5},
    "winger_ml_mr_attack": {"width": 1.8, "runners": 1.1, "penetration": 1.0, "boxPresence": 0.5, "attackDuty": 1.0},
    "winger_aml_amr_attack": {"width": 1.8, "runners": 1.1, "penetration": 1.0, "boxPresence": 0.5, "attackDuty": 1.0},
    "if_attack": {"runners": 1.2, "penetration": 1.4, "boxPresence": 0.8, "attackDuty": 1.0},
    "am_support": {"creativity": 1.4, "ballProgression": 0.7, "runners": 0.5, "pressing": 0.3},
    "ap_mc_attack": {"creativity": 1.8, "ballProgression": 0.8, "penetration": 0.5, "attackDuty": 1.0},
    "ap_amc_attack": {"creativity": 1.8, "ballProgression": 0.8, "penetration": 0.5, "attackDuty": 1.0},
    "ss_attack": {"runners": 1.5, "penetration": 1.2, "boxPresence": 1.0, "attackDuty": 1.0},
    "dlf_support": {"creativity": 0.9, "ballProgression": 0.5, "boxPresence": 0.7, "aerialOutlet": 0.4},
    "cf_support": {"creativity": 0.8, "ballProgression": 0.6, "boxPresence": 0.9, "aerialOutlet": 0.7},
    "af_attack": {"runners": 1.5, "penetration": 1.6, "boxPresence": 1.0, "attackDuty": 1.0},
    "p_attack": {"runners": 1.4, "penetration": 1.4, "boxPresence": 0.9, "attackDuty": 1.0},
    "tm_attack": {"aerialOutlet": 1.8, "boxPresence": 1.3, "attackDuty": 1.0},
}


_INSTRUCTION_REQUIREMENTS: Mapping[str, Mapping[str, float]] = {
    "Fairly Narrow": {"creativity": 1.5, "ballProgression": 1.5},
    "Fairly Wide": {"width": 3.0},
    "Narrower": {"creativity": 1.5, "ballProgression": 1.5},
    "Shorter Passing": {"ballProgression": 2.0, "creativity": 1.5},
    "Slightly More Direct Passing": {"aerialOutlet": 0.8, "runners": 1.5},
    "Play Out Of Defence": {"ballProgression": 3.0, "restDefence": 2.5},
    "Work Ball Into Box": {"creativity": 2.0, "boxPresence": 1.5},
    "Higher Tempo": {"runners": 1.5, "pressing": 1.0},
    "Lower Tempo": {"creativity": 1.5, "restDefence": 2.0},
    "Slower Tempo": {"creativity": 1.5, "restDefence": 2.0},
    "Counter": {"runners": 2.0, "penetration": 1.5},
    "Counter-Press": {"pressing": 3.0, "restDefence": 2.5},
    "Much More Urgent Pressing": {"pressing": 4.0},
    "Standard Line of Engagement": {"defensiveCover": 2.0},
    "Higher Line of Engagement": {"pressing": 2.5, "restDefence": 2.5},
    "Much Higher Line of Engagement": {"pressing": 3.5, "restDefence": 3.0},
    "Drop Deeper Line of Engagement": {"defensiveCover": 3.0, "restDefence": 3.0},
    "Much Lower Line of Engagement": {"defensiveCover": 3.5, "restDefence": 3.5},
    "Standard Defensive Line": {"restDefence": 2.0},
    "Higher Defensive Line": {"pressing": 2.0, "restDefence": 3.0},
    "Drop Off More Defensive Line": {"defensiveCover": 3.0, "restDefence": 3.0},
    "Much Deeper Defensive Line": {"defensiveCover": 3.5, "restDefence": 3.5},
    "Regroup": {"defensiveCover": 3.0, "restDefence": 3.0},
}


def role_traits(role: RoleDefinition) -> Mapping[str, float]:
    return role.system_traits or _DEFAULT_ROLE_TRAITS.get(role.key, {})


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
    contributions = _contributions(roles)
    demands: dict[str, float] = {}
    for instruction in instructions:
        for dimension, minimum in _INSTRUCTION_REQUIREMENTS.get(instruction, {}).items():
            demands[dimension] = max(demands.get(dimension, 0.0), minimum)
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
