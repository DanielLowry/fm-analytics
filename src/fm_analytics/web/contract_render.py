"""HTML for the Contracts page and the squad player report's contract panel.

Presentation only: every verdict, band and number comes from
`reporting.build_contract_review`. Class names are written out in full (not
assembled) because the stylesheet build keeps only classes it finds in these
sources.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Sequence
from urllib.parse import quote

from fm_analytics.analytics.contract_planning import (
    ACTION_VERDICTS,
    RISK_LABELS,
    ContractAssessment,
    ContractReview,
    ContractRisk,
    FormBand,
    PositionLevel,
    Reason,
    VERDICT_ADVICE,
    VERDICT_LABELS,
    Verdict,
    ordinal_text,
)
from fm_analytics.web.ui import ordered_positions, position_key

VERDICT_CLASSES = {
    Verdict.SECURE_NOW: "fm-contract-v-secure",
    Verdict.RENEW_EARLY: "fm-contract-v-renew",
    Verdict.KEEP_IF_TERMS: "fm-contract-v-keep",
    Verdict.YOUR_CALL: "fm-contract-v-call",
    Verdict.REPLACE_FIRST: "fm-contract-v-replace",
    Verdict.LET_GO: "fm-contract-v-letgo",
    Verdict.LET_RUN_DOWN: "fm-contract-v-letgo",
    Verdict.REVIEW_LATER: "fm-contract-v-quiet",
    Verdict.SURPLUS: "fm-contract-v-letgo",
    Verdict.SETTLED: "fm-contract-v-quiet",
    Verdict.ON_LOAN: "fm-contract-v-quiet",
    Verdict.UNKNOWN: "fm-contract-v-quiet",
}

RISK_CLASSES = {
    ContractRisk.ANY_DAY: "fm-contract-risk-now",
    ContractRisk.ENDS_SOON: "fm-contract-risk-soon",
    ContractRisk.NEXT_YEAR: "fm-contract-risk-later",
    ContractRisk.SETTLED: "fm-contract-risk-settled",
    ContractRisk.ON_LOAN: "fm-contract-risk-settled",
    ContractRisk.UNKNOWN: "fm-contract-risk-unknown",
}

TONE_CLASSES = {
    "good": "fm-contract-chip-good",
    "neutral": "fm-contract-chip-neutral",
    "warn": "fm-contract-chip-warn",
    "bad": "fm-contract-chip-bad",
}

TILE_TEXT = {
    Verdict.SECURE_NOW: "Offer new contracts",
    Verdict.RENEW_EARLY: "Ending in 6–18 months",
    Verdict.KEEP_IF_TERMS: "Worth keeping, not at any price",
    Verdict.YOUR_CALL: "Give them minutes first",
    Verdict.REPLACE_FIRST: "Only cover somewhere",
    Verdict.LET_GO: "Let them leave",
}

CONTRACT_TYPES = {
    "full_time": "Full-time",
    "part_time": "Part-time",
    "amateur": "Amateur",
    "youth": "Youth",
    "non_contract": "Non-contract",
}

# Ratings are drawn on one fixed scale so a slope means the same on every row.
_SPARK_FLOOR, _SPARK_CEILING = 5.5, 8.0


def _esc(value: object) -> str:
    return html.escape(str(value))


def _day(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def _player_link(item: ContractAssessment) -> str:
    return f"<a href='/squad/player/{quote(item.player_id, safe='')}'>{_esc(item.player_name)}</a>"


def squad_status_label(status: str | None) -> str | None:
    if not status or status == "not_set":
        return None
    return status.replace("_", " ").capitalize()


def contract_summary(item: ContractAssessment) -> str:
    """The contract in words: what FM's contract screen would say."""
    if item.risk is ContractRisk.ON_LOAN:
        return f"On loan from {item.contracted_club}" if item.contracted_club else "On loan"
    if item.risk is ContractRisk.ANY_DAY:
        return "Non-contract"
    if item.end_date is None:
        kind = CONTRACT_TYPES.get(item.contract_type or "", "")
        return f"{kind} · no end date read".strip(" ·") if kind else "No contract read"
    months = item.months_left or 0
    remaining = (
        "ended" if months < 0
        else "under a month" if months == 0
        else f"{months} month{'s' if months != 1 else ''}"
    )
    return f"Ends {_day(item.end_date)} · {remaining}"


def risk_pill(item: ContractAssessment) -> str:
    return f"<span class='fm-contract-risk {RISK_CLASSES[item.risk]}'>{_esc(item.risk_label)}</span>"


def verdict_pill(verdict: Verdict) -> str:
    return f"<span class='fm-contract-verdict {VERDICT_CLASSES[verdict]}'>{_esc(VERDICT_LABELS[verdict])}</span>"


def reason_chips(reasons: Sequence[Reason]) -> str:
    return "<div class='fm-contract-chips'>" + "".join(
        f"<span class='fm-contract-chip {TONE_CLASSES[reason.tone]}'>{_esc(reason.label)}</span>"
        for reason in reasons
    ) + "</div>"


def sparkline(ratings: Sequence[float]) -> str:
    """Recent competitive ratings, oldest first, on the fixed 5.5–8.0 scale."""
    if len(ratings) < 2:
        return ""
    width, height, pad = 84, 22, 2
    step = (width - 2 * pad) / (len(ratings) - 1)

    def y(value: float) -> float:
        clamped = min(_SPARK_CEILING, max(_SPARK_FLOOR, value))
        share = (clamped - _SPARK_FLOOR) / (_SPARK_CEILING - _SPARK_FLOOR)
        return round(height - pad - share * (height - 2 * pad), 2)

    points = " ".join(f"{round(pad + index * step, 2)},{y(value)}" for index, value in enumerate(ratings))
    last_x, last_y = round(pad + (len(ratings) - 1) * step, 2), y(ratings[-1])
    seven = y(7.0)
    label = "Last {} competitive ratings: {}".format(len(ratings), ", ".join(f"{value:.2f}" for value in ratings))
    return (
        f"<svg class='fm-contract-spark' viewBox='0 0 {width} {height}' width='{width}' height='{height}' "
        f"role='img' aria-label='{_esc(label)}'><title>{_esc(label)}</title>"
        f"<line class='fm-contract-spark-ref' x1='0' x2='{width}' y1='{seven}' y2='{seven}'/>"
        f"<polyline points='{points}'/><circle cx='{last_x}' cy='{last_y}' r='2'/></svg>"
    )


def _form_reading(item: ContractAssessment, review: ContractReview) -> str:
    if item.average_rating is None:
        return "<b>—</b><small>no competitive minutes</small>"
    detail = []
    if item.form is FormBand.NO_EVIDENCE:
        detail.append(f"too few minutes ({item.minutes:,})")
    elif item.form_rank is not None:
        detail.append(f"{ordinal_text(item.form_rank)} of {review.rated_players}")
    detail.append(f"{item.starts} start{'s' if item.starts != 1 else ''}")
    if item.form is not FormBand.NO_EVIDENCE:
        detail.append(f"{item.minutes:,} min")
    return (
        f"<b>{item.average_rating:.2f}</b>{sparkline(item.recent_ratings)}"
        f"<small>{_esc(' · '.join(detail))}</small>"
    )


_LEVEL_TEXT = {
    PositionLevel.STARTER: "starter level",
    PositionLevel.SQUAD: "squad level",
    PositionLevel.BELOW: "below squad level",
}


def _position_reading(item: ContractAssessment) -> str:
    if item.position_score is None:
        return "<b>—</b><small>no eligible role</small>"
    role = f"{item.position_role} at {item.position}" if item.position else item.position_role
    return (
        f"<b>{item.position_score:.1f}</b>"
        f"<small>{_esc(role or '')} · {_esc(_LEVEL_TEXT[item.level])}</small>"
    )


def _xi_reading(item: ContractAssessment) -> str:
    if item.xi_slot is None:
        if item.only_cover_for:
            return "<b>Bench</b><small>only cover at " + _esc(", ".join(item.only_cover_for)) + "</small>"
        return "<b>Not in XI</b><small>not a recommended starter</small>"
    cover = (
        "no available cover"
        if item.cover_name is None
        else f"cover {item.cover_name} {item.cover_score:.1f} vs his {item.starter_score:.1f}"
    )
    return f"<b>{_esc(item.xi_slot)}</b><small>{_esc(cover)}</small>"


def _readings(item: ContractAssessment, review: ContractReview) -> str:
    rows = (
        ("Form", _form_reading(item, review)),
        ("Position score", _position_reading(item)),
        ("Recommended XI", _xi_reading(item)),
        ("Contract", f"<b>{_esc(contract_summary(item))}</b>"
                     + (f"<small>{_esc(CONTRACT_TYPES.get(item.contract_type, ''))}</small>"
                        if item.contract_type in CONTRACT_TYPES and item.risk is not ContractRisk.ANY_DAY else "")),
    )
    return "<dl class='fm-contract-readings'>" + "".join(
        f"<div><dt>{label}</dt><dd>{value}</dd></div>" for label, value in rows
    ) + "</dl>"


def _who(item: ContractAssessment) -> str:
    facts = [", ".join(ordered_positions(item.positions)) or "?"]
    if item.age is not None:
        facts.append(f"age {item.age}")
    status = squad_status_label(item.squad_status)
    if status:
        facts.append(f"status: {status.lower()}")
    if not item.first_team:
        facts.append("other club squad")
    return "<span>" + _esc(" · ".join(facts)) + "</span>"


def action_card(rank: int, item: ContractAssessment, review: ContractReview) -> str:
    return (
        f"<article class='fm-contract-card {VERDICT_CLASSES[item.verdict]}'>"
        "<header class='fm-contract-card-head'>"
        f"<span class='fm-contract-rank' aria-label='Priority {rank}'>{rank}</span>"
        f"<div class='fm-contract-who'>{_player_link(item)}{_who(item)}</div>"
        f"{risk_pill(item)}"
        f"<div class='fm-contract-keep' title='Keep value: orders players within a verdict'>"
        f"<b>{item.keep_value}</b><small>keep</small></div>"
        "</header>"
        + _readings(item, review)
        + reason_chips(item.reasons)
        + "</article>"
    )


def _hero(review: ContractReview) -> str:
    xi, at_risk = review.xi, review.xi_at_risk
    if not xi:
        headline = "No recommended XI to measure contract risk against"
    elif at_risk:
        headline = f"{len(at_risk)} of your {len(xi)} recommended starters could leave within six months"
    else:
        headline = "Every recommended starter is under contract beyond the next six months"
    names = ", ".join(item.player_name for item in at_risk)
    form_rule = (
        f"Strong form is a rating of {review.strong_from:.2f} or more and poor form below "
        f"{review.poor_below:.2f}, among the {review.rated_players} first-team players with "
        f"{review.policy.min_minutes:,}+ competitive minutes in the last year."
        if review.strong_from is not None and review.poor_below is not None
        else "Too few players have enough competitive minutes to split form into thirds."
    )
    note = (
        f"<p class='fm-contract-note'>{_esc(review.history_note)}</p>" if review.history_note else ""
    )
    return (
        "<section class='fm-decision-hero fm-contract-hero'>"
        f"<span class='eyebrow'>Contract planning · {_esc(_day(review.game_date))}</span>"
        f"<h2>{_esc(headline)}</h2>"
        + (f"<p class='fm-contract-names'>{_esc(names)}</p>" if names else "")
        + f"<p>Measured against the recommended XI for <b>{_esc(review.tactic_name)}</b>. {_esc(form_rule)}</p>"
        + note
        + "</section>"
    )


def _tiles(review: ContractReview) -> str:
    tiles = []
    for verdict in (*ACTION_VERDICTS, Verdict.LET_GO):
        members = review.with_verdict(verdict)
        detail = TILE_TEXT[verdict]
        if verdict is Verdict.SECURE_NOW:
            any_day = sum(1 for item in members if item.risk is ContractRisk.ANY_DAY)
            if any_day:
                detail = f"{any_day} can leave any day"
        elif verdict is Verdict.LET_GO and members:
            poor = sum(1 for item in members if item.form is FormBand.POOR)
            unused = sum(1 for item in members if item.form is FormBand.NO_EVIDENCE)
            detail = f"{poor} played poorly · {unused} barely used"
        tiles.append(
            f"<a class='fm-decision-stat fm-contract-tile {VERDICT_CLASSES[verdict]}' href='#verdict-{verdict.value}'>"
            f"<span>{_esc(VERDICT_LABELS[verdict])}</span><b>{len(members)}</b><small>{_esc(detail)}</small></a>"
        )
    return "<nav class='fm-contract-tiles' aria-label='Verdicts'>" + "".join(tiles) + "</nav>"


def _action_list(review: ContractReview) -> str:
    groups, rank = [], 0
    for verdict in ACTION_VERDICTS:
        members = review.with_verdict(verdict)
        if not members:
            continue
        cards = []
        for item in members:
            rank += 1
            cards.append(action_card(rank, item, review))
        groups.append(
            f"<section class='fm-contract-group' id='verdict-{verdict.value}'>"
            f"<h3>{verdict_pill(verdict)}<span class='fm-contract-group-count'>{len(members)}</span></h3>"
            f"<p class='fm-contract-advice'>{_esc(VERDICT_ADVICE[verdict])}</p>"
            "<div class='fm-contract-cards'>" + "".join(cards) + "</div></section>"
        )
    body = "".join(groups) or "<p class='muted'>Nothing needs a contract decision right now.</p>"
    return (
        "<section class='fm-workspace-panel fm-contract-actions'><div class='fm-panel-heading'><div>"
        "<h2>Who to act on, in order</h2>"
        "<p>Ranked by verdict, then players who can leave any day, then keep value. Keep value only orders "
        "players within a verdict: 40% form, 30% position score, 30% how far the XI drops without him.</p>"
        f"</div><span class='fm-panel-count'>{rank} players</span></div>" + body + "</section>"
    )


def _let_go_table(items: Sequence[ContractAssessment]) -> str:
    rows = []
    for item in items:
        positions = ordered_positions(item.positions)
        rows.append(
            "<tr>"
            f"<td>{_player_link(item)}</td>"
            f"<td>{item.age if item.age is not None else '?'}</td>"
            f"<td data-sort='{position_key(positions[0])[0] if positions else 99}'>{_esc(', '.join(positions))}</td>"
            f"<td>{_esc(contract_summary(item))}</td>"
            f"<td data-sort='{item.average_rating or 0:.2f}'>"
            + (f"{item.average_rating:.2f} ({item.minutes:,} min)" if item.average_rating is not None else "—")
            + "</td>"
            f"<td data-sort='{item.position_score or 0:.4f}'>"
            + (f"{item.position_score:.1f}" if item.position_score is not None else "—")
            + f"</td><td>{reason_chips(item.reasons)}</td></tr>"
        )
    # "Pos", not "Positions": the shared table script re-sorts any roster with a
    # Positions column by position, which would undo the priority order.
    return (
        "<div class='fm-table-card'><table><tr><th>Player</th><th>Age</th><th>Pos</th>"
        "<th>Contract</th><th>Form</th><th>Position score</th><th>Reasons</th></tr>"
        + "".join(rows) + "</table></div>"
    )


def _let_go(review: ContractReview) -> str:
    """Played poorly (or below squad level) first; the barely used, folded away, after."""
    members = review.with_verdict(Verdict.LET_GO)
    if not members:
        return ""
    decided = [item for item in members if item.form is not FormBand.NO_EVIDENCE]
    unused = [item for item in members if item.form is FormBand.NO_EVIDENCE]
    main = (
        _let_go_table(decided) if decided
        else "<p class='muted'>Nobody with real match evidence is a let-go call.</p>"
    )
    folded = (
        "<details class='fm-contract-unused'>"
        f"<summary>{len(unused)} barely used: under {review.policy.min_minutes:,} competitive minutes, "
        "below starter level on attributes and not in the XI</summary>"
        + _let_go_table(unused) + "</details>"
        if unused else ""
    )
    return (
        f"<section class='fm-workspace-panel' id='verdict-{Verdict.LET_GO.value}'><div class='fm-panel-heading'><div>"
        f"<h2>{verdict_pill(Verdict.LET_GO)}</h2>"
        f"<p>{_esc(VERDICT_ADVICE[Verdict.LET_GO])} Players with real match evidence are listed; "
        "the barely used are folded away below so they do not bury those decisions.</p>"
        f"</div><span class='fm-panel-count'>{len(members)} players</span></div>"
        + main + folded + "</section>"
    )


_TIMELINE_ROWS = (
    (ContractRisk.ANY_DAY, "Non-contract: another club can offer terms at any time"),
    (ContractRisk.ENDS_SOON, "Can agree a pre-contract elsewhere; leaves for nothing at expiry"),
    (ContractRisk.NEXT_YEAR, "Renew on your terms before the final six months"),
    (ContractRisk.SETTLED, "More than 18 months left"),
    (ContractRisk.ON_LOAN, "Contracted to another club"),
    (ContractRisk.UNKNOWN, "No usable contract read"),
)


def _timeline(review: ContractReview) -> str:
    rows = []
    for risk, note in _TIMELINE_ROWS:
        members = [item for item in review.assessments if item.risk is risk]
        if not members:
            continue
        members.sort(key=lambda item: (item.end_date or date.max, not item.in_xi, item.player_name.casefold()))
        chips = "".join(
            f"<a class='fm-contract-dot {VERDICT_CLASSES[item.verdict]}' "
            f"href='/squad/player/{quote(item.player_id, safe='')}' "
            f"title='{_esc(item.verdict_label)} · {_esc(contract_summary(item))}'>"
            + ("<b>XI</b>" if item.in_xi else "")
            + f"{_esc(item.player_name)}</a>"
            for item in members
        )
        rows.append(
            f"<div class='fm-contract-lane'><div class='fm-contract-lane-label'>"
            f"<b>{_esc(RISK_LABELS[risk])}</b><span>{len(members)} · {_esc(note)}</span></div>"
            f"<div class='fm-contract-lane-players'>{chips}</div></div>"
        )
    legend = "".join(
        f"<span class='fm-contract-dot {VERDICT_CLASSES[verdict]}'>{_esc(VERDICT_LABELS[verdict])}</span>"
        for verdict in (Verdict.SECURE_NOW, Verdict.RENEW_EARLY, Verdict.KEEP_IF_TERMS,
                        Verdict.YOUR_CALL, Verdict.REPLACE_FIRST, Verdict.LET_GO, Verdict.SETTLED)
    )
    return (
        "<section class='fm-workspace-panel fm-contract-timeline'><div class='fm-panel-heading'><div>"
        "<h2>When players could leave</h2>"
        "<p>Every player by contract risk, coloured by verdict. <b>XI</b> marks a recommended starter.</p>"
        "</div></div>" + "".join(rows)
        + f"<div class='fm-contract-legend' aria-label='Verdict colours'>{legend}</div></section>"
    )


def _all_players(review: ContractReview, show_squad: bool) -> str:
    rows = []
    for item in review.assessments:
        positions = ordered_positions(item.positions)
        rows.append(
            "<tr>"
            f"<td>{_player_link(item)}</td>"
            + (f"<td>{'First team' if item.first_team else 'Other squad'}</td>" if show_squad else "")
            + f"<td data-sort='{position_key(positions[0])[0] if positions else 99}'>{_esc(', '.join(positions))}</td>"
            f"<td>{item.age if item.age is not None else '?'}</td>"
            f"<td>{risk_pill(item)}</td>"
            f"<td data-sort='{item.end_date.isoformat() if item.end_date else ''}'>{_esc(contract_summary(item))}</td>"
            f"<td data-sort='{item.average_rating or 0:.2f}'>"
            + (f"{item.average_rating:.2f}" if item.average_rating is not None else "—")
            + f"</td><td data-sort='{item.minutes}'>{item.minutes:,}</td>"
            f"<td data-sort='{item.position_score or 0:.4f}'>"
            + (f"{item.position_score:.1f}" if item.position_score is not None else "—")
            + "</td>"
            f"<td>{_esc(item.xi_slot or '—')}</td>"
            f"<td>{_esc(squad_status_label(item.squad_status) or '—')}</td>"
            f"<td data-sort='{list(Verdict).index(item.verdict)}'>{verdict_pill(item.verdict)}</td>"
            f"<td data-sort='{item.keep_value}'>{item.keep_value}</td>"
            "</tr>"
        )
    return (
        "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
        "<h2>All players</h2><p>Click a heading to sort; the default order is the priority order above.</p>"
        f"</div><span class='fm-panel-count'>{len(review.assessments)} players</span></div>"
        "<div class='fm-table-card'><table class='sortable'><tr><th>Player</th>"
        + ("<th>Squad</th>" if show_squad else "")
        + "<th>Pos</th><th>Age</th><th>Risk</th><th>Contract</th><th>Rating</th><th>Minutes</th>"
        "<th>Position score</th><th>XI slot</th><th>Squad status</th><th>Verdict</th><th>Keep</th></tr>"
        + "".join(rows) + "</table></div></section>"
    )


def _method(review: ContractReview) -> str:
    policy = review.policy
    return (
        "<details class='fm-workspace-panel fm-contract-method'><summary>How verdicts are decided</summary>"
        "<ul>"
        f"<li><b>Contract risk</b>: non-contract players can leave any day; a contract ending within "
        f"{policy.ends_soon_months} months is urgent; {policy.ends_soon_months}–{policy.renewal_window_months} "
        "months is time to renew early.</li>"
        f"<li><b>Form</b>: average rating in competitive matches in the last year, in thirds of the first team's "
        f"players with {policy.min_minutes:,}+ minutes. Fewer minutes is no match evidence.</li>"
        f"<li><b>Position score</b>: the Squad page's in-position score for his best role. Starter level is at or "
        f"above the recommended XI's median starter ({review.reference_score:.1f}); squad level is at least "
        f"{review.squad_level_score:.1f}, the Depth page's starter bar.</li>"
        "<li><b>Hard to replace</b>: his first cover in the recommended XI drops off sharply, or there is none: "
        "the Depth page's own weak-cover rule.</li>"
        "<li><b>Core</b> needs strong form with at least a squad-level position score, or a starter-level score "
        "with solid form, or being hard to replace. <b>Marginal</b> is poor form, a below-squad-level score or no "
        "match evidence, and not in the XI. A player with no match evidence but a starter-level score or an XI "
        "place is <b>unproven</b>.</li>"
        "<li><b>Verdict</b>: core and urgent is <i>Secure now</i>; core with 6–18 months left is <i>Renew early</i>; "
        "useful and urgent is <i>Keep if the terms are right</i>; unproven and urgent is <i>Your call</i>; marginal "
        "and urgent is <i>Let go</i>, unless he is the only cover somewhere, which makes it <i>Replace first</i>.</li>"
        "<li><b>Not included</b>: wages and what a renewal would cost, whether the player would sign, and "
        "potential, which FM hides. Age is the only development signal used.</li>"
        "</ul></details>"
    )


def contracts_body(review: ContractReview, scope_form: str = "", *, show_squad: bool = False) -> str:
    return (
        "<div class='fm-contract-page'>"
        + _hero(review)
        + scope_form
        + _tiles(review)
        + _action_list(review)
        + _let_go(review)
        + _timeline(review)
        + _all_players(review, show_squad)
        + _method(review)
        + "</div>"
    )


def contract_panel(item: ContractAssessment, review: ContractReview) -> str:
    """The squad player report's view of the same assessment."""
    return (
        f"<section class='fm-workspace-panel fm-contract-page fm-contract-panel {VERDICT_CLASSES[item.verdict]}' id='contract'>"
        "<div class='fm-panel-heading'><div><h2>Contract plan</h2>"
        f"<p>{verdict_pill(item.verdict)} {_esc(item.advice)}</p></div>"
        f"<div class='fm-contract-keep' title='Keep value: orders players within a verdict'>"
        f"<b>{item.keep_value}</b><small>keep</small></div></div>"
        + _readings(item, review)
        + reason_chips(item.reasons)
        + "<p class='fm-player-back'><a href='/contracts'>Compare with every player on the Contracts page</a></p>"
        "</section>"
    )
