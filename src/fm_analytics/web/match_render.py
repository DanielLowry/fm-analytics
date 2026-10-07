"""HTML for the Matches pages. Rendering only: every number comes from
`reporting.build_match_review` / `build_match_report`, never from here."""

from __future__ import annotations

import html
from typing import Iterable, Mapping, Sequence
from urllib.parse import quote

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.match_analysis import (
    COMPETITION_SCOPE_LABELS,
    METRICS,
    MIN_GROUP_MATCHES,
    NO_TACTIC,
    GroupSummary,
    MatchReport,
    MatchReview,
    MatchSummary,
)
from fm_analytics.analytics.match_diagnostics import MatchDiagnostics
from fm_analytics.analytics.match_interventions import InterventionEvaluation, StoredIntervention
from fm_analytics.analytics.match_strength import GROUPING_LABELS
from fm_analytics.analytics.opponent import AXIS_DEFINITIONS

_METRIC = {key: (label, percentage) for key, label, percentage in METRICS}
_RATING_AXIS = next(axis for axis in AXIS_DEFINITIONS if axis.key == "quality")
RATING_LABELS = {
    -2: f"-2 · {_RATING_AXIS.low}",
    -1: "-1 · weaker than us",
    0: "0 · about the same",
    1: "+1 · stronger than us",
    2: f"+2 · {_RATING_AXIS.high}",
}


def _e(value: object) -> str:
    return html.escape(str(value))


def match_url(key: str) -> str:
    return "/matches/" + quote(key, safe="")


_RESULT_NAMES = {"W": "Won", "D": "Drawn", "L": "Lost"}
_EVENT_NAMES = {"goal": "goal", "clear_cut_chance": "clear-cut chance"}


def chip(result: str) -> str:
    return f"<span class='chip chip-{result}' title='{_RESULT_NAMES[result]}'>{result}</span>"


def form_strip(summaries: Iterable[MatchSummary]) -> str:
    return "<span class='form-strip'>" + "".join(chip(summary.result) for summary in summaries) + "</span>"


def _number(value: float | None, percentage: bool) -> str:
    if value is None:
        return "–"
    return f"{value:.0f}%" if percentage else (f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}")


def versus(ours: float | None, theirs: float | None, percentage: bool = False) -> str:
    """Our figure, a bar split in proportion, theirs."""
    if ours is None and theirs is None:
        return "<span class='muted'>–</span>"
    total = (ours or 0) + (theirs or 0)
    share = 50.0 if not total else 100 * (ours or 0) / total
    if percentage and ours is not None and theirs is None:
        share = ours
    return (
        "<span class='versus'>"
        f"<span class='us'>{_number(ours, percentage)}</span>"
        f"<span class='bars'><span class='b-us' style='width:{share:.0f}%'></span>"
        f"<span class='b-them' style='width:{100 - share:.0f}%'></span></span>"
        f"<span class='them'>{_number(theirs, percentage)}</span></span>"
    )


def _group_metric(group: GroupSummary, key: str) -> str:
    _label, percentage = _METRIC[key]
    if not group.detailed:
        return "<span class='muted'>–</span>"
    return versus(group.averages_for.get(key), group.averages_against.get(key), percentage)


def _thin(group: GroupSummary) -> tuple[str, str]:
    if not group.matches or group.enough:
        return "", ""
    return " class='thin'", f"<span class='thin-note'>too few to read ({group.matches} of {MIN_GROUP_MATCHES})</span>"


def group_table(groups: Sequence[GroupSummary], summaries: Sequence[MatchSummary], *, first_column: str) -> str:
    rows = []
    for group in groups:
        if not group.matches:
            continue
        in_group = [s for s in summaries if s.band.key == group.key or (group.key in ("home", "away") and s.side == group.key)]
        row_class, note = _thin(group)
        ppg = f"{group.points_per_game:.2f}" if group.points_per_game is not None else "–"
        rows.append(
            f"<tr{row_class}><td><strong>{_e(group.label)}</strong>{note}</td>"
            f"<td>{group.matches}</td><td>{form_strip(in_group)}<br>"
            f"<span class='muted'>W{group.wins} D{group.draws} L{group.losses}</span></td>"
            f"<td>{ppg}</td>"
            f"<td>{versus(group.goals_for / group.matches, group.goals_against / group.matches)}</td>"
            + "".join(f"<td>{_group_metric(group, key)}</td>" for key in ("shots", "shots_on_target", "clear_cut_chances", "possession"))
            + f"<td class='muted'>{group.detailed}</td></tr>"
        )
    if not rows:
        return "<p class='muted'>No matches in this selection.</p>"
    return (
        "<div class='table-scroll'><table><thead><tr>"
        f"<th>{_e(first_column)}</th><th>P</th><th>Results</th><th>Pts/game</th><th>Goals per match</th>"
        "<th>Shots</th><th>On target</th><th>Clear-cut chances</th><th>Possession</th>"
        "<th title='Matches whose full stats were captured'>With stats</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def tactic_grid(review: MatchReview) -> str:
    bands = [band for band in review.bands if any(s.band.key == band.key for s in review.matches)]
    if not review.tactics or not bands:
        return "<p class='muted'>No matches in this selection.</p>"
    head = "".join(f"<th>{_e(band.label)}</th>" for band in bands)
    rows = []
    for row in review.tactics:
        cells = []
        for band in bands:
            group = row.by_band[band.key]
            if not group.matches:
                cells.append("<td class='muted'>–</td>")
                continue
            thin = "" if group.enough else " class='muted'"
            ccc = ""
            if group.detailed:
                ccc = (f"<br><span class='muted'>clear-cut {_number(group.averages_for['clear_cut_chances'], False)}"
                       f"–{_number(group.averages_against['clear_cut_chances'], False)}</span>")
            cells.append(
                f"<td{thin}>W{group.wins} D{group.draws} L{group.losses} · "
                f"{group.points_per_game:.2f} pts/g{ccc}</td>"
            )
        label = _e(row.label)
        if row.tactic_key is None:
            label = f"<span class='muted'>{label}</span>"
        rows.append(f"<tr><td><strong>{label}</strong><br><span class='muted'>{row.overall.matches} matches</span></td>{''.join(cells)}</tr>")
    return (
        "<div class='table-scroll'><table><thead><tr><th>Tactic</th>" + head + "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def goals_section(review: MatchReview) -> str:
    goals = review.goals
    if not goals.goals_for_total and not goals.goals_against_total:
        return "<p class='muted'>No goals in this selection yet.</p>"
    peak = max((*goals.scored, *goals.conceded, 1))
    columns = "".join(
        f"<div class='col' title='{_e(period)}: scored {s}, conceded {c}'>"
        f"<span class='bar-for' style='height:{100 * s / peak:.0f}%'></span>"
        f"<span class='bar-against' style='height:{100 * c / peak:.0f}%'></span></div>"
        for period, s, c in zip(goals.periods, goals.scored, goals.conceded)
    )
    labels = "".join(f"<span>{_e(period)}<br>{s}–{c}</span>" for period, s, c in zip(goals.periods, goals.scored, goals.conceded))

    def ranked(title: str, items: Sequence[tuple[str, int]]) -> str:
        body = "".join(f"<li>{_e(label)} <strong>{count}</strong></li>" for label, count in items) or "<li class='muted'>None yet</li>"
        return f"<div class='match-card'><h3>{_e(title)}</h3><ol>{body}</ol></div>"

    timing = (
        f"<p class='intro'>When goals came, from the {goals.timed_matches} of {len(review.matches)} matches "
        f"whose goal times are known ({goals.timed_goals_for} scored, {goals.timed_goals_against} conceded). "
        "<span class='key-for'>Scored</span><span class='key-against'>Conceded</span></p>"
        f"<div class='period-chart'>{columns}</div><div class='period-labels'>{labels}</div>"
        if goals.timed_matches else
        "<p class='muted'>Goal times are not known for these matches yet: read matches from FM to fill them in.</p>"
    )
    discipline = (
        f"<p class='muted'>Penalties: {goals.penalties_for} for, {goals.penalties_against} against · "
        f"own goals: {goals.own_goals_for} for, {goals.own_goals_against} against · "
        f"sent off: {goals.sent_off_ours} of ours, {goals.sent_off_theirs} of theirs.</p>"
    )
    who = (
        f"<p class='intro'>Who scored and made them, from the {goals.goals_for_covered} of "
        f"{goals.goals_for_total} goals scored and {goals.goals_against_covered} of "
        f"{goals.goals_against_total} conceded in matches with full stats.</p>"
        "<div class='match-cards'>"
        + ranked("Scored by", goals.scorers)
        + ranked("Set up by (assists)", goals.assisters)
        + ranked("Conceded to", goals.conceded_to)
        + "</div>"
        if goals.goals_for_covered or goals.goals_against_covered else
        "<p class='muted'>Scorers by role need matches with full stats; none in this selection has them.</p>"
    )
    return (
        timing
        + discipline
        + who
        + "<p class='muted'>Penalties and own goals are read from FM; whether any other goal came from open "
        "play or a set piece, and where the shot came from, are not read yet.</p>"
    )


def _per_90(role, value: int) -> str:
    rate = role.per_90(value)
    return f" <span class='muted'>({rate:.1f} per 90)</span>" if rate is not None and value else ""


def roles_table(review: MatchReview) -> str:
    if not review.roles:
        return "<p class='muted'>No match with full stats in this selection yet.</p>"
    rows = []
    for role in review.roles:
        share = role.shot_share
        bar = f"<span class='share' style='width:{60 * share:.0f}px'></span>{100 * share:.0f}%" if share is not None else "–"
        label = _e(role.label) if role.confirmed else f"<span class='warn'>{_e(role.label)}</span>"
        rating = f"{role.average_rating:.2f}" if role.average_rating is not None else "–"
        rows.append(
            f"<tr><td>{label}</td><td data-sort='{role.appearances}'>{role.appearances} "
            f"<span class='muted'>({role.starts} starts)</span></td>"
            f"<td data-sort='{role.minutes}'>{role.minutes}</td>"
            f"<td data-sort='{role.shots}'>{role.shots} <span class='muted'>({role.shots_on_target} on target)</span></td>"
            f"<td data-sort='{role.per_90(role.shots) or 0}'>{_number(role.per_90(role.shots), False)}</td>"
            f"<td data-sort='{share or 0}'>{bar}</td><td>{role.goals}</td><td>{role.assists}</td>"
            f"<td data-sort='{role.per_90(role.goals + role.assists) or 0}'>"
            f"{_number(role.per_90(role.goals + role.assists), False)}</td>"
            f"<td>{role.clear_cut_chances}</td>"
            f"<td data-sort='{role.key_passes}'>{role.key_passes}{_per_90(role, role.key_passes)}</td>"
            f"<td data-sort='{role.chances_created}'>{role.chances_created}{_per_90(role, role.chances_created)}</td>"
            f"<td>{role.dribbles}</td><td>{rating}</td></tr>"
        )
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Role</th><th>Appearances</th><th>Minutes</th>"
        "<th>Shots</th><th>Shots per 90</th><th>Share of team shots</th><th>Goals</th><th>Assists</th>"
        "<th>Goals + assists per 90</th><th>Clear-cut chances</th><th>Key passes</th>"
        "<th>Chances created</th><th>Dribbles</th>"
        f"<th>Average rating</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def unconfirmed_roles_form(review: MatchReview, catalogue: FootballCatalogue) -> str:
    if not review.unconfirmed_roles:
        return ""
    options = "".join(
        f"<option value='{_e(key)}'>{_e(role.name)}</option>"
        for key, role in sorted(catalogue.roles.items(), key=lambda item: item[1].name)
    )
    items = "".join(
        f"<li><strong>FM code {code.code:#x}</strong> · {code.appearances} appearances, e.g. {_e(code.examples[0])} "
        "<form class='inline' method='post' action='/matches/role-code'>"
        f"<input type='hidden' name='code' value='{code.code}'><select name='role'>{options}</select>"
        "<button type='submit'>Confirm</button></form></li>"
        for code in review.unconfirmed_roles
    )
    return (
        "<h2>Roles to confirm</h2><p class='intro'>FM names a role only by a code. These codes are new: "
        "check the player's role on FM's tactics screen for that match and pick it here. It is stored "
        f"once and used for every match.</p><ul>{items}</ul>"
    )


def matches_table(summaries: Sequence[MatchSummary], catalogue: FootballCatalogue) -> str:
    rows = []
    for summary in reversed(summaries):
        match = summary.match
        strength = summary.strength
        position = (
            f"<span class='muted'>{strength.opponent.position} of {strength.opponent.teams}</span>"
            if strength.opponent else ""
        )
        tactic = catalogue.tactics[summary.tactic_key].name if summary.tactic_key in catalogue.tactics else ""
        if tactic and summary.tactic_inferred:
            tactic = f"{_e(tactic)} <span class='muted' title='Worked out from the roles in the line-up'>(line-up)</span>"
        else:
            tactic = _e(tactic) or "<span class='muted'>–</span>"
        stats = (
            f"<td>{versus(summary.ours['shots'], summary.theirs['shots'])}</td>"
            f"<td>{versus(summary.ours['clear_cut_chances'], summary.theirs['clear_cut_chances'])}</td>"
            f"<td>{versus(summary.ours['possession'], summary.theirs['possession'], True)}</td>"
            if summary.ours else "<td colspan='3' class='muted'>result only</td>"
        )
        rows.append(
            f"<tr><td data-sort='{match.date.isoformat()}'><a href='{match_url(match.key)}'>{match.date:%d %b %Y}</a></td>"
            f"<td>{_e(match.competition.label)}</td><td>{summary.venue}</td>"
            f"<td>{_e(summary.opponent.name)} {position}</td>"
            f"<td class='nowrap' data-sort='{summary.goals_for - summary.goals_against}'>{chip(summary.result)} "
            f"{summary.goals_for}–{summary.goals_against}</td>"
            f"<td>{_e(summary.band.label)}</td><td>{tactic}</td>{stats}</tr>"
        )
    if not rows:
        return "<p class='muted'>No matches in this selection.</p>"
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Date</th><th>Competition</th><th>Venue</th>"
        "<th>Opponent (position at kickoff)</th><th>Result</th><th>Opposition</th><th>Tactic</th>"
        f"<th>Shots</th><th>Clear-cut chances</th><th>Possession</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def review_filters(review: MatchReview, catalogue: FootballCatalogue, pinned: Sequence[str]) -> str:
    filters = review.filters

    def select(name: str, options: Sequence[tuple[str, str]], current: str | None) -> str:
        body = "".join(
            f"<option value='{_e(value)}'{' selected' if value == (current or '') else ''}>{_e(label)}</option>"
            for value, label in options
        )
        return f"<select name='{name}'>{body}</select>"

    tactic_keys = list(pinned) + sorted(key for key in {s.tactic_key for s in review.matches} if key and key not in pinned)
    tactics = [("", "Any tactic")] + [
        (key, catalogue.tactics[key].name) for key in tactic_keys if key in catalogue.tactics
    ] + [(NO_TACTIC, "Tactic not known")]
    return (
        "<form class='filters fm-match-filters' method='get' action='/matches'>"
        f"<label>Group opponents by{select('group', list(GROUPING_LABELS.items()), filters.grouping)}</label>"
        f"<label>Competitions{select('competitions', list(COMPETITION_SCOPE_LABELS.items()), filters.competitions)}</label>"
        f"<label>Venue{select('venue', [('', 'Home and away'), ('home', 'Home'), ('away', 'Away')], filters.venue)}</label>"
        f"<label>Tactic{select('tactic', tactics, filters.tactic)}</label>"
        "<button type='submit'>Show</button></form>"
    )


def capture_panel(status: str, message: str | None, ok: bool) -> str:
    notice = ""
    if message:
        notice = f"<p class='{'muted' if ok else 'error'}'>{_e(message)}</p>"
    return (
        "<div class='refresh-panel'><form class='refresh' method='post' action='/matches/capture'>"
        f"<span>{_e(status)}</span> <button type='submit'>Read matches from FM</button></form>{notice}"
        "<details><summary>How match stats get in</summary><p class='muted'>Reading is read-only: nothing is "
        "written to FM and there is nothing to do in FM. Results come from the game's memory, and full stats "
        "for every match from the match archive FM keeps on disk. Everything read is checked to add up "
        "before it is kept.</p></details></div>"
    )


def export_links() -> str:
    links = " · ".join(f"<a href='/api/export?detail={level}'>{level}</a>" for level in ("basic", "standard", "verbose"))
    return (
        f"<p class='muted'>Export the season as JSON: {links}. The same document "
        "<code>fm-matches export --detail &lt;level&gt;</code> writes.</p>"
    )


def _intervention_panel(
    evaluation: InterventionEvaluation | None,
    interventions: Sequence[StoredIntervention],
) -> str:
    closed = [item for item in interventions if not item.active]
    history = ""
    if closed:
        rows = "".join(
            f"<li><strong>{_e(item.proposal.title)}</strong> — {_e((item.outcome or 'closed').replace('_', ' '))}"
            + (f" · {_e(item.outcome_note)}" if item.outcome_note else "") + "</li>"
            for item in closed[:5]
        )
        history = (
            "<details class='fm-intervention-history'><summary>Previous controlled tests</summary>"
            f"<ul>{rows}</ul></details>"
        )
    if evaluation is None:
        return history
    item = evaluation.intervention
    proposal = item.proposal
    progress = min(100, 100 * evaluation.exposures / evaluation.target_matches)
    evidence = "".join(f"<li>{_e(line)}</li>" for line in evaluation.evidence)
    note = (
        f"<p class='fm-intervention-note'><strong>Manager note:</strong> {_e(proposal.manager_note)}</p>"
        if proposal.manager_note else ""
    )
    outcome_buttons = (
        "<button type='submit' name='outcome' value='adopted'>Record as adopted</button>"
        "<button class='secondary' type='submit' name='outcome' value='not_supported'>Close as not supported</button>"
        if evaluation.review_due else ""
    )
    controls = (
        "<form class='fm-intervention-controls' method='post' action='/matches/intervention/finish'>"
        f"<input type='hidden' name='intervention' value='{item.id}'>"
        "<label>Closing note <input name='note' maxlength='500' placeholder='What did you learn?'></label>"
        f"<div>{outcome_buttons}<button class='danger' type='submit' name='outcome' value='stopped'>Stop test</button></div>"
        "</form>"
    )
    return (
        f"<article class='fm-active-intervention status-{_e(evaluation.status)}'>"
        "<div class='fm-intervention-top'><div><span class='eyebrow'>Active controlled test</span>"
        f"<h3>{_e(proposal.title)}</h3></div><span class='fm-intervention-status'>{_e(evaluation.status_label)}</span></div>"
        f"<p>{_e(proposal.hypothesis)}</p><p><strong>Test:</strong> {_e(proposal.controlled_intervention)}</p>"
        + note
        + "<div class='fm-intervention-progress'><span>Eligible evidence</span>"
        f"<div><i style='width:{progress:.0f}%'></i></div><strong>{evaluation.exposures} / {evaluation.target_matches}</strong></div>"
        f"<p class='fm-intervention-verdict'>{_e(evaluation.summary)}</p>"
        + (f"<ul class='fm-diagnostic-evidence'>{evidence}</ul>" if evidence else "")
        + controls + "</article>" + history
    )


def diagnostics_section(
    diagnostics: MatchDiagnostics,
    intervention: InterventionEvaluation | None,
    interventions: Sequence[StoredIntervention],
) -> str:
    """The explainable diagnostic result; all decisions were made in analytics."""
    quality = diagnostics.quality
    gate_class = "ready" if quality.team_findings_allowed else "waiting"
    gate = (
        f"<div class='fm-diagnostic-gate {gate_class}'><strong>Evidence gate</strong> "
        f"{quality.eligible_team_matches} of {quality.selected_matches} selected matches have valid "
        f"full team stats; team findings require 5.</div>"
    )

    def evidence(items: Sequence[str]) -> str:
        return "<ul class='fm-diagnostic-evidence'>" + "".join(
            f"<li>{_e(item)}</li>" for item in items
        ) + "</ul>"

    opportunity_cards = []
    for finding in diagnostics.opportunities:
        start = ""
        if intervention is None:
            start = (
                "<form class='fm-start-intervention' method='post' action='/matches/intervention/start'>"
                f"<input type='hidden' name='finding' value='{_e(finding.key)}'>"
                "<label>Test note <input name='note' maxlength='500' "
                "placeholder='Optional: player or exact setting'></label>"
                "<button type='submit'>Start this controlled test</button></form>"
            )
        opportunity_cards.append(
            "<article class='fm-diagnostic-card opportunity'>"
            f"<div class='fm-diagnostic-card-head'><span class='eyebrow'>{_e(finding.problem_class)}</span>"
            f"<span class='fm-confidence {_e(finding.confidence)}'>{_e(finding.confidence)} confidence</span></div>"
            f"<h4>{_e(finding.title)}</h4><p>{_e(finding.hypothesis)}</p>"
            + evidence(finding.evidence)
            + "<dl class='fm-diagnostic-test'>"
            f"<dt>Controlled test</dt><dd>{_e(finding.intervention)}</dd>"
            f"<dt>Expected benefit</dt><dd>{_e(finding.expected_benefit)}</dd>"
            f"<dt>Evaluate after</dt><dd>{finding.evaluation_matches} eligible matches or starts</dd>"
            f"<dt>Success</dt><dd>{_e(finding.success_condition)}</dd>"
            f"<dt>Stop condition</dt><dd>{_e(finding.stop_condition)}</dd></dl>"
            + start + "</article>"
        )
    opportunities = (
        "<div class='fm-diagnostic-cards'>" + "".join(opportunity_cards) + "</div>"
        if opportunity_cards else
        "<p class='fm-diagnostic-empty'>No opportunity currently clears both the evidence gate and the effect threshold.</p>"
    )

    assurances = (
        "<div class='fm-diagnostic-cards assurances'>" + "".join(
            "<article class='fm-diagnostic-card assurance'>"
            f"<h4>{_e(item.title)}</h4>{evidence(item.evidence)}</article>"
            for item in diagnostics.do_not_change
        ) + "</div>"
        if diagnostics.do_not_change else
        "<p class='muted'>No area has enough positive evidence to protect yet.</p>"
    )
    limitations = [issue.message for issue in quality.issues] + [
        f"{item.title}: {item.reason}" for item in diagnostics.unavailable
    ]
    details = (
        "<details class='fm-diagnostic-limits'><summary>Evidence limits and unavailable diagnoses</summary>"
        + evidence(limitations) + "</details>"
        if limitations else ""
    )
    return (
        _intervention_panel(intervention, interventions)
        + gate
        + "<div class='fm-diagnostic-heading'><div><h3>Top current opportunities</h3>"
        "<p>Ranked by the strongest exploitable evidence, not by a tactic score.</p></div>"
        "<p class='fm-one-test'><strong>Run one controlled test at a time.</strong> Evaluate it after five eligible matches.</p></div>"
        + opportunities
        + "<div class='fm-diagnostic-heading protect'><div><h3>Do not change</h3>"
        "<p>Areas where the evidence says the current process is working.</p></div></div>"
        + assurances + details
    )


def review_body(
    review: MatchReview,
    diagnostics: MatchDiagnostics,
    intervention: InterventionEvaluation | None,
    interventions: Sequence[StoredIntervention],
    catalogue: FootballCatalogue,
    *,
    pinned: Sequence[str],
    capture: str,
) -> str:
    overall = review.overall
    ppg = f"{overall.points_per_game:.2f}" if overall.points_per_game is not None else "–"
    detailed = sum(1 for s in review.matches if s.ours)
    sample_note = (
        "enough matches to start comparing groups"
        if overall.enough
        else f"early season — groups need {MIN_GROUP_MATCHES} matches before they are reliable"
    )

    def panel(
        title: str,
        description: str,
        content: str,
        *,
        panel_class: str = "",
        panel_id: str = "",
    ) -> str:
        identifier = f" id='{panel_id}'" if panel_id else ""
        return (
            f"<section class='fm-workspace-panel fm-match-panel {panel_class}'{identifier}>"
            "<div class='fm-panel-heading'><div>"
            f"<h2>{title}</h2><p>{description}</p>"
            "</div></div>"
            + content
            + "</section>"
        )

    season_intro = (
        "How your matches have played out against different kinds of opponent. "
        f"<strong>{overall.matches}</strong> matches (W{overall.wins} D{overall.draws} L{overall.losses}, "
        f"{ppg} points a game); <strong>{detailed}</strong> with full stats. Figures are yours against theirs, "
        f"per match. A group under {MIN_GROUP_MATCHES} matches is greyed out: too few to read anything into."
    )
    return (
        "<nav class='fm-section-nav' aria-label='Match review sections'><a href='#match-list'>Matches</a><a href='#review-filters'>Review filters</a><a href='#match-analysis'>Analysis</a></nav>"
        "<section class='fm-match-review-hero'><span class='eyebrow'>Season review</span>"
        "<h2>Your results, read in context</h2>"
        f"<p>{season_intro}</p>"
        "<div class='fm-match-review-actions'><a class='button-link' href='#match-list'>Browse matches</a>"
        "<a class='button-link secondary' href='#review-filters'>Adjust review</a></div></section>"
        "<section class='fm-decision-grid fm-match-summary' aria-label='Season summary'>"
        "<article class='fm-decision-stat'><span>Record</span>"
        f"<b>W{overall.wins} D{overall.draws} L{overall.losses}</b><small>{overall.matches} matches selected</small></article>"
        "<article class='fm-decision-stat'><span>Points per game</span>"
        f"<b>{ppg}</b><small>{sample_note}</small></article>"
        "<article class='fm-decision-stat'><span>Evidence</span>"
        f"<b>{detailed} / {overall.matches}</b><small>matches with full stats</small></article></section>"
        + "<section class='fm-workspace-panel fm-match-capture-panel'>" + capture + "</section>"
        + "<section class='fm-workspace-panel fm-match-filter-panel' id='review-filters'><div class='fm-panel-heading'><div>"
        "<h2>Review filters</h2><p>Choose the comparison that matters, then read results before drawing conclusions.</p>"
        "</div></div>" + review_filters(review, catalogue, pinned) + "</section>"
        + panel(
            "Matches",
            "Open a match to review its scoreline, stats, players, and manager note.",
            matches_table(review.matches, catalogue),
            panel_class="fm-match-list",
            panel_id="match-list",
        )
        + "<details class='fm-workspace-panel fm-disclosure' id='match-analysis'><summary>Analysis and diagnostics</summary>"
        + panel(
            "Diagnostic engine",
            "Season-wide evidence-gated hypotheses, adjusted for opponent strength and venue. Review filters below do not move the recommendation.",
            diagnostics_section(diagnostics, intervention, interventions),
            panel_class="fm-match-diagnostics",
        )

        + panel(
            "Against different opposition",
            _e(review.grouping_label) + ".",
            group_table(review.groups, review.matches, first_column="Opposition"),
            panel_class="fm-match-opposition",
        )
        + panel(
            "Your tactics against each kind of opponent",
            "A tactic comes from your note on the match or, failing that, from the roles in the line-up when they match exactly one tactic.",
            tactic_grid(review),
            panel_class="fm-match-tactics",
        )
        + panel(
            "Home and away",
            "The same selected matches, separated by venue.",
            group_table(review.venues, review.matches, first_column="Venue"),
        )
        + panel("Where goals come from", "Timing and scorer information from the available match evidence.", goals_section(review), panel_class="fm-match-goals")
        + panel(
            "Who creates and shoots",
            "By the role each player was set to in the match, including substitutes, from matches with full stats.",
            roles_table(review),
            panel_class="fm-match-roles",
        )
        + ("<section class='fm-workspace-panel fm-match-confirmations'>" + unconfirmed_roles_form(review, catalogue) + "</section>" if review.unconfirmed_roles else "")

        + "</details>"
    )


# -- one match ----------------------------------------------------------------


def _stint(player) -> str:
    parts = []
    if player.came_on:
        parts.append(f"on {player.came_on}′")
    if player.went_off:
        parts.append(f"off {player.went_off}′")
    return f" <span class='muted'>({', '.join(parts)})</span>" if parts else ""


def _player_rows(report: MatchReport, side: str) -> str:
    detail = report.summary.match.detail
    rows = []
    for player in detail.players_for(side):
        if not player.played:
            continue
        stat = player.stat
        rows.append(
            f"<tr><td>{player.shirt}</td><td>{_e(player.label)}</td>"
            f"<td>{_e(report.role_labels.get((player.side, player.short_id), ''))}</td>"
            f"<td data-sort='{player.minutes}'>{player.minutes}{_stint(player)}</td>"
            f"<td>{f'{player.rating:.2f}' if player.rating is not None else '–'}</td>"
            f"<td>{stat('shots')} <span class='muted'>({stat('shots_on_target')}, {stat('shots_blocked')})</span></td>"
            f"<td>{stat('goals')}</td><td>{stat('assists')}</td><td>{stat('clear_cut_chances')}</td>"
            f"<td>{stat('key_passes')}</td><td>{stat('chances_created')}</td><td>{stat('dribbles')}</td>"
            f"<td>{stat('passes_completed')}/{stat('passes_attempted')}</td>"
            f"<td>{stat('tackles_won')}/{stat('tackles_attempted')}</td><td>{stat('headers_won')}/{stat('headers_attempted')}</td>"
            f"<td>{stat('fouls')}</td><td>{stat('corners_taken')}</td>"
            f"<td data-sort='{player.distance_m}'>{player.distance_m / 1000:.1f} km</td></tr>"
        )
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>#</th><th>Player</th><th>Role</th><th>Minutes</th><th>Rating</th>"
        "<th>Shots (on target, blocked)</th><th>Goals</th><th>Assists</th><th>Clear-cut chances</th>"
        "<th>Key passes</th><th>Chances created</th><th>Dribbles</th><th>Passes</th><th>Tackles</th><th>Headers</th><th>Fouls</th><th>Corners</th><th>Distance</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def note_form(
    report: MatchReport, catalogue: FootballCatalogue, pinned: Sequence[str], note
) -> str:
    summary = report.summary
    current_tactic = getattr(note, "tactic_key", None)
    tactic_keys = list(pinned) + sorted(key for key in catalogue.tactics if key not in pinned)
    tactic_options = "<option value=''>Not recorded</option>" + "".join(
        f"<option value='{_e(key)}'{' selected' if key == current_tactic else ''}>"
        f"{'★ ' if key in pinned else ''}{_e(catalogue.tactics[key].name)}</option>"
        for key in tactic_keys
    )
    current_rating = getattr(note, "opponent_rating", None)
    rating_options = "<option value=''>Not rated</option>" + "".join(
        f"<option value='{value}'{' selected' if value == current_rating else ''}>{_e(label)}</option>"
        for value, label in RATING_LABELS.items()
    )
    hint = ""
    if summary.tactic_inferred and summary.tactic_key in catalogue.tactics:
        hint = (f"<p class='muted'>From the roles in the line-up this looks like "
                f"<strong>{_e(catalogue.tactics[summary.tactic_key].name)}</strong>; record it only if that is wrong "
                "or to be sure.</p>")
    return (
        "<h2>Your notes</h2>" + hint +
        "<form class='note-form' method='post' action='/matches/note'>"
        f"<input type='hidden' name='match' value='{_e(summary.match.key)}'>"
        f"<label>Tactic you used<select name='tactic'>{tactic_options}</select></label>"
        f"<label>How strong you judged them before kickoff<select name='rating'>{rating_options}</select></label>"
        f"<textarea name='note' maxlength='1000' placeholder='Anything worth remembering'>{_e(getattr(note, 'note', ''))}</textarea>"
        "<div><button type='submit'>Save notes</button></div></form>"
    )


def match_body(
    report: MatchReport, catalogue: FootballCatalogue, pinned: Sequence[str], note, *, copy_control: str = ""
) -> str:
    summary = report.summary
    match = summary.match
    strength = summary.strength
    context = []
    if strength.opponent and strength.ours:
        context.append(
            f"At kickoff {_e(summary.opponent.name)} were <strong>{strength.opponent.position} of "
            f"{strength.opponent.teams}</strong> ({strength.opponent.played} played, {strength.opponent.points} pts) "
            f"and you were <strong>{strength.ours.position}</strong> ({strength.ours.points} pts): "
            f"{_e(summary.band.label.lower())}."
        )
    else:
        context.append(f"{_e(summary.opponent.name)} are not in a league table you play in.")
    if match.attendance:
        context.append(f"Attendance {match.attendance:,}.")
    header = (
        "<section class='fm-match-detail-hero'><span class='eyebrow'>Match review</span>"
        f"<p class='fm-match-detail-meta'>{match.date:%A %d %B %Y} · {_e(match.competition.name)} · {summary.venue}</p>"
        f"<div class='fm-match-detail-result'>{chip(summary.result)}<p>{' '.join(context)}</p></div>"
        f"{copy_control}</section>"
    )

    def panel(title: str, description: str, content: str, *, panel_class: str = "") -> str:
        return (
            f"<section class='fm-workspace-panel fm-match-panel fm-match-detail-panel {panel_class}'>"
            "<div class='fm-panel-heading'><div>"
            f"<h2>{title}</h2>"
            + (f"<p>{description}</p>" if description else "")
            + "</div></div>"
            + content
            + "</section>"
        )

    if match.detail is None:
        return header + panel(
            "Match evidence",
            "The result is retained, but detailed match stats are not available for this fixture.",
            "<p class='warn'>Only the result was found for this match: FM's archive had no stats for it "
            "that added up.</p>",
            panel_class="fm-match-evidence-gap",
        ) + "<section class='fm-workspace-panel fm-match-notes-panel'>" + note_form(
            report, catalogue, pinned, note
        ) + "</section>"
    ours, theirs = summary.ours, summary.theirs
    stat_rows = "".join(
        f"<tr><td>{_e(label)}</td><td>{versus(ours[key], theirs[key], percentage)}</td></tr>"
        for key, label, percentage in METRICS
    )
    timeline = "".join(
        f"<li>{event.minute}′ {'You' if event.side == summary.side else _e(summary.opponent.name)}: "
        f"{_EVENT_NAMES[event.kind]}</li>"
        for event in match.detail.events
        if event.kind in _EVENT_NAMES
    )
    other = "away" if summary.side == "home" else "home"
    return (
        header
        + "<section class='fm-workspace-panel fm-match-score-panel'><div class='fm-panel-heading'><div>"
        "<h2>Match stats</h2><p>You, then them, as FM's match stats panel shows them.</p>"
        "</div></div><div class='fm-table-card fm-match-stat-table'>"
        f"<table><tbody>{stat_rows}</tbody></table></div></section>"
        + (panel("Timeline", "Key goals and clear-cut chances recorded in the match timeline.", f"<ol class='fm-match-timeline'>{timeline}</ol>", panel_class="fm-match-timeline-panel") if timeline else "")
        + panel("Your players", "Minutes, match contribution, and role for your side.", _player_rows(report, summary.side), panel_class="fm-match-players")
        + panel(_e(summary.opponent.name), "Their recorded player statistics.", _player_rows(report, other), panel_class="fm-match-players")
        + "<section class='fm-workspace-panel fm-match-notes-panel'>" + note_form(report, catalogue, pinned, note) + "</section>"
    )



def tactic_record_panel(
    review: MatchReview, catalogue: FootballCatalogue, tactic_keys: Sequence[str], quality: int
) -> str:
    """The Tactics page's evidence box: what has happened so far, changing no score."""
    rows_by_key = {row.tactic_key: row for row in review.tactics}
    keys = list(tactic_keys) or [row.tactic_key for row in review.tactics if row.tactic_key]
    lines = []
    for key in keys:
        row = rows_by_key.get(key)
        name = _e(catalogue.tactics[key].name) if key in catalogue.tactics else _e(key)
        if row is None or not row.overall.matches:
            lines.append(f"<li>{name}: <span class='muted'>no recorded matches yet</span></li>")
            continue
        group = row.overall
        detail = ""
        if group.detailed:
            detail = (f" · shots {_number(group.averages_for['shots'], False)}–{_number(group.averages_against['shots'], False)},"
                      f" clear-cut {_number(group.averages_for['clear_cut_chances'], False)}–"
                      f"{_number(group.averages_against['clear_cut_chances'], False)} a match")
        thin = "" if group.enough else " <span class='muted'>(too few to read)</span>"
        lines.append(f"<li>{name}: W{group.wins} D{group.draws} L{group.losses}, "
                     f"{group.points_per_game:.2f} pts/g{detail}{thin}</li>")
    band_key = "stronger" if quality > 0 else "weaker" if quality < 0 else "similar"
    band = next(group for group in review.groups if group.key == band_key)
    if band.matches:
        rated = (f"<p>Against sides you rated <strong>{_e(band.label.lower())}</strong> before kickoff: "
                 f"W{band.wins} D{band.draws} L{band.losses} from {band.matches}"
                 f"{'' if band.enough else ' (too few to read)'}.</p>")
    else:
        rated = ("<p class='muted'>Rate each opponent on its match page (how strong you judged them before "
                 "kickoff) to see your record against sides like the one set above.</p>")
    return (
        "<div class='opponent-summary'><strong>Your match record</strong> "
        "<span class='muted'>(evidence only; it changes no score)</span>"
        f"<ul>{''.join(lines)}</ul>{rated}<a href='/matches'>All matches →</a></div>"
    )


def tactic_history_panel(review: MatchReview, catalogue: FootballCatalogue, tactic_key: str) -> str:
    """The tactic page's record of league and cup matches played with this tactic. Evidence only."""
    name = catalogue.tactics[tactic_key].name if tactic_key in catalogue.tactics else tactic_key
    overall = review.overall
    heading = (
        "<section class='fm-workspace-panel fm-tactic-history' id='tactic-history'>"
        "<div class='fm-panel-heading'><div><h2>How this tactic has played</h2>"
        f"<p>Your league and cup matches with {_e(name)}: the tactic from your note on the match, or from "
        "its line-up when that fits this tactic alone. What happened, not a prediction; it changes no score.</p>"
        f"</div><span class='fm-panel-count'>{overall.matches} match{'' if overall.matches == 1 else 'es'}</span></div>"
    )
    if not overall.matches:
        return heading + "<p class='muted'>No league or cup match recorded with this tactic yet.</p></section>"
    ppg = f"{overall.points_per_game:.2f}"
    sample = "enough to compare" if overall.enough else f"too few to read ({overall.matches} of {MIN_GROUP_MATCHES})"
    detailed = sum(1 for summary in review.matches if summary.ours)
    stats = (
        "<section class='fm-decision-grid' aria-label='Record with this tactic'>"
        "<article class='fm-decision-stat'><span>Record</span>"
        f"<b>W{overall.wins} D{overall.draws} L{overall.losses}</b><small>{form_strip(review.matches[-6:])}</small></article>"
        "<article class='fm-decision-stat'><span>Points per game</span>"
        f"<b>{ppg}</b><small>{sample}</small></article>"
        "<article class='fm-decision-stat'><span>Goals</span>"
        f"<b>{overall.goals_for}–{overall.goals_against}</b><small>{detailed} of {overall.matches} with full stats</small></article>"
        "</section>"
    )
    return (
        heading
        + stats
        + "<h3>Against different opposition</h3>"
        + group_table(review.groups, review.matches, first_column="Opposition")
        + "<h3>When goals came</h3>"
        + goals_section(review)
        + "<details><summary>Every match with this tactic</summary>"
        + matches_table(review.matches, catalogue)
        + "</details>"
        f"<p><a href='/matches?tactic={quote(tactic_key)}'>Review these matches on the Matches page →</a></p>"
        "</section>"
    )
