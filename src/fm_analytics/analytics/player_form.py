"""Recent form in one exact job, as a small nudge to a player's score for that job.

A player's form counts only for the job it was earned in: the tactic, the
position and the role with its duty (`analytics.appearance_context` works
those out). Poor games as a Box-to-Box Midfielder (Support) in Vertical 4-4-2
never touch his Central Midfielder (Support) score, nor his Box-to-Box score
in another tactic. See docs/tactic-role-form-plan.md §2.

For each player and job, his last `max_ratings` FM ratings from the last
`window_days` game days are averaged, newer ones counting more (each one older
counts `recency` times as much) and a part-match counting by its share of 90
minutes. That average is compared with a fixed neutral rating, and the
difference moves his score by at most `max_change` either way, scaled down
when there are few ratings. No ratings, or a disabled policy, is exactly no
change, and a missing rating is never treated as a bad one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping

from fm_analytics.analytics.appearance_context import AppearanceContext
from fm_analytics.domain.matches import MATCH_MINUTES


@dataclass(frozen=True)
class FormPolicy:
    version: int = 3
    enabled: bool = True
    max_ratings: int = 10
    window_days: int = 90
    min_minutes: int = 30
    # Each rating counts this much of the one after it: the 10th most recent
    # counts about 30% as much as the latest.
    recency: float = 0.87
    # A modelling choice, not a claimed FM average: form above it helps, below it hurts.
    neutral_rating: float = 6.7
    # How many full, recent matches it takes for form to have half its full effect.
    confidence_matches: float = 3.0
    # 50% stronger than the plan's first 0.02 / 0.02, at the manager's request
    # (3 October 2026): every form effect is 1.5 times the first release's.
    change_per_rating_point: float = 0.03
    max_change: float = 0.03

    def __post_init__(self) -> None:
        if not 0 < self.recency <= 1:
            raise ValueError("recency must be above 0 and at most 1")
        if self.max_ratings < 1 or self.window_days < 1 or self.confidence_matches <= 0:
            raise ValueError("max_ratings, window_days and confidence_matches must be positive")
        if not 0 <= self.max_change < 1:
            raise ValueError("max_change must be at least 0 and below 1")


@dataclass(frozen=True)
class FormRating:
    """One rating that counted, with how much it counted."""

    match_key: str
    date: date
    opponent: str
    rating: float
    minutes: int
    weight: float


@dataclass(frozen=True)
class JobForm:
    player_id: str
    player: str
    tactic_key: str
    position: str
    role_key: str
    ratings: tuple[FormRating, ...]  # newest first
    average: float  # weighted
    confidence: float  # 0..1: how much of the full effect the ratings earn
    multiplier: float

    @property
    def change(self) -> float:
        """The change to his score for this job, as a fraction (+0.011 is +1.1%)."""
        return self.multiplier - 1


JobKey = tuple[str, str, str, str]  # player ID, tactic key, position, role key


@dataclass(frozen=True)
class FormLookup:
    """Every player's form in every job he has rated games in, as of one date."""

    policy: FormPolicy
    as_of: date | None
    jobs: Mapping[JobKey, JobForm]

    def multiplier(self, player_id: str, tactic_key: str, position: str, role_key: str) -> float:
        """1.0 exactly when he has no qualifying ratings in that exact job."""
        form = self.jobs.get((player_id, tactic_key, position, role_key))
        return form.multiplier if form is not None else 1.0

    def job(self, player_id: str, tactic_key: str, position: str, role_key: str) -> JobForm | None:
        return self.jobs.get((player_id, tactic_key, position, role_key))

    def for_player(self, player_id: str) -> dict[tuple[str, str, str], float]:
        """His form in each job, keyed (tactic, position, role), as `PlayerSelectionInput.form` takes it."""
        return {
            (tactic, position, role): job.multiplier
            for (owner, tactic, position, role), job in self.jobs.items()
            if owner == player_id
        }


def build_form(
    contexts: Iterable[AppearanceContext], *, as_of: date | None, policy: FormPolicy = FormPolicy()
) -> FormLookup:
    """Form from the appearances whose job is known, played up to `as_of` (all of them with None)."""
    if not policy.enabled:
        return FormLookup(policy, as_of, {})
    since = as_of - timedelta(days=policy.window_days) if as_of is not None else None
    by_job: dict[JobKey, list[AppearanceContext]] = defaultdict(list)
    for context in contexts:
        played = context.match.date
        if (
            context.usable
            and context.player.minutes >= policy.min_minutes
            and (as_of is None or since < played <= as_of)
        ):
            key = (context.player.player_id, context.tactic_key, context.position, context.role_key)
            by_job[key].append(context)
    jobs = {key: _job_form(key, appearances, policy) for key, appearances in by_job.items()}
    return FormLookup(policy, as_of, jobs)


def _job_form(key: JobKey, appearances: list[AppearanceContext], policy: FormPolicy) -> JobForm:
    newest_first = sorted(appearances, key=lambda c: (c.match.date, c.match.key), reverse=True)
    ratings = tuple(
        FormRating(
            match_key=context.match.key,
            date=context.match.date,
            opponent=context.match.team("away" if context.player.side == "home" else "home").name,
            rating=context.player.rating,
            minutes=context.player.minutes,
            weight=policy.recency ** age * min(context.player.minutes / MATCH_MINUTES, 1.0),
        )
        for age, context in enumerate(newest_first[: policy.max_ratings])
    )
    total = sum(item.weight for item in ratings)
    average = sum(item.weight * item.rating for item in ratings) / total
    confidence = total / (total + policy.confidence_matches)
    raw = policy.change_per_rating_point * (average - policy.neutral_rating)
    change = confidence * max(-policy.max_change, min(policy.max_change, raw))
    player_id, tactic_key, position, role_key = key
    return JobForm(
        player_id=player_id,
        player=newest_first[0].player.label,
        tactic_key=tactic_key,
        position=position,
        role_key=role_key,
        ratings=ratings,
        average=average,
        confidence=confidence,
        multiplier=1 + change,
    )
