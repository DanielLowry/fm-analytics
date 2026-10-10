"""Where the manager's own tactics need help: `reporting.weakest_slots`, for scouting and trial priority.

Moved out of `reporting` unchanged (it re-exports both names), so it is still
the one computation `/scouting` and the server use; it reads only what
`reporting.build_recommendation_bundle` already computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fm_analytics.analytics import MVP_CATALOGUE, WeaknessKind, opponent_attribute_emphasis
from fm_analytics.analytics.catalogue import FootballCatalogue

if TYPE_CHECKING:
    from fm_analytics.reporting import RecommendationBundle


@dataclass(frozen=True)
class WeakSlot:
    """One slot a pinned tactic (or the top-ranked tactic, with no pins) needs help at.

    Read entirely from an already-computed `WeaknessReport`; see
    `weakest_slots`. `starter_score`/`cover_score` are the same tapered
    central figure `/depth` itself shows for the starter and first available
    backup, so this can never disagree with that page about who they are.
    """

    tactic_key: str
    tactic_name: str
    slot_key: str
    position: str
    role_key: str
    role_name: str
    # The role's attribute weights in this slot, heaviest first (ties by
    # name), as this tactic and the bundle's opponent profile weight them --
    # the same weighting the weakness report scored the starter and cover
    # with. Which of these matter enough to trigger re-scouting is the
    # caller's threshold, not this list's.
    role_attributes: tuple[tuple[str, float], ...]
    # "starter": the starter himself is the weak link. "cover": the starter is
    # fine, but there is no backup, or the backup drops off sharply.
    concern: str
    starter_name: str | None
    starter_score: float | None
    cover_name: str | None
    cover_score: float | None
    message: str


# Which weakness kinds name a slot worth surfacing here, and as which concern.
# Structural/simultaneous/temporary gaps and shared cover describe a squad-wide
# shortage or a scheduling clash, not a single slot's role being weak, so they
# are deliberately left out -- see docs/archive/tasks/medium-weakest-slot-service.md.
_WEAK_SLOT_CONCERNS = {
    WeaknessKind.WEAK_STARTER: "starter",
    WeaknessKind.NO_BACKUP: "cover",
    WeaknessKind.WEAK_BACKUP: "cover",
}


def weakest_slots(
    bundle: RecommendationBundle,
    *,
    catalogue: FootballCatalogue = MVP_CATALOGUE,
    limit: int = 8,
) -> tuple[WeakSlot, ...]:
    """Where the manager's own tactics need help, for scouting and trial priority.

    Covers the pinned tactics in their configured order, or just the
    top-ranked tactic with no pins -- the same tactics `bundle.pinned`/
    `bundle.primary` already default to. Reads only the weakness reports
    `build_recommendation_bundle` already computed; this calculates no new
    score, so `/scouting`'s navigation and trial-priority sort cannot
    disagree with `/depth` about where a tactic is weak.

    Worst starters first (lowest starter score), then worst cover (lowest
    cover score, with no cover at all ranked worse than any real backup), each
    group in tactic-then-slot order for ties. `limit` bounds the combined
    result, applied after that ordering, so the most severe items are the ones
    trimmed away last, never first.
    """
    tactics = bundle.pinned or (bundle.recommendation.selected,)
    starters: list[WeakSlot] = []
    covers: list[WeakSlot] = []
    seen: set[tuple[str, str, str]] = set()
    extra_emphasis = opponent_attribute_emphasis(bundle.policy.opponent)
    for evaluation in tactics:
        report = bundle.squad_depth.per_tactic[evaluation.tactic.key]
        depth_by_slot = {slot_depth.slot.key: slot_depth for slot_depth in report.depth}
        derived = catalogue.for_context(evaluation.tactic.key, extra_emphasis=extra_emphasis)
        for weakness in report.weaknesses:
            concern = _WEAK_SLOT_CONCERNS.get(weakness.kind)
            if concern is None:
                continue
            for slot_key in weakness.slot_keys:
                identity = (evaluation.tactic.key, slot_key, concern)
                if identity in seen:
                    continue
                seen.add(identity)
                slot_depth = depth_by_slot.get(slot_key)
                if slot_depth is None or slot_depth.starter is None:
                    continue
                role_key = slot_depth.starter.intrinsic_role_score.role_key
                cover = slot_depth.available_backups[0] if slot_depth.available_backups else None
                item = WeakSlot(
                    tactic_key=evaluation.tactic.key,
                    tactic_name=evaluation.tactic.name,
                    slot_key=slot_key,
                    position=slot_depth.slot.position,
                    role_key=role_key,
                    role_name=catalogue.roles[role_key].name,
                    role_attributes=tuple(
                        (attribute.name, attribute.weight)
                        for attribute in sorted(
                            derived.role_for_slot(slot_depth.slot, role_key).attributes,
                            key=lambda attribute: (-attribute.weight, attribute.name),
                        )
                    ),
                    concern=concern,
                    starter_name=slot_depth.starter.player_name,
                    starter_score=slot_depth.starter.tapered_attribute_score.central,
                    cover_name=cover.player_name if cover else None,
                    cover_score=cover.role_score.score.central if cover else None,
                    message=weakness.message,
                )
                (starters if concern == "starter" else covers).append(item)
    starters.sort(key=lambda item: (item.starter_score, item.tactic_key, item.slot_key))
    covers.sort(
        key=lambda item: (
            item.cover_score if item.cover_score is not None else -1.0,
            item.tactic_key,
            item.slot_key,
        )
    )
    return tuple((starters + covers)[:limit])
