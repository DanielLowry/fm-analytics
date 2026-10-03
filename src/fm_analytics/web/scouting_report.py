"""HTML for a single player's scouting or squad report.

Split out of ``scouting_render.py`` (which lays out the results tables). Like
it, nothing here computes a score of its own: the numbers come from
``fm_analytics.analytics`` (``score_role``) and ``fm_analytics.reporting`` and
are only laid out, so a figure on a report is the same figure everywhere else.
"""

from __future__ import annotations

import html

from fm_analytics.web.attribute_export import candidate_export_record, export_controls, player_export_record
from fm_analytics.web.ui import ordered_positions, position_key
from fm_analytics.analytics import (
    FamiliarityPolicy,
    ScoutingCandidate,
    TacticScoutingAssessment,
    score_role,
)
from fm_analytics.domain.models import Visibility
from fm_analytics.persistence import MAX_VERDICT_NOTE_LENGTH, Verdict, VerdictRecord
from fm_analytics.reporting import build_player_role_scores
from fm_analytics.web.rendering import role_score_cells
from fm_analytics.web.scouting_render import (
    NOT_CURRENT_BADGE,
    _ATTRIBUTE_GROUPS,
    _attribute_label,
    last_seen_club,
    _three_gains,
    _three_scores,
    _visible_observation_counts,
)


def player_scouting_report(
    candidate: ScoutingCandidate,
    catalogue,
    *,
    headline: str = "",
    verdict: str = "",
    back_href: str = "/scouting?view=scouted",
) -> str:
    """Render a scouted player's exhaustive report.

    ``verdict`` is the manager's own decision panel, already rendered by
    ``verdict_panel``; it needs a database this module deliberately never
    touches, so it arrives as HTML rather than being looked up here.
    """
    current = candidate.in_current_feed
    facts = [
        ("Club", candidate.club if current else last_seen_club(candidate)),
        ("Age", str(candidate.age) if candidate.age is not None else None),
        ("Nationality", candidate.nationality),
        ("Footedness", candidate.footedness),
        (
            "Scouting knowledge",
            (
                f"{candidate.scouting_knowledge}%"
                + (" (last known)" if candidate.dropped_from_scout_reports or not current else "")
                if candidate.scouting_knowledge is not None else None
            ),
        ),
        ("Availability", candidate.availability),
        ("Transfer status", candidate.transfer_status),
        ("Contract type", candidate.contract_type),
        ("Contract ends", candidate.contract_end),
    ]
    facts.extend((key, value) for key, value in (candidate.facts or {}).items())
    if not current:
        facts.extend(_last_seen_facts(candidate))
    return _player_detail_report(
        candidate.name, candidate.attributes,
        candidate.positions_for(include_raw_external_positions=True),
        candidate.raw_position_familiarity or {}, facts, catalogue,
        back_href=back_href, back_label="Back to scouting",
        familiarity_source="the captured raw 0–20 position rating",
        headline=_history_banner(candidate) + verdict + headline,
        attributes_captured=candidate.current_attributes_captured,
        historical_attributes=candidate.last_known_attributes,
        historical_observed_at=candidate.last_known_attributes_observed_at,
        readings=candidate.history.attributes if candidate.history else None,
        out_of_date_before=candidate.history.out_of_date_before if candidate.history else None,
        export_record=candidate_export_record(candidate, include_raw_positions=True),
    )


def _history_banner(candidate: ScoutingCandidate) -> str:
    """Say up front when any of this report is remembered rather than current."""
    history = candidate.history
    if history is None:
        return ""
    oldest = history.oldest_seen_on
    age = (
        f" The oldest thing used here was last seen on <b>{html.escape(oldest)}</b>"
        + (", which is <b>out of date</b>." if history.out_of_date else ".")
        if oldest else ""
    )
    if not history.in_current_feed:
        return (
            f"<div class='history-banner fm-player-history'>{NOT_CURRENT_BADGE} <b>Not in the current scouting "
            "feed.</b> Everything here is what you saw earlier in this save, as of the dates "
            "shown; he may since have moved, signed a new contract or stopped being gettable."
            + age + "</div>"
        )
    return (
        "<div class='history-banner fm-player-history'>Some attributes FM no longer shows are filled in from "
        "what you saw earlier; they are marked <i>historical</i> with the day they were last "
        "seen." + age + "</div>"
    )


def _last_seen_facts(candidate: ScoutingCandidate) -> list[tuple[str, str | None]]:
    """A history-only player's market facts, dated and never presented as current."""
    history = candidate.history
    profile = (history.profile if history else None) or {}
    seen = history.profile_last_seen_on if history else None
    suffix = f" (as of {seen})" if seen else " (historical)"
    value = profile.get("value")
    return [
        (label, f"{text}{suffix}")
        for label, text in (
            ("Contract type", profile.get("contract_type")),
            ("Contract ends", profile.get("contract_end")),
            ("Transfer status", profile.get("transfer_status")),
            ("Value", f"£{value:,}" if isinstance(value, int) else None),
        )
        if text
    ]


def verdict_panel(
    verdict: VerdictRecord | None,
    *,
    player_id: str,
    decided_on: str | None,
    enabled: bool,
) -> str:
    """The manager's own Target / Watch / Reject decision for this player.

    Pure HTML over a record the page has already read: no database access
    happens here. Where verdicts are unavailable the report is exactly what it
    was before this feature existed, and without a capture date the current
    state is shown but cannot be changed -- a decision that cannot be dated
    honestly is worse than one that is left alone.
    """
    if not enabled:
        return ""
    state = (
        f"<p class='verdict-state'>Current verdict: "
        f"<b>{html.escape(verdict.verdict.value.capitalize())}</b>"
        + (f" &mdash; {html.escape(verdict.note)}" if verdict.note else "")
        + f"<span class='muted'>, decided {html.escape(verdict.decided_on)}</span></p>"
        if verdict is not None
        else "<p class='verdict-state muted'>No verdict recorded yet.</p>"
    )
    if decided_on is None:
        return state
    chosen = verdict.verdict if verdict is not None else ""
    options = "".join(
        f"<option value='{value}'" + (" selected" if value == chosen else "") + f">{value.capitalize()}</option>"
        for value in Verdict
    )
    note = verdict.note if verdict is not None else ""
    return (
        "<section class='fm-workspace-panel fm-verdict-panel'><div class='fm-panel-heading'><div>"
        "<h2>Signing verdict</h2>"
        "<p>Your own decision, kept in this tool's local knowledge database: FM is never told, "
        "and nothing about it comes from a hidden rating.</p></div></div>"
        + state
        + "<form class='verdict' method='post' action='/scouting/verdict'>"
        f"<input type='hidden' name='player_id' value='{html.escape(player_id, quote=True)}'>"
        f"<input type='hidden' name='decidedOn' value='{html.escape(decided_on, quote=True)}'>"
        f"<label>Verdict<select name='verdict'>{options}</select></label>"
        f"<label>Note<input name='note' maxlength='{MAX_VERDICT_NOTE_LENGTH}' "
        f"value='{html.escape(note, quote=True)}' placeholder='Why, in your own words'></label>"
        "<button type='submit' name='action' value='save'>Save verdict</button>"
        "<button type='submit' name='action' value='clear'>Clear verdict</button>"
        "</form></section>"
    )


def squad_player_report(
    player, catalogue, *, squad_label: str | None = None, back_href: str = "/squad", contract_panel: str = "",
) -> str:
    """Render the equivalent report for a player in any owned club squad.

    `contract_panel` is the already-rendered Contracts verdict for him, shown
    above his scores; empty when the squad could not be assessed.
    """
    contract = player.contract
    facts = [
        ("Squad", squad_label),
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
        "<section class='fm-workspace-panel fm-player-score-summary'><div class='fm-panel-heading'><div>"
        "<h2>Best-role scores</h2>"
        "<p>The same three scores, calculated the same way, as the Squad roster: "
        "<b>attribute-based</b> (attributes and role fit only), <b>in-position</b> (adds positional "
        "familiarity) and <b>today’s selection score</b> (adds match readiness). "
        "Each shows the player's strongest role by that measure.</p></div></div>"
        "<div class='fm-player-table'><table><tr><th title='Attribute-based role score (best role)'>Role fit</th>"
        "<th title='In-position role score (best role)'>In-position</th>"
        "<th title='Today’s selection score (best role)'>Today</th></tr>"
        f"<tr>{role_score_cells(scores)}</tr></table></div></section>"
    )
    return _player_detail_report(
        player.name, player.attributes, player.positions, player.position_familiarity,
        facts, catalogue, back_href=back_href, back_label="Back to squad",
        familiarity_source="the captured 0–20 position familiarity rating",
        headline=contract_panel + headline,
        export_record=player_export_record(
            player.name, player.age, player.attributes, player.positions, player.position_familiarity,
            familiarity_source="Squad familiarity (0–20)",
        ),
    )


def _player_detail_report(
    name, attributes, player_positions, familiarity, facts, catalogue, *,
    back_href: str, back_label: str, familiarity_source: str, headline: str = "",
    attributes_captured: bool = True,
    historical_attributes=None, historical_observed_at: str | None = None,
    readings=None, out_of_date_before: str | None = None,
    export_record=None,
) -> str:
    """Render every attribute and catalogue role for a scouted or owned player."""
    policy = FamiliarityPolicy()
    positions = ordered_positions({
        position for role in catalogue.roles.values() for position in role.eligible_positions
    })
    known_positions = set(player_positions)
    position_rows = "".join(
        _position_familiarity_row(position, known_positions, familiarity, policy)
        for position in positions
    )
    attributes_html = _full_attribute_sheet(
        attributes, captured=attributes_captured,
        readings=readings, out_of_date_before=out_of_date_before,
    )
    historical_html = _historical_attribute_section(
        historical_attributes or {}, historical_observed_at
    )
    score_sections = "".join(
        _position_role_scores(attributes, position, catalogue, familiarity, policy)
        for position in sorted(positions, key=lambda p: (p not in known_positions, position_key(p)))
    )
    main_labels = {"Club", "Squad", "Age", "Nationality", "Footedness", "Scouting knowledge", "Availability", "Condition", "Match fitness", "Preferred foot"}
    def render_facts(items):
        return "".join(
            "<div><dt>" + html.escape(label) + "</dt><dd>" + html.escape(value) + "</dd></div>"
            for label, value in items if value
        )
    fact_rows = render_facts((label, value) for label, value in facts if label in main_labels or label in {"Injured", "Suspended"} and value == "Yes")
    extra_facts = render_facts((label, value) for label, value in facts if label not in main_labels and not (label in {"Injured", "Suspended"} and value == "Yes"))
    more_facts = ("<details class='fm-disclosure fm-player-more'><summary>More player information</summary>"
                  "<dl class='fm-player-facts'>" + extra_facts + "</dl></details>") if extra_facts else ""
    return (
        "<div class='fm-player-report'>"
        f"<p class='fm-player-back'><a href='{html.escape(back_href, quote=True)}'>← {html.escape(back_label)}</a></p>"
        "<section class='fm-player-profile' id='player-overview'><div class='fm-panel-heading'><div>"
        "<span class='eyebrow'>Player profile</span><h2>Player information</h2>"
        f"<p>{html.escape(', '.join(player_positions) or 'No positions captured')}</p>"
        "</div></div><dl class='fm-player-facts'>" + fact_rows + "</dl>" + more_facts + "</section>"
        + "<nav class='fm-section-nav' aria-label='Player report sections'>"
        "<a href='#player-overview'>Overview</a><a href='#player-attributes'>Attributes</a>"
        "<a href='#player-roles'>Role fit</a>"
        + ("<a href='#player-history'>History</a>" if historical_html else "") + "</nav>"
        + headline + (export_controls(records=[export_record]) if export_record else "") +
        "<details class='fm-workspace-panel fm-disclosure fm-player-attributes' id='player-attributes'><summary>Current attributes</summary><div><div class='fm-panel-heading'><div>"
        "<h2>Current attributes</h2>"
        + (
            "<p>Values visible now, plus remembered values marked "
            "<i>historical</i> where FM shows nothing today; both are used in the scores "
            "below. Ranges retain the uncertainty scouting reported.</p>"
            if readings else
            "<p>Only values visible now are used in the scores below. "
            "Ranges retain the uncertainty currently reported by scouting.</p>"
        )
        + "</div></div><div class='fm-player-attribute-groups'>" + attributes_html + "</div></div></details>"
        + historical_html
        + "<section class='fm-workspace-panel fm-player-position-summary'><div class='fm-panel-heading'><div>"
        + "<h2>Position score summary</h2>"
        "<p>Each row uses the highest estimated attribute-based role score among the roles available "
        "at that position. Positions are kept in the table even when they have not been captured, "
        "so it also shows the modelled potential after positional training.</p>"
        + "</div></div><div class='fm-player-table'>" + _position_score_summary(attributes, positions, catalogue, familiarity, policy) + "</div></section>"
        + "<details class='fm-workspace-panel fm-disclosure fm-player-familiarity'><summary>Position familiarity</summary><div><div class='fm-panel-heading'><div>"
        + "<h2>Position familiarity</h2>"
        f"<p>Familiarity is {html.escape(familiarity_source)}. The multiplier is the "
        "same discount used for an in-position score; a missing rating is left unknown rather than assumed.</p>"
        "</div></div><div class='fm-player-table'><table><tr><th>Position</th><th>Position captured</th><th>Familiarity / in-position multiplier</th></tr>"
        + position_rows + "</table></div></div></details>"
        + "<section class='fm-workspace-panel fm-player-role-scores' id='player-roles'><div class='fm-panel-heading'><div>"
        + "<h2>All attribute-based role scores by position</h2>"
        "<p>Floor and ceiling are the bounds supported by scouting. The cautious estimate is deliberately "
        "conservative when an attribute is unknown; estimate treats unknown attributes as mid-scale. "
        "In-position estimate applies the listed familiarity multiplier where one was captured.</p>"
        + "</div></div><div class='fm-player-role-groups'>" + score_sections + "</div></section>"
        "</div>"
    )


def _full_attribute_sheet(
    attributes, *, captured: bool = True, readings=None, out_of_date_before: str | None = None
) -> str:
    """Every attribute, grouped like FM; ``readings`` marks the remembered ones, dated."""
    readings = readings or {}
    groups: list[str] = []
    for title, keys in _ATTRIBUTE_GROUPS:
        rows = []
        for key in keys:
            observation = attributes.get(key)
            if observation is None:
                continue
            reading = readings.get(key)
            if reading is None:
                when = "<td class='muted'>Now</td>" if readings else ""
                css = ""
            else:
                stale = out_of_date_before is not None and reading.last_seen_on < out_of_date_before
                when = (
                    f"<td>Historical, last seen {html.escape(reading.last_seen_on)}"
                    + (" <span class='dropped-warning'>out of date</span>" if stale else "")
                    + "</td>"
                )
                css = " class='attr-historical'"
            rows.append(
                f"<tr{css}>"
                f"<td>{html.escape(_attribute_label(key))}</td>"
                f"<td>{html.escape(observation.display())}</td>"
                + when + "</tr>"
            )
        if rows:
            groups.append(
                f"<section class='report-attribute-group'><h3>{title}</h3>"
                "<div class='fm-player-table'><table><tr><th>Attribute</th><th>Scouted value</th>"
                + ("<th>Seen</th>" if readings else "") + "</tr>"
                + "".join(rows) + "</table></div></section>"
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
        "<details class='fm-workspace-panel fm-disclosure fm-player-history-detail' id='player-history'><summary>Attribute history</summary><div><div class='fm-panel-heading'><div>"
        "<h2>Past scouting knowledge</h2>"
        "<p class='warn'><b>Historical only.</b> These values were last visible on "
        f"<b>{when}</b>. They are not treated as current and are not used in any "
        "score, filter, or recommendation on this page, except where the same value "
        "appears above marked <i>historical</i>.</p></div></div>"
        "<div class='fm-player-attribute-groups'>" + _full_attribute_sheet(attributes) + "</div></div></details>"
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
        f"<details class='position-role-report fm-disclosure'><summary>{html.escape(position)} "
        f"<span class='muted'>— familiarity {familiarity_text}</span></summary>"
        "<div class='fm-player-table'><table><tr><th>Role</th><th>Floor</th><th>Cautious estimate</th><th>Estimate</th>"
        "<th>Ceiling</th><th>In-position estimate</th><th>Breakdown</th></tr>"
        + "".join(rows) + "</table></div></details>"
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
