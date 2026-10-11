"""The Matches page's "Season trends": leads not won, chances allowed while ahead, the last 15 minutes,
and before and after your changes.

Rendering only: every figure and running total comes from `analytics.season_trends` through
`reporting.build_season_trends`. The charts are drawn as the "Results against chances" ones are, with
their frame (`season_chances_render`) and hover (`frontend/scripts/trend-chart.js`), which only shows
a match's figures, already written out below.
"""

from __future__ import annotations

import json
import math
from typing import Sequence
from urllib.parse import quote

from fm_analytics.analytics.match_breakdowns import Tally
from fm_analytics.analytics.season_trends import CHANGE_WINDOW, ChangeGroup, MatchTrend, SeasonTrends, TrendWindow
from fm_analytics.web.season_chances_render import (
    HEIGHT,
    LEFT,
    RIGHT,
    WIDTH,
    _e,
    _end_label,
    _frame,
    _path,
    _scale,
    _x,
)


def _per_90(tally: Tally, name: str, *, ours: bool = False) -> float | None:
    return tally.per_90(getattr(tally, name))[0 if ours else 1]


def _rate(value: float | None, places: int = 2) -> str:
    return "–" if value is None else f"{value:.{places}f}"


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else f"−{-value}" if value < 0 else "0"


def _match_link(match_key: str, text: str) -> str:
    return f"<a href='/matches/{quote(match_key, safe='')}'>{_e(text)}</a>"


def _tiles(trends: SeasonTrends) -> str:
    season = trends.window("season")
    ahead, level = season.by_state["ahead"], season.by_state["level"]
    usual = f" · sides that led won {season.usual_hold:.0%}" if season.usual_hold is not None else ""
    tiles = [
        ("Dropped from winning positions", f"{season.dropped} <i>points</i>",
         f"Led in {season.led}: won {season.led_won}, drew {season.led_drawn}, lost {season.led_lost}{usual}"),
        ("Their chances while you led", f"{_rate(_per_90(ahead, 'clear_cut_chances'))} <i>clear-cut a 90</i>",
         f"{_rate(_per_90(ahead, 'shots'), 1)} shots a 90 · level: {_rate(_per_90(level, 'clear_cut_chances'))} "
         f"and {_rate(_per_90(level, 'shots'), 1)}" if ahead.minutes >= 1 else "You have not led in these matches"),
        ("The last 15 minutes", f"{season.late_goals[0]}–{season.late_goals[1]} <i>goals</i>",
         f"Points won +{season.late_won}, lost −{season.late_lost} · clear-cut chances "
         f"{season.late.clear_cut_chances[0]}–{season.late.clear_cut_chances[1]}"),
    ]
    subs = trends.group("substitutions")
    if subs is not None:
        tiles.append((
            "Their chances after your substitutions",
            f"{_rate(_per_90(subs.before, 'clear_cut_chances'))} → {_rate(_per_90(subs.after, 'clear_cut_chances'))}",
            f"Clear-cut a 90, {CHANGE_WINDOW} minutes before and after · {subs.changes} changes",
        ))
    return (
        "<section class='fm-decision-grid fm-match-summary fm-opp-tiles fm-trends-tiles' aria-label='Season trends'>"
        + "".join(f"<article class='fm-decision-stat'><span>{label}</span><b>{value}</b><small>{_e(note)}</small></article>"
                  for label, value, note in tiles)
        + "</section>"
    )


def _versus(pair: Sequence[int]) -> str:
    return f"{pair[0]}–{pair[1]}"


def _windows_table(windows: Sequence[TrendWindow]) -> str:
    rows = []
    for window in windows:
        ahead, level = window.by_state["ahead"], window.by_state["level"]
        led = (f"led {window.led}: W{window.led_won} D{window.led_drawn} L{window.led_lost}" if window.led
               else "never led")
        rows.append(
            f"<tr><th scope='row'>{_e(window.label)}</th><td>{window.matches}</td>"
            f"<td><b>{window.dropped}</b> <span class='muted'>{led}</span></td>"
            f"<td><b>{_rate(_per_90(ahead, 'clear_cut_chances'))}</b> "
            f"<span class='muted'>(level {_rate(_per_90(level, 'clear_cut_chances'))})</span></td>"
            f"<td><b>{_rate(_per_90(ahead, 'shots'), 1)}</b> "
            f"<span class='muted'>(level {_rate(_per_90(level, 'shots'), 1)})</span></td>"
            f"<td>{_versus(window.late_goals)}</td><td>{_versus(window.late.clear_cut_chances)}</td>"
            f"<td><b>+{window.late_won}</b> / <b>−{window.late_lost}</b></td></tr>"
        )
    return (
        "<div class='table-scroll fm-chances-table fm-trends-table'><table data-fm-plain><thead>"
        "<tr><th rowspan='2'></th><th rowspan='2'>Matches</th><th rowspan='2'>Points dropped from winning positions</th>"
        "<th colspan='2'>Their chances while you led, per 90</th><th colspan='3'>After 75′</th></tr>"
        "<tr><th>Clear-cut</th><th>Shots</th><th>Goals</th><th>Clear-cut chances</th><th>Points won / lost</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _axis(values: Sequence[int], *, signed: bool) -> tuple[int, int, list[tuple[float, str]]]:
    """(Bottom, top, gridlines): whole points, at most about six steps, around zero when `signed`."""
    top = max(2 if signed else 3, *(abs(value) for value in values))
    step = next(size for size in (1, 2, 5, 10, 20, 50, 100) if (2 * top if signed else top) / size <= 6)
    top = math.ceil(top / step) * step
    low = -top if signed else 0
    return low, top, [(value, _signed(value) if signed else str(value)) for value in range(low, top + 1, step)]


def _running_chart(matches: Sequence[MatchTrend], attribute: str, label: str, *, signed: bool) -> str:
    count = len(matches)
    values = [getattr(match, attribute) for match in matches]
    low, high, ticks = _axis(values, signed=signed)
    y = _scale(low, high)
    frame, hits = _frame(matches, ticks, y)
    zero = (f"<line class='fm-trend-zero' x1='{LEFT}' x2='{WIDTH - RIGHT}' y1='{y(0):.1f}' y2='{y(0):.1f}'/>"
            if signed else "")
    points = [(_x(index, count), y(value)) for index, value in enumerate(values)]
    end = _end_label(*points[-1], _signed(values[-1]) if signed else str(values[-1]))
    return (
        f"<svg class='fm-trend-svg' viewBox='0 0 {WIDTH} {HEIGHT}' role='img' aria-label='{_e(label)}; every match "
        "is in the table below.'>" + frame + zero + f"<path class='fm-trend-line ours' d='{_path(points)}'/>"
        + end + hits + "</svg>"
    )


def _score_line(match: MatchTrend) -> str:
    return " · ".join(f"{ours}–{theirs} <span class='muted'>{_e(clock)}′</span>" for clock, ours, theirs in match.goals)


def _hover_rows(matches: Sequence[MatchTrend]) -> str:
    """Each match's figures, written out for the hover; nothing is worked out in the browser."""
    rows = [
        {
            "match": f"{match.date:%d %b %Y} · {match.opponent} ({match.venue[0]}) · {match.result} "
                     f"{match.goals_for}–{match.goals_against}",
            "lines": [
                [str(match.dropped), "dropped from a winning position"],
                [_signed(match.late_points), f"points after 75′ (from {match.score_after_75[0]}–{match.score_after_75[1]})"],
                [str(match.dropped_so_far), "dropped so far"],
                [_signed(match.late_so_far), "after 75′ so far"],
            ],
        }
        for match in matches
    ]
    # `</` cannot appear inside the script element, whatever an opponent is called.
    return json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")


def _charts(trends: SeasonTrends) -> str:
    timed = [match for match in trends.matches if match.timed]
    if len(timed) < 2:
        return ""
    return (
        "<div class='fm-trend' data-fm-trend>"
        f"<script type='application/json' class='fm-trend-data'>{_hover_rows(timed)}</script>"
        "<figure><figcaption><b>Points dropped from winning positions</b><span>Running total: a draw after leading "
        "drops two, a defeat three. The steeper it climbs, the more leads are slipping</span></figcaption>"
        "<div class='fm-trend-scroll'>"
        + _running_chart(timed, "dropped_so_far", "Points dropped from winning positions, as a running total",
                         signed=False)
        + "</div></figure><figure><figcaption><b>Points won and lost after 75′</b><span>Running total of each result "
        "against the score after 75 minutes: rising, the last 15 minutes win you points; falling, they cost you"
        "</span></figcaption><div class='fm-trend-scroll'>"
        + _running_chart(timed, "late_so_far", "Points won and lost after 75 minutes, as a running total", signed=True)
        + "</div></figure></div>"
    )


def _dropped_table(trends: SeasonTrends) -> str:
    dropped = trends.dropped_matches
    if not dropped:
        return ""
    rows = "".join(
        f"<tr><td data-sort='{match.date.isoformat()}'>{_match_link(match.key, f'{match.date:%d %b %Y}')}</td>"
        f"<td>{_e(match.opponent)}</td><td>{_e(match.venue)}</td>"
        f"<td>{match.result} {match.goals_for}–{match.goals_against}</td>"
        f"<td class='fm-trends-goals'>{_score_line(match)}</td><td>{match.dropped}</td></tr>"
        for match in reversed(dropped)
    )
    return (
        f"<details class='fm-chances-method fm-trend-table'><summary>The {len(dropped)} match"
        f"{'es' if len(dropped) != 1 else ''} you led and did not win</summary>"
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Date</th><th>Opponent</th><th>Venue</th>"
        "<th>Result</th><th>How the score went</th><th>Points dropped</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
    )


def _before_after(before: Tally, after: Tally, name: str, *, ours: bool) -> str:
    was, now = _per_90(before, name, ours=ours), _per_90(after, name, ours=ours)
    arrow = "" if was is None or now is None or abs(now - was) < 0.005 else (" ▲" if now > was else " ▼")
    places = 1 if name == "shots" else 2
    return (f"<td data-sort='{now if now is not None else -1:.2f}'><span class='muted'>{_rate(was, places)}</span> → "
            f"<b>{_rate(now, places)}</b><span class='fm-trends-arrow' aria-hidden='true'>{arrow}</span></td>")


def _group_row(group: ChangeGroup) -> str:
    theirs = group.key == "theirs"
    return (
        f"<tr class='{'fm-trends-baseline' if theirs else ''}'><th scope='row'>{_e(group.label)}</th>"
        f"<td>{group.changes}</td>"
        + _before_after(group.before, group.after, "shots", ours=True)
        + _before_after(group.before, group.after, "shots", ours=False)
        + _before_after(group.before, group.after, "clear_cut_chances", ours=True)
        + _before_after(group.before, group.after, "clear_cut_chances", ours=False)
        + f"<td><span class='muted'>{_versus(group.before.goals)}</span> → <b>{_versus(group.after.goals)}</b></td>"
        f"<td class='muted'>{group.before.minutes:.0f} / {group.after.minutes:.0f}</td></tr>"
    )


def _changes(trends: SeasonTrends) -> str:
    if not trends.change_groups:
        return ""
    ours = [change for change in trends.changes if change.ours]
    rows = "".join(
        f"<tr><td data-sort='{change.date.isoformat()}-{change.minute:03d}'>"
        f"{_match_link(change.match_key, f'{change.date:%d %b %Y}')}</td><td>{_e(change.opponent)}</td>"
        f"<td data-sort='{change.minute}'>{change.minute}′</td><td>{_versus(change.score)}</td>"
        f"<td>{_e(change.what)}</td>"
        f"<td>{_versus(change.before.shots)} · {_versus(change.before.clear_cut_chances)} · "
        f"{_versus(change.before.goals)} <span class='muted'>({change.before.minutes:.0f}′)</span></td>"
        f"<td>{_versus(change.after.shots)} · {_versus(change.after.clear_cut_chances)} · "
        f"{_versus(change.after.goals)} <span class='muted'>({change.after.minutes:.0f}′)</span></td></tr>"
        for change in reversed(ours)
    )
    every = (
        f"<details class='fm-chances-method fm-trend-table'><summary>Every change you made ({len(ours)})</summary>"
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Date</th><th>Opponent</th><th>Minute</th>"
        "<th>Score</th><th>Change</th><th>Before <span class='muted'>(shots · clear-cut · goals)</span></th>"
        "<th>After</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
    ) if ours else ""
    return (
        "<h3 class='fm-trends-heading'>Before and after your changes</h3>"
        "<div class='table-scroll fm-chances-table fm-trends-table fm-trends-changes'><table data-fm-plain><thead>"
        "<tr><th rowspan='2'></th><th rowspan='2'>Changes</th><th colspan='2'>Shots per 90</th>"
        "<th colspan='2'>Clear-cut chances per 90</th><th rowspan='2'>Goals</th>"
        "<th rowspan='2'>Minutes <span class='muted'>(before / after)</span></th></tr>"
        "<tr><th>Yours</th><th>Theirs</th><th>Yours</th><th>Theirs</th></tr></thead>"
        f"<tbody>{''.join(_group_row(group) for group in trends.change_groups)}</tbody></table></div>"
        f"<p class='fm-chances-caption'>Each change against the {CHANGE_WINDOW} minutes before it and the "
        f"{CHANGE_WINDOW} after, stopping at the change before or after it; substitutions in the same minute are one "
        "change, and “made while ahead” is the score at that minute. Later minutes bring more chances anyway, and a "
        "lead changes how both sides play, so their substitutions are alongside: a shift that follows theirs too is "
        "the clock or the score rather than your change.</p>"
        + every
    )


def _caption(trends: SeasonTrends) -> str:
    season = trends.window("season")
    parts = [f"Results figures count the {season.timed} matches with every goal timed"
             + (", extra-time matches aside" if season.timed < season.matches else "") + "."]
    left_out = ", ".join(f"{count} with {why}" for why, count in trends.left_out.items())
    parts.append(f"Chance figures are the By the score and By period panels' own: {season.split_matches} matches"
                 + (f", leaving out {left_out}" if left_out else "") + ".")
    parts.append("“After 75′” is from FM's 76th minute, added time included. Click a match on a chart to open it.")
    return f"<p class='fm-chances-caption'>{' '.join(parts)}</p>"


def season_trends_section(trends: SeasonTrends) -> str:
    """The panel's contents: the season's figures window by window, the running totals, and your changes."""
    if not trends.matches:
        return "<p class='fm-diagnostic-empty'>No matches in this selection.</p>"
    return (
        _tiles(trends) + _windows_table(trends.windows) + _charts(trends) + _dropped_table(trends)
        + _caption(trends) + _changes(trends)
    )
