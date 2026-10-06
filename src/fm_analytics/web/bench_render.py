"""Matchday-bench priority presentation for tactic detail pages."""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping

from fm_analytics.analytics import BenchSelection, TacticEvaluation
from fm_analytics.domain.models import Player
from fm_analytics.web.scouting_render import squad_player_link


def bench_priority_section(
    evaluation: TacticEvaluation,
    bench: BenchSelection,
    players_by_id: Mapping[str, Player],
    bench_size: int,
    exclude_link: Callable[[Player], str] | None = None,
) -> str:
    """Render the ordered substitute unit for this configured bench size."""
    slots_by_key = {slot.key: slot for slot in evaluation.tactic.slots}

    def labels(slot_keys: tuple[str, ...]) -> str:
        return ", ".join(
            key
            if slots_by_key[key].position == key
            else f"{key} ({slots_by_key[key].position})"
            for key in slot_keys
        )

    goalkeeper_slots = {
        slot.key for slot in evaluation.tactic.slots if slot.position == "GK"
    }
    rows = []
    for priority, entry in enumerate(bench.entries, start=1):
        new_cover = entry.newly_covered_slots
        if priority == 1 and goalkeeper_slots.intersection(entry.covered_slots):
            extra = tuple(
                slot for slot in entry.newly_credible_slots
                if slot not in goalkeeper_slots
            )
            reason = "Reserve goalkeeper"
            if extra:
                reason += "; also adds credible cover for " + labels(extra)
        elif entry.newly_credible_slots:
            reason = "Adds credible cover for " + labels(entry.newly_credible_slots)
        elif new_cover:
            reason = "Fills uncovered slots " + labels(new_cover)
        elif entry.improved_slots:
            reason = "Improves cover for " + labels(entry.improved_slots)
        else:
            reason = "Best remaining match-ready option"
        rows.append(
            "<tr>"
            f"<td><b>{priority}</b></td>"
            f"<td>{squad_player_link(players_by_id[entry.player_id])}</td>"
            f"<td>{html.escape(reason)}</td>"
            f"<td>{html.escape(entry.primary_assignment.slot.key)} — "
            f"{html.escape(entry.primary_assignment.intrinsic_role_score.role_name)}</td>"
            f"<td>{html.escape(labels(entry.credible_slots) or '—')}</td>"
            f"<td>{html.escape(labels(entry.covered_slots))}</td>"
            + (f"<td>{exclude_link(players_by_id[entry.player_id])}</td>" if exclude_link else "")
            + "</tr>"
        )
    rows_html = "".join(rows) or (
        f"<tr><td colspan='{7 if exclude_link else 6}' class='warn'>No eligible substitutes.</td></tr>"
    )
    has_reserve_keeper = any(
        goalkeeper_slots.intersection(entry.covered_slots) for entry in bench.entries
    )
    warning = (
        "<p class='warn'>No eligible reserve goalkeeper is available.</p>"
        if goalkeeper_slots and not has_reserve_keeper
        else ""
    )
    threshold = round(bench.credible_cover_ratio * 100)
    if bench.weakly_covered_slots:
        warning += (
            "<p class='warn'>Only below-threshold cover is available for "
            f"{html.escape(labels(bench.weakly_covered_slots))}. Credible cover scores "
            f"at least {threshold}% of the selected starter today.</p>"
        )
    if bench.uncovered_slots:
        warning += (
            "<p class='warn'>No eligible bench player can fill "
            f"{html.escape(labels(bench.uncovered_slots))}.</p>"
        )
    return (
        "<section class='fm-workspace-panel fm-bench-panel' id='matchday-bench'>"
        "<div class='fm-panel-heading'><div><h2>Matchday bench</h2>"
        f"<p>{len(bench.entries)} of {bench_size} substitute places selected for this tactic. "
        "The whole bench is planned together: reserve goalkeeper first; "
        "later picks preserve the widest position cover possible, then favour credible cover "
        f"(at least {threshold}% of the starter's score), nominal gaps, and improvements "
        "to existing cover.</p>"
        "</div><span class='fm-panel-count'>"
        f"{len(bench.entries)} selected</span></div>"
        + warning
        + "<div class='fm-table-card'><table><tr><th>Priority</th><th>Substitute</th><th>Why this priority</th>"
        "<th>Best use</th><th>Credible cover</th><th>Can fill</th>"
        + ("<th></th>" if exclude_link else "") + "</tr>"
        + rows_html
        + "</table></div></section>"
    )
