"""HTML for one match's page. Rendering only: every number, the timeline and
the shots come from `reporting.build_match_report`, never from here."""

from __future__ import annotations

from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.match_analysis import METRICS, MatchReport
from fm_analytics.analytics.opponent import AXIS_DEFINITIONS
from fm_analytics.analytics.single_match_diagnosis import OneMatchDiagnosis
from fm_analytics.web.match_diagnosis_render import match_diagnosis_panel
from fm_analytics.web.match_render import _e, chip, versus

_RATING_AXIS = next(axis for axis in AXIS_DEFINITIONS if axis.key == "quality")
RATING_LABELS = {
    -2: f"-2 · {_RATING_AXIS.low}",
    -1: "-1 · weaker than us",
    0: "0 · about the same",
    1: "+1 · stronger than us",
    2: f"+2 · {_RATING_AXIS.high}",
}


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


def timeline_items(report: MatchReport) -> str:
    """The Timeline panel's list items: one per goal, clear-cut chance, booking or sending-off."""
    timeline = report.timeline
    if timeline is None:
        return ""
    opponent = _e(report.summary.opponent.name)
    items = []
    for entry in timeline.entries:
        who = f": {_e(entry.player)}" if entry.player else ""
        extra = []
        if entry.assisted_by:
            extra.append(f"assist {_e(entry.assisted_by)}")
        if entry.from_clear_cut_chance:
            extra.append("from a clear-cut chance")
        items.append(
            f"<li class='{'ours' if entry.ours else 'theirs'} kind-{entry.kind}'>"
            f"<span class='fm-match-minute'>{entry.clock}′</span> {'You' if entry.ours else opponent} – "
            f"{_e(entry.label)}{who}"
            + (f" <span class='fm-goal-how'>{_e(entry.how.text)}</span>" if entry.how and entry.how.text else "")
            + (f" <span class='muted'>({', '.join(extra)})</span>" if extra else "")
            + "</li>"
        )
    return "".join(items)


def _shot_line(label: str, side) -> str:
    return (
        f"<tr><td>{label}</td><td>{side.shots}</td><td>{side.on_goal}</td><td>{side.wide}</td>"
        f"<td>{side.over}</td><td>{side.first_half}</td><td>{side.second_half}</td></tr>"
    )


def shots_table(report: MatchReport) -> str:
    """The Shots panel: each side's totals by where they went and by half, then every shot."""
    timeline = report.timeline
    if timeline is None or not timeline.shots:
        return ""
    opponent = _e(report.summary.opponent.name)
    totals = (
        "<div class='table-scroll'><table data-fm-plain><thead><tr><th></th><th>Shots</th><th>On goal</th><th>Wide</th>"
        "<th>Over</th><th>First half</th><th>Second half</th></tr></thead><tbody>"
        + _shot_line("You", timeline.ours) + _shot_line(opponent, timeline.theirs)
        + "</tbody></table></div>"
    )
    rows = "".join(
        f"<tr class='{'ours' if shot.ours else 'theirs'} shot-{shot.outcome}'><td data-sort='{index}'>{shot.clock}′</td>"
        f"<td>{'You' if shot.ours else opponent}</td><td>{_e(shot.player or '')}</td><td>{shot.label}</td></tr>"
        for index, shot in enumerate(timeline.shots)
    )
    return totals + (
        "<details class='fm-match-shot-list'><summary>Every shot</summary><div class='table-scroll'>"
        "<table class='sortable'><thead><tr><th>Minute</th><th>Team</th><th>Player</th><th>Where it went</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
        "<p class='muted fm-match-note'>The match clock runs on through first-half added time, so a shot then shows as 46′.</p>"
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
    report: MatchReport,
    catalogue: FootballCatalogue,
    pinned: Sequence[str],
    note,
    *,
    copy_control: str = "",
    diagnosis: OneMatchDiagnosis | None = None,
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
    timeline = report.timeline
    if timeline and timeline.opponent_formation:
        context.append(f"They lined up <strong>{_e(timeline.opponent_formation)}</strong>.")
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

    diagnosis_panel = (
        match_diagnosis_panel(diagnosis, summary.opponent.name, has_stats=match.detail is not None)
        if diagnosis is not None else ""
    )
    if match.detail is None:
        return header + diagnosis_panel + panel(
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
    events = timeline_items(report)
    shots = shots_table(report)
    other = "away" if summary.side == "home" else "home"
    return (
        header
        + diagnosis_panel
        + "<section class='fm-workspace-panel fm-match-score-panel'><div class='fm-panel-heading'><div>"
        "<h2>Match stats</h2><p>You, then them, as FM's match stats panel shows them.</p>"
        "</div></div><div class='fm-table-card fm-match-stat-table'>"
        f"<table><tbody>{stat_rows}</tbody></table></div></section>"
        + (panel("Timeline", "Goals, clear-cut chances and cards, as FM's match timeline records them.", f"<ol class='fm-match-timeline'>{events}</ol>", panel_class="fm-match-timeline-panel") if events else "")
        + (panel("Shots", "Every shot, and where it was going: on goal (inside the posts and under the bar, "
                 "whether saved, blocked or scored), wide or over.", shots, panel_class="fm-match-shots") if shots else "")
        + panel("Your players", "Minutes, match contribution, and role for your side.", _player_rows(report, summary.side), panel_class="fm-match-players")
        + panel(_e(summary.opponent.name), "Their recorded player statistics.", _player_rows(report, other), panel_class="fm-match-players")
        + "<section class='fm-workspace-panel fm-match-notes-panel'>" + note_form(report, catalogue, pinned, note) + "</section>"
    )
