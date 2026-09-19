"""HTML for the Scouting page's attribute sheets and position rankings.

Split out of ``handlers.py``. Nothing here computes a score: the numbers come
from ``fm_analytics.analytics`` (``rank_for_position`` / ``score_role``) and are
only laid out here, so a figure on this page is the same figure the analytics
layer produces everywhere else.
"""

from __future__ import annotations

import html
from typing import Sequence

from fm_analytics.analytics import (
    PositionRanking,
    ScoutingCandidate,
    contract_months_left,
    default_descending,
    is_free_agent,
    is_transfer_listed,
)
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


# (heading, sort key). A key of None is not sortable.
_COLUMNS: tuple[tuple[str, str | None], ...] = (
    ("#", None), ("Player", "name"), ("Age", "age"), ("Scouted", "scouted"),
    ("Contract", None), ("Best role", "role"), ("Min", "minimum"), ("Median", "median"), ("Max", "ceiling"),
    ("Range", "upside"), ("Known / ranged / unknown", "known"), ("Attributes", None),
)


_FAMILIARITY_COLUMNS: tuple[tuple[str, str | None], ...] = (
    ("Familiarity", "familiarity"), ("In position today", "adjusted"),
)


def _columns(show_familiarity: bool) -> tuple[tuple[str, str | None], ...]:
    if not show_familiarity:
        return _COLUMNS
    at = next(i for i, (_, key) in enumerate(_COLUMNS) if key == "upside") + 1
    return _COLUMNS[:at] + _FAMILIARITY_COLUMNS + _COLUMNS[at:]


def _header(sort: str, descending: bool, show_familiarity: bool = False) -> str:
    cells = []
    for title, key in _columns(show_familiarity):
        if key is None:
            cells.append(f"<th>{title}</th>")
            continue
        arrow = (" ▼" if descending else " ▲") if key == sort else ""
        default = "desc" if default_descending(key) else "asc"
        cells.append(
            f"<th><button type='button' class='sort-btn' data-sort='{key}' "
            f"data-default='{default}'>{title}{arrow}</button></th>"
        )
    return "<tr>" + "".join(cells) + "</tr>"


def ranking_results(
    rankings: Sequence[PositionRanking],
    *,
    position: str | None,
    sort: str,
    sort_label: str,
    descending: bool,
    raw_positions: bool = False,
) -> str:
    scope = f"Ranked for {html.escape(position)}" if position else "Ranked, all positions"
    if not rankings:
        return f"<h2>{scope}</h2><p class='muted'>No candidates match these filters.</p>"
    displayed = rankings[:_MAX_SCOUTING_ROWS]
    show_familiarity = any(item.multiplier is not None for item in displayed)
    rows = "".join(
        _ranking_row(rank, item, show_familiarity) for rank, item in enumerate(displayed, start=1)
    )
    return (
        f"<h2>{scope} ({len(rankings)})</h2>"
        "<p class='muted'>Each player is scored in whichever role suits him best"
        + (" at this position" if position else " (roles for his own positions where known, "
           "otherwise every role)")
        + ". <b>Min</b> counts every unknown attribute as 1 and every range at its "
        "low end; <b>Max</b> counts unknowns as 20 and ranges at their top; <b>Median</b> "
        "puts each range at its midpoint and each unknown mid-scale. A wide gap between "
        "min and max is where more scouting would change the picture. "
        "Click any column heading to sort by it. "
        f"Sorted by <b>{html.escape(sort_label)}</b> ({'high to low' if descending else 'low to high'})."
        + (
            " Position eligibility uses raw external data (the accepted visibility gap)."
            if raw_positions else ""
        )
        + (
            " <b>Familiarity</b> is his rating (out of 20) for the position; <b>In position "
            "today</b> multiplies the three scores by the same familiarity discount the "
            "Tactics page applies, so it is comparable with a squad player's selection "
            "score, while Min / Median / Max stay comparable with his plain role score."
            if show_familiarity else ""
        )
        + "</p>"
        + (
            f"<p class='muted'>Showing the first {len(displayed)} players.</p>"
            if len(rankings) > len(displayed) else ""
        )
        + f"<table>{_header(sort, descending, show_familiarity)}{rows}</table>"
    )


def _familiarity_cells(item: PositionRanking) -> str:
    if item.multiplier is None:
        return "<td>—</td><td>—</td>"
    return (
        f"<td>{item.familiarity}/20 <span class='muted'>(×{item.multiplier:.2f})</span></td>"
        f"<td><b>{item.adjusted_median:.1f}</b><br>"
        f"<span class='muted'>{item.adjusted_minimum:.1f}–{item.adjusted_maximum:.1f}</span></td>"
    )


def _contract_cell(candidate: ScoutingCandidate) -> str:
    """What a manager needs to know about getting him, in the order it matters."""
    notes: list[str] = []
    if is_free_agent(candidate):
        notes.append("<b>Free agent</b>")
    if is_transfer_listed(candidate):
        notes.append("<b>Transfer listed</b>")
    if candidate.contract_end:
        months = contract_months_left(candidate)
        left = f" ({months} mo)" if months is not None and months >= 0 else ""
        notes.append(f"Expires {html.escape(candidate.contract_end)}{left}")
    return "<br>".join(notes) or "<span class='muted'>—</span>"


def _ranking_row(rank: int, item: PositionRanking, show_familiarity: bool = False) -> str:
    candidate = item.candidate
    return (
        "<tr>"
        f"<td>{rank}</td>"
        f"<td>{html.escape(candidate.name)}"
        f"<br><span class='muted'>{html.escape(candidate.club or 'No club')}</span></td>"
        f"<td>{candidate.age if candidate.age is not None else '—'}</td>"
        f"<td>{_scouting_knowledge_cell(candidate)}</td>"
        f"<td>{_contract_cell(candidate)}</td>"
        f"<td>{html.escape(item.role_name)}</td>"
        f"<td>{item.minimum:.1f}</td><td><b>{item.median:.1f}</b></td><td>{item.maximum:.1f}</td>"
        f"<td>{score_bar(item.minimum, item.median, item.maximum)}</td>"
        + (_familiarity_cells(item) if show_familiarity else "")
        + f"<td>{item.known_attributes} / {item.ranged_attributes} / {item.unknown_attributes}</td>"
        f"<td>{attribute_sheet(candidate)}</td>"
        "</tr>"
    )
