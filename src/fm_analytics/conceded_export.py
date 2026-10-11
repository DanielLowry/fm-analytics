"""Goals and chances conceded as JSON: the Conceded page's copy, `fm-matches conceded --json`, and their
entry in a match page's copy and the Matches page's "Copy all match data".

Serialisation only: `analytics.conceded` works it out, and the pages show the
same figures. Near or back post and our players in the zone are guesses from
positions (`guesses` says how), never FM's record.
"""

from __future__ import annotations

from typing import Any

from fm_analytics.analytics.conceded import POST_GUESS, ZONE_GUESS, ConcededMoment, ConcededReview, Tally
from fm_analytics.analytics.match_timeline import CORNER_GUESS


def _tallies(rows: tuple[Tally, ...], *, chances: bool = False) -> list[dict[str, Any]]:
    return [{"key": row.key, "label": row.label, "goals": row.goals, **({"chances": row.chances} if chances else {})}
            for row in rows]


def _moment(moment: ConcededMoment) -> dict[str, Any]:
    return {
        "match": moment.match_key, "date": moment.date.isoformat(), "opponent": moment.opponent, "venue": moment.venue,
        "minute": moment.clock, "goal": moment.goal, "kind": moment.kind, "outcome": moment.outcome,
        "score_before_us_them": f"{moment.score_before[0]}-{moment.score_before[1]}",
        "taker": moment.taker, "taker_position": moment.taker_position, "taker_side_of_our_pitch": moment.taker_side,
        "how": moment.how, "how_key": moment.how_key, "from_clear_cut_chance": moment.from_clear_cut_chance,
        "delivered_by": moment.delivered_by, "delivery_position": moment.delivery_position,
        "delivered_down": moment.delivery_flank, "post_guess": moment.post,
        "ours_facing_the_delivery_guess": [player.label for player in moment.facing_delivery],
        "ours_in_the_zone_guess": [player.label for player in moment.in_zone],
        "penalty_given_away_by_your_record": moment.given_away_by,
    }


def conceded_json(review: ConcededReview) -> dict[str, Any]:
    """Every goal and clear-cut chance conceded, and the breakdowns the pages show."""
    return {
        "matches_with_full_stats": review.matches,
        "matches_without_stats": review.without_stats,
        "goals": review.goals,
        "other_clear_cut_chances": review.chances,
        "goals_from_clear_cut_chances": review.goals_from_chances,
        "how": _tallies(review.how),
        "delivered_down": _tallies(review.flanks),
        "delivered_by_position": _tallies(review.delivered_by),
        "post_guess": _tallies(review.posts),
        "taken_by_position": _tallies(review.takers, chances=True),
        "where_from": _tallies(review.areas),
        "when": _tallies(review.periods, chances=True),
        "ours_in_the_zone_guess": [
            {"player": record.name, "positions": record.positions, "goals": record.goals, "chances": record.chances,
             "minutes": record.minutes, "goals_per_90": record.per90}
            for record in review.zone
        ],
        "moments": [_moment(moment) for moment in review.moments],
        "guesses": {"post": POST_GUESS, "zone": ZONE_GUESS, "possibly_from_corners": CORNER_GUESS},
    }
