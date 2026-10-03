"""Recent form on the Tactics page: a chip per player and the ratings behind it.

The numbers are the recommendation's own (`SlotAssignment.form_change`, the
points form moved today's score) and its `FormLookup`; nothing is recomputed
here. See `analytics.player_form`.
"""

from __future__ import annotations

import html

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.player_form import FormLookup, JobForm


def job_form(form: FormLookup | None, assignment, tactic_key: str) -> JobForm | None:
    if form is None:
        return None
    return form.job(
        assignment.player_id, tactic_key, assignment.slot.position, assignment.intrinsic_role_score.role_key
    )


def _job_label(job: JobForm) -> str:
    tactic = MVP_CATALOGUE.tactics[job.tactic_key].name if job.tactic_key in MVP_CATALOGUE.tactics else job.tactic_key
    role = MVP_CATALOGUE.roles[job.role_key].name if job.role_key in MVP_CATALOGUE.roles else job.role_key
    return f"{job.position} {role} in {tactic}"


def _signed(value: float, unit: str = "") -> str:
    """+0.4, -0.2, or a plain 0.0 for anything that rounds to nothing (never "-0.0")."""
    return f"0.0{unit}" if abs(value) < 0.05 else f"{value:+.1f}{unit}"


def _games(count: int) -> str:
    return f"{count} game{'s' if count != 1 else ''}"


def form_chip(assignment, job: JobForm | None) -> str:
    """Points form adds to or takes from today's score, with the average behind it on hover."""
    if job is None:
        return (
            "<span class='form-chip form-none' title='No rated games of 30+ minutes in this exact job "
            "in the last 90 days, so form does not change this score'>–</span>"
        )
    change = assignment.form_change
    if change >= 0.05:
        kind, label = "form-up", f"▲ {_signed(change)}"
    elif change <= -0.05:
        kind, label = "form-down", f"▼ {_signed(change)}"
    else:
        kind, label = "form-flat", _signed(change)
    title = (
        f"Average {job.average:.2f} over his last {_games(len(job.ratings))} as {_job_label(job)}: "
        f"{_signed(change)} on today's score ({_signed(100 * job.change, '%')})"
    )
    return f"<span class='form-chip {kind}' title='{html.escape(title, quote=True)}'>{label}</span>"


def form_card(assignment, job: JobForm | None) -> str:
    """The form step in a starter's "Why him?" breakdown; it is applied last."""
    if job is None:
        return (
            "<div><span>Recent form</span><b>0.0</b>"
            "<small>no rated games in this job</small></div>"
        )
    return (
        "<div><span>Recent form</span>"
        f"<b>{_signed(assignment.form_change)}</b>"
        f"<small>avg {job.average:.2f} · {_games(len(job.ratings))}</small></div>"
    )


def form_ratings(job: JobForm | None, form: FormLookup | None) -> str:
    """The ratings behind a player's form in this job, newest first, and how much each counted."""
    if job is None or form is None:
        return ""
    newest = job.ratings[0].weight or 1.0
    rows = "".join(
        "<tr>"
        f"<td>{rating.date:%d %b %Y}</td>"
        f"<td>{html.escape(rating.opponent)}</td>"
        f"<td class='num'>{rating.rating:.2f}</td>"
        f"<td class='num'>{rating.minutes}′</td>"
        f"<td class='num'>{100 * rating.weight / newest:.0f}%</td>"
        "</tr>"
        for rating in job.ratings
    )
    policy = form.policy
    return (
        "<details class='form-ratings'>"
        f"<summary>Recent form as {html.escape(_job_label(job))}</summary>"
        f"<p class='muted'>His last {policy.max_ratings} ratings in this exact job from the last "
        f"{policy.window_days} days ({policy.min_minutes}+ minutes), newer ones counting more. "
        f"An average above {policy.neutral_rating} raises his score here and below it lowers it, by at "
        f"most {100 * policy.max_change:g}%, less with few games. His other jobs are not affected.</p>"
        "<table><tr><th>Date</th><th>Opponent</th><th class='num'>Rating</th><th class='num'>Minutes</th>"
        "<th class='num'>Counts</th></tr>"
        + rows
        + "</table></details>"
    )


def form_note(form: FormLookup | None) -> str:
    """One line under the Starting XI heading saying whether form is in the scores."""
    if form is None:
        return (
            "<p class='muted form-note'>Recent form is not included: there is no match history "
            "for this club yet (read matches on the Matches page).</p>"
        )
    return (
        "<p class='muted form-note'>Today's scores include recent form: each player's last "
        f"{form.policy.max_ratings} ratings in his exact job, up to {form.as_of:%d %b %Y}. "
        "Hover the form figure for his average; expand a player for the games.</p>"
    )
