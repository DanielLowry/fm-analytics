"""Compare sensible structures after solving every complete player assignment.

The routine builders split a fixed budget over the jobs in each responsibility.
This keeps comparison linear, so each candidate still has an exact global
assignment. Coverage requirements decide eligibility before fit is compared.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, TYPE_CHECKING

from fm_analytics.analytics.role_scoring import ScoreBand
from fm_analytics.analytics.set_piece_config import DefensiveApproach, DefensiveTemplate

if TYPE_CHECKING:
    from fm_analytics.analytics.set_pieces import SetPieceRoutine


@dataclass(frozen=True)
class TemplateComparison:
    key: str
    name: str
    box_defenders: int
    wall_players: int
    edge_players: int
    outlets: int
    zonal_defenders: int
    tall_markers: int
    score: ScoreBand
    unfilled_jobs: int


@dataclass(frozen=True)
class TemplateSelection:
    template_key: str
    template_name: str
    description: str
    approach: str
    comparisons: tuple[TemplateComparison, ...]


def comparison_score(routine: SetPieceRoutine) -> ScoreBand:
    """Missing players contribute no coverage, rather than inflating an average."""
    total = sum(a.role.importance for a in routine.assignments) + sum(r.importance for r in routine.unfilled_roles)
    if not total:
        return ScoreBand(0.0, 0.0, 0.0)
    return ScoreBand(**{
        bound: round(sum(a.role.importance * getattr(a.score.score, bound) for a in routine.assignments) / total, 6)
        for bound in ("lower", "central", "upper")
    })


def select_defensive_plan(
    templates: tuple[DefensiveTemplate, ...], policy: DefensiveApproach, approach: str,
    solve: Callable[[DefensiveTemplate], SetPieceRoutine],
) -> SetPieceRoutine:
    """Filter coverage/commitment, solve all candidates, rank on a common budget.

    This policy boundary is where future opposition coverage requirements can
    restrict candidates. No opposition evidence is currently inferred here.
    """
    candidates = []
    for template in templates:
        if not policy.accepts(template):
            continue
        routine = solve(template)
        comparison = TemplateComparison(
            template.key, template.name, template.box_defenders,
            template.jobs["wall"], template.jobs["edge"], template.jobs["forward"],
            template.zonal_defenders, template.jobs.get("tall", 0),
            comparison_score(routine), len(routine.unfilled_roles),
        )
        candidates.append((template, routine, comparison))
    if not candidates:
        raise ValueError(f"No defensive free-kick template meets the {approach} coverage requirements")
    # Equal quality prefers more coverage and fewer outlets. Canonical keys
    # stabilize remaining ties, regardless of JSON/input iteration order.
    candidates.sort(key=lambda item: (
        item[2].unfilled_jobs, -item[2].score.central, -item[2].score.lower,
        item[2].outlets, -item[2].box_defenders, item[2].key,
    ))
    template, routine, _ = candidates[0]
    return replace(routine, selection=TemplateSelection(
        template.key, template.name, template.description, approach,
        tuple(comparison for _, _, comparison in candidates),
    ))
