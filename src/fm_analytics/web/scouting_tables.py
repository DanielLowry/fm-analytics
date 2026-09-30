"""Shared table and attribute-sheet fragments for scouting pages."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Callable, Sequence
from urllib.parse import quote

from fm_analytics.analytics import (
    PositionRanking,
    ScoutingAssessment,
    ScoutingCandidate,
    default_descending,
)
from fm_analytics.domain.models import Visibility
from fm_analytics.web.rendering import (
    _label,
    _scouting_href,
    _scouting_knowledge_cell,
    role_score_cells,
)

_ATTRIBUTE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Technical", ("corners", "crossing", "dribbling", "finishing", "firstTouch", "heading", "longShots", "marking", "passing", "tackling", "technique")),
    ("Mental", ("aggression", "anticipation", "bravery", "composure", "concentration", "decisions", "determination", "flair", "offTheBall", "positioning", "teamwork", "vision", "workRate")),
    ("Physical", ("acceleration", "agility", "balance", "jumpingReach", "naturalFitness", "pace", "stamina", "strength")),
    ("Goalkeeping", ("aerialReach", "commandOfArea", "communication", "handling", "kicking", "oneOnOnes", "reflexes", "rushingOut", "throwing")),
)
_LABELS = {
    "firstTouch": "First Touch", "longShots": "Long Shots", "offTheBall": "Off The Ball",
    "workRate": "Work Rate", "jumpingReach": "Jumping Reach", "naturalFitness": "Natural Fitness",
    "aerialReach": "Aerial Reach", "commandOfArea": "Command Of Area", "oneOnOnes": "One On Ones",
    "rushingOut": "Rushing Out",
}

def _attribute_label(key: str) -> str:
    return _LABELS.get(key) or _label(key)

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
            reading = candidate.historical_reading(key)
            title = ""
            if reading is not None:
                css += " attr-historical"
                title = f" title='Historical: last seen {html.escape(reading.last_seen_on, quote=True)}'"
            rows.append(
                f"<div class='{css}'{title}><span>{html.escape(_attribute_label(key))}</span><b>{value}</b></div>"
            )
        if rows:
            groups.append(f"<div class='sheet-group'><h4>{title}</h4>{''.join(rows)}</div>")
    if not groups:
        if not candidate.current_attributes_captured:
            return "<span class='warn'>Not captured from FM</span>"
        return "<span class='muted'>No attributes currently visible</span>"
    historical = len(candidate.history.attributes) if candidate.history else 0
    return (
        f"<details class='sheet'><summary>Attributes ({shown} shown"
        + (f", {historical} historical" if historical else "") + ")</summary>"
        f"<div class='sheet-groups'>{''.join(groups)}</div></details>"
    )


def scouting_player_link(candidate: ScoutingCandidate) -> str:
    """A stable link to the player's full scouting report."""
    return (
        f"<a href='/scouting/player/{quote(candidate.id, safe='')}' "
        f"class='player-link'>{html.escape(candidate.name)}</a>"
    )


def squad_player_link(player) -> str:
    """A stable link to an owned player's full squad report."""
    return (
        f"<a href='/squad/player/{quote(player.id, safe='')}' class='player-link'>"
        f"{html.escape(player.name)}</a>"
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


@dataclass(frozen=True)
class _Column:
    """One results column: its heading, the server-side sort it triggers, and its cell."""

    title: str
    sort: str | None
    cell: Callable[[int, Any], str]
    hint: str = ""


def _sortable_table(
    columns: Sequence[_Column], items: Sequence[Any], *, sort: str, descending: bool
) -> str:
    """The one results table every scouting view uses.

    A column with a ``sort`` key renders as a button the page's script turns
    into a server-side re-sort (so the top of a long list is the true top by
    that column, not the top of what was on screen); the active column is
    marked with an arrow and ``aria-sort``. Which columns exist is the caller's
    choice, which is why every view can offer the same behaviour.
    """
    cells = []
    for column in columns:
        title = f" title='{html.escape(column.hint, quote=True)}'" if column.hint else ""
        if column.sort is None:
            cells.append(f"<th{title}>{column.title}</th>")
            continue
        active = column.sort == sort
        arrow = (" ▼" if descending else " ▲") if active else ""
        aria = (" aria-sort='descending'" if descending else " aria-sort='ascending'") if active else ""
        default = "desc" if default_descending(column.sort) else "asc"
        cells.append(
            f"<th{aria}><button type='button' class='sort-btn'{title} data-sort='{column.sort}' "
            f"data-default='{default}'>{column.title}{arrow}</button></th>"
        )
    rows = "".join(
        "<tr>" + "".join(column.cell(rank, item) for column in columns) + "</tr>"
        for rank, item in enumerate(items, start=1)
    )
    return (
        "<div class='table-scroll'><table class='results'>"
        f"<tr>{''.join(cells)}</tr>{rows}</table></div>"
    )


def _results_view(
    heading: str,
    *,
    total: int,
    shown: int,
    limit: int,
    sort_label: str,
    descending: bool,
    lead: str,
    explanation: str,
    table: str,
) -> str:
    """The frame around every results table: heading, sort line, notes, table, more."""
    more = ""
    if total > shown:
        step = min(_SHOW_MORE_STEP, total - shown)
        more = (
            f"<p class='show-more'><button type='button' data-limit='{limit + _SHOW_MORE_STEP}'>"
            f"Show {step} more</button> <span class='muted'>Showing {shown} of {total}.</span></p>"
        )
    return (
        f"<h2>{heading} ({total})</h2>"
        f"<p class='results-summary'>Sorted by <b>{html.escape(sort_label)}</b> "
        f"({'high to low' if descending else 'low to high'}); click any column heading to "
        f"re-sort. {lead}</p>"
        f"<details class='explain'><summary>How to read these columns</summary>{explanation}</details>"
        + table + more
    )


def no_results(heading: str, *, pool_size: int, scouted_only: bool) -> str:
    """The one empty state, so every view says the same thing for the same reason."""
    if pool_size == 0:
        reason = (
            "No manager-visible scouting candidates have been loaded yet. Supply a "
            "verified scouting capture with <code>--scouting-json</code>."
        )
    else:
        reason = (
            "No candidates match these filters."
            + (
                " Only players you hold a scout report on -- FM's own Scouted list -- "
                "are listed on the Scouted tab; try <b>All players</b>, or tick "
                "<b>Everyone ever scouted</b> for players who have since dropped off it."
                if scouted_only else ""
            )
        )
    return f"<h2>{heading}</h2><p class='muted'>{reason}</p>"


_CONCERN_LABELS = {"starter": "Starter", "cover": "Cover"}

_EMPTY_WEAK_SLOT_NOTE = "No weak slots in the tactics in play right now."


def weakest_slots_panel(rows, query: dict[str, list[str]], *, note: str | None = None) -> str:
    """The **Weakest slots** navigation block at the top of ``/scouting``.

    ``rows`` is the prepared ``reporting.weakest_slots`` result -- which slots
    need help and why -- so nothing here decides or re-scores a weakness. Each
    row is one link to the candidate list for that tactic, position and role,
    with the concern spelled out in words next to it rather than left to a
    colour. With no rows the block stays in place and says why in ``note``:
    the manager should see that the answer is "nothing is weak", not that the
    panel failed to load.
    """
    heading = (
        "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
        "<h2>Weakest slots</h2>"
        "<p>Where the tactics in play need help. Each link opens the candidates "
        "for that tactic, position and role.</p></div>"
    )
    if not rows:
        return heading + f"</div><p class='muted'>{html.escape(note or _EMPTY_WEAK_SLOT_NOTE)}</p></section>"

    items: list[str] = []
    for row in rows:
        where = (
            row.slot_key
            if row.slot_key == row.position
            else f"{row.slot_key} ({row.position})"
        )
        # The link supplies the table's tactic, position and role, so it also
        # owns the sort and the name search: carrying those over would either
        # order a different table or search for somebody else entirely.
        href = _scouting_href(
            query,
            tactic=row.tactic_key,
            position=row.position,
            role=row.role_key,
            name=None,
            sort=None,
            dir=None,
        )
        concern = _CONCERN_LABELS.get(row.concern, row.concern)
        items.append(
            "<li>"
            f"<a href='{html.escape(href, quote=True)}'>"
            f"{html.escape(row.tactic_name)} · {html.escape(where)} · "
            f"{html.escape(row.role_name)}</a>"
            f"<span class='muted'> — {html.escape(concern)} concern: "
            f"{html.escape(row.message)}</span>"
            "</li>"
        )
    return (
        heading
        + f"<span class='fm-panel-count'>{len(rows)} slot(s)</span></div>"
        + f"<ul class='fm-risk-list'>{''.join(items)}</ul>"
        + "</section>"
    )


_SHOW_MORE_STEP = 100

_MIN_HINT = "Every unknown attribute counts as 1 and every range at its low end."
_MEDIAN_HINT = "Every range at its midpoint and every unknown attribute mid-scale."
_MAX_HINT = "Every unknown attribute counts as 20 and every range at its top."
_SCORE_EXPLANATION = (
    "<p class='muted'><b>Min</b> counts every unknown attribute as 1 and every range at "
    "its low end; <b>Max</b> counts unknowns as 20 and ranges at their top; <b>Median</b> "
    "puts each range at its midpoint and each unknown mid-scale. A wide gap between min "
    "and max is where more scouting would change the picture. These are <b>attribute-based "
    "role scores</b>: they do not apply positional familiarity.</p>"
)
