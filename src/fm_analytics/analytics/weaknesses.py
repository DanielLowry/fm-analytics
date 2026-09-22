from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticSlot
from fm_analytics.analytics.attribute_taper import assess_tapers, taper_role_score
from fm_analytics.analytics.opponent import OpponentProfile, attribute_emphasis
from fm_analytics.analytics.role_scoring import RoleDefinition, RoleScore, score_role
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
    """Flag weak links relative to this squad, not against fixed cut-offs.

    The question this answers is "how do I get the most out of the players I
    have", so a weakness is defined against the team itself: a starter is a
    weak link when their role fit falls well below the XI's median, and cover
    is weak when it drops off sharply from the starter it would replace. The
    same policy therefore means the same thing for a non-league squad and an
    elite one. Comparison against rival squads is a separate, later question
    that needs other clubs' data.
    """

    version: str = "weakness-v2"
    starter_ratio: float = 0.85
    backup_ratio: float = 0.80

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("weakness policy version is required")
        for value in (self.starter_ratio, self.backup_ratio):
            if not 0 < value <= 1:
                raise ValueError("weakness ratios must be greater than 0 and at most 1")


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
    # The role score that would clear this weakness, so a recruitment brief
    # can state a concrete bar. Relative to this squad; see WeaknessPolicy.
    target_score: float | None = None


@dataclass(frozen=True)
class WeaknessReport:
    tactic_key: str
    policy_version: str
    reference_score: float
    starter_ratio: float
    backup_ratio: float
    depth: tuple[SlotDepth, ...]
    weaknesses: tuple[Weakness, ...]


def assess_weaknesses(
    evaluation: TacticEvaluation,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    policy: WeaknessPolicy = WeaknessPolicy(),
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
) -> WeaknessReport:
    if evaluation.tactic.key not in catalogue.tactics:
        raise ValueError("evaluation tactic does not belong to the catalogue")
    catalogue = catalogue.for_context(
        evaluation.tactic.key, extra_emphasis=attribute_emphasis(opponent)
    )
    starters = {assignment.slot.key: assignment for assignment in evaluation.assignments}
    starter_ids = {assignment.player_id for assignment in evaluation.assignments}
    reference = round(
        median(
            assignment.tapered_attribute_score.central
            for assignment in evaluation.assignments
        )
        if evaluation.assignments
        else 0.0,
        6,
    )
    starter_bar = round(reference * policy.starter_ratio, 6)
    depth: list[SlotDepth] = []
    weaknesses: list[Weakness] = []

    for slot in evaluation.tactic.slots:
        starter = starters.get(slot.key)
        # Depth is assessed against the role the joint optimiser actually
        # selected, rather than the template's former default role.
        role_key = (
            starter.intrinsic_role_score.role_key
            if starter is not None
            else slot.role_key
        )
        available, unavailable = _backups_for_slot(
            slot,
            role_key,
            players,
            starter_ids,
            catalogue,
            readiness_policy,
        )
        occupied = _occupied_starter_cover(
            slot,
            role_key,
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
                Weakness(
                    kind, (slot.key,), None, f"{slot.key} is unfilled: {reason}", starter_bar
                )
            )
            continue
        starter_score = starter.tapered_attribute_score.central
        backup_bar = round(starter_score * policy.backup_ratio, 6)
        if starter_score < starter_bar:
            weaknesses.append(
                Weakness(
                    WeaknessKind.WEAK_STARTER,
                    (slot.key,),
                    starter.player_id,
                    f"{starter.player_name} is a weak link at {slot.key} "
                    f"({starter_score:.0f} vs XI median {reference:.0f})",
                    starter_bar,
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
                    backup_bar,
                )
            )
        elif available[0].role_score.score.central < backup_bar:
            weaknesses.append(
                Weakness(
                    WeaknessKind.WEAK_BACKUP,
                    (slot.key,),
                    available[0].player_id,
                    f"cover at {slot.key} drops off sharply "
                    f"({available[0].role_score.score.central:.0f} vs starter {starter_score:.0f})",
                    backup_bar,
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
                    round(
                        max(
                            starters[key].tapered_attribute_score.central
                            for key in slot_keys
                            if key in starters
                        )
                        * policy.backup_ratio,
                        6,
                    ),
                )
            )

    return WeaknessReport(
        tactic_key=evaluation.tactic.key,
        policy_version=policy.version,
        reference_score=reference,
        starter_ratio=policy.starter_ratio,
        backup_ratio=policy.backup_ratio,
        depth=tuple(depth),
        weaknesses=tuple(weaknesses),
    )


def _tactic_role_score(
    catalogue: FootballCatalogue,
    slot: TacticSlot,
    role: RoleDefinition,
    player: PlayerSelectionInput,
) -> RoleScore:
    """A player's role score in this tactic's slot, with its attribute taper applied.

    Cover is judged like for like with the starter he would replace, whose score
    (`SlotAssignment.tapered_attribute_score`) carries the same taper.
    """
    return taper_role_score(
        score_role(role, player.attributes),
        assess_tapers(catalogue.tapers_for_slot(slot), player.attributes),
    )


def _backups_for_slot(
    slot: TacticSlot,
    role_key: str,
    players: Sequence[PlayerSelectionInput],
    starter_ids: set[str],
    catalogue: FootballCatalogue,
    readiness_policy: ReadinessPolicy,
) -> tuple[tuple[DepthCandidate, ...], tuple[DepthCandidate, ...]]:
    role = catalogue.role_for_slot(slot, role_key)
    available: list[DepthCandidate] = []
    unavailable: list[DepthCandidate] = []
    for player in players:
        if player.id in starter_ids or slot.position not in player.positions:
            continue
        candidate = DepthCandidate(
            player_id=player.id,
            player_name=player.name,
            role_score=_tactic_role_score(catalogue, slot, role, player),
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
    role_key: str,
    players: Sequence[PlayerSelectionInput],
    starter_ids: set[str],
    catalogue: FootballCatalogue,
) -> tuple[DepthCandidate, ...]:
    role = catalogue.role_for_slot(slot, role_key)
    candidates = (
        DepthCandidate(
            player_id=player.id,
            player_name=player.name,
            role_score=_tactic_role_score(catalogue, slot, role, player),
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
