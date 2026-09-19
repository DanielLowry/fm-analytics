"""HTML for the Scouting page's attribute sheets and position rankings.

Split out of ``handlers.py``. Nothing here computes a score: the numbers come
from ``fm_analytics.analytics`` (``rank_for_position`` / ``score_role``) and are
only laid out here, so a figure on this page is the same figure the analytics
layer produces everywhere else.
"""

from __future__ import annotations

import html
from typing import Sequence

from fm_analytics.analytics import PositionRanking, ScoutingCandidate
from fm_analytics.domain.models import Visibility
from fm_analytics.web.rendering import (
    _MAX_SCOUTING_ROWS,
    _label,
    _scouting_knowledge_cell,
)

# The order FM's own attribute screens use, so a sheet can be read against the
# game side by side. Goalkeeping attributes only appear when a player has them.
_ATTRIBUTE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Technical", (
        "corners", "crossing", "dribbling", "finishing", "firstTouch", "heading",
        "longShots", "marking", "passing", "tackling", "technique",
    )),
    ("Mental", (
        "aggression", "anticipation", "bravery", "composure", "concentration",
        "decisions", "determination", "flair", "offTheBall", "positioning",
        "teamwork", "vision", "workRate",
    )),
    ("Physical", (
        "acceleration", "agility", "balance", "jumpingReach", "naturalFitness",
        "pace", "stamina", "strength",
    )),
    ("Goalkeeping", (
        "aerialReach", "commandOfArea", "communication", "handling", "kicking",
        "oneOnOnes", "reflexes", "rushingOut", "throwing",
    )),
)


_LABELS = {
    "firstTouch": "First Touch", "longShots": "Long Shots", "offTheBall": "Off The Ball",
    "workRate": "Work Rate", "jumpingReach": "Jumping Reach", "naturalFitness": "Natural Fitness",
    "aerialReach": "Aerial Reach", "commandOfArea": "Command Of Area", "oneOnOnes": "One On Ones",
    "rushingOut": "Rushing Out",
}


def _attribute_label(key: str) -> str:
    return _LABELS.get(key) or _label(key)


def attribute_sheet(candidate: ScoutingCandidate) -> str:
    """Every attribute FM lets the manager see for this player, grouped like FM."""
    shown = 0
    groups: list[str] = []
    for title, keys in _ATTRIBUTE_GROUPS:
        rows: list[str] = []
        for key in keys:
            observation = candidate.attributes.get(key)
            if observation is None:
                continue
            visible = observation.visibility is not Visibility.UNKNOWN
            shown += visible
            value = html.escape(observation.display()) if visible else "-"
            css = "attr" if visible else "attr attr-hidden"
            rows.append(
                f"<div class='{css}'><span>{html.escape(_attribute_label(key))}</span><b>{value}</b></div>"
            )
        if rows:
            groups.append(f"<div class='sheet-group'><h4>{title}</h4>{''.join(rows)}</div>")
    if not groups:
        return "<span class='muted'>No attributes captured</span>"
    return (
        f"<details class='sheet'><summary>Attributes ({shown} shown)</summary>"
        f"<div class='sheet-groups'>{''.join(groups)}</div></details>"
    )


def score_bar(minimum: float, median: float, maximum: float) -> str:
    """A 0-100 bar: the shaded stretch is min..max, the tick is the median."""
    def pct(value: float) -> float:
        return max(0.0, min(100.0, value))

    left, right = pct(minimum), pct(maximum)
    return (
        "<span class='bar'>"
        f"<span class='bar-fill' style='left:{left:.1f}%;width:{max(right - left, 0.8):.1f}%'></span>"
        f"<span class='bar-mark' style='left:{pct(median):.1f}%'></span></span>"
    )


def ranking_results(
    rankings: Sequence[PositionRanking],
    *,
    position: str,
    sort_label: str,
    raw_positions: bool = False,
) -> str:
    if not rankings:
        return (
            f"<h2>Ranked for {html.escape(position)}</h2><p class='muted'>No candidates "
            "match these filters.</p>"
        )
    displayed = rankings[:_MAX_SCOUTING_ROWS]
    rows = "".join(_ranking_row(rank, item) for rank, item in enumerate(displayed, start=1))
    return (
        f"<h2>Ranked for {html.escape(position)} ({len(rankings)})</h2>"
        "<p class='muted'>Each player is scored in whichever role suits him best at this "
        "position. <b>Min</b> counts every unknown attribute as 1 and every range at its "
        "low end; <b>Max</b> counts unknowns as 20 and ranges at their top; <b>Median</b> "
        "puts each range at its midpoint and each unknown mid-scale. A wide gap between "
        "min and max is where more scouting would change the picture. "
        f"Sorted by <b>{html.escape(sort_label)}</b>."
        + (
            " Position eligibility uses raw external data (the accepted visibility gap)."
            if raw_positions else ""
        )
        + "</p>"
        + (
            f"<p class='muted'>Showing the first {len(displayed)} players.</p>"
            if len(rankings) > len(displayed) else ""
        )
        + "<table><tr><th>#</th><th>Player</th><th>Age</th><th>Scouted</th><th>Best role</th>"
        "<th>Min</th><th>Median</th><th>Max</th><th>Range</th><th>Known / ranged / unknown</th>"
        f"<th>Attributes</th></tr>{rows}</table>"
    )


def _ranking_row(rank: int, item: PositionRanking) -> str:
    candidate = item.candidate
    return (
        "<tr>"
        f"<td>{rank}</td>"
        f"<td>{html.escape(candidate.name)}"
        f"<br><span class='muted'>{html.escape(candidate.club or 'No club')}</span></td>"
        f"<td>{candidate.age if candidate.age is not None else '—'}</td>"
        f"<td>{_scouting_knowledge_cell(candidate)}</td>"
        f"<td>{html.escape(item.role_name)}</td>"
        f"<td>{item.minimum:.1f}</td><td><b>{item.median:.1f}</b></td><td>{item.maximum:.1f}</td>"
        f"<td>{score_bar(item.minimum, item.median, item.maximum)}</td>"
        f"<td>{item.known_attributes} / {item.ranged_attributes} / {item.unknown_attributes}</td>"
        f"<td>{attribute_sheet(candidate)}</td>"
        "</tr>"
    )
