"""Visibility-aware ranking and filtering for external scouting candidates.

This module deliberately consumes only a candidate feed made of manager-visible
observations.  It never falls back to a raw FM value when a field is unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleScore, score_role
from fm_analytics.domain import AttributeObservation, Visibility


class ScoutRecommendation(StrEnum):
    PROVEN_FIT = "proven-fit"
    SCOUT_TO_DECIDE = "scout-to-decide"
    SCOUT_FIRST = "scout-first"
    UNLIKELY = "unlikely"


@dataclass(frozen=True)
class ScoutingCandidate:
    """One discoverable player and only the facts visible to this manager."""

    id: str
    name: str
    positions: tuple[str, ...]
    attributes: Mapping[str, AttributeObservation]
    age: int | None = None
    club: str | None = None
    nationality: str | None = None
    footedness: str | None = None
    transfer_status: str | None = None
    availability: str | None = None
    facts: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("scouting candidates require an id and name")
        if self.age is not None and self.age < 0:
            raise ValueError("scouting candidate age cannot be negative")
        if self.facts is not None and any(not key or not isinstance(value, str) for key, value in self.facts.items()):
            raise ValueError("scouting facts must have non-empty keys and string values")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScoutingCandidate":
        attributes_raw = raw.get("attributes", {})
        facts_raw = raw.get("facts", {})
        if not isinstance(attributes_raw, Mapping) or not isinstance(facts_raw, Mapping):
            raise TypeError("scouting attributes and facts must be objects")
        positions = raw.get("positions")
        if not isinstance(positions, list) or not all(isinstance(item, str) and item for item in positions):
            raise TypeError("scouting candidate positions must be a string list")
        age = raw.get("age")
        if age is not None and (not isinstance(age, int) or isinstance(age, bool)):
            raise TypeError("scouting candidate age must be an integer or null")

        def optional_text(name: str) -> str | None:
            value = raw.get(name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"scouting candidate {name} must be a string or null")
            return value

        if any(not isinstance(name, str) or not isinstance(value, Mapping) for name, value in attributes_raw.items()):
            raise TypeError("scouting attributes must map names to observations")
        if any(not isinstance(name, str) or not isinstance(value, str) for name, value in facts_raw.items()):
            raise TypeError("scouting facts must map names to visible strings")
        return cls(
            id=_required_text(raw, "id"), name=_required_text(raw, "name"),
            positions=tuple(positions), age=age, club=optional_text("club"),
            nationality=optional_text("nationality"), footedness=optional_text("footedness"),
            transfer_status=optional_text("transferStatus"), availability=optional_text("availability"),
            attributes={
                str(name): AttributeObservation.from_dict(value)
                for name, value in attributes_raw.items()
            },
            facts=dict(facts_raw),
        )


@dataclass(frozen=True)
class ScoutingFilters:
    position: str | None = None
    role_key: str | None = None
    minimum_age: int | None = None
    maximum_age: int | None = None
    club_contains: str | None = None
    nationality: str | None = None
    footedness: str | None = None
    transfer_status: str | None = None
    availability: str | None = None
    visibility: str = "any"
    minimum_floor: float | None = None
    minimum_ceiling: float | None = None
    include_unlikely: bool = False
    facts: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.minimum_age is not None and self.maximum_age is not None and self.minimum_age > self.maximum_age:
            raise ValueError("minimum age cannot exceed maximum age")
        if self.minimum_floor is not None and self.minimum_ceiling is not None and self.minimum_floor > self.minimum_ceiling:
            raise ValueError("minimum floor cannot exceed minimum ceiling")


@dataclass(frozen=True)
class ScoutingAssessment:
    candidate: ScoutingCandidate
    role_score: RoleScore
    recommendation: ScoutRecommendation
    known_attributes: int
    ranged_attributes: int
    unknown_attributes: int
    scout_next: tuple[str, ...]

    @property
    def visibility_summary(self) -> str:
        total = self.known_attributes + self.ranged_attributes + self.unknown_attributes
        return f"{self.known_attributes}/{total} known · {self.ranged_attributes} ranged · {self.unknown_attributes} unknown"


def assess_scouting_candidates(
    candidates: Sequence[ScoutingCandidate],
    catalogue: FootballCatalogue,
    filters: ScoutingFilters,
) -> tuple[ScoutingAssessment, ...]:
    """Filter on visible facts and rank the remaining players for one role.

    The lower and upper values remain visible.  Unknown information never
    increases a player's central score, but an entirely unknown relevant
    profile is explicitly surfaced as a player to scout first rather than
    silently discarded.
    """
    if not filters.role_key or filters.role_key not in catalogue.roles:
        return ()
    role = catalogue.roles[filters.role_key]
    assessments: list[ScoutingAssessment] = []
    for candidate in candidates:
        # An unknown position is not a match for a position filter.  Without
        # that filter the player remains in the discovery queue: it is a
        # reason to scout, not permission to silently invent eligibility.
        if filters.position and filters.position not in candidate.positions:
            continue
        if candidate.positions and not set(role.eligible_positions).intersection(candidate.positions):
            continue
        if not _matches_visible_filters(candidate, filters):
            continue
        score = score_role(role, candidate.attributes)
        observations = [item.observation for item in score.contributions]
        known = sum(item.visibility is Visibility.KNOWN for item in observations)
        ranged = sum(item.visibility is Visibility.RANGE for item in observations)
        unknown = len(observations) - known - ranged
        if filters.visibility == "known" and (ranged or unknown):
            continue
        if filters.visibility == "partial" and not ranged:
            continue
        if filters.visibility == "unknown" and known + ranged:
            continue
        if filters.minimum_floor is not None and score.score.lower < filters.minimum_floor:
            continue
        recommendation = _recommendation(score, known, ranged, unknown, filters)
        if recommendation is ScoutRecommendation.UNLIKELY and not filters.include_unlikely:
            continue
        assessments.append(
            ScoutingAssessment(
                candidate=candidate,
                role_score=score,
                recommendation=recommendation,
                known_attributes=known,
                ranged_attributes=ranged,
                unknown_attributes=unknown,
                scout_next=tuple(gap.attribute for gap in score.information_gaps[:4]),
            )
        )
    return tuple(sorted(assessments, key=_sort_key))


def available_fact_values(candidates: Sequence[ScoutingCandidate]) -> dict[str, tuple[str, ...]]:
    """Dynamic filter choices supplied by the capture, e.g. FM search facts."""
    values: dict[str, set[str]] = {}
    for candidate in candidates:
        for key, value in (candidate.facts or {}).items():
            if value:
                values.setdefault(key, set()).add(value)
    return {key: tuple(sorted(items, key=str.casefold)) for key, items in sorted(values.items())}


def _matches_visible_filters(candidate: ScoutingCandidate, filters: ScoutingFilters) -> bool:
    if filters.minimum_age is not None and (candidate.age is None or candidate.age < filters.minimum_age):
        return False
    if filters.maximum_age is not None and (candidate.age is None or candidate.age > filters.maximum_age):
        return False
    if filters.club_contains and filters.club_contains.casefold() not in (candidate.club or "").casefold():
        return False
    for expected, actual in (
        (filters.nationality, candidate.nationality),
        (filters.footedness, candidate.footedness),
        (filters.transfer_status, candidate.transfer_status),
        (filters.availability, candidate.availability),
    ):
        if expected and expected != actual:
            return False
    for key, value in (filters.facts or {}).items():
        if value and (candidate.facts or {}).get(key) != value:
            return False
    return True


def _recommendation(
    score: RoleScore, known: int, ranged: int, unknown: int, filters: ScoutingFilters
) -> ScoutRecommendation:
    threshold = filters.minimum_ceiling
    if threshold is not None and score.score.upper < threshold:
        return ScoutRecommendation.UNLIKELY
    if known == 0 and ranged == 0:
        return ScoutRecommendation.SCOUT_FIRST
    if unknown or ranged:
        return ScoutRecommendation.SCOUT_TO_DECIDE
    return ScoutRecommendation.PROVEN_FIT


def _sort_key(item: ScoutingAssessment) -> tuple[object, ...]:
    priority = {
        ScoutRecommendation.PROVEN_FIT: 0,
        ScoutRecommendation.SCOUT_FIRST: 1,
        ScoutRecommendation.SCOUT_TO_DECIDE: 2,
        ScoutRecommendation.UNLIKELY: 3,
    }[item.recommendation]
    return (
        priority,
        -item.role_score.score.lower,
        -item.role_score.score.upper,
        item.candidate.name.casefold(),
        item.candidate.id,
    )


def _required_text(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"scouting candidate {name} is required")
    return value
