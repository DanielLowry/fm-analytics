"""The Conceded page and a match page's conceded panel, from `reporting.build_conceded_review`.

Presentation only. The share bars are the Opponent page's (`opponent-report.css`):
one hue for the goals, each bar with its count and share printed beside it.
"""

from __future__ import annotations

import html
from typing import Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.conceded import (
    FLANK_WORDS,
    POST_GUESS,
    ZONE_GUESS,
    ConcededMoment,
    ConcededReview,
    Tally,
)
from fm_analytics.analytics.match_analysis import MatchReview, season_label
from fm_analytics.analytics.match_timeline import CORNER_GUESS
from fm_analytics.web.match_render import match_url, review_filters

SIDES = {"left": "our left", "right": "our right", "centre": "central"}
POSTS = {"near": "Near post", "back": "Back post", "middle": "In the middle"}


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _day(value) -> str:
    return f"{value.day} {value:%b %Y}"


def _bars(rows: Sequence[Tally], total: int, *, chances: bool = False) -> str:
    if not rows:
        return "<p class='muted'>None.</p>"
    items = []
    for row in rows:
        share = row.goals / total if total else 0.0
        extra = f" · {row.chances} chance{'s' if row.chances != 1 else ''}" if chances else ""
        title = f"{row.goals} of {total} goals" + (f", and {row.chances} more clear-cut chances" if chances else "")
        items.append(
            f"<li class='fm-opp-bar-row{' guess' if 'guess' in row.label else ''}'>"
            f"<span class='fm-opp-bar-label'>{_e(row.label)}</span>"
            f"<span class='fm-opp-track' title='{_e(title)}'><span class='fm-opp-bar' style='width:{100 * share:.0f}%'></span></span>"
            f"<span class='fm-opp-bar-value'><b>{row.goals}</b> <small>{share:.0%}{extra}</small></span></li>"
        )
    return "<ul class='fm-opp-bars'>" + "".join(items) + "</ul>"


def _card(title: str, note: str, body: str) -> str:
    return f"<article class='fm-conceded-card'><h3>{title}</h3><p class='muted'>{note}</p>{body}</article>"


def _what(moment: ConcededMoment) -> str:
    if not moment.goal:
        return f"<span class='fm-conceded-kind chance'>Chance</span> {_e(moment.outcome)}"
    if moment.kind in ("penalty", "own_goal"):
        return f"<span class='fm-conceded-kind goal'>{_e(moment.outcome)}</span>"
    words = _e(moment.how or "Not described by FM")
    if moment.how_key == "possibly_corner":
        words += f" <span class='fm-conceded-guess' title='{_e(CORNER_GUESS)}'>possibly a corner (guess)</span>"
    return f"<span class='fm-conceded-kind goal'>{_e(moment.outcome)}</span> {words}"


def _who(name: str | None, detail: str) -> str:
    if not name:
        return "<span class='muted'>–</span>"
    return f"{_e(name)}<small>{_e(detail)}</small>"


def _ours(moment: ConcededMoment) -> str:
    if moment.given_away_by:
        return f"Given away by <b>{_e(moment.given_away_by)}</b> <small>your record</small>"
    parts = []
    if moment.facing_delivery:
        parts.append("Facing the delivery: " + ", ".join(_e(player.label) for player in moment.facing_delivery))
    if moment.in_zone:
        parts.append("Where it was met: " + ", ".join(_e(player.label) for player in moment.in_zone))
    if not parts:
        return "<span class='muted'>–</span>"
    return "<span class='fm-conceded-guess-cell'>" + "<br>".join(parts) + "</span>"


def _rows(moments: Sequence[ConcededMoment], *, with_match: bool) -> str:
    head = (("<th>Match</th>" if with_match else "")
            + "<th>Min</th><th>Score before</th><th>What</th><th>Taken by</th><th>Delivered by</th>"
            "<th>Post <small>guess</small></th><th>Ours around <small>guess</small></th>")
    rows = []
    for moment in moments:
        match = (
            f"<td data-sort='{moment.date.toordinal()}'><a href='{_e(match_url(moment.match_key))}'>{_e(_day(moment.date))}</a>"
            f"<small>{_e(moment.opponent)} ({moment.venue})</small></td>" if with_match else ""
        )
        delivery = FLANK_WORDS.get(moment.delivery_flank or "", "")
        rows.append(
            f"<tr class='{'goal' if moment.goal else 'chance'}'>{match}"
            f"<td data-sort='{moment.minute * 100 + moment.added_time}'>{_e(moment.clock)}′</td>"
            f"<td>{moment.score_before[0]}–{moment.score_before[1]}</td>"
            f"<td class='fm-conceded-what'>{_what(moment)}</td>"
            f"<td class='fm-conceded-who'>{_who(moment.taker, ' · '.join(filter(None, (moment.taker_position, SIDES.get(moment.taker_side)))))}</td>"
            + (f"<td class='fm-conceded-who'>{_who(moment.delivered_by, ' · '.join(filter(None, (moment.delivery_position, delivery))))}</td>"
               if moment.goal else "<td class='fm-conceded-who'><span class='muted'>Not in FM's record</span></td>")
            + f"<td>{_e(POSTS.get(moment.post or '', '–'))}</td>"
            f"<td class='fm-conceded-ours'>{_ours(moment)}</td></tr>"
        )
    plain = "" if with_match else " data-fm-plain"
    return (f"<div class='table-scroll fm-conceded-table'><table{plain}><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _guesses() -> str:
    return (
        "<details class='fm-chances-method fm-opp-method'><summary>What is FM's record and what is a guess</summary>"
        "<p>FM's own record: each goal's scorer, its assist, how it was scored (a header or a shot, from a cross, "
        "a penalty, a direct free kick, and from where), each clear-cut chance and who had it, where his shot "
        "went, and where every player played, with substitutions and sendings-off.</p>"
        f"<p><b>Near or back post</b> is a guess. {_e(POST_GUESS)}</p>"
        f"<p><b>Ours around</b> is a guess. {_e(ZONE_GUESS)}</p>"
        f"<p><b>Possibly a corner</b> is the match page's guess: {_e(CORNER_GUESS)} No post or zone is guessed for "
        "a set piece, where it is met depends on the routine.</p></details>"
    )


def _zone_table(review: ConcededReview) -> str:
    if not review.zone:
        return "<p class='muted'>No goal or chance with a zone to guess.</p>"
    rows = "".join(
        f"<tr><td>{_e(record.name)}</td><td>{_e(record.positions)}</td><td><b>{record.goals}</b></td>"
        f"<td>{record.chances}</td><td>{record.minutes:,}</td>"
        f"<td data-sort='{record.per90 or 0}'>{'–' if record.per90 is None else f'{record.per90:.2f}'}</td></tr>"
        for record in review.zone
    )
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Player</th><th>Where he was</th>"
        "<th>Goals</th><th>Chances</th><th>His minutes</th><th>Goals per 90</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _tiles(review: ConcededReview) -> str:
    matches = review.matches or 1
    how = {row.key: row.goals for row in review.how}
    crosses = how.get("header_from_cross", 0) + how.get("foot_from_cross", 0)
    set_pieces = how.get("penalty", 0) + how.get("direct_free_kick", 0) + how.get("possibly_corner", 0)
    flanks = {row.key: row.goals for row in review.flanks}
    posts = {row.key: row.goals for row in review.posts}
    chances = review.chances + review.goals_from_chances

    def tile(label: str, value: str, note: str) -> str:
        return f"<article class='fm-decision-stat'><span>{_e(label)}</span><b>{value}</b><small>{note}</small></article>"

    return (
        "<section class='fm-decision-grid fm-match-summary fm-opp-tiles fm-conceded-tiles' aria-label='Conceded summary'>"
        + tile("Goals conceded", str(review.goals), f"{review.goals / matches:.2f} a match in {review.matches}")
        + tile("From crosses", str(crosses), f"{how.get('header_from_cross', 0)} headed; corners aside")
        + tile("Set pieces", str(set_pieces),
               f"{how.get('penalty', 0)} pens, {how.get('direct_free_kick', 0)} free kicks, "
               f"{how.get('possibly_corner', 0)} possible corners")
        + tile("Delivered", f"{flanks.get('left', 0)} <i>our left</i> · {flanks.get('right', 0)} <i>our right</i>",
               f"{flanks.get('middle', 0)} from a central position")
        + tile("Back post (a guess)", str(posts.get("back", 0)),
               f"of {review.cross_goals_from_a_flank} crosses from a flank; {posts.get('near', 0)} near post")
        + tile("Clear-cut chances", str(chances), f"{review.goals_from_chances} of them scored")
        + "</section>"
    )


def conceded_body(
    review: MatchReview, conceded: ConcededReview, catalogue: FootballCatalogue, pinned: Sequence[str],
    *, copy_control: str = "",
) -> str:
    """The whole Conceded page for the matches the filters select."""
    season = f"{season_label(review.filters.season)} season" if review.filters.season is not None else "All seasons"
    filters = review_filters(review, catalogue, pinned, action="/conceded", grouping=False)
    intro = (
        f"Every goal and clear-cut chance against us in <strong>{conceded.matches}</strong> matches with full stats"
        + (f" ({conceded.without_stats} more have the result only, and are left out)" if conceded.without_stats else "")
        + ": who delivered it and from where, who finished it, near or back post, and which of our players were "
        "around. The filters are the Matches page's."
    )
    hero = (
        "<section class='fm-match-review-hero fm-opp-hero fm-conceded-hero'>"
        f"<div class='fm-opp-hero-top'><div><span class='eyebrow'>Goals and chances conceded · {_e(season)}</span>"
        f"<h2>How we concede</h2><p>{intro}</p></div></div>"
        f"<div class='fm-opp-hero-foot'>{filters}{copy_control}</div></section>"
    )
    if not conceded.matches:
        return hero + "<section class='fm-workspace-panel'><p class='muted'>No match with full stats is selected.</p></section>"
    goals = conceded.goals
    cards = (
        _card("How", "FM's description of each goal.", _bars(conceded.how, goals))
        + _card("Delivered", "The assist, by the flank its player played, from our side.", _bars(conceded.flanks, goals))
        + _card("Delivered by", "Their assist-maker's position.", _bars(conceded.delivered_by, goals))
        + _card("Near or back post <small>guess</small>",
                f"Goals from crosses from a flank ({conceded.cross_goals_from_a_flank}), corners aside.",
                _bars(conceded.posts, conceded.cross_goals_from_a_flank))
        + _card("Scored by, or had the chance", "Their player's position: goals, then other clear-cut chances.",
                _bars(conceded.takers, goals, chances=True))
        + _card("Where from", "Where FM says each goal was scored from.", _bars(conceded.areas, goals))
        + _card("When", "Goals, then other clear-cut chances, by period.", _bars(conceded.periods, goals, chances=True))
    )
    return (
        "<nav class='fm-section-nav' aria-label='Conceded sections'><a href='#conceded-breakdown'>Breakdown</a>"
        "<a href='#conceded-ours'>Our players around</a><a href='#conceded-every'>Every goal and chance</a>"
        "<a href='/matches'>Matches</a></nav>"
        + hero + _tiles(conceded)
        + "<section class='fm-workspace-panel fm-match-panel' id='conceded-breakdown'><div class='fm-panel-heading'><div>"
        "<h2>Where they come from</h2><p>Goals conceded, broken down; each bar is a share of the goals.</p></div></div>"
        f"<div class='fm-conceded-cards'>{cards}</div>{_guesses()}</section>"
        + "<section class='fm-workspace-panel fm-match-panel' id='conceded-ours'><div class='fm-panel-heading'><div>"
        "<h2>Our players around <small class='fm-conceded-guess'>a guess</small></h2>"
        "<p>How often each of ours was in the positions facing the delivery or covering where a goal or chance was "
        "met. FM does not record where players were: this is from positions, at that minute.</p></div></div>"
        + _zone_table(conceded) + "</section>"
        + "<section class='fm-workspace-panel fm-match-panel' id='conceded-every'><div class='fm-panel-heading'><div>"
        "<h2>Every goal and chance</h2><p>Latest first. Open a match for its timeline and every shot.</p>"
        "</div></div>" + _rows(conceded.moments, with_match=True) + "</section>"
    )


def conceded_match_panel(conceded: ConcededReview) -> str:
    """A match page's goals and chances conceded, or nothing when there were none."""
    if not conceded.moments:
        return ""
    moments = tuple(reversed(conceded.moments))  # in match order
    return (
        "<section class='fm-workspace-panel fm-match-panel fm-conceded-match' id='conceded'>"
        "<div class='fm-panel-heading'><div><h2>Goals and chances conceded</h2>"
        "<p>Who delivered each, who finished it, near or back post and who of ours was around. Post and who was "
        "around are guesses from positions; <a href='/conceded'>every match's</a> are on the Conceded page.</p>"
        "</div></div>" + _rows(moments, with_match=False) + _guesses() + "</section>"
    )
