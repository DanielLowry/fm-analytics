"""HTML fragments for set-piece assignment and routine panels."""

from __future__ import annotations

import html
from urllib.parse import urlencode

from fm_analytics.web.rendering import _band

def _routine_taker(report, task_key: str, side: str | None):
    """The routine assignment is authoritative for crossed deliveries."""
    prefix = {
        "corners": "attacking_corner",
        "indirect_free_kicks": "attacking_wide_free_kick",
    }.get(task_key)
    if prefix is None or side is None:
        return None, None
    routine = next(item for item in report.routines if item.key == f"{prefix}_{side}")
    assignment = next(
        (item for item in routine.assignments if item.role.taker_task_key == task_key),
        None,
    )
    return routine, assignment


def _set_piece_choice(report, recommendation):
    """Return the one manager-facing choice plus its evidence state."""
    routine, assignment = _routine_taker(
        report, recommendation.task.key, recommendation.side
    )
    if assignment is not None:
        warning = (
            "Provisional — dedicated taker evidence is missing."
            if recommendation.suggested is None else ""
        )
        return (
            assignment.player.name,
            _band(assignment.score.score),
            f"Whole-routine choice · {round(routine.evidence_coverage * 100):.0f}% evidence",
            warning,
        )
    candidate = recommendation.suggested
    if candidate is None:
        message = (
            "More evidence needed" if recommendation.candidates else "No available player"
        )
        return None, "—", message, ""
    warning = (
        f"Proxy — {recommendation.task.proxy_for_unread_attribute} is not captured."
        if candidate.evidence_mode == "proxy" else ""
    )
    return candidate.player.name, _band(candidate.score.score), candidate.evidence_label, warning


def _set_piece_assignment_cards(report) -> str:
    groups = (
        ("Corners", (("corners", "left", "Left"), ("corners", "right", "Right"))),
        (
            "Wide free kicks",
            (
                ("indirect_free_kicks", "left", "Left"),
                ("indirect_free_kicks", "right", "Right"),
            ),
        ),
        (
            "Direct free kicks",
            (
                ("direct_free_kicks", "left", "Left"),
                ("direct_free_kicks", "right", "Right"),
            ),
        ),
        ("Penalties", (("penalties", None, "First choice"),)),
        ("Long throws", (("long_throws", None, "First choice"),)),
    )
    recommendations = {
        (item.task.key, item.side): item for item in report.recommendations
    }
    cards = []
    for title, entries in groups:
        lines = []
        for task_key, side, label in entries:
            recommendation = recommendations[(task_key, side)]
            player_name, _score, evidence, warning = _set_piece_choice(
                report, recommendation
            )
            evidence_class = " class='choice-warning'" if warning or player_name is None else ""
            lines.append(
                "<div class='set-piece-choice'>"
                f"<span>{html.escape(label)}</span>"
                f"<b>{html.escape(player_name) if player_name else 'No evidence-based recommendation'}</b>"
                f"<small{evidence_class}>{html.escape(warning or evidence)}</small></div>"
            )
        cards.append(
            "<article class='set-piece-assignment-card'>"
            f"<h3>{html.escape(title)}</h3>{''.join(lines)}</article>"
        )
    return "<div class='set-piece-assignments'>" + "".join(cards) + "</div>"


def _set_piece_routine_plan(routine, labels: dict[str, str]) -> str:
    assignments = []
    evidence_rows = []
    for assignment in routine.assignments:
        contributions = sorted(
            assignment.score.contributions,
            key=lambda item: (-item.weight, item.attribute),
        )[:3]
        evidence = " · ".join(
            f"{labels.get(item.attribute, item.attribute)} {item.observation.display()}"
            for item in contributions
        )
        side_fit = (
            "<div><dt>Delivery-side fit</dt><dd>"
            + html.escape(assignment.side_fit_label)
            + "</dd></div>"
            if assignment.role.taker_task_key else ""
        )
        selection_note = (
            "<details class='routine-assignment-note'><summary>Why "
            + html.escape(assignment.player.name)
            + "?</summary><div class='routine-assignment-reason'>"
            f"<p>{html.escape(assignment.role.explanation)}</p><dl>"
            f"<div><dt>Job fit</dt><dd>{_band(assignment.score.score)}</dd></div>"
            "<div><dt>Strongest visible inputs</dt><dd>"
            + (html.escape(evidence) if evidence else "More evidence needed")
            + "</dd></div>" + side_fit + "</dl>"
            "<small>This is a whole-routine choice: every player can fill only one job, "
            "so the optimizer maximizes the combined fit of the complete routine.</small>"
            "</div></details>"
        )
        assignments.append(
            "<div class='routine-assignment'>"
            f"<b>{html.escape(assignment.player.name)}</b>"
            "<span><strong>" + html.escape(assignment.role.instruction) + "</strong>"
            f"<small>{html.escape(assignment.role.zone)}</small></span>"
            f"<span class='set-piece-unit'>{html.escape(assignment.role.unit)}</span>"
            + selection_note + "</div>"
        )
        evidence_rows.append(
            "<tr>"
            f"<th scope='row'>{html.escape(assignment.player.name)}</th>"
            f"<td>{html.escape(assignment.role.instruction)}</td>"
            f"<td>{_band(assignment.score.score)}</td>"
            f"<td>{html.escape(evidence)}</td>"
            f"<td>{html.escape(assignment.role.explanation)}</td></tr>"
        )
    unfilled = (
        "<div class='advisory-banner'><b>Partial routine</b>Not enough eligible players to fill: "
        + ", ".join(html.escape(role.instruction) for role in routine.unfilled_roles)
        + ".</div>" if routine.unfilled_roles else ""
    )
    shape_summary = (
        f"{routine.players_in_box} in box · {routine.players_held_back} held back"
        if routine.phase == "attacking" else
        f"{routine.players_in_box} box defenders · {routine.players_held_back} outlet"
    )
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in routine.notes)
    return (
        "<section class='set-piece-routine' aria-labelledby='selected-routine'>"
        "<div class='routine-heading'><div>"
        f"<h3 id='selected-routine'>{html.escape(routine.name)}</h3>"
        f"<p>{html.escape(routine.objective)}</p></div>"
        f"<span>{shape_summary} · {round(routine.evidence_coverage * 100):.0f}% evidence</span></div>"
        "<div class='routine-assignments'>" + "".join(assignments) + "</div>" + unfilled
        + "<details class='routine-evidence'><summary>Why this plan?</summary>"
        "<div class='table-scroll'><table><thead><tr>"
        "<th scope='col'>Player</th><th scope='col'>Job</th><th scope='col'>Job fit</th>"
        "<th scope='col'>Strongest inputs</th><th scope='col'>Purpose</th>"
        "</tr></thead><tbody>" + "".join(evidence_rows) + "</tbody></table></div>"
        + ("<ul class='legend'>" + notes + "</ul>" if notes else "")
        + "</details></section>"
    )


def _set_piece_routine_switcher(report, selected_key: str, query: dict[str, str], labels) -> str:
    routines = {item.key: item for item in report.routines}
    selected = routines[selected_key]

    def link(label: str, routine_key: str, active: bool) -> str:
        href = "/set-pieces?" + urlencode({**query, "routine": routine_key})
        current = " aria-current='page'" if active else ""
        return f"<a href='{html.escape(href, quote=True)}'{current}>{html.escape(label)}</a>"

    attacking = selected.phase == "attacking"
    phase_tabs = (
        link("Attacking", "attacking_corner_left", attacking)
        + link("Defending", "defending_corner", not attacking)
    )
    if attacking:
        side = selected.side or "left"
        is_corner = selected.key.startswith("attacking_corner")
        event_tabs = (
            link("Corners", f"attacking_corner_{side}", is_corner)
            + link("Wide free kicks", f"attacking_wide_free_kick_{side}", not is_corner)
        )
        prefix = "attacking_corner" if is_corner else "attacking_wide_free_kick"
        side_tabs = (
            link("Left", f"{prefix}_left", side == "left")
            + link("Right", f"{prefix}_right", side == "right")
        )
        secondary = (
            "<nav class='routine-tabs' aria-label='Attacking routine type'>" + event_tabs + "</nav>"
            "<nav class='routine-tabs' aria-label='Delivery side'>" + side_tabs + "</nav>"
        )
    else:
        is_corner = selected.key == "defending_corner"
        secondary = (
            "<nav class='routine-tabs' aria-label='Defensive routine type'>"
            + link("Corners", "defending_corner", is_corner)
            + link("Wide free kicks", "defending_wide_free_kick", not is_corner)
            + "</nav>"
        )
    return (
        "<div class='routine-switcher'>"
        "<nav class='routine-tabs primary' aria-label='Routine phase'>" + phase_tabs + "</nav>"
        + secondary + "</div>" + _set_piece_routine_plan(selected, labels)
    )
