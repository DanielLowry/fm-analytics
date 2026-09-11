from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticSlot
from fm_analytics.analytics.role_scoring import RoleScore, score_role
from fm_analytics.analytics.xi_selection import (
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    TacticEvaluation,
    is_player_selectable,
)


class WeaknessKind(StrEnum):
    STRUCTURAL_GAP = "structural_gap"
    SIMULTANEOUS_GAP = "simultaneous_gap"
    TEMPORARY_GAP = "temporary_gap"
    WEAK_STARTER = "weak_starter"
    NO_BACKUP = "no_backup"
    WEAK_BACKUP = "weak_backup"
    SHARED_COVER = "shared_cover"


@dataclass(frozen=True)
class WeaknessPolicy:
    version: str = "weakness-v1"
    starter_score_threshold: float = 50
    backup_score_threshold: float = 40

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("weakness policy version is required")
        for value in (self.starter_score_threshold, self.backup_score_threshold):
            if not 0 <= value <= 100:
                raise ValueError("weakness score thresholds must be between 0 and 100")


@dataclass(frozen=True)
class DepthCandidate:
    player_id: str
    player_name: str
    role_score: RoleScore


@dataclass(frozen=True)
class SlotDepth:
    slot: TacticSlot
    starter: SlotAssignment | None
    available_backups: tuple[DepthCandidate, ...]
    temporarily_unavailable: tuple[DepthCandidate, ...]
    occupied_starter_cover: tuple[DepthCandidate, ...]


@dataclass(frozen=True)
class Weakness:
    kind: WeaknessKind
    slot_keys: tuple[str, ...]
    player_id: str | None
    message: str


@dataclass(frozen=True)
class WeaknessReport:
    tactic_key: str
    policy_version: str
    starter_score_threshold: float
    backup_score_threshold: float
    depth: tuple[SlotDepth, ...]
    weaknesses: tuple[Weakness, ...]


def assess_weaknesses(
    evaluation: TacticEvaluation,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    policy: WeaknessPolicy = WeaknessPolicy(),
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
) -> WeaknessReport:
    if evaluation.tactic.key not in catalogue.tactics:
        raise ValueError("evaluation tactic does not belong to the catalogue")
    starters = {assignment.slot.key: assignment for assignment in evaluation.assignments}
    starter_ids = {assignment.player_id for assignment in evaluation.assignments}
    depth: list[SlotDepth] = []
    weaknesses: list[Weakness] = []

    for slot in evaluation.tactic.slots:
        starter = starters.get(slot.key)
        available, unavailable = _backups_for_slot(
            slot,
            players,
            starter_ids,
            catalogue,
            readiness_policy,
        )
        occupied = _occupied_starter_cover(
            slot,
            players,
            starter_ids,
            catalogue,
        )
        slot_depth = SlotDepth(
            slot=slot,
            starter=starter,
            available_backups=available,
            temporarily_unavailable=unavailable,
            occupied_starter_cover=occupied,
        )
        depth.append(slot_depth)
        if starter is None:
            if unavailable:
                kind = WeaknessKind.TEMPORARY_GAP
                reason = "only free position-eligible players are unavailable"
            elif occupied:
                kind = WeaknessKind.SIMULTANEOUS_GAP
                reason = "the only position-eligible cover is used in another starting slot"
            else:
                kind = WeaknessKind.STRUCTURAL_GAP
                reason = "no position-eligible player exists"
            weaknesses.append(
                Weakness(kind, (slot.key,), None, f"{slot.key} is unfilled: {reason}")
            )
            continue
        if starter.intrinsic_role_score.score.central < policy.starter_score_threshold:
            weaknesses.append(
                Weakness(
                    WeaknessKind.WEAK_STARTER,
                    (slot.key,),
                    starter.player_id,
                    f"{starter.player_name} is below the starter role-fit threshold at {slot.key}",
                )
            )
        if not available:
            detail = "currently available"
            if unavailable:
                detail += "; nominal cover is temporarily unavailable"
            weaknesses.append(
                Weakness(
                    WeaknessKind.NO_BACKUP,
                    (slot.key,),
                    None,
                    f"{slot.key} has no {detail} backup",
                )
            )
        elif available[0].role_score.score.central < policy.backup_score_threshold:
            weaknesses.append(
                Weakness(
                    WeaknessKind.WEAK_BACKUP,
                    (slot.key,),
                    available[0].player_id,
                    f"best available cover is below the backup threshold at {slot.key}",
                )
            )

    cover_slots: dict[str, list[str]] = {}
    cover_names: dict[str, str] = {}
    for slot_depth in depth:
        if slot_depth.available_backups:
            backup = slot_depth.available_backups[0]
            cover_slots.setdefault(backup.player_id, []).append(slot_depth.slot.key)
            cover_names[backup.player_id] = backup.player_name
    for player_id, slot_keys in cover_slots.items():
        if len(slot_keys) > 1:
            weaknesses.append(
                Weakness(
                    WeaknessKind.SHARED_COVER,
                    tuple(slot_keys),
                    player_id,
                    f"{cover_names[player_id]} is first cover for multiple simultaneous slots",
                )
            )

    return WeaknessReport(
        tactic_key=evaluation.tactic.key,
        policy_version=policy.version,
        starter_score_threshold=policy.starter_score_threshold,
        backup_score_threshold=policy.backup_score_threshold,
        depth=tuple(depth),
        weaknesses=tuple(weaknesses),
    )


def _backups_for_slot(
    slot: TacticSlot,
    players: Sequence[PlayerSelectionInput],
    starter_ids: set[str],
    catalogue: FootballCatalogue,
    readiness_policy: ReadinessPolicy,
) -> tuple[tuple[DepthCandidate, ...], tuple[DepthCandidate, ...]]:
    role = catalogue.roles[slot.role_key]
    available: list[DepthCandidate] = []
    unavailable: list[DepthCandidate] = []
    for player in players:
        if player.id in starter_ids or slot.position not in player.positions:
            continue
        candidate = DepthCandidate(
            player_id=player.id,
            player_name=player.name,
            role_score=score_role(role, player.attributes),
        )
        target = (
            available
            if is_player_selectable(player, policy=readiness_policy)
            else unavailable
        )
        target.append(candidate)
    key = lambda item: (
        -item.role_score.score.central,
        -item.role_score.score.lower,
        item.player_name.casefold(),
        item.player_id,
    )
    return tuple(sorted(available, key=key)), tuple(sorted(unavailable, key=key))


def _occupied_starter_cover(
    slot: TacticSlot,
    players: Sequence[PlayerSelectionInput],
    starter_ids: set[str],
    catalogue: FootballCatalogue,
) -> tuple[DepthCandidate, ...]:
    role = catalogue.roles[slot.role_key]
    candidates = (
        DepthCandidate(
            player_id=player.id,
            player_name=player.name,
            role_score=score_role(role, player.attributes),
        )
        for player in players
        if player.id in starter_ids and slot.position in player.positions
    )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                -item.role_score.score.central,
                item.player_name.casefold(),
                item.player_id,
            ),
        )
    )
