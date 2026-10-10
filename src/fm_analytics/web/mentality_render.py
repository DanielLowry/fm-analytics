"""Recording the mentality a match was played in, and the figures split by it.

Forms and tables only: the record is `domain.mentality.MentalityPlan`, and
every number comes from `reporting` (the Matches page's breakdowns, a match's
own split by the score). FM keeps no record of the mentality we can read, so
it is the manager's own, kept apart from everything read from FM.
"""

from __future__ import annotations

import html
from typing import Mapping

from fm_analytics.analytics.match_breakdowns import STATES, Breakdowns, ScoreSplit
from fm_analytics.domain.mentality import MAX_CHANGES, MENTALITIES, MentalityPlan
from fm_analytics.web.match_render import versus

CHANGE_ROWS = 3
_STATE_LABELS = {"level": "Level", "ahead": "Ahead", "behind": "Behind"}


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def plan_from_form(form: Mapping[str, list[str]]) -> MentalityPlan | None:
    """The plan a form's mentality fields give, or None when no kickoff mentality is chosen."""
    start = form.get("mentality", [""])[0].strip()
    changes = []
    for minute, name in zip(form.get("change_minute", []), form.get("change_mentality", [])):
        minute, name = minute.strip(), name.strip()
        if not minute and not name:
            continue
        if not minute or not name:
            raise ValueError("Each mentality change needs both a minute and a mentality.")
        if not minute.isdigit():
            raise ValueError(f"{minute!r} is not a minute.")
        changes.append((int(minute), name))
    if not start:
        if changes:
            raise ValueError("Choose the mentality at kickoff before any change.")
        return None
    return MentalityPlan.build(start, changes)


def _options(current: str | None, blank: str) -> str:
    return f"<option value=''>{_e(blank)}</option>" + "".join(
        f"<option{' selected' if name == current else ''}>{_e(name)}</option>" for name in MENTALITIES
    )


def mentality_fields(plan: MentalityPlan | None) -> str:
    """The kickoff mentality and a row per change (blank rows are ignored), for any form."""
    changes: list[tuple[int | str, str | None]] = list(plan.changes[1:]) if plan else []
    rows = changes + [("", None)] * min(CHANGE_ROWS, MAX_CHANGES - len(changes))
    change_rows = "".join(
        "<div class='fm-mentality-change'>"
        f"<label>From minute<input type='number' name='change_minute' min='1' max='120' value='{minute}'></label>"
        f"<label>Changed to<select name='change_mentality'>{_options(name, '—')}</select></label></div>"
        for minute, name in rows
    )
    return (
        "<fieldset class='fm-mentality wide'><legend>Mentality</legend>"
        f"<label>At kickoff<select name='mentality'>{_options(plan.start if plan else None, 'Not recorded')}</select></label>"
        f"<div class='fm-mentality-changes'>{change_rows}</div>"
        "<p class='muted'>A row for each change you made, from the minute you made it. Blank rows are ignored.</p>"
        "</fieldset>"
    )


def hidden_mentality(plan: MentalityPlan | None) -> str:
    """A plan as hidden fields, for a form that posts a label again unchanged."""
    if plan is None:
        return ""
    return f"<input type='hidden' name='mentality' value='{_e(plan.start)}'>" + "".join(
        f"<input type='hidden' name='change_minute' value='{minute}'>"
        f"<input type='hidden' name='change_mentality' value='{_e(name)}'>"
        for minute, name in plan.changes[1:]
    )


def mentality_panel(match_key: str, plan: MentalityPlan | None) -> str:
    """A match page's record of the mentality it was played in."""
    current = (f"<p>Recorded: <strong>{_e(plan.text)}</strong></p>" if plan
               else "<p class='muted'>Not recorded for this match.</p>")
    return (
        "<section class='fm-workspace-panel fm-match-mentality-panel'><div class='fm-panel-heading'><div>"
        "<h2>Mentality</h2><p>FM keeps no record of the mentality that our code can read, so record it here: "
        "what you started in and each change. Reading matches from FM never changes it.</p></div></div>"
        + current
        + "<form class='fm-experiment-form' method='post' action='/matches/mentality'>"
        f"<input type='hidden' name='match' value='{_e(match_key)}'>"
        + mentality_fields(plan)
        + "<div class='wide'><button type='submit'>Save mentality</button>"
        + (" <button type='submit' name='clear' value='1' class='secondary'>Clear it</button>" if plan else "")
        + "</div></form></section>"
    )


def _figures(tally, per_90: bool) -> str:
    def pair(name: str) -> str:
        values = getattr(tally, name)
        return versus(*(tally.per_90(values) if per_90 else values))

    return (f"<td data-sort='{tally.minutes:.0f}'>{tally.minutes:.0f}</td><td>{pair('shots')}</td>"
            f"<td>{pair('on_goal')}</td><td>{pair('clear_cut_chances')}</td><td>{versus(*tally.goals)}</td>"
            + (f"<td>{versus(*tally.per_90(tally.goals))}</td>" if per_90 else ""))


def mentality_split(found: Breakdowns | ScoreSplit, *, per_90: bool) -> str:
    """By the mentality in use, then by mentality and the score together; empty without a recorded mentality."""
    if not found.by_mentality:
        return ""
    unit = " per 90" if per_90 else ""
    head = (f"<th>Minutes</th><th>Shots{unit}</th><th>On goal{unit}</th><th>Clear-cut chances{unit}</th><th>Goals</th>"
            + ("<th>Goals per 90</th>" if per_90 else ""))
    by_mentality = "".join(
        f"<tr><td>{_e(name)}</td>{_figures(tally, per_90)}</tr>"
        for name, tally in found.by_mentality.items() if tally.minutes >= 1
    )
    by_both = "".join(
        f"<tr><td>{_e(name)}</td><td>{_STATE_LABELS[state]}</td>{_figures(tally, per_90)}</tr>"
        for name in found.by_mentality for state in STATES
        if (tally := found.by_mentality_state.get((name, state))) is not None and tally.minutes >= 1
    )
    return (
        f"<div class='table-scroll'><table data-fm-plain><thead><tr><th>Mentality</th>{head}</tr></thead>"
        f"<tbody>{by_mentality}</tbody></table></div>"
        f"<h3>By mentality and the score</h3><div class='table-scroll'><table class='sortable'><thead><tr>"
        f"<th>Mentality</th><th>Score</th>{head}</tr></thead><tbody>{by_both}</tbody></table></div>"
    )


def match_mentality_split(split: ScoreSplit | None) -> str:
    """One match's own split by its mentality, beside its split by the score."""
    if split is None or not split.by_mentality:
        return ""
    return (
        "<h3>By mentality</h3>" + mentality_split(split, per_90=False)
        + "<p class='muted fm-match-note'>You, then them, in each mentality you recorded for this match.</p>"
    )


def mentality_breakdown(found: Breakdowns) -> str:
    """The Matches page's panel content: these matches by the mentality you recorded."""
    if not found.mentality_matches:
        return ""
    return mentality_split(found, per_90=True) + (
        f"<p class='muted fm-match-note'>You, then them, from the {found.mentality_matches} of "
        f"{found.split_matches} matches with every shot and goal time that have a recorded mentality. A change "
        "counts from the minute you recorded. Small numbers of minutes say little.</p>"
    )
