"""The Matches page's "Results against chances": the season view of each match page's "Result vs chances".

Rendering only: every figure, average and running total comes from
`analytics.season_chances` through `reporting.build_match_diagnostics`. The
charts are drawn here as SVG; `frontend/scripts/trend-chart.js` only moves a
crosshair and shows a match's figures, already written out below, on hover.
"""

from __future__ import annotations

import html
import json
import math
from typing import Sequence
from urllib.parse import quote

from fm_analytics.analytics.match_diagnostics import MatchDiagnostics
from fm_analytics.analytics.season_chances import ROLLING, ChanceWindow, MatchChances, SeasonChances

WIDTH, HEIGHT = 1000, 230
LEFT, RIGHT, TOP, BOTTOM = 44, 72, 14, 30
X_LABELS = 8


def _e(value: object) -> str:
    return html.escape(str(value))


def _standing_tag(standing: str, *, conceding: bool) -> str:
    if standing == "usual":
        return "<span class='fm-chances-standing usual'>about usual</span>"
    good = (standing == "below") == conceding
    words = "more than luck explains" if standing == "above" else "fewer than luck explains"
    return f"<span class='fm-chances-standing {'above' if good else 'below'}'>{words}</span>"


def _windows_table(windows: Sequence[ChanceWindow]) -> str:
    rows = "".join(
        f"<tr><th scope='row'>{_e(window.label)}</th><td>{window.matches}</td>"
        f"<td><b>{window.points}</b> <span class='muted'>({window.expected_points:.1f})</span></td>"
        f"<td><b>{window.goals_for}</b> <span class='muted'>({window.worth_for:.1f})</span> "
        + _standing_tag(window.scoring, conceding=False) + "</td>"
        f"<td><b>{window.goals_against}</b> <span class='muted'>({window.worth_against:.1f})</span> "
        + _standing_tag(window.conceding, conceding=True) + "</td></tr>"
        for window in windows
    )
    return (
        "<div class='table-scroll fm-chances-table'><table data-fm-plain><thead><tr><th></th><th>Matches</th>"
        "<th>Points <span class='muted'>(usual)</span></th><th>Scored <span class='muted'>(chances worth)</span></th>"
        "<th>Conceded <span class='muted'>(chances worth)</span></th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _x(index: int, count: int) -> float:
    return LEFT + (index + 0.5) * (WIDTH - LEFT - RIGHT) / count


def _scale(low: float, high: float):
    def y(value: float) -> float:
        return TOP + (high - value) / (high - low) * (HEIGHT - TOP - BOTTOM)
    return y


def _path(points: Sequence[tuple[float, float]]) -> str:
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)


def _frame(matches: Sequence[MatchChances], ticks: Sequence[tuple[float, str]], y) -> tuple[str, str]:
    """(Gridlines with their values, the months along the bottom and the crosshair; a hit column per match,
    drawn last so it is on top.)"""
    count = len(matches)
    grid = "".join(
        f"<line class='fm-trend-grid' x1='{LEFT}' x2='{WIDTH - RIGHT}' y1='{y(value):.1f}' y2='{y(value):.1f}'/>"
        f"<text class='fm-trend-tick' x='{LEFT - 6}' y='{y(value) + 3.5:.1f}' text-anchor='end'>{_e(label)}</text>"
        for value, label in ticks
    )
    step = max(1, math.ceil(count / X_LABELS))
    months = "".join(
        f"<text class='fm-trend-tick' x='{_x(index, count):.1f}' y='{HEIGHT - 8}' text-anchor='middle'>"
        f"{matches[index].date:%b} ’{matches[index].date:%y}</text>"
        for index in range(0, count, step)
    )
    width = (WIDTH - LEFT - RIGHT) / count
    hits = "".join(
        f"<a href='/matches/{quote(match.key, safe='')}' tabindex='-1'>"
        f"<rect class='fm-trend-hit' data-i='{index}' data-x='{_x(index, count):.1f}' "
        f"x='{LEFT + index * width:.1f}' y='{TOP}' width='{width:.2f}' height='{HEIGHT - TOP - BOTTOM}'/></a>"
        for index, match in enumerate(matches)
    )
    cross = f"<line class='fm-trend-cross' x1='0' x2='0' y1='{TOP}' y2='{HEIGHT - BOTTOM}'/>"
    return grid + months + cross, hits


def _end_label(x: float, y: float, text: str) -> str:
    return f"<text class='fm-trend-end' x='{x + 8:.1f}' y='{y + 4.5:.1f}'>{_e(text)}</text>"


def _chances_chart(matches: Sequence[MatchChances]) -> str:
    """Each side's chances, averaged over the last ROLLING matches."""
    count = len(matches)
    top = max(2.0, math.ceil(1.15 * max(
        max(match.rolling_for or 0, match.rolling_against or 0) for match in matches
    ) * 2) / 2)
    y = _scale(0.0, top)
    ticks = [(value / 2, f"{value / 2:.1f}") for value in range(0, int(top * 2) + 1)]
    frame, hits = _frame(matches, ticks, y)
    lines = ends = ""
    last_y = []
    for css, attribute, who in (("ours", "rolling_for", "You"), ("theirs", "rolling_against", "Them")):
        points = [
            (_x(index, count), y(getattr(match, attribute)))
            for index, match in enumerate(matches) if getattr(match, attribute) is not None
        ]
        if not points:
            continue
        lines += f"<path class='fm-trend-line {css}' d='{_path(points)}'/>"
        last_y.append((points[-1], f"{who} {getattr(matches[-1], attribute):.1f}"))
    # End labels only when they sit apart; when the lines meet, the legend and the hover carry them.
    if len(last_y) == 2 and abs(last_y[0][0][1] - last_y[1][0][1]) >= 14:
        ends = "".join(_end_label(x, value_y, text) for (x, value_y), text in last_y)
    return (
        f"<svg class='fm-trend-svg' viewBox='0 0 {WIDTH} {HEIGHT}' role='img' "
        f"aria-label='Each side’s chances, averaged over the last {ROLLING} matches; every match is in the table below.'>"
        + frame + lines + ends + hits + "</svg>"
    )


def _luck_chart(matches: Sequence[MatchChances]) -> str:
    """Points less what the chances usually bring, as a running total."""
    count = len(matches)
    reach = max(2, math.ceil(max(abs(match.points_above_usual) for match in matches)))
    step = 1 if reach <= 4 else 2 if reach <= 8 else 5
    reach = math.ceil(reach / step) * step
    y = _scale(-reach, reach)
    ticks = [(value, f"{value:+d}" if value else "0") for value in range(-reach, reach + 1, step)]
    frame, hits = _frame(matches, ticks, y)
    points = [(_x(index, count), y(match.points_above_usual)) for index, match in enumerate(matches)]
    zero = f"<line class='fm-trend-zero' x1='{LEFT}' x2='{WIDTH - RIGHT}' y1='{y(0):.1f}' y2='{y(0):.1f}'/>"
    end = _end_label(*points[-1], f"{matches[-1].points_above_usual:+.1f}")
    return (
        f"<svg class='fm-trend-svg' viewBox='0 0 {WIDTH} {HEIGHT}' role='img' "
        "aria-label='Points less what your chances usually bring, as a running total; every match is in the table below.'>"
        + frame + zero + f"<path class='fm-trend-line ours' d='{_path(points)}'/>" + end + hits + "</svg>"
    )


def _hover_rows(matches: Sequence[MatchChances]) -> str:
    """Each match's figures, written out for the hover; nothing is worked out in the browser."""
    rows = [
        {
            "match": f"{match.date:%d %b %Y} · {match.opponent} ({match.venue[0]}) · {match.result} "
                     f"{match.goals_for}–{match.goals_against}",
            "worth": f"{match.worth_for:.1f}–{match.worth_against:.1f}",
            "ours": "" if match.rolling_for is None else f"{match.rolling_for:.2f}",
            "theirs": "" if match.rolling_against is None else f"{match.rolling_against:.2f}",
            "points": f"{match.points} (usually {match.expected_points:.1f})",
            "running": f"{match.points_above_usual:+.1f}",
        }
        for match in matches
    ]
    # `</` cannot appear inside the script element, whatever an opponent is called.
    return json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")


def _match_table(matches: Sequence[MatchChances]) -> str:
    rows = "".join(
        f"<tr><td data-sort='{index}'><a href='/matches/{quote(match.key, safe='')}'>{match.date:%d %b %Y}</a></td>"
        f"<td>{_e(match.opponent)}</td><td>{_e(match.venue)}</td>"
        f"<td>{match.result} {match.goals_for}–{match.goals_against}</td>"
        f"<td>{match.worth_for:.1f}–{match.worth_against:.1f}</td>"
        f"<td>{match.points} <span class='muted'>({match.expected_points:.1f})</span></td>"
        f"<td data-sort='{match.points_above_usual:.2f}'>{match.points_above_usual:+.1f}</td></tr>"
        for index, match in enumerate(matches)
    )
    return (
        "<details class='fm-chances-method fm-trend-table'><summary>Every match</summary>"
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Date</th><th>Opponent</th><th>Venue</th>"
        "<th>Score <span class='muted'>(goals from shots)</span></th><th>Chances worth</th>"
        "<th>Points <span class='muted'>(usual)</span></th><th>Running total</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
    )


def _summary(chances: SeasonChances) -> str:
    season = chances.window("season")
    words = {"above": "more than luck alone usually explains", "below": "fewer than luck alone usually explains"}
    if season.scoring == season.conceding == "usual":
        verdict = "Both are within what luck alone usually leaves."
    else:
        verdict = " ".join(
            f"{what.capitalize()} {words[standing]}." for what, standing in (
                ("you scored", season.scoring), ("you conceded", season.conceding),
            ) if standing != "usual"
        )
    return (
        f"<p class='fm-chances-summary'>Over {season.matches} matches you took <b>{season.points}</b> points, where "
        f"chances like yours usually bring <b>{season.expected_points:.0f}</b>. You scored {season.goals_for} from "
        f"chances worth {season.worth_for:.1f} and conceded {season.goals_against} from chances worth "
        f"{season.worth_against:.1f}. {verdict}</p>"
    )


def season_chances_section(diagnostics: MatchDiagnostics) -> str:
    """The panel's contents: what the chances were worth against the results, window by window and over time."""
    chances = diagnostics.chances
    if chances is None:
        reason = next((item.reason for item in diagnostics.unavailable if item.key == "results_vs_chances"), None)
        return f"<p class='fm-diagnostic-empty'>Not yet: {_e(reason)}</p>" if reason else ""
    matches = chances.matches
    rates = chances.rates
    legend = (
        "<div class='fm-trend-legend'><span><i class='ours'></i>You</span><span><i class='theirs'></i>Them</span></div>"
    )
    return (
        _summary(chances)
        + _windows_table(chances.windows)
        + "<div class='fm-trend' data-fm-trend>"
        f"<script type='application/json' class='fm-trend-data'>{_hover_rows(matches)}</script>"
        f"<figure><figcaption><b>Chances each way</b><span>Average of the last {ROLLING} matches, in goals</span>"
        f"</figcaption>{legend}<div class='fm-trend-scroll'>{_chances_chart(matches)}</div></figure>"
        "<figure><figcaption><b>Points against what your chances usually bring</b><span>Running total: above "
        "zero, more points so far than chances like yours usually bring; below, fewer</span></figcaption>"
        f"<div class='fm-trend-scroll'>{_luck_chart(matches)}</div></figure></div>"
        + _match_table(matches)
        + "<p class='fm-chances-caption'>Each shot is worth how often shots of its kind were scored in these "
        f"{rates.matches} matches, both sides counted: {rates.value('clear_cut'):.0%} of clear-cut chances and "
        f"{rates.value('other'):.0%} of other shots; a penalty is worth {rates.value('penalty'):g}. Goals are goals "
        "from shots, own goals aside. Click a match on a chart to open it."
        + (f" {chances.left_out} match(es) without every shot recorded are left out." if chances.left_out else "")
        + "</p>"
    )
