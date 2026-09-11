from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleScore, score_role
from fm_analytics.analytics.weaknesses import (
    WeaknessKind,
    WeaknessReport,
)
from fm_analytics.imports import VisibleExportPlayer


class CandidateVerdict(StrEnum):
    MEETS_THRESHOLD = "meets_threshold"
    POSSIBLE_WITH_MORE_SCOUTING = "possible_with_more_scouting"


@dataclass(frozen=True)
class RecruitmentBrief:
    tactic_key: str
    slot_keys: tuple[str, ...]
    position: str
    role_key: str
    need: str
    minimum_role_score: float
    reason: str


@dataclass(frozen=True)
class RecruitmentCandidate:
    player_id: str
    player_name: str
    role_score: RoleScore
    verdict: CandidateVerdict
    scout_more: tuple[str, ...]


@dataclass(frozen=True)
class RecruitmentShortlist:
    brief: RecruitmentBrief
    catalogue_version: str
    candidates: tuple[RecruitmentCandidate, ...]


def build_recruitment_briefs(
    report: WeaknessReport,
    catalogue: FootballCatalogue,
) -> tuple[RecruitmentBrief, ...]:
    if report.tactic_key not in catalogue.tactics:
        raise ValueError("weakness report tactic does not belong to the catalogue")
    tactic = catalogue.tactics[report.tactic_key]
    slots = {slot.key: slot for slot in tactic.slots}
    briefs: list[RecruitmentBrief] = []
    seen: set[tuple[str, str, str]] = set()
    for weakness in report.weaknesses:
        if weakness.kind is WeaknessKind.TEMPORARY_GAP:
            continue
        if weakness.kind is WeaknessKind.WEAK_STARTER:
            need = "starter"
            threshold = report.starter_score_threshold
        else:
            need = "depth"
            threshold = report.backup_score_threshold
        relevant_slots = tuple(slots[key] for key in weakness.slot_keys)
        grouped: dict[tuple[str, str], list[str]] = {}
        for slot in relevant_slots:
            grouped.setdefault((slot.position, slot.role_key), []).append(slot.key)
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


def shortlist_candidates(
    brief: RecruitmentBrief,
    players: Sequence[VisibleExportPlayer],
    catalogue: FootballCatalogue,
    *,
    excluded_player_ids: frozenset[str] = frozenset(),
) -> RecruitmentShortlist:
    try:
        role = catalogue.roles[brief.role_key]
    except KeyError as exc:
        raise ValueError(f"unknown recruitment role {brief.role_key!r}") from exc

    candidates: list[RecruitmentCandidate] = []
    seen_ids: set[str] = set()
    for player in players:
        if player.id in seen_ids:
            raise ValueError("recruitment candidate player ids must be unique")
        seen_ids.add(player.id)
        if player.id in excluded_player_ids:
            continue
        if brief.position not in player.positions:
            continue
        result = score_role(role, player.attributes)
        if result.score.upper < brief.minimum_role_score:
            continue
        meets = result.score.lower >= brief.minimum_role_score
        candidates.append(
            RecruitmentCandidate(
                player_id=player.id,
                player_name=player.name,
                role_score=result,
                verdict=(
                    CandidateVerdict.MEETS_THRESHOLD
                    if meets
                    else CandidateVerdict.POSSIBLE_WITH_MORE_SCOUTING
                ),
                scout_more=(
                    ()
                    if meets
                    else tuple(gap.attribute for gap in result.information_gaps)
                ),
            )
        )
    return RecruitmentShortlist(
        brief=brief,
        catalogue_version=catalogue.version,
        candidates=tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.verdict is not CandidateVerdict.MEETS_THRESHOLD,
                    -item.role_score.score.central,
                    -item.role_score.score.lower,
                    item.player_name.casefold(),
                    item.player_id,
                ),
            )
        ),
    )
