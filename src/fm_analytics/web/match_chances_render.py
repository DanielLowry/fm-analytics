"""A match page's "Result vs chances": how well you played and whether the score was fair to it.

Rendering only: every figure and every judgement in it (the verdict, the
odds, the explanations, what to take from it) was made by
`analytics.match_chances`, which `reporting.build_match_diagnosis` runs.
"""

from __future__ import annotations

import html

from fm_analytics.analytics.chance_value import one_in
from fm_analytics.analytics.match_chances import FinishingRecord, ResultVsChances, SideChances, UsualWorth
from fm_analytics.analytics.single_match_diagnosis import OneMatchDiagnosis


def _e(value: object) -> str:
    return html.escape(str(value))


def _odds_bar(chances: ResultVsChances, result: str) -> str:
    """Win, draw and lose as one bar, with what happened marked."""
    segments = ""
    for key, label, share in (("W", "Win", chances.win), ("D", "Draw", chances.draw), ("L", "Lose", chances.loss)):
        actual = key == result
        segments += (
            f"<span class='fm-chances-odds-{key}{' actual' if actual else ''}' style='flex-grow:{max(share, 0.04):.3f}'"
            f" title='{label} {share:.0%}{' · what happened' if actual else ''}'>"
            f"<b>{share:.0%}</b><small>{label}{' ✓' if actual else ''}</small></span>"
        )
    words = f"win {chances.win:.0%}, draw {chances.draw:.0%}, lose {chances.loss:.0%}"
    return (
        f"<div class='fm-chances-odds' role='img' aria-label='Chances like these: {words}.'>{segments}</div>"
        "<p class='fm-chances-caption'>How often chances like these win, draw and lose. The tick is what happened.</p>"
    )


def _side_row(label: str, side: SideChances, css: str) -> str:
    penalties = f" <span class='muted'>({side.penalties} pen.)</span>" if side.penalties else ""
    own_goals = f" <span class='muted'>+{side.own_goals} o.g.</span>" if side.own_goals else ""
    return (
        f"<tr class='{css}'><th scope='row'>{_e(label)}</th><td>{side.shots}</td>"
        f"<td>{side.clear_cut}{penalties}</td><td><b>{side.worth:.1f}</b></td>"
        f"<td>{side.on_goal} <span class='muted'>({side.usual_on_goal:.1f})</span></td>"
        f"<td>{side.scored_on_goal} <span class='muted'>({side.usual_scored_on_goal:.1f})</span></td>"
        f"<td><b>{side.goals}</b>{own_goals}</td></tr>"
    )


def _breakdown(chances: ResultVsChances, opponent: str) -> str:
    return (
        "<div class='table-scroll fm-chances-table'><table data-fm-plain><thead><tr><th></th><th>Shots</th>"
        "<th>Clear-cut</th><th>Chances worth</th><th title='Penalties aside; usual for chances like these in brackets'>"
        "On goal <span class='muted'>(usual)</span></th>"
        "<th title='Of those on goal; usual from that many shots on goal in brackets'>Went in <span class='muted'>"
        "(usual)</span></th><th>Goals</th></tr></thead><tbody>"
        + _side_row("You", chances.ours, "ours") + _side_row(opponent, chances.theirs, "theirs")
        + "</tbody></table></div>"
    )


def _usual_cell(check: UsualWorth, scale: float, who: str) -> str:
    """Chances worth against the usual range, drawn like the Diagnosis's own usual ranges."""
    def at(value: float) -> str:
        return f"{min(max(100 * value / scale, 0.0), 100.0):.1f}%"

    tone = "usual" if check.favourable is None else "good" if check.favourable else "bad"
    tag = (
        f"<span class='fm-usual-tag {tone}'>{'▲ Above' if check.standing == 'above' else '▼ Below'}</span>"
        if check.standing != "usual" else ""
    )
    return (
        f"<div class='fm-usual-cell {tone}' role='cell' data-side='{_e(who)}' "
        f"title='Chances worth {check.actual:.1f} · usual {check.low:.1f}–{check.high:.1f}'>"
        f"<b>{check.actual:.1f}</b><span class='fm-usual-meter' aria-hidden='true'>"
        f"<i style='left:{at(check.low)};width:calc({at(check.high)} - {at(check.low)})'></i>"
        f"<em style='left:{at(check.actual)}'></em></span>"
        f"<small>usual {check.low:.1f}–{check.high:.1f}</small>{tag}</div>"
    )


def _usual(chances: ResultVsChances, compared_with: str, opponent: str) -> str:
    if not chances.usual:
        return ""
    ours, theirs = chances.usual
    scale = 1.15 * max(1.0, *(max(check.actual, check.high) for check in chances.usual))
    return (
        f"<section class='fm-chances-usual'><h3>Against your usual for {_e(compared_with)}</h3>"
        "<div class='fm-usual-grid' role='table' aria-label='Chances worth against your usual range'>"
        "<div class='fm-usual-row fm-usual-head' role='row'><span role='columnheader'></span>"
        f"<span role='columnheader'>You</span><span role='columnheader'>{_e(opponent)}</span></div>"
        "<div class='fm-usual-row' role='row'><span class='fm-usual-label' role='rowheader'>Chances worth</span>"
        + _usual_cell(ours, scale, "You") + _usual_cell(theirs, scale, opponent) + "</div></div></section>"
    )


def _standing(record: FinishingRecord) -> str:
    if record.standing == "usual":
        return "<span class='fm-chances-standing usual'>about usual</span>"
    words = "below their chances" if record.standing == "below" else "above their chances"
    return (
        f"<span class='fm-chances-standing {record.standing}' title='Luck alone leaves a gap this large "
        f"{_e(one_in(record.luck_odds))}'>{words}</span>"
    )


def _finishing(chances: ResultVsChances) -> str:
    team = chances.team_finishing
    items = [
        f"<li><b>The team</b> {team.goals} goals from chances worth {team.worth:.1f} "
        f"<span>{team.matches} matches · {team.clear_cut_scored} of {team.clear_cut} clear-cut chances</span> "
        + _standing(team) + "</li>"
    ]
    for record in chances.finishers:
        today = f"today {record.today_goals} from {record.today_worth:.1f}"
        if not record.shots:
            items.append(f"<li><b>{_e(record.name)}</b> {today} <span>no other shots recorded</span></li>")
            continue
        items.append(
            f"<li><b>{_e(record.name)}</b> {today}; before, {record.goals} from {record.worth:.1f} "
            f"<span>{record.matches} matches · {record.clear_cut_scored} of {record.clear_cut} clear-cut chances</span> "
            + _standing(record) + "</li>"
        )
    return (
        "<section><h3>Finishing over your other matches</h3>"
        f"<ul class='fm-chances-finishing'>{''.join(items)}</ul></section>"
    )


def _missed(chances: ResultVsChances) -> str:
    missed = chances.ours.missed_clear_cut
    if not missed:
        return ""
    items = "".join(
        f"<li><span class='fm-match-minute'>{_e(item.clock)}′</span> {_e(item.player or 'Unknown player')} "
        f"<span class='muted'>{_e(item.outcome)}</span></li>"
        for item in missed
    )
    return f"<section><h3>Clear-cut chances you missed</h3><ul class='fm-chances-missed'>{items}</ul></section>"


def match_chances_panel(diagnosis: OneMatchDiagnosis, opponent: str, result: str, *, has_stats: bool) -> str:
    """The panel, or a line saying why the match can't be judged; nothing for a match with no stats."""
    heading = (
        "<div class='fm-panel-heading'><div><h2>Result vs chances</h2>"
        "<p>How well you played, judged by the chances each side made, and whether the score was fair to them.</p>"
        "</div></div>"
    )
    chances = diagnosis.chances
    if chances is None:
        if not has_stats or diagnosis.chances_not_judged is None:
            return ""
        return (
            "<section class='fm-workspace-panel fm-match-panel fm-chances'>" + heading
            + f"<p class='muted'>{_e(diagnosis.chances_not_judged)}</p></section>"
        )
    explanations = "".join(f"<li>{_e(line)}</li>" for line in chances.explanations)
    notes = (
        (f"<section><h3>Why the score and the chances differ</h3>"
         f"<ul class='fm-match-diagnosis-list'>{explanations}</ul></section>" if explanations else "")
        + _missed(chances)
        + _usual(chances, diagnosis.compared_with, opponent)
        + _finishing(chances)
    )
    return (
        f"<section class='fm-workspace-panel fm-match-panel fm-chances tone-{chances.tone}'>" + heading
        + "<div class='fm-chances-top'><div class='fm-chances-verdict'>"
        f"<span class='fm-chances-badge tone-{chances.tone}'>{_e(chances.verdict)}</span>"
        f"<p class='fm-chances-summary'>{_e(chances.summary)}</p>"
        f"<p class='fm-chances-takeaway'>{_e(chances.takeaway)}</p></div>"
        "<dl class='fm-chances-scoreboard'>"
        f"<div><dt>Score</dt><dd>{chances.ours.score}–{chances.theirs.score}</dd></div>"
        f"<div><dt>Chances worth</dt><dd>{chances.ours.worth:.1f}–{chances.theirs.worth:.1f}</dd></div>"
        f"<div><dt>Points</dt><dd>{chances.points}<small>usually {chances.expected_points:.1f}</small></dd></div>"
        "</dl></div>"
        + _odds_bar(chances, result)
        + _breakdown(chances, opponent)
        + f"<div class='fm-match-diagnosis-notes'>{notes}</div>"
        + "<details class='fm-chances-method'><summary>How this is worked out</summary>"
        f"<p>{_e(chances.method)}</p></details>"
        + "</section>"
    )
