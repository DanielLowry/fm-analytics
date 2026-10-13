"""Game-plan labels on the tactics pages: chips, the filter, and the best tactic for each plan.

The labels come from `analytics.game_plan`; they group and filter, and change no
score, so everything here reads the ranking the bundle already computed.
"""

from __future__ import annotations

import html
from typing import Mapping
from urllib.parse import quote

from fm_analytics.analytics.game_plan import GAME_PLANS, GAME_PLANS_BY_KEY, GamePlanLabel

PLAN_QUERY = "plan"


def plan_from_query(query: dict[str, list[str]]) -> str | None:
    """The `plan` filter, or None for every tactic; an unknown plan is an error."""
    value = (query.get(PLAN_QUERY) or [""])[0].strip()
    if not value:
        return None
    if value not in GAME_PLANS_BY_KEY:
        raise ValueError(
            "plan must be one of " + ", ".join(plan.key for plan in GAME_PLANS)
        )
    return value


def plan_chips(labels: tuple[GamePlanLabel, ...]) -> str:
    if not labels:
        return ""
    return "<span class='fm-plan-chips'>" + "".join(
        f"<span class='fm-plan-chip' title='{html.escape(label.plan.summary, quote=True)}'>"
        f"{html.escape(label.label)}</span>"
        for label in labels
    ) + "</span>"


def plan_filter(current: str | None, query: str, counts: Mapping[str, int]) -> str:
    """Links that filter the comparison to one game plan, keeping the other controls."""
    def href(plan_key: str | None) -> str:
        parts = [query] if query else []
        if plan_key:
            parts.append(f"{PLAN_QUERY}={quote(plan_key)}")
        return html.escape("/tactics" + ("?" + "&".join(parts) if parts else "") + "#compare", quote=True)

    links = [
        f"<a class='fm-plan-filter-link{' is-active' if current is None else ''}' href='{href(None)}'>All</a>"
    ]
    for plan in GAME_PLANS:
        if not counts.get(plan.key):
            continue
        active = " is-active" if plan.key == current else ""
        links.append(
            f"<a class='fm-plan-filter-link{active}' href='{href(plan.key)}' "
            f"title='{html.escape(plan.summary, quote=True)}'>{html.escape(plan.label)} "
            f"<span class='muted'>{counts[plan.key]}</span></a>"
        )
    return "<nav class='fm-plan-filter' aria-label='Filter by game plan'>" + "".join(links) + "</nav>"


def best_by_plan_panel(ranked, labels_by_key, band, link_query_suffix: str) -> str:
    """The highest-ranked tactic of each game plan for this squad.

    `ranked` is the bundle's evaluations in rank order; `band` formats a score.
    """
    rows = []
    for plan in GAME_PLANS:
        for rank, evaluation in enumerate(ranked, start=1):
            labels = labels_by_key[evaluation.tactic.key]
            if any(label.key == plan.key for label in labels):
                others = [label.label for label in labels if label.key != plan.key]
                also = (f"<br><span class='muted'>Also: {html.escape(', '.join(others))}</span>" if others else "")
                rows.append(
                    "<tr>"
                    f"<td><b>{html.escape(plan.label)}</b><br><span class='muted'>{html.escape(plan.summary)}</span></td>"
                    f"<td>{html.escape(evaluation.tactic.name)}<br><span class='muted'>"
                    f"{html.escape(evaluation.tactic.formation)} · {html.escape(evaluation.tactic.mentality)}</span>{also}</td>"
                    f"<td>{rank}</td>"
                    f"<td><b>{band(evaluation.score)}</b></td>"
                    f"<td><a class='tactic-link' href='/tactics/{quote(evaluation.tactic.key, safe='')}"
                    f"{link_query_suffix}'>View tactic →</a></td>"
                    "</tr>"
                )
                break
    return (
        "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
        "<h2>Best of each game plan</h2>"
        "<p>Which plan to play is your call against each opponent; this is the tactic of each kind "
        "that suits this squad best. Game plans are read from each tactic's own settings and do not "
        "change any score.</p></div></div>"
        "<div class='fm-table-card'><table><tr><th>Game plan</th><th>Best tactic</th><th>Rank</th>"
        "<th>Play-now score</th><th></th></tr>"
        + "".join(rows)
        + "</table></div></section>"
    )


def plan_detail(labels: tuple[GamePlanLabel, ...]) -> str:
    """The tactic page's line saying which plan it follows and why."""
    if not labels:
        return "<p><b>Game plan:</b> none of the catalogue's plans; its settings mix no clear lever.</p>"
    parts = [
        f"{html.escape(label.label)} ({html.escape(', '.join(label.reasons))})" for label in labels
    ]
    return "<p><b>Game plan:</b> " + "; ".join(parts) + ".</p>"
