"""Matchday-bench priority presentation for tactic detail pages."""

from __future__ import annotations

import html
from collections.abc import Mapping

from fm_analytics.analytics import BenchSelection, TacticEvaluation
from fm_analytics.domain.models import Player
from fm_analytics.web.scouting_render import squad_player_link


def bench_priority_section(
    evaluation: TacticEvaluation,
    bench: BenchSelection,
    players_by_id: Mapping[str, Player],
    bench_size: int,
) -> str:
    """Render the ordered, safe-to-truncate substitute list."""
    goalkeeper_slots = {
        slot.key for slot in evaluation.tactic.slots if slot.position == "GK"
    }
    rows = []
    for priority, entry in enumerate(bench.entries, start=1):
        new_cover = entry.newly_covered_slots
        if priority == 1 and goalkeeper_slots.intersection(entry.covered_slots):
            extra = tuple(slot for slot in new_cover if slot not in goalkeeper_slots)
            reason = "Reserve goalkeeper"
            if extra:
                reason += "; also adds " + ", ".join(extra)
        elif new_cover:
            reason = "Adds cover for " + ", ".join(new_cover)
        else:
            reason = "Best remaining match-ready option"
        rows.append(
            "<tr>"
            f"<td><b>{priority}</b></td>"
            f"<td>{squad_player_link(players_by_id[entry.player_id])}</td>"
            f"<td>{html.escape(reason)}</td>"
            f"<td>{html.escape(entry.primary_assignment.slot.key)} — "
            f"{html.escape(entry.primary_assignment.intrinsic_role_score.role_name)}</td>"
            f"<td>{html.escape(', '.join(entry.covered_slots))}</td>"
            "</tr>"
        )
    rows_html = "".join(rows) or (
        "<tr><td colspan='5' class='warn'>No eligible substitutes.</td></tr>"
    )
    has_reserve_keeper = any(
        goalkeeper_slots.intersection(entry.covered_slots) for entry in bench.entries
    )
    warning = (
        "<p class='warn'>No eligible reserve goalkeeper is available.</p>"
        if goalkeeper_slots and not has_reserve_keeper
        else ""
    )
    return (
        "<h2>Matchday bench</h2>"
        f"<p class='muted'>{len(bench.entries)} of {bench_size} substitute places selected "
        "for this tactic. Take players from the top when fewer places are allowed: "
        "the reserve goalkeeper comes first, then new positional coverage, then "
        "playing quality.</p>"
        + warning
        + "<table><tr><th>Priority</th><th>Substitute</th><th>Why this priority</th>"
        "<th>Best use</th><th>All slots covered</th></tr>"
        + rows_html
        + "</table>"
    )
