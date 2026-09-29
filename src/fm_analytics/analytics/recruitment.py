from __future__ import annotations

from dataclasses import dataclass

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.weaknesses import (
    WeaknessKind,
    WeaknessReport,
)


@dataclass(frozen=True)
class RecruitmentBrief:
    tactic_key: str
    slot_keys: tuple[str, ...]
    position: str
    role_key: str
    need: str
    minimum_role_score: float
    reason: str


def build_recruitment_briefs(
    report: WeaknessReport,
    catalogue: FootballCatalogue,
) -> tuple[RecruitmentBrief, ...]:
    if report.tactic_key not in catalogue.tactics:
        raise ValueError("weakness report tactic does not belong to the catalogue")
    tactic = catalogue.tactics[report.tactic_key]
    slots = {slot.key: slot for slot in tactic.slots}
    selected_roles = {
        item.slot.key: item.intrinsic_role_score.role_key
        for item in (depth.starter for depth in report.depth)
        if item is not None
    }
    briefs: list[RecruitmentBrief] = []
    seen: set[tuple[str, str, str]] = set()
    for weakness in report.weaknesses:
        if weakness.kind is WeaknessKind.TEMPORARY_GAP:
            continue
        need = "starter" if weakness.kind is WeaknessKind.WEAK_STARTER else "depth"
        threshold = weakness.target_score if weakness.target_score is not None else 0.0
        relevant_slots = tuple(slots[key] for key in weakness.slot_keys)
        grouped: dict[tuple[str, str], list[str]] = {}
        for slot in relevant_slots:
            grouped.setdefault(
                (slot.position, selected_roles.get(slot.key, slot.role_key)), []
            ).append(slot.key)
        for (position, role_key), slot_keys in grouped.items():
            identity = (position, role_key, need)
            if identity in seen:
                continue
            seen.add(identity)
            briefs.append(
                RecruitmentBrief(
                    tactic_key=report.tactic_key,
                    slot_keys=tuple(slot_keys),
                    position=position,
                    role_key=role_key,
                    need=need,
                    minimum_role_score=threshold,
                    reason=weakness.message,
                )
            )
    return tuple(briefs)
