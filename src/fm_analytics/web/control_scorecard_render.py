"""HTML for the Matches page's "Control against each third" panel.

Rendering only: every figure comes from `reporting.build_control_scorecard`
(`analytics/control_scorecard.py`), never from here.
"""

from __future__ import annotations

from fm_analytics.analytics.control_scorecard import KINDS, MEASURES, ControlRow, ControlScorecard
from fm_analytics.web.match_render import _e

_MARGINS = {"corner_margin", "sot_margin", "ccc_margin"}


def _cell(row: ControlRow, key: str, percent: bool) -> str:
    value = row.values[key]
    if value is None:
        return "<td class='muted'>–</td>"
    text = f"{value:.1f}%" if percent else f"{value:+.1f}" if key in _MARGINS else f"{value:.1f}"
    return f"<td data-sort='{value:.3f}'>{text}</td>"


def _row(row: ControlRow, row_class: str) -> str:
    few = "" if row.enough else " <span class='muted'>(few)</span>"
    return (
        f"<tr class='{row_class}{'' if row.enough else ' thin'}'><td>{_e(row.label)}{few}</td>"
        f"<td>{row.matches}</td>"
        + "".join(_cell(row, measure.key, measure.percent) for measure in MEASURES)
        + "</tr>"
    )


def control_scorecard_section(scorecard: ControlScorecard) -> str:
    if not any(band.ours.matches or band.benchmark.matches for band in scorecard.bands):
        return ""
    kind_headers = "".join(
        f"<th colspan='{sum(1 for m in MEASURES if m.kind == kind)}'>{_e(label)}</th>" for kind, label in KINDS
    )
    lower = " <span class='muted'>(lower is better)</span>"
    measure_headers = "".join(
        f"<th>{_e(measure.label)}{'' if measure.higher_is_better else lower}</th>" for measure in MEASURES
    )
    body = []
    for band in scorecard.bands:
        body.append(f"<tr class='fm-control-third'><th colspan='{len(MEASURES) + 2}'>{_e(band.label)}</th></tr>")
        body.append(_row(band.ours, "fm-control-ours"))
        body.extend(_row(row, "fm-control-plan") for row in band.plans)
        if scorecard.has_benchmark:
            body.append(_row(band.benchmark, "fm-control-benchmark"))
    benchmark_note = (
        "<b>League top third</b> is every archived league match between two other clubs in which one was in "
        "the top third of the table at kickoff, from that club's side"
        + (f", in season {scorecard.season} only" if scorecard.season is not None else "")
        + f" ({scorecard.benchmark_matches} club-sides): what a promotion-chasing side in this league gets against "
          "opponents of the same strength. It is league matches only; your rows follow the filters above."
        if scorecard.has_benchmark
        else "There is no league benchmark yet: no other clubs' matches are recorded. Reading matches from FM "
             "records them."
    )
    return (
        "<section class='fm-workspace-panel fm-match-panel fm-match-control' id='control'>"
        "<div class='fm-panel-heading'><div><h2>Control against each third</h2>"
        "<p>How far your matches show each kind of control, against opponents in each third of the table at "
        "kickoff: possession (how much of the ball, how well it was kept), territory (crosses, corners, and how "
        "well they kept the ball under your pressure) and chances (the on-target and clear-cut-chance margins). "
        "Split by the game plan of the tactic you played, a tactic with two plans counting in both, and set "
        "beside the league's top third.</p></div></div>"
        "<div class='table-scroll'><table data-fm-plain class='fm-control-table'><thead>"
        f"<tr><th rowspan='2'>Matches</th><th rowspan='2'>Played</th>{kind_headers}</tr>"
        f"<tr>{measure_headers}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        f"<p class='muted fm-match-note'>Margins are you minus them. {benchmark_note} Rows marked few have fewer "
        "than five matches with full stats.</p></section>"
    )
