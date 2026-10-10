"""A match page's Diagnosis: the match against your usual range, how it went, and who stood out.

Rendering only: every judgement in it (the ranges, above or below, good or
bad for you, who stood out) was made by `analytics.single_match_diagnosis`.
"""

from __future__ import annotations

import html

from fm_analytics.analytics.single_match_diagnosis import OneMatchDiagnosis, UsualRangeCheck


def _e(value: object) -> str:
    return html.escape(str(value))


def _usual_range(check: UsualRangeCheck) -> str:
    low, high = check.usual_low, check.usual_high
    return f"{low}" if low == high else f"{low}–{high}"


def _usual_cell(check: UsualRangeCheck, scale: float, who: str) -> str:
    """One figure as a dot against its shaded usual range, with the figures in words too."""
    def at(value: float) -> str:
        return f"{min(max(100 * value / scale, 0.0), 100.0):.1f}%"

    tone = "usual" if check.favourable is None else "good" if check.favourable else "bad"
    tag = (
        f"<span class='fm-usual-tag {tone}'>{'▲' if check.standing == 'above' else '▼'} "
        f"{'Above' if check.standing == 'above' else 'Below'}</span>"
        if check.standing != "usual" else ""
    )
    return (
        f"<div class='fm-usual-cell {tone}' role='cell' data-side='{_e(who)}' "
        f"title='{check.actual} {_e(check.label.lower())} · usual {_usual_range(check)}'>"
        f"<b>{check.actual}</b>"
        "<span class='fm-usual-meter' aria-hidden='true'>"
        f"<i style='left:{at(check.usual_low)};width:calc({at(check.usual_high)} - {at(check.usual_low)})'></i>"
        f"<em style='left:{at(check.actual)}'></em></span>"
        f"<small>usual {_usual_range(check)}</small>{tag}</div>"
    )


def match_diagnosis_panel(diagnosis: OneMatchDiagnosis, opponent: str, *, has_stats: bool) -> str:
    """The match page's Diagnosis; every judgement in it was made by `diagnose_one_match`."""
    rows = ""
    if diagnosis.checks:
        by_metric: dict[str, dict[str, UsualRangeCheck]] = {}
        for check in diagnosis.checks:
            by_metric.setdefault(check.metric, {})[check.side] = check
        for pair in by_metric.values():
            scale = 1.15 * max(1, *(max(check.actual, check.usual_high) for check in pair.values()))
            rows += (
                f"<div class='fm-usual-row' role='row'><span class='fm-usual-label' role='rowheader'>"
                f"{_e(pair['ours'].label)}</span>"
                + _usual_cell(pair["ours"], scale, "You") + _usual_cell(pair["theirs"], scale, opponent)
                + "</div>"
            )
        rows = (
            "<div class='fm-usual-grid' role='table' aria-label='This match against your usual range'>"
            "<div class='fm-usual-row fm-usual-head' role='row'><span role='columnheader'></span>"
            f"<span role='columnheader'>You</span><span role='columnheader'>{_e(opponent)}</span></div>"
            + rows + "</div>"
        )

    def players(items, direction: str) -> str:
        return "".join(
            f"<li class='{direction}'><b>{_e(item.name)}</b> {item.rating:.2f} "
            f"<span>usually {item.usual:.2f} as {_e(item.role)} · {item.matches} matches</span></li>"
            for item in items
        )

    notes = ""
    if diagnosis.game_state:
        notes += (
            "<section><h3>How it played out</h3><ul class='fm-match-diagnosis-list'>"
            + "".join(f"<li>{_e(line)}</li>" for line in diagnosis.game_state) + "</ul></section>"
        )
    if diagnosis.above_usual or diagnosis.below_usual:
        notes += (
            "<section><h3>Players against their usual</h3><ul class='fm-match-diagnosis-list players'>"
            + players(diagnosis.above_usual, "up") + players(diagnosis.below_usual, "down") + "</ul></section>"
        )
    if not has_stats and not notes:
        return ""
    if diagnosis.not_compared is None:
        description = f"Against your usual range for {_e(diagnosis.compared_with)}, from your other competitive matches."
        chip = f"<span class='fm-diagnostic-usable'>vs <b>{diagnosis.baseline_matches}</b> matches</span>"
    else:
        # Without stats the evidence panel below already says why.
        description = _e(diagnosis.not_compared) if has_stats else ""
        chip = ""
    return (
        "<section class='fm-workspace-panel fm-match-panel fm-match-diagnosis'>"
        "<div class='fm-panel-heading'><div><h2>Diagnosis</h2>"
        + (f"<p>{description}</p>" if description else "") + f"</div>{chip}</div>"
        + (f"<p class='fm-match-diagnosis-headline'>{_e(diagnosis.headline)}</p>" if diagnosis.headline else "")
        + rows
        + (f"<div class='fm-match-diagnosis-notes'>{notes}</div>" if notes else "")
        + "</section>"
    )
