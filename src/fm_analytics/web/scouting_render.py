"""HTML for the Scouting page's attribute sheets and position rankings.

Split out of ``handlers.py``. Nothing here computes a score: the numbers come
from ``fm_analytics.analytics`` (``rank_for_position`` / ``score_role``) and are
only laid out here, so a figure on this page is the same figure the analytics
layer produces everywhere else.
"""

from __future__ import annotations

import html
from typing import Sequence
from urllib.parse import quote

from fm_analytics.analytics import (
    FamiliarityPolicy,
    PositionRanking,
    ScoutingCandidate,
    contract_months_left,
    default_descending,
    is_free_agent,
    is_transfer_listed,
    score_role,
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


def player_scouting_report(candidate: ScoutingCandidate, catalogue) -> str:
    """Render a scouted player's exhaustive report."""
    facts = [
        ("Club", candidate.club),
        ("Age", str(candidate.age) if candidate.age is not None else None),
        ("Nationality", candidate.nationality),
        ("Footedness", candidate.footedness),
        ("Scouting knowledge", f"{candidate.scouting_knowledge}%" if candidate.scouting_knowledge is not None else None),
        ("Availability", candidate.availability),
        ("Transfer status", candidate.transfer_status),
        ("Contract type", candidate.contract_type),
        ("Contract ends", candidate.contract_end),
    ]
    facts.extend((key, value) for key, value in (candidate.facts or {}).items())
    return _player_detail_report(
        candidate.name, candidate.attributes,
        candidate.positions_for(include_raw_external_positions=True),
        candidate.raw_position_familiarity or {}, facts, catalogue,
        back_href="/scouting?view=scouted", back_label="Back to scouted players",
        familiarity_source="the captured raw 0–20 position rating",
    )


def squad_player_report(player, catalogue) -> str:
    """Render the equivalent report for an owned senior-squad player."""
    contract = player.contract
    facts = [
        ("Age", str(player.age) if player.age is not None else None),
        ("Availability", player.availability),
        ("Condition", f"{player.condition_percent}%" if player.condition_percent is not None else None),
        ("Match fitness", f"{player.match_fitness_percent}%" if player.match_fitness_percent is not None else None),
        ("Injured", "Yes" if player.injured else "No" if player.injured is not None else None),
        ("Suspended", "Yes" if player.suspended else "No" if player.suspended is not None else None),
        ("Preferred foot", player.preferred_foot),
        ("Contract type", contract.contract_type if contract else None),
        ("Contract ends", contract.end_date.isoformat() if contract and contract.end_date else None),
        ("Squad status", contract.squad_status if contract else None),
        ("Transfer status", contract.transfer_status if contract else None),
    ]
    return _player_detail_report(
        player.name, player.attributes, player.positions, player.position_familiarity,
        facts, catalogue, back_href="/squad", back_label="Back to squad",
        familiarity_source="the captured 0–20 position familiarity rating",
    )


def _player_detail_report(
    name, attributes, player_positions, familiarity, facts, catalogue, *,
    back_href: str, back_label: str, familiarity_source: str,
) -> str:
    """Render every attribute and catalogue role for a scouted or owned player."""
    policy = FamiliarityPolicy()
    positions = sorted({
        position for role in catalogue.roles.values() for position in role.eligible_positions
    })
    known_positions = set(player_positions)
    position_rows = "".join(
        _position_familiarity_row(position, known_positions, familiarity, policy)
        for position in positions
    )
    attributes_html = _full_attribute_sheet(attributes)
    score_sections = "".join(
        _position_role_scores(attributes, position, catalogue, familiarity, policy)
        for position in positions
    )
    fact_rows = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in facts if value
    ) or "<tr><td colspan='2' class='muted'>No additional facts captured</td></tr>"
    return (
        f"<p><a href='{html.escape(back_href, quote=True)}'>← {html.escape(back_label)}</a></p>"
        "<h2>Player information</h2><table class='report-facts'>" + fact_rows + "</table>"
        "<h2>All captured attributes</h2>"
        "<p class='muted'>Values shown as a range retain the uncertainty reported by scouting.</p>"
        + attributes_html
        + "<h2>Position score summary</h2>"
        "<p class='muted'>Each row uses the highest estimated attribute-based role score among the roles available "
        "at that position. Positions are kept in the table even when they have not been captured, "
        "so it also shows the modelled potential after positional training.</p>"
        + _position_score_summary(attributes, positions, catalogue, familiarity, policy)
        + "<h2>Position familiarity</h2>"
        f"<p class='muted'>Familiarity is {html.escape(familiarity_source)}. The multiplier is the "
        "same discount used for an in-position score; a missing rating is left unknown rather than assumed.</p>"
        "<table><tr><th>Position</th><th>Position captured</th><th>Familiarity / in-position multiplier</th></tr>"
        + position_rows + "</table>"
        + "<h2>All attribute-based role scores by position</h2>"
        "<p class='muted'>Floor and ceiling are the bounds supported by scouting. The cautious estimate is deliberately "
        "conservative when an attribute is unknown; estimate treats unknown attributes as mid-scale. "
        "In-position estimate applies the listed familiarity multiplier where one was captured.</p>"
        + score_sections
    )


def _full_attribute_sheet(attributes) -> str:
    groups: list[str] = []
    for title, keys in _ATTRIBUTE_GROUPS:
        rows = []
        for key in keys:
            observation = attributes.get(key)
            if observation is None:
                continue
            rows.append(
                "<tr>"
                f"<td>{html.escape(_attribute_label(key))}</td>"
                f"<td>{html.escape(observation.display())}</td>"
                "</tr>"
            )
        if rows:
            groups.append(
                f"<section class='report-attribute-group'><h3>{title}</h3>"
                "<table><tr><th>Attribute</th><th>Scouted value</th></tr>"
                + "".join(rows) + "</table></section>"
            )
    return "".join(groups) or "<p class='muted'>No attributes captured.</p>"


def _position_familiarity_row(position, known_positions, familiarity, policy) -> str:
    if position in familiarity:
        rating = familiarity[position]
        rating_text = (
            f"{rating}/20 (×{policy.multiplier(max(rating, policy.scale_minimum)):.2f})"
        )
    else:
        rating_text = "Not captured"
    return (
        "<tr>"
        f"<td>{html.escape(position)}</td>"
        f"<td>{'Captured position' if position in known_positions else '—'}</td>"
        f"<td>{rating_text}</td></tr>"
    )


def _position_score_summary(attributes, positions, catalogue, familiarity, policy) -> str:
    """One best-role line per position for the top of a player report."""
    rows: list[str] = []
    for position in positions:
        role_scores = [
            (role, score_role(role, attributes))
            for role in catalogue.roles.values()
            if position in role.eligible_positions
        ]
        role, score = max(
            role_scores,
            key=lambda item: (item[1].median, item[1].score.upper, item[0].key),
        )
        rating = familiarity.get(position)
        if rating is None:
            familiarity_text = "Not captured"
            in_position_estimate = "—"
        else:
            multiplier = policy.multiplier(max(rating, policy.scale_minimum))
            familiarity_text = f"{rating}/20 (×{multiplier:.2f})"
            in_position_estimate = f"{score.median * multiplier:.1f}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(position)}</td><td>{html.escape(role.name)}</td>"
            f"<td>{score.score.lower:.1f}</td><td>{score.score.central:.1f}</td>"
            f"<td><b>{score.median:.1f}</b></td><td>{score.score.upper:.1f}</td>"
            f"<td>{familiarity_text}</td><td>{in_position_estimate}</td>"
            "</tr>"
        )
    return (
        "<table><tr><th>Position</th><th>Best role (by estimate)</th><th>Floor</th>"
        "<th>Cautious estimate</th><th>Estimate</th><th>Ceiling</th><th>Familiarity</th>"
        "<th>In-position estimate</th></tr>"
        + "".join(rows) + "</table>"
    )


def _position_role_scores(attributes, position, catalogue, familiarity, policy) -> str:
    rating = familiarity.get(position)
    multiplier = (
        policy.multiplier(max(rating, policy.scale_minimum)) if rating is not None else None
    )
    rows: list[str] = []
    roles = sorted(
        (role for role in catalogue.roles.values() if position in role.eligible_positions),
        key=lambda role: (role.name, role.key),
    )
    for role in roles:
        score = score_role(role, attributes)
        input_rows = "".join(
            "<tr>"
            f"<td>{html.escape(_attribute_label(contribution.attribute))}</td>"
            f"<td>{contribution.weight:g}</td>"
            f"<td>{html.escape(contribution.observation.display())}</td>"
            f"<td>{contribution.points.lower:.1f} / {contribution.points.central:.1f} / {contribution.points.upper:.1f}</td>"
            "</tr>"
            for contribution in score.contributions
        )
        inputs = (
            "<details class='role-inputs'><summary>Attribute score inputs</summary>"
            "<table><tr><th>Attribute</th><th>Weight</th><th>Scouted value</th>"
            "<th>Points (floor / current / ceiling)</th></tr>"
            + input_rows + "</table></details>"
        )
        in_position = "—" if multiplier is None else f"{score.median * multiplier:.1f}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(role.name)}</td><td>{score.score.lower:.1f}</td>"
            f"<td>{score.score.central:.1f}</td><td><b>{score.median:.1f}</b></td>"
            f"<td>{score.score.upper:.1f}</td><td>{in_position}</td><td>{inputs}</td>"
            "</tr>"
        )
    familiarity_text = "not captured" if rating is None else f"{rating}/20 (×{multiplier:.2f})"
    return (
        f"<section class='position-role-report'><h3>{html.escape(position)} "
        f"<span class='muted'>— familiarity {familiarity_text}</span></h3>"
        "<table><tr><th>Role</th><th>Floor</th><th>Cautious estimate</th><th>Estimate</th>"
        "<th>Ceiling</th><th>In-position estimate</th><th>Breakdown</th></tr>"
        + "".join(rows) + "</table></section>"
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
    ("Value", "value"), ("FM search", None), ("Contract", None), ("Best role", "role"), ("Min", "minimum"), ("Median", "median"), ("Max", "ceiling"),
    ("Range", "upside"), ("Role attributes known", "known"), ("Attributes", None),
)


_FAMILIARITY_COLUMNS: tuple[tuple[str, str | None], ...] = (
    ("Familiarity", "familiarity"), ("In-position role score", "adjusted"),
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
        "min and max is where more scouting would change the picture. These are <b>attribute-based "
        "role scores</b>: they do not apply positional familiarity. "
        "Click any column heading to sort by it. "
        f"Sorted by <b>{html.escape(sort_label)}</b> ({'high to low' if descending else 'low to high'})."
        + (
            " Position eligibility uses raw external data (the accepted visibility gap)."
            if raw_positions else ""
        )
        + (
            " <b>Familiarity</b> is his rating (out of 20) for the position; <b>In-position "
            "role score</b> applies the same familiarity multiplier as Squad. It does not "
            "apply condition or match fitness, which Tactics adds to produce today’s selection score."
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


def _knowledge_cell(item: PositionRanking) -> str:
    """How much of *this role's* attribute list is known for him.

    The total is the number of attributes the role scores, not the 32 a player
    has: reading "11 / 0 / 0" as "only 11 of his attributes are known" was the
    obvious misreading, so the denominator is now shown.
    """
    total = item.known_attributes + item.ranged_attributes + item.unknown_attributes
    headline = f"{item.known_attributes} of {total} known"
    if not item.ranged_attributes and not item.unknown_attributes:
        return f"<b>{headline}</b>"
    parts = []
    if item.ranged_attributes:
        parts.append(f"{item.ranged_attributes} ranged")
    if item.unknown_attributes:
        parts.append(f"{item.unknown_attributes} unknown")
    return f"{headline}<br><span class='muted'>{' &middot; '.join(parts)}</span>"


def _value_cell(candidate: ScoutingCandidate) -> str:
    """FM's own Value figure. Also the best available proxy for whether he would
    join us: see ``docs/scouting-workspace.md`` on the interest estimate."""
    if candidate.value is None:
        return "<span class='muted'>—</span>"
    if candidate.value == 0:
        return "<span class='muted'>&pound;0</span>"
    return f"&pound;{candidate.value:,}"


def _search_match_cell(candidate: ScoutingCandidate) -> str:
    """Whether FM's own on-screen Player Search matched him when the capture ran.

    Deliberately says nothing about *which* filter: the result list is readable,
    the criteria that produced it are not."""
    if candidate.matched_active_search is None:
        return "<span class='muted'>—</span>"
    return "<b>Match</b>" if candidate.matched_active_search else "<span class='muted'>no</span>"


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
        f"<td>{scouting_player_link(candidate)}"
        f"<br><span class='muted'>{html.escape(candidate.club or 'No club')}</span></td>"
        f"<td>{candidate.age if candidate.age is not None else '—'}</td>"
        f"<td>{_scouting_knowledge_cell(candidate)}</td>"
        f"<td>{_value_cell(candidate)}</td>"
        f"<td>{_search_match_cell(candidate)}</td>"
        f"<td>{_contract_cell(candidate)}</td>"
        f"<td>{html.escape(item.role_name)}</td>"
        f"<td>{item.minimum:.1f}</td><td><b>{item.median:.1f}</b></td><td>{item.maximum:.1f}</td>"
        f"<td>{score_bar(item.minimum, item.median, item.maximum)}</td>"
        + (_familiarity_cells(item) if show_familiarity else "")
        + f"<td>{_knowledge_cell(item)}</td>"
        f"<td>{attribute_sheet(candidate)}</td>"
        "</tr>"
    )
