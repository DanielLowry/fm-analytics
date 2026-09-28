"""The scouting pool: today's feed plus everyone the save's knowledge history remembers.

`persistence.best_known` assembles what the manager has seen of each player as
of one in-game date. This module merges those profiles into the current
scouting feed and returns the one `ScoutingCandidate` pool that both the
scouting list and the player report read. It is pure: no SQL, no HTML.

Field-by-field precedence:

* **Attributes.** A value the current feed shows, exact or ranged, always
  wins. A best-known value fills an attribute the feed shows as unknown or
  omits, and is named in `CandidateHistory.attributes` with the day it was
  last seen, so every renderer can mark it as history. Filled values are
  scored like any other visible value: the manager did see them.
* **Current-feed profile facts** (club, contract, transfer status, value,
  interest, scouting knowledge, positions...) are never touched.
* **A player missing from the feed** is built from his latest profile row:
  age, nationality, footedness, positions, position ratings and scouting
  knowledge, as last recorded. Club, contract, transfer status, value and
  search facts stay in `CandidateHistory.profile`, for display only, so no
  market or interest filter can admit him on an old fact. He is marked
  `in_current_feed=False`, which the filters treat as not currently
  realistic.

Identity is the save key plus FM's player id, never the name.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import replace
from datetime import date
from typing import Any, Mapping, Sequence

from fm_analytics.analytics.scouting_candidate import (
    CandidateHistory,
    HistoricalReading,
    ScoutingCandidate,
)
from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence.best_known import BestKnownProfile, SelectedAttribute

# The active plan's default for "out of date": six calendar months of game time.
DEFAULT_OUT_OF_DATE_MONTHS = 6


def compose_candidate_pool(
    current: Sequence[ScoutingCandidate],
    profiles: Mapping[str, BestKnownProfile],
    *,
    save_key: str,
    as_of: str,
    out_of_date_months: int = DEFAULT_OUT_OF_DATE_MONTHS,
) -> tuple[ScoutingCandidate, ...]:
    """Every current candidate once, in feed order, then every history-only player by id.

    ``profiles`` must be ``best_known_profiles(save_key, as_of)`` for the same
    save and date; a profile from any other save or date is refused rather than
    merged. A current candidate the history adds nothing to is returned as the
    very same object, so caches keyed on candidate identity keep working.
    """
    cutoff = months_before(as_of, out_of_date_months)
    for player_id, profile in profiles.items():
        if profile.save_key != save_key or profile.player_id != player_id:
            raise ValueError(
                f"profile for {profile.save_key}/{profile.player_id} cannot join save {save_key!r}"
            )
        if profile.as_of != as_of:
            raise ValueError(f"profile for {player_id} is as of {profile.as_of}, not {as_of}")
    pool: list[ScoutingCandidate] = []
    seen: set[str] = set()
    for candidate in current:
        if candidate.id in seen:
            raise ValueError(f"the scouting feed lists player {candidate.id} twice")
        seen.add(candidate.id)
        profile = profiles.get(candidate.id)
        pool.append(
            candidate if profile is None
            else _with_history(candidate, profile, as_of=as_of, cutoff=cutoff)
        )
    for player_id in sorted(set(profiles) - seen):
        pool.append(_from_history(profiles[player_id], as_of=as_of, cutoff=cutoff))
    return tuple(pool)


def months_before(as_of: str, months: int) -> str:
    """The in-game date ``months`` calendar months before ``as_of``, clamped to month end."""
    if months < 0:
        raise ValueError("an out-of-date age cannot be negative")
    day = date.fromisoformat(as_of)
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1])).isoformat()


def _reading(selected: SelectedAttribute) -> HistoricalReading:
    return HistoricalReading(
        observed_on=selected.observed_on,
        last_seen_on=selected.last_seen_on,
        source=selected.source,
    )


def _with_history(
    candidate: ScoutingCandidate, profile: BestKnownProfile, *, as_of: str, cutoff: str
) -> ScoutingCandidate:
    attributes = dict(candidate.attributes)
    readings: dict[str, HistoricalReading] = {}
    for name, knowledge in profile.attributes.items():
        best = knowledge.best_known
        if best is None:
            continue
        shown = attributes.get(name)
        if shown is not None and shown.visibility is not Visibility.UNKNOWN:
            continue
        attributes[name] = best.observation
        readings[name] = _reading(best)
    if not readings:
        return candidate
    return replace(
        candidate,
        attributes=attributes,
        history=CandidateHistory(
            as_of=as_of, in_current_feed=True, out_of_date_before=cutoff, attributes=readings,
        ),
    )


def _from_history(profile: BestKnownProfile, *, as_of: str, cutoff: str) -> ScoutingCandidate:
    facts: Mapping[str, Any] = profile.profile or {}
    attributes: dict[str, AttributeObservation] = {}
    readings: dict[str, HistoricalReading] = {}
    for name, knowledge in profile.attributes.items():
        if knowledge.best_known is not None:
            attributes[name] = knowledge.best_known.observation
            readings[name] = _reading(knowledge.best_known)
        else:
            # Captured, never learned: the same unknown the feed would show.
            attributes[name] = knowledge.latest.observation
    familiarity = facts.get("raw_position_familiarity")
    return ScoutingCandidate(
        id=profile.player_id,
        name=profile.name,
        positions=tuple(facts.get("positions") or ()),
        raw_positions=tuple(facts.get("raw_positions") or ()),
        raw_position_familiarity=dict(familiarity) if familiarity else None,
        attributes=attributes,
        age=facts.get("age"),
        nationality=facts.get("nationality"),
        footedness=facts.get("footedness"),
        scouting_knowledge=facts.get("scouting_knowledge"),
        in_player_search=False,
        # Today's date: a verdict recorded on his report is decided now.
        captured_game_date=as_of,
        history=CandidateHistory(
            as_of=as_of,
            in_current_feed=False,
            out_of_date_before=cutoff,
            attributes=readings,
            profile=profile.profile,
            profile_last_seen_on=profile.profile_last_seen_on,
        ),
    )
