"""`fm-matches conceded`: the Conceded page in text, from the one `reporting.build_conceded_review`."""

from __future__ import annotations

from fm_analytics.analytics.conceded import FLANK_WORDS, POST_GUESS, ZONE_GUESS, ConcededReview, Tally

SIDES = {"left": "our left", "right": "our right", "centre": "central"}


def _row(rows: tuple[Tally, ...], *, chances: bool = False) -> str:
    return "  ".join(
        f"{row.label} {row.goals}" + (f"/{row.chances}" if chances else "") for row in rows
    ) or "none"


def format_conceded(review: ConcededReview) -> str:
    """Every goal and clear-cut chance against us, broken down, as the Conceded page shows them."""
    lines = [
        f"Goals and chances conceded: {review.goals} goals and {review.chances} more clear-cut chances in "
        f"{review.matches} matches with full stats"
        + (f" ({review.without_stats} more without stats, left out)" if review.without_stats else "") + ".",
        "",
        "How: " + _row(review.how),
        "Delivered: " + _row(review.flanks),
        "Delivered by (their position): " + _row(review.delivered_by),
        f"Near or back post (a guess, {review.cross_goals_from_a_flank} goals from crosses from a flank): "
        + _row(review.posts),
        "Scored or had the chance (their position, goals/chances): " + _row(review.takers, chances=True),
        "Where from: " + _row(review.areas),
        "When (goals/chances): " + _row(review.periods, chances=True),
        "",
        "Our players in the zone (a guess): goals, chances, minutes, goals in his zone per 90",
    ]
    lines += [
        f"  {record.name:<24} {record.positions:<10} {record.goals:>3} {record.chances:>3} {record.minutes:>6}  "
        f"{'-' if record.per90 is None else f'{record.per90:.2f}'}"
        for record in review.zone
    ]
    lines += ["", "Every goal and chance, latest first:"]
    for moment in review.moments:
        taker = f"{moment.taker or '?'} ({moment.taker_position or '?'}, {SIDES.get(moment.taker_side, moment.taker_side)})"
        line = (f"  {moment.date} {moment.venue} {moment.opponent:<24} {moment.clock:>5}' "
                f"{moment.score_before[0]}-{moment.score_before[1]}  {moment.outcome}: {taker}")
        if moment.how:
            line += f"; {moment.how}"
        if moment.how_key == "possibly_corner":
            line += " (possibly a corner, a guess)"
        if moment.delivered_by:
            line += (f"; delivered by {moment.delivered_by} ({moment.delivery_position}, "
                     f"{FLANK_WORDS.get(moment.delivery_flank or '', '?')})")
        if moment.post:
            line += f"; {moment.post} post (guess)"
        if moment.given_away_by:
            line += f"; given away by {moment.given_away_by} (your record)"
        if moment.around:
            line += "; ours around (guess): " + ", ".join(player.label for player in moment.around)
        lines.append(line)
    lines += ["", "Guesses: " + POST_GUESS, ZONE_GUESS]
    return "\n".join(lines)
