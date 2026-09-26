"""HTML for a single player's scouting or squad report.

Split out of ``scouting_render.py`` (which lays out the results tables). Like
it, nothing here computes a score of its own: the numbers come from
``fm_analytics.analytics`` (``score_role``) and ``fm_analytics.reporting`` and
are only laid out, so a figure on a report is the same figure everywhere else.
"""

from __future__ import annotations

import html

from fm_analytics.analytics import (
    FamiliarityPolicy,
    ScoutingCandidate,
    TacticScoutingAssessment,
    score_role,
)
from fm_analytics.domain.models import Visibility
from fm_analytics.reporting import build_player_role_scores
from fm_analytics.web.rendering import role_score_cells
from fm_analytics.web.scouting_render import (
    _ATTRIBUTE_GROUPS,
    _attribute_label,
    _three_gains,
    _three_scores,
    _visible_observation_counts,
)


def player_scouting_report(
    candidate: ScoutingCandidate,
    catalogue,
    *,
    headline: str = "",
) -> str:
    """Render a scouted player's exhaustive report."""
    facts = [
        ("Club", candidate.club),
        ("Age", str(candidate.age) if candidate.age is not None else None),
        ("Nationality", candidate.nationality),
        ("Footedness", candidate.footedness),
        (
            "Scouting knowledge",
            (
                f"{candidate.scouting_knowledge}%"
                + (" (last known)" if candidate.dropped_from_scout_reports else "")
                if candidate.scouting_knowledge is not None else None
            ),
        ),
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
        headline=headline,
        attributes_captured=candidate.current_attributes_captured,
        historical_attributes=candidate.last_known_attributes,
        historical_observed_at=candidate.last_known_attributes_observed_at,
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
    scores = build_player_role_scores(player, catalogue=catalogue)
    headline = (
        "<h2>Best-role scores</h2>"
        "<p class='muted'>The same three scores, calculated the same way, as the Squad roster: "
        "<b>attribute-based</b> (attributes and role fit only), <b>in-position</b> (adds positional "
        "familiarity) and <b>today’s selection score</b> (adds match readiness). "
        "Each shows the player's strongest role by that measure.</p>"
        "<table><tr><th>Attribute-based role score (best role)</th>"
        "<th>In-position role score (best role)</th>"
        "<th>Today’s selection score (best role)</th></tr>"
        f"<tr>{role_score_cells(scores)}</tr></table>"
    )
    return _player_detail_report(
        player.name, player.attributes, player.positions, player.position_familiarity,
        facts, catalogue, back_href="/squad", back_label="Back to squad",
        familiarity_source="the captured 0–20 position familiarity rating",
        headline=headline,
    )


def _player_detail_report(
    name, attributes, player_positions, familiarity, facts, catalogue, *,
    back_href: str, back_label: str, familiarity_source: str, headline: str = "",
    attributes_captured: bool = True,
    historical_attributes=None, historical_observed_at: str | None = None,
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
    attributes_html = _full_attribute_sheet(
        attributes, captured=attributes_captured
    )
    historical_html = _historical_attribute_section(
        historical_attributes or {}, historical_observed_at
    )
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
        + headline +
        "<h2>Current attributes</h2>"
        "<p class='muted'>Only values visible now are used in the scores below. "
        "Ranges retain the uncertainty currently reported by scouting.</p>"
        + attributes_html
        + historical_html
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


def _full_attribute_sheet(attributes, *, captured: bool = True) -> str:
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
    if groups:
        return "".join(groups)
    if not captured:
        return (
            "<p class='warn'><b>Not captured from FM.</b> This does not mean FM "
            "shows no attributes. Capture the current Player Search attributes "
            "from the All players tab to get FM's current answer.</p>"
        )
    return "<p class='muted'>No attributes currently visible.</p>"


def _historical_attribute_section(attributes, observed_at: str | None) -> str:
    if _visible_observation_counts(attributes) == (0, 0):
        return ""
    when = html.escape(observed_at or "date not captured")
    return (
        "<h2>Past scouting knowledge</h2>"
        "<p class='warn'><b>Historical only.</b> These values were last visible on "
        f"<b>{when}</b>. They are not treated as current and are not used in any "
        "score, filter, or recommendation on this page.</p>"
        + _full_attribute_sheet(attributes)
    )


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


def tactic_player_impact(
    assessment: TacticScoutingAssessment | None,
    *,
    tactic,
    baseline,
) -> str:
    """Render one candidate's squad-relative value for a selected tactic."""
    heading = f"<h3>Impact on {html.escape(tactic.name)}</h3>"
    if assessment is None:
        return (
            heading
            + "<p class='muted'>This player has no captured eligible position in "
            "this tactic. Enable raw external positions if you want to accept that "
            "visibility gap.</p>"
        )
    outcome = (
        "Starts"
        + (
            " · replaces " + html.escape(", ".join(assessment.replaced_player_names))
            if assessment.replaced_player_names
            else ""
        )
        if assessment.starts_at_estimate
        else "Depth at estimate"
    )
    return (
        heading
        + "<p>The whole XI and its permitted roles are re-optimised with this player "
        "added to the squad.</p>"
        + "<table><tr><th>Current tactic score</th><th>Projected tactic score</th>"
        "<th>XI gain</th><th>Best tactic job</th><th>Outcome</th></tr><tr>"
        f"<td>{_three_scores(baseline.score.lower, baseline.score.central, baseline.score.upper)}</td>"
        f"<td>{_three_scores(assessment.projected_score.floor, assessment.projected_score.estimate, assessment.projected_score.ceiling)}</td>"
        f"<td>{_three_gains(assessment.score_gain.floor, assessment.score_gain.estimate, assessment.score_gain.ceiling)}</td>"
        f"<td><b>{html.escape(assessment.best_position)}</b> · "
        f"{html.escape(assessment.best_role_name)}<br>"
        "<span class='muted'>Player fit</span><br>"
        f"{_three_scores(assessment.player_fit.lower, assessment.player_fit.central, assessment.player_fit.upper)}</td>"
        f"<td>{outcome}</td></tr></table>"
        "<p class='muted'>Values are floor / estimate / ceiling. The player is "
        "assumed available, fully fit and match fit; owned players retain today’s "
        "readiness. A player who does not improve the XI shows a gain of +0.0.</p>"
    )
