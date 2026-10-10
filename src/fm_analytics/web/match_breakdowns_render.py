"""HTML for the Matches page's breakdowns: by the score, by period, how the goals came,
by the formation faced, and each player's season. Rendering only: every number comes
from `reporting.build_match_breakdowns` and `build_match_review`, never from here."""

from __future__ import annotations

from typing import Mapping

from fm_analytics.analytics.match_analysis import MatchReview
from fm_analytics.analytics.match_breakdowns import PERIODS, STATES, Breakdowns, PlayerEvents, Tally
from fm_analytics.web.match_render import _e, versus

STATE_LABELS = {"level": "Level", "ahead": "Ahead", "behind": "Behind"}


def _panel(title: str, description: str, content: str, panel_class: str) -> str:
    return (
        f"<section class='fm-workspace-panel fm-match-panel {panel_class}'>"
        f"<div class='fm-panel-heading'><div><h2>{title}</h2><p>{description}</p></div></div>"
        + content + "</section>"
    )


def _pair(pair: tuple[float | None, float | None] | list[int]) -> str:
    ours, theirs = pair
    return versus(ours, theirs)


def _left_out(breakdowns: Breakdowns) -> str:
    if not breakdowns.left_out:
        return ""
    reasons = ", ".join(f"{count} with {reason}" for reason, count in breakdowns.left_out.items())
    return f" Left out: {reasons}."


_NO_SPLIT = ("<p class='muted'>This needs matches with every shot and goal time, which FM's match archive "
             "gives once matches are read from FM; none in this selection has them yet.</p>")


def score_table(breakdowns: Breakdowns) -> str:
    if not breakdowns.split_matches:
        return _NO_SPLIT
    rows = []
    for state in STATES:
        tally = breakdowns.by_state[state]
        if tally.minutes < 1:
            continue
        rows.append(
            f"<tr><td>{STATE_LABELS[state]}</td><td data-sort='{tally.minutes:.0f}'>{tally.minutes:.0f}</td>"
            f"<td>{_pair(tally.per_90(tally.shots))}</td><td>{_pair(tally.per_90(tally.on_goal))}</td>"
            f"<td>{_pair(tally.per_90(tally.clear_cut_chances))}</td><td>{_pair(tally.goals)}</td>"
            f"<td>{_pair(tally.per_90(tally.goals))}</td></tr>"
        )
    return (
        "<div class='table-scroll'><table data-fm-plain><thead><tr><th>Score</th><th>Minutes</th><th>Shots per 90</th>"
        "<th>On goal per 90</th><th>Clear-cut chances per 90</th><th>Goals</th><th>Goals per 90</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f"<p class='muted fm-match-note'>You, then them. From {breakdowns.split_matches} matches with every "
        f"shot and goal time.{_left_out(breakdowns)} Minutes around half-time are approximate: FM's clock "
        "runs on through first-half added time.</p>"
    )


def period_table(breakdowns: Breakdowns) -> str:
    if not breakdowns.split_matches:
        return _NO_SPLIT
    rows = "".join(
        f"<tr><td>{label}</td><td>{_pair(tally.shots)}</td><td>{_pair(tally.on_goal)}</td>"
        f"<td>{_pair(tally.clear_cut_chances)}</td><td>{_pair(tally.goals)}</td></tr>"
        for label, tally in ((label, breakdowns.by_period[label]) for label, _start, _end in PERIODS)
    )
    return (
        "<div class='table-scroll'><table data-fm-plain><thead><tr><th>Minutes</th><th>Shots</th><th>On goal</th>"
        f"<th>Clear-cut chances</th><th>Goals</th></tr></thead><tbody>{rows}</tbody></table></div>"
        f"<p class='muted fm-match-note'>You, then them, totals over the same {breakdowns.split_matches} matches.</p>"
    )


def goal_types(breakdowns: Breakdowns) -> str:
    def card(title: str, found: Mapping) -> str:
        sections = []
        for key, heading in (("how", "How"), ("strike", "Struck"), ("area", "From")):
            counts = found.get(key)
            if counts:
                items = "".join(f"<li>{_e(label[:1].upper() + label[1:])} <strong>{count}</strong></li>"
                                for label, count in counts.most_common())
                sections.append(f"<h4>{heading}</h4><ol>{items}</ol>")
        return f"<div class='match-card'><h3>{title}</h3>{''.join(sections) or '<p class=muted>None</p>'}</div>"

    return (
        "<div class='match-cards'>" + card("Scored", breakdowns.goals_for) + card("Conceded", breakdowns.goals_against)
        + "</div><p class='muted fm-match-note'>From FM's description of each goal. “Other open play” is "
        "a goal from inside the area that FM doesn't mark as a cross, a free kick or a penalty; FM's record "
        "doesn't say whether a cross came from a corner.</p>"
    )


def formation_table(breakdowns: Breakdowns) -> str:
    if not breakdowns.formations:
        return "<p class='muted'>FM's name for the opposition's formation is not known for these matches.</p>"
    rows = []
    for record in breakdowns.formations:
        each = lambda pair: (pair[0] / record.with_stats, pair[1] / record.with_stats) if record.with_stats else (None, None)  # noqa: E731
        points = (3 * record.won + record.drawn) / record.played
        rows.append(
            f"<tr><td>{_e(record.formation)}</td><td>{record.played}</td>"
            f"<td>W{record.won} D{record.drawn} L{record.lost}</td><td data-sort='{points:.2f}'>{points:.2f}</td>"
            f"<td>{_pair((record.goals_for, record.goals_against))}</td>"
            f"<td>{_pair(each(record.shots))}</td><td>{_pair(each(record.clear_cut_chances))}</td></tr>"
        )
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>They played</th><th>Matches</th>"
        "<th>Record</th><th>Points per game</th><th>Goals</th><th>Shots per match</th>"
        f"<th>Clear-cut chances per match</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        "<p class='muted fm-match-note'>The opposition's formation as FM names it, at kick-off.</p>"
    )


def _per_90(value: float, minutes: int) -> str:
    return f" <span class='muted'>({90 * value / minutes:.2f})</span>" if minutes else ""


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "–"


def players_table(review: MatchReview, breakdowns: Breakdowns) -> str:
    if not review.players:
        return "<p class='muted'>No match with full stats in this selection yet.</p>"
    rows = []
    for season in review.players:
        stat = season.stat
        extra = breakdowns.players.get(season.player_id or season.name) or PlayerEvents(season.player_id or season.name)
        minutes = season.minutes
        goal_notes = [f"{count} {label}" for count, label in (
            (extra.headers, "headed"), (extra.volleys, "volleyed"), (extra.penalties, "pen."),
            (extra.from_outside_the_area, "from distance")) if count]
        rating = f"{season.average_rating:.2f}" if season.average_rating is not None else "–"
        rows.append(
            f"<tr><td>{_e(season.name)}</td>"
            f"<td data-sort='{season.appearances}'>{season.appearances} <span class='muted'>({season.starts})</span></td>"
            f"<td>{minutes}</td><td>{rating}</td>"
            f"<td data-sort='{stat('goals')}'>{stat('goals')}"
            + (f" <span class='muted'>({', '.join(goal_notes)})</span>" if goal_notes else "") + "</td>"
            f"<td>{stat('assists')}</td>"
            f"<td data-sort='{stat('shots')}'>{stat('shots')}{_per_90(stat('shots'), minutes)}</td>"
            f"<td data-sort='{extra.shots_on_goal}'>{extra.shots_on_goal} · {extra.shots_wide} · {extra.shots_over}</td>"
            f"<td data-sort='{extra.clear_cut_chances}'>{extra.clear_cut_chances}"
            + (f" <span class='muted'>({extra.clear_cut_chances_scored} scored)</span>" if extra.clear_cut_chances else "")
            + "</td>"
            f"<td data-sort='{stat('key_passes')}'>{stat('key_passes')}{_per_90(stat('key_passes'), minutes)}</td>"
            f"<td data-sort='{stat('chances_created')}'>{stat('chances_created')}{_per_90(stat('chances_created'), minutes)}</td>"
            f"<td>{stat('dribbles')}</td>"
            f"<td>{_percent(stat('passes_completed'), stat('passes_attempted'))}</td>"
            f"<td>{stat('tackles_won')} <span class='muted'>({_percent(stat('tackles_won'), stat('tackles_attempted'))})</span></td>"
            f"<td>{stat('headers_won')} <span class='muted'>({_percent(stat('headers_won'), stat('headers_attempted'))})</span></td>"
            f"<td>{stat('fouls')}</td><td data-sort='{extra.yellow_cards + 3 * extra.sent_off}'>"
            f"{extra.yellow_cards}{f' / {extra.sent_off} off' if extra.sent_off else ''}</td>"
            f"<td>{f'{season.distance_m / 1000 * 90 / minutes:.1f}' if minutes else '–'}</td></tr>"
        )
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Player</th><th>Apps (starts)</th>"
        "<th>Minutes</th><th>Average rating</th><th>Goals</th><th>Assists</th><th>Shots (per 90)</th>"
        "<th>Shots on goal · wide · over</th><th>Clear-cut chances</th><th>Key passes (per 90)</th>"
        "<th>Chances created (per 90)</th><th>Dribbles</th><th>Passes completed</th><th>Tackles won</th>"
        "<th>Headers won</th><th>Fouls</th><th>Booked</th><th>km per 90</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        "<p class='muted fm-match-note'>Your players in these matches, from FM's player stats, timeline and shots. "
        "“On goal” counts shots going in under the bar, saved or blocked as well as scored.</p>"
    )


def breakdown_panels(review: MatchReview, breakdowns: Breakdowns | None) -> str:
    """The Matches page's breakdown panels for the selected matches."""
    if breakdowns is None:
        return ""
    return (
        _panel("By the score", "Shots, chances and goals while level, ahead and behind: a side that leads usually "
               "faces more of the ball, so this keeps the score apart from how a tactic plays.",
               score_table(breakdowns), "fm-match-by-score")
        + _panel("By period", "The same in 15-minute periods.", period_table(breakdowns), "fm-match-by-period")
        + _panel("How the goals came", "Scored and conceded, by how, how they were struck and where from.",
                 goal_types(breakdowns), "fm-match-goal-types")
        + _panel("Against each formation", "Your results and chances against each formation the opposition used.",
                 formation_table(breakdowns), "fm-match-formations")
        + _panel("Your players", "Each player's season in these matches: what he made, where his shots went, "
                 "his clear-cut chances, and his bookings.", players_table(review, breakdowns), "fm-match-season-players")
    )
