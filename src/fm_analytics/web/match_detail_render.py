"""HTML for one match's page. Rendering only: every number, the timeline and
the shots come from `reporting.build_match_report`, never from here."""

from __future__ import annotations

from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.match_analysis import METRICS, MatchReport
from fm_analytics.analytics.match_timeline import CORNER_GUESS
from fm_analytics.analytics.opponent import AXIS_DEFINITIONS
from fm_analytics.analytics.single_match_diagnosis import OneMatchDiagnosis
from fm_analytics.web.match_chances_render import match_chances_panel
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
            f"<td>{_position(player)}</td>"
            f"<td data-sort='{player.minutes}'>{player.minutes}{_stint(player)}</td>"
            f"<td>{f'{player.rating:.2f}' if player.rating is not None else '–'}</td>"
            f"<td>{stat('shots')} <span class='muted'>({stat('shots_on_target')}, {stat('shots_blocked')})</span></td>"
            f"<td>{stat('goals')}{_conceded(player)}</td><td>{stat('assists')}</td><td>{stat('clear_cut_chances')}</td>"
            f"<td>{stat('key_passes')}</td><td>{stat('chances_created')}</td><td>{stat('dribbles')}</td>"
            f"<td>{stat('passes_completed')}/{stat('passes_attempted')}</td>"
            f"<td>{stat('tackles_won')}/{stat('tackles_attempted')}</td><td>{stat('headers_won')}/{stat('headers_attempted')}</td>"
            f"<td>{stat('fouls')}</td><td>{stat('corners_taken')}</td>"
            f"<td data-sort='{player.distance_m}'>{player.distance_m / 1000:.1f} km</td></tr>"
        )
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>#</th><th>Player</th><th>Role</th><th>Position</th><th>Minutes</th><th>Rating</th>"
        "<th>Shots (on target, blocked)</th><th>Goals</th><th>Assists</th><th>Clear-cut chances</th>"
        "<th>Key passes</th><th>Chances created</th><th>Dribbles</th><th>Passes</th><th>Tackles</th><th>Headers</th><th>Fouls</th><th>Corners</th><th>Distance</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        + _unused(detail.players_for(side))
    )


def _position(player) -> str:
    """Where he started (and which side of a central pair), and where he ended up if that differs."""
    start = player.start_position
    if start and player.start_centre_side:
        start += f" ({player.start_centre_side})"
    if start and player.position and player.position != player.start_position:
        return f"{_e(start)} → {_e(player.position)}"
    return _e(start or player.position or "–")


def _conceded(player) -> str:
    if (player.start_position or player.position) != "GK":
        return ""
    return f" <span class='muted'>({player.stat('goals_conceded')} conceded)</span>"


def _unused(players) -> str:
    names = [player.label for player in players if not player.played]
    return f"<p class='muted fm-match-note'>Unused substitutes: {_e(', '.join(names))}.</p>" if names else ""


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
        if entry.given_away_by:
            extra.append(f"given away by {_e(entry.given_away_by)}, your record")
        items.append(
            f"<li class='{'ours' if entry.ours else 'theirs'} kind-{entry.kind}'>"
            f"<span class='fm-match-minute'>{entry.clock}′</span> {'You' if entry.ours else opponent} – "
            f"{_e(entry.label)}{who}"
            + (f" <span class='fm-goal-how'>{_e(entry.how.text)}</span>" if entry.how and entry.how.text else "")
            + (f" <span class='fm-guess' title='A guess. {_e(CORNER_GUESS)}'>possibly from a corner · guess</span>"
               if entry.possibly_from_a_corner else "")
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
        f"<tr class='{'ours' if shot.ours else 'theirs'} shot-{shot.outcome}'><td data-sort='{index}'>{shot.clock}′"
        f" <span class='muted'>({shot.match_clock})</span></td>"
        f"<td>{'You' if shot.ours else opponent}</td><td>{_e(shot.player or '')}</td><td>{shot.label}</td></tr>"
        for index, shot in enumerate(timeline.shots)
    )
    return totals + goal_mouths(report) + score_split_table(report) + (
        "<details class='fm-match-shot-list'><summary>Every shot</summary><div class='table-scroll'>"
        "<table class='sortable'><thead><tr><th>Minute (clock)</th><th>Team</th><th>Player</th><th>Where it went</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
        "<p class='muted fm-match-note'>The match clock runs on through first-half added time, so a shot then shows as 46′.</p>"
    )


# The goal-mouth picture: metres across (-10 to 10) and up (0 to 6) from the
# middle of the goal line, 20 pixels to the metre.
_SCALE, _HALF_WIDTH, _HEIGHT = 20, 10.0, 6.0


def _goal_mouth(shots, title: str, whose: str) -> str:
    width, height = 2 * _HALF_WIDTH * _SCALE, _HEIGHT * _SCALE
    x = lambda across: (max(-_HALF_WIDTH, min(_HALF_WIDTH, across)) + _HALF_WIDTH) * _SCALE  # noqa: E731
    y = lambda up: height - max(0.0, min(_HEIGHT, up)) * _SCALE  # noqa: E731
    frame = (
        f"<line class='ground' x1='0' y1='{height}' x2='{width}' y2='{height}'/>"
        f"<path class='frame' d='M{x(-3.66)} {height} V{y(2.44)} H{x(3.66)} V{height}'/>"
    )
    dots = "".join(
        f"<circle class='shot-dot shot-{shot.outcome}' cx='{x(shot.across):.1f}' cy='{y(shot.up):.1f}' "
        f"r='{6 if shot.outcome == 'goal' else 4}'><title>{shot.clock}′ {_e(shot.player or '')}: {shot.label}</title></circle>"
        for shot in shots
    )
    return (
        f"<figure class='fm-goal-mouth {whose}'><svg viewBox='-4 -4 {width + 8} {height + 8}' role='img' "
        f"aria-label='{_e(title)}'>{frame}{dots}</svg><figcaption>{_e(title)}</figcaption></figure>"
    )


def goal_mouths(report: MatchReport) -> str:
    """Where each side's shots crossed the goal line, or would have without a save or block."""
    timeline = report.timeline
    ours = [shot for shot in timeline.shots if shot.ours]
    theirs = [shot for shot in timeline.shots if not shot.ours]
    return (
        "<div class='fm-goal-mouths'>"
        + _goal_mouth(ours, "Your shots, as they reached the goal line", "ours")
        + _goal_mouth(theirs, f"{report.summary.opponent.name}'s shots, as they reached the goal line", "theirs")
        + "</div><p class='muted fm-match-note'>Big dots are goals, filled ones on goal (saved, blocked or "
        "scored), hollow ones wide or over. Shots further out are drawn at the edge.</p>"
    )


def score_split_table(report: MatchReport) -> str:
    """This match's shots, chances and goals while level, ahead and behind."""
    split = report.timeline.by_score if report.timeline else None
    if split is None:
        return ""
    names = {"level": "Level", "ahead": "Ahead", "behind": "Behind"}
    rows = "".join(
        f"<tr><td>{names[state]}</td><td>{tally.minutes:.0f}</td><td>{tally.shots[0]}–{tally.shots[1]}</td>"
        f"<td>{tally.on_goal[0]}–{tally.on_goal[1]}</td><td>{tally.clear_cut_chances[0]}–{tally.clear_cut_chances[1]}</td>"
        f"<td>{tally.goals[0]}–{tally.goals[1]}</td></tr>"
        for state, tally in split.by_state.items() if tally.minutes >= 1
    )
    return (
        "<h3>By the score</h3><div class='table-scroll'><table data-fm-plain><thead><tr><th>Score</th><th>Minutes</th>"
        "<th>Shots</th><th>On goal</th><th>Clear-cut chances</th><th>Goals</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div><p class='muted fm-match-note'>You, then them, while the score "
        "was each way; a goal's own shot counts in the score before it.</p>"
    )


def _count_rows(match, side: str) -> str:
    """The counts behind the panel's percentages, as FM's stats panel has them."""
    other = "away" if side == "home" else "home"
    ours, theirs = match.detail.team(side), match.detail.team(other)
    rows = []
    for done, tried, label in (("passes_completed", "passes_attempted", "Passes completed (of attempted)"),
                               ("tackles_won", "tackles_attempted", "Tackles won (of attempted)"),
                               ("headers_won", "headers_attempted", "Headers won (of attempted)")):
        rows.append(
            f"<tr><td>{label}</td><td>{versus(ours.get(done), theirs.get(done))}"
            f"<span class='muted'> of {ours.get(tried, 0)} and {theirs.get(tried, 0)}</span></td></tr>"
        )
    return "".join(rows)


def _result_incidents(report: MatchReport) -> str:
    """The goals and sendings-off FM's result records, for a match without full stats."""
    summary = report.summary
    kinds = {"goal": "Goal", "penalty": "Penalty", "own_goal": "Own goal", "sent_off": "Sent off"}
    items = "".join(
        f"<li class='{'ours' if (incident.side == summary.side) else 'theirs'} kind-{incident.kind}'>"
        f"<span class='fm-match-minute'>{incident.clock}′</span> "
        f"{'You' if incident.side == summary.side else _e(summary.opponent.name)} – {kinds[incident.kind]}"
        f"{': ' + _e(incident.player) if incident.player else ''}</li>"
        for incident in summary.match.incidents
    )
    return f"<ol class='fm-match-timeline'>{items}</ol>" if items else ""


def penalty_forms(report: MatchReport) -> str:
    """A form per penalty scored against us: who gave it away, as you saw it on FM's replay."""
    if not report.penalties:
        return ""
    forms = []
    for penalty in report.penalties:
        heading = f"{penalty.clock}′, scored by {_e(penalty.taker or 'their player')}"
        if not penalty.on_pitch:
            forms.append(f"<p>{heading}: <span class='muted'>this match's line-ups were not read, so there is "
                         "nobody to choose from.</span></p>")
            continue
        options = "<option value=''>Not recorded</option>" + "".join(
            f"<option value='{short_id}'{' selected' if short_id == penalty.given_away_by_id else ''}>{_e(name)}</option>"
            for short_id, name in penalty.on_pitch
        )
        forms.append(
            "<form class='note-form fm-penalty-form' method='post' action='/matches/penalty'>"
            f"<input type='hidden' name='match' value='{_e(penalty.match_key)}'>"
            f"<input type='hidden' name='minute' value='{penalty.minute}'>"
            f"<input type='hidden' name='added' value='{penalty.added_time}'>"
            f"<label>{heading}: who gave it away?<select name='player'>{options}</select></label>"
            "<div><button type='submit'>Save</button></div></form>"
        )
    return (
        "<h3>Penalties you gave away</h3><p class='muted'>FM doesn't record who gave a penalty away, so this is "
        "yours to note from the replay. Reading matches from FM never changes it.</p>" + "".join(forms)
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
    notes: bool = True,
) -> str:
    """One match's page. `notes=False` leaves out the forms that save to the match
    history (notes, who gave a penalty away), for a stored replay that is not in it."""
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
    saved = match.detail.saved_tactics.get(summary.side) if match.detail else None
    if saved and saved.name:
        context.append(f"You lined up in <strong>{_e(saved.name)}</strong> (FM's saved tactic).")
    if timeline and timeline.opponent_formation:
        context.append(f"They lined up <strong>{_e(timeline.opponent_formation)}</strong>.")
    if match.after_extra_time:
        home, away = match.score_at_90
        context.append(f"After 90 minutes it was {home}–{away}; the score shown is after extra time.")
    if match.penalties:
        home, away = match.penalties
        context.append(f"Penalty shootout {home}–{away}.")
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
        match_chances_panel(diagnosis, summary.opponent.name, summary.result, has_stats=match.detail is not None)
        + match_diagnosis_panel(diagnosis, summary.opponent.name, has_stats=match.detail is not None)
        if diagnosis is not None else ""
    )
    if match.detail is None:
        return header + diagnosis_panel + panel(
            "Match evidence",
            "The result is retained, but detailed match stats are not available for this fixture.",
            "<p class='warn'>Only the result was found for this match: FM's archive had no stats for it "
            "that added up.</p>" + _result_incidents(report),
            panel_class="fm-match-evidence-gap",
        ) + (_notes_panel(report, catalogue, pinned, note) if notes else "")
    ours, theirs = summary.ours, summary.theirs
    stat_rows = "".join(
        f"<tr><td>{_e(label)}</td><td>{versus(ours[key], theirs[key], percentage)}</td></tr>"
        for key, label, percentage in METRICS
    ) + _count_rows(match, summary.side)
    events = timeline_items(report)
    corner_note = (
        f"<p class='muted fm-match-note'>“Possibly from a corner” is a guess, not something FM records. "
        f"{_e(CORNER_GUESS)}</p>"
        if report.timeline and any(entry.possibly_from_a_corner for entry in report.timeline.entries) else ""
    )
    shots = shots_table(report)
    other = "away" if summary.side == "home" else "home"
    return (
        header
        + diagnosis_panel
        + "<section class='fm-workspace-panel fm-match-score-panel'><div class='fm-panel-heading'><div>"
        "<h2>Match stats</h2><p>You, then them, as FM's match stats panel shows them.</p>"
        "</div></div><div class='fm-table-card fm-match-stat-table'>"
        f"<table><tbody>{stat_rows}</tbody></table></div></section>"
        + (panel("Timeline", "Goals, clear-cut chances and cards, as FM's match timeline records them.",
                 f"<ol class='fm-match-timeline'>{events}</ol>" + corner_note, panel_class="fm-match-timeline-panel")
           if events else "")
        + (panel("Shots", "Every shot, and where it was going: on goal (inside the posts and under the bar, "
                 "whether saved, blocked or scored), wide or over.", shots, panel_class="fm-match-shots") if shots else "")
        + panel("Your players", "Minutes, match contribution, and role for your side.", _player_rows(report, summary.side), panel_class="fm-match-players")
        + panel(_e(summary.opponent.name), "Their recorded player statistics.", _player_rows(report, other), panel_class="fm-match-players")
        + (_notes_panel(report, catalogue, pinned, note) if notes else "")
    )


def _notes_panel(report: MatchReport, catalogue: FootballCatalogue, pinned: Sequence[str], note) -> str:
    return (
        "<section class='fm-workspace-panel fm-match-notes-panel'>" + note_form(report, catalogue, pinned, note)
        + penalty_forms(report) + "</section>"
    )
