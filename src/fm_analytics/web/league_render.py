"""HTML pieces for the League pages: knowledge, changes, and what to scout next.

Pure formatting over `analytics.league_insights` results; nothing is scored here.
"""
from __future__ import annotations

import html
from urllib.parse import quote, urlencode

from fm_analytics.web.attribute_export import attribute_label

escape = html.escape


def player_href(club_id: str, player_id: str, tactic: str = "") -> str:
    path = "/league/teams/" + quote(club_id, safe="") + "/players/" + quote(player_id, safe="")
    return escape(path + ("?" + urlencode({"tactic": tactic}) if tactic else ""), quote=True)


def score_range(score) -> str:
    return f"{score.lower:.1f}–{score.upper:.1f}" if score else "—"


def squad_knowledge(team) -> str:
    known, ranged, unknown, missing = team.knowledge_counts
    return f"{known} exact · {ranged} ranged · {unknown} unknown · {missing} uncaptured"


def starters_knowledge(team) -> str:
    """How well the conservative XI is known; the whole squad's inputs when unscored."""
    if team.score is None:
        return "Squad inputs: " + squad_knowledge(team)
    known, partly, unknown = team.starters
    return f"Starters: {known} known · {partly} partly known · {unknown} unknown"


def coverage_cell(counts) -> str:
    exact, ranged, unknown, missing = counts
    return f"{exact} exact · {ranged} ranged · {unknown} unknown" + (f" · {missing} uncaptured" if missing else "")


def change_cell(team) -> str:
    """The overview's short "since last read" entry."""
    change = team.change
    if change is None:
        return "—"
    parts = []
    if change.previous_status:
        parts.append("status changed")
    if change.previous and change.current:
        delta = change.current.central - change.previous.central
        width = (change.current.upper - change.current.lower) - (change.previous.upper - change.previous.lower)
        if abs(delta) >= 0.05:
            parts.append(f"{delta:+.1f}")
        if abs(width) >= 0.05:
            parts.append("range narrower" if width < 0 else "range wider")
    if change.tactic:
        parts.append("new system")
    if change.players_in or change.players_out:
        parts.append("XI changed")
    return escape(", ".join(parts) or "rescored") + f"<br><small>since {change.since.isoformat()}</small>"


def change_text(team) -> str:
    """The team page's full account of what moved since the previous read."""
    change = team.change
    if change is None:
        return ""
    parts = []
    if change.previous_status:
        parts.append(f"was {escape(change.previous_status.replace('_', ' '))}")
    if change.previous or change.current:
        parts.append(f"best XI range {score_range(change.previous)} → {score_range(change.current)}")
    if change.tactic:
        parts.append(f"conservative system now {escape(change.tactic)}")
    if change.players_in:
        parts.append("into the conservative XI: " + escape(", ".join(change.players_in)))
    if change.players_out:
        parts.append("out of it: " + escape(", ".join(change.players_out)))
    return (f"<p class='fm-metric-note'>Since the read at game date {change.since.isoformat()}: "
            + "; ".join(parts) + ".</p>")


def xi_difference_text(difference) -> str:
    if difference.same:
        return "<p class='muted'>Same players and system as the conservative XI.</p>"
    parts = []
    if difference.tactic:
        parts.append(f"system {escape(difference.tactic)}")
    if difference.players_in:
        parts.append("in: " + escape(", ".join(difference.players_in)))
    if difference.players_out:
        parts.append("out: " + escape(", ".join(difference.players_out)))
    return "<p class='muted'>Differs from the conservative XI: " + "; ".join(parts) + ".</p>"


def _attribute(gap) -> str:
    label = "Scout more" if gap.supplied else "Capture needed"
    return f"{escape(attribute_label(gap.attribute))} ({label})"


def gap_list(gaps) -> str:
    return "".join(f"<li>{_attribute(gap)}: {gap.uncertainty_span:.1f} uncertain role-fit points</li>" for gap in gaps)


def priority_items(priorities, tactic: str = "", *, show_club: bool = False) -> str:
    items = []
    for row in priorities:
        stakes = []
        if row.ceiling_at_stake >= 0.05:
            stakes.append(f"up to {row.ceiling_at_stake:.1f} points of their best case rest on him")
        if row.floor_at_stake >= 0.05:
            stakes.append(f"at his best he lifts their floor by at least {row.floor_at_stake:.1f}")
        club = f"{escape(row.club_name)}, " if show_club else ""
        items.append(
            f"<li><a href='{player_href(row.club_id, row.player_id, tactic)}'>{escape(row.player_name)}</a> "
            f"<small>({club}{escape(row.job)}{'; only in their best-case XI' if row.only_in_best_case else ''})</small>: "
            + "; ".join(stakes)
            + (f" — <b>{escape(row.settles)}</b>" if row.settles else "")
            + (". Learn: " + ", ".join(_attribute(gap) for gap in row.attributes) if row.attributes else "")
            + ".</li>")
    return "".join(items)
