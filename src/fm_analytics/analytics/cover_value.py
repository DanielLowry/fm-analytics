"""How a scouting candidate compares as first cover, not just as a starter.

Split out of ``tactic_scouting.py`` (a cohesive sub-concern: see
``docs/tasks/senior-cover-value-contract.md``) rather than left inline, so a
non-starting candidate's cover value stays a small, independently testable
unit reused by the tactic-scouting ranking.
"""

from __future__ import annotations

from dataclasses import dataclass

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleScoreCache, ScoreBand
from fm_analytics.analytics.weaknesses import WeaknessKind, WeaknessReport
from fm_analytics.analytics.xi_models import FamiliarityPolicy, PlayerSelectionInput, ReadinessPolicy
from fm_analytics.analytics.xi_selection import score_player_for_slot


@dataclass(frozen=True)
class CoverAssessment:
    """How a non-starting candidate compares as first cover in his best backup slot.

    Reuses the exact tactic-weighted role score and taper the `/depth` page's
    own first-cover figure already uses (``weaknesses.DepthCandidate.role_score``),
    so the two pages can never disagree about who the first cover is. Only the
    single slot where the candidate clears the current cover by the largest
    margin is reported; a candidate who does not clear any eligible slot's
    current cover has no ``CoverAssessment`` at all (see
    ``TacticScoutingAssessment.cover_assessment``), rather than one showing a
    zero or negative margin.
    """

    slot_key: str
    position: str
    role_key: str
    role_name: str
    # The candidate's own tapered role score in this slot -- comparable
    # like-for-like with ``current_cover_score`` and with a starter's
    # ``tapered_attribute_score``.
    candidate_score: ScoreBand
    # None when the slot currently has no available backup at all: the
    # candidate would become first cover outright, not merely a better one.
    current_cover_name: str | None
    current_cover_score: float | None

    @property
    def margin(self) -> float:
        """How far the candidate's central score clears the current cover's.

        When there is no current cover, this is simply the candidate's own
        central score: there is nothing to subtract it from.
        """
        baseline = self.current_cover_score if self.current_cover_score is not None else 0.0
        return round(self.candidate_score.central - baseline, 6)


# Weakness kinds that mark a slot as needing help, either at starter or at
# cover -- the reserved decision `medium-weakest-slot-service` and
# `senior-trial-scenario-semantics` both settle the same way: structural,
# simultaneous and temporary gaps, and shared cover, do not by themselves
# make a slot's *role* one worth trialling towards.
_CONCERNING_WEAKNESS_KINDS = frozenset({
    WeaknessKind.WEAK_STARTER, WeaknessKind.NO_BACKUP, WeaknessKind.WEAK_BACKUP,
})


def is_weak_slot(weakness_report: WeaknessReport, slot_key: str) -> bool:
    return any(
        slot_key in weakness.slot_keys and weakness.kind in _CONCERNING_WEAKNESS_KINDS
        for weakness in weakness_report.weaknesses
    )


def best_cover_assessment(
    candidate_input: PlayerSelectionInput,
    weakness_report: WeaknessReport,
    derived_catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy,
    familiarity_policy: FamiliarityPolicy,
    role_score_cache: RoleScoreCache | None,
) -> CoverAssessment | None:
    """The one slot where this candidate clears the current first cover by most.

    Compares like-for-like with ``weaknesses.DepthCandidate.role_score``: the
    same role (whichever the actual starter plays, or the slot's default role
    if it is unfilled) and the same tactic attribute taper, with no readiness
    or familiarity discount on either side. Considers only slots where the
    candidate is position-eligible, and only ``available_backups`` -- a
    temporarily unavailable cover is not who he would actually be compared
    with today.
    """
    best: CoverAssessment | None = None
    for slot_depth in weakness_report.depth:
        slot = slot_depth.slot
        if slot.position not in candidate_input.positions:
            continue
        role_key = (
            slot_depth.starter.intrinsic_role_score.role_key
            if slot_depth.starter is not None
            else slot.role_key
        )
        assignment = score_player_for_slot(
            candidate_input,
            slot,
            derived_catalogue,
            readiness_policy=readiness_policy,
            familiarity_policy=familiarity_policy,
            role_key=role_key,
            role_score_cache=role_score_cache,
        )
        if assignment is None:
            continue
        current_cover = slot_depth.available_backups[0] if slot_depth.available_backups else None
        current_cover_score = current_cover.role_score.score.central if current_cover else None
        candidate_score = assignment.tapered_attribute_score
        if current_cover_score is not None and candidate_score.central <= current_cover_score:
            continue
        candidate_assessment = CoverAssessment(
            slot_key=slot.key,
            position=slot.position,
            role_key=role_key,
            role_name=derived_catalogue.role_for_slot(slot, role_key).name,
            candidate_score=candidate_score,
            current_cover_name=current_cover.player_name if current_cover else None,
            current_cover_score=current_cover_score,
        )
        if best is None or candidate_assessment.margin > best.margin:
            best = candidate_assessment
    return best
