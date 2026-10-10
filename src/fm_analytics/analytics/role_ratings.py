"""Each role's match ratings against opposition players in the same position.

FM rates positions differently: full-backs and defensive midfielders score
lower than strikers whoever plays there, so a role's average rating means
little against a fixed bar. Here each start in a role is set against the
average rating of the opposition players who started in the same position in
the same matches, left and right taken together. Only starts of at least
`MIN_RATED_MINUTES` count, on both sides, so a substitute's short spell is not
compared with a full match. FM shows every rating here on its player match
stats screen.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from statistics import mean, stdev

from fm_analytics.analytics.match_analysis import MatchReview

MIN_RATED_MINUTES = 60
MIN_BASELINE_STARTS = 10
POSITION_GROUPS = {
    "GK": "goalkeepers", "SW": "sweepers", "DR": "full-backs", "DL": "full-backs", "DC": "centre-backs",
    "WBR": "wing-backs", "WBL": "wing-backs", "DM": "defensive midfielders", "MR": "wide midfielders",
    "ML": "wide midfielders", "MC": "central midfielders", "AMR": "wide attackers", "AML": "wide attackers",
    "AMC": "attacking midfielders", "ST": "strikers",
}


@dataclass(frozen=True)
class RoleRating:
    label: str  # the role, as the review's roles table names it
    group: str  # the position group most of its starts were in ("central midfielders")
    starts: int  # its rated starts with an opposition baseline
    rating: float
    usual: float  # the opposition's average in the same positions, start for start
    baseline_starts: int  # the opposition starts behind `usual`
    spread: float  # how far one start's gap from `usual` typically strays

    @property
    def gap(self) -> float:
        return self.rating - self.usual

    @property
    def luck_odds(self) -> float:
        """How often luck alone leaves a gap at least this large this way (by the normal approximation)."""
        if self.starts < 2 or self.spread == 0:
            return 0.0 if self.gap else 1.0
        z = self.gap / (self.spread / math.sqrt(self.starts))
        return 0.5 * math.erfc(abs(z) / math.sqrt(2))


def role_ratings(review: MatchReview) -> tuple[RoleRating, ...]:
    """Every role with at least two rated starts against the opposition in the same positions."""
    baseline: dict[str, list[float]] = {}
    starts: dict[str, list[tuple[str, float]]] = {}
    for row in review.matches:
        if row.match.detail is None:
            continue
        for player in row.match.detail.players:
            group = POSITION_GROUPS.get(player.position or "")
            if not player.started or player.rating is None or player.minutes < MIN_RATED_MINUTES or group is None:
                continue
            if player.side != row.side:
                baseline.setdefault(group, []).append(player.rating)
                continue
            role = review.appearance_roles.get((row.match.key, player.side, player.short_id))
            if role:
                starts.setdefault(role, []).append((group, player.rating))
    usual = {group: mean(ratings) for group, ratings in baseline.items() if len(ratings) >= MIN_BASELINE_STARTS}
    found = []
    for role, rated in starts.items():
        rated = [(group, rating) for group, rating in rated if group in usual]
        if len(rated) < 2:
            continue
        groups = Counter(group for group, _rating in rated)
        found.append(RoleRating(
            label=role,
            group=groups.most_common(1)[0][0],
            starts=len(rated),
            rating=mean(rating for _group, rating in rated),
            usual=mean(usual[group] for group, _rating in rated),
            baseline_starts=sum(len(baseline[group]) for group in groups),
            spread=stdev(rating - usual[group] for group, rating in rated),
        ))
    return tuple(sorted(found, key=lambda item: item.label))
