"""Visibility-aware ranking and filtering for external scouting candidates.

Manager-visible observations are the default. The sole exception is an
explicitly labelled raw external-position path, enabled only after the product
owner accepted its documented short-term visibility gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleScore, score_role
from fm_analytics.analytics.xi_models import FamiliarityPolicy
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
    raw_positions: tuple[str, ...] = ()
    age: int | None = None
    club: str | None = None
    nationality: str | None = None
    footedness: str | None = None
    transfer_status: str | None = None
    availability: str | None = None
    facts: Mapping[str, str] | None = None
    scouting_knowledge: int | None = None
    dropped_from_scout_reports: bool = False
    # Raw 0-20 rating per position code. Finer than the eligibility list and,
    # for a player the manager does not own, beyond what FM's own screens
    # necessarily show, so it is only ever used behind the same opt-in as
    # ``raw_positions`` (see ``rank_for_position``).
    raw_position_familiarity: Mapping[str, int] | None = None
    # What makes a player gettable. ``has_contract`` is False for an unattached
    # player (a free agent) and None when it is not known; ``contract_end`` is an
    # ISO date.
    contract_end: str | None = None
    contract_type: str | None = None
    has_contract: bool | None = None
    # Transfer value in pounds, as FM's own Value column shows it.
    value: int | None = None
    # The game date the capture was taken at; contract expiry is measured from it.
    captured_game_date: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("scouting candidates require an id and name")
        if self.age is not None and self.age < 0:
            raise ValueError("scouting candidate age cannot be negative")
        if self.facts is not None and any(not key or not isinstance(value, str) for key, value in self.facts.items()):
            raise ValueError("scouting facts must have non-empty keys and string values")
        if self.scouting_knowledge is not None and not 0 <= self.scouting_knowledge <= 100:
            raise ValueError("scouting knowledge must be between 0 and 100")
        if self.dropped_from_scout_reports and self.scouting_knowledge is None:
            raise ValueError("a player dropped from scout reports must still carry a last-known knowledge level")
        if self.contract_end is not None:
            date.fromisoformat(self.contract_end)  # ValueError on a malformed date
        if self.raw_position_familiarity is not None and any(
            not position or not isinstance(rating, int) or isinstance(rating, bool) or not 0 <= rating <= 20
            for position, rating in self.raw_position_familiarity.items()
        ):
            raise ValueError("position familiarity must map position codes to ratings from 0 to 20")

    def is_scouted(self) -> bool:
        """True for any player with a current or last-known scouting-knowledge record.

        This -- not a non-empty ``attributes`` -- is the correct test for
        "belongs on the Scouted tab": a hydrated-but-never-scouted player has
        attributes too, and a dropped player still belongs here with a
        warning, not with the general browse list.
        """
        return self.scouting_knowledge is not None

    def positions_for(self, *, include_raw_external_positions: bool) -> tuple[str, ...]:
        """Return verified positions, plus accepted-gap raw positions if opted in."""
        if not include_raw_external_positions:
            return self.positions
        return tuple(dict.fromkeys(self.positions + self.raw_positions))

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScoutingCandidate":
        attributes_raw = raw.get("attributes", {})
        facts_raw = raw.get("facts", {})
        if not isinstance(attributes_raw, Mapping) or not isinstance(facts_raw, Mapping):
            raise TypeError("scouting attributes and facts must be objects")
        positions = _string_list(raw, "positions")
        raw_positions = _string_list(raw, "rawPositions", default=[])
        age = raw.get("age")
        if age is not None and (not isinstance(age, int) or isinstance(age, bool)):
            raise TypeError("scouting candidate age must be an integer or null")
        scouting_knowledge = raw.get("scoutingKnowledge")
        if scouting_knowledge is not None and (
            not isinstance(scouting_knowledge, int) or isinstance(scouting_knowledge, bool)
        ):
            raise TypeError("scouting candidate scoutingKnowledge must be an integer or null")
        dropped = raw.get("droppedFromScoutReports", False)
        if not isinstance(dropped, bool):
            raise TypeError("scouting candidate droppedFromScoutReports must be a boolean")
        has_contract = raw.get("hasContract")
        if has_contract is not None and not isinstance(has_contract, bool):
            raise TypeError("scouting candidate hasContract must be a boolean")
        familiarity = raw.get("rawPositionFamiliarity")
        if familiarity is not None and not isinstance(familiarity, Mapping):
            raise TypeError("scouting candidate rawPositionFamiliarity must be an object")

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
            positions=tuple(positions), raw_positions=tuple(raw_positions), age=age,
            club=optional_text("club"),
            nationality=optional_text("nationality"), footedness=optional_text("footedness"),
            transfer_status=optional_text("transferStatus"), availability=optional_text("availability"),
            attributes={
                str(name): AttributeObservation.from_dict(value)
                for name, value in attributes_raw.items()
            },
            facts=dict(facts_raw),
            scouting_knowledge=scouting_knowledge,
            dropped_from_scout_reports=dropped,
            raw_position_familiarity=dict(familiarity) if familiarity is not None else None,
            contract_end=optional_text("contractEnd"), contract_type=optional_text("contractType"),
            has_contract=has_contract, captured_game_date=optional_text("capturedGameDate"),
            value=raw.get("value"),
        )


MARKET_FILTERS = {
    "any": "Any",
    "gettable": "Gettable (any of the below)",
    "free": "Free agent",
    "listed": "Transfer listed",
    "expiring": "Contract running out",
}
_LISTED_STATUSES = frozenset({
    "transfer_listed", "transfer_and_loan_listed", "transfer_listed_by_request",
    "transfer_listed_not_for_loan", "listed_by_request_not_for_loan",
})


def is_free_agent(candidate: "ScoutingCandidate") -> bool:
    # No club is not enough on its own: an unreadable contract also leaves the
    # club empty. Only a contract read that succeeded and found none counts.
    return candidate.has_contract is False


def is_transfer_listed(candidate: "ScoutingCandidate") -> bool:
    return candidate.transfer_status in _LISTED_STATUSES


def contract_months_left(candidate: "ScoutingCandidate") -> int | None:
    if candidate.contract_end is None or candidate.captured_game_date is None:
        return None
    end, now = date.fromisoformat(candidate.contract_end), date.fromisoformat(candidate.captured_game_date)
    return (end.year - now.year) * 12 + end.month - now.month - (end.day < now.day)


def _matches_market(candidate: "ScoutingCandidate", filters: "ScoutingFilters") -> bool:
    if filters.market == "any":
        return True
    months = contract_months_left(candidate)
    expiring = months is not None and months <= filters.expiring_months
    checks = {
        "free": is_free_agent(candidate), "listed": is_transfer_listed(candidate),
        "expiring": expiring,
    }
    if filters.market == "gettable":
        return any(checks.values())
    return checks[filters.market]


@dataclass(frozen=True)
class ScoutingFilters:
    position: str | None = None
    role_key: str | None = None
    minimum_age: int | None = None
    maximum_age: int | None = None
    name_contains: str | None = None
    club_contains: str | None = None
    nationality: str | None = None
    footedness: str | None = None
    transfer_status: str | None = None
    availability: str | None = None
    visibility: str = "any"
    minimum_floor: float | None = None
    minimum_ceiling: float | None = None
    include_unlikely: bool = False
    include_raw_external_positions: bool = False
    scouted_only: bool = False
    market: str = "any"
    expiring_months: int = 6
    ranking_sort: str = "median"
    ranking_descending: bool | None = None
    facts: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.market not in MARKET_FILTERS:
            raise ValueError("market filter is invalid")
        if self.expiring_months < 0:
            raise ValueError("expiring months cannot be negative")
        if self.ranking_sort not in RANKING_SORTS:
            raise ValueError("ranking sort is invalid")
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
        positions = candidate.positions_for(
            include_raw_external_positions=filters.include_raw_external_positions
        )
        # An unknown position is not a match for a position filter.  Without
        # that filter the player remains in the discovery queue: it is a
        # reason to scout, not permission to silently invent eligibility.
        if filters.position and filters.position not in positions:
            continue
        if positions and not set(role.eligible_positions).intersection(positions):
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


RANKING_SORTS = {
    "median": "Median (best guess)",
    "minimum": "Min (floor)",
    "ceiling": "Ceiling (best case)",
    "upside": "Upside (ceiling above median)",
    "age": "Age",
    "scouted": "Scouted %",
    "known": "Attributes known",
    "name": "Player name",
    "role": "Best role",
    "adjusted": "In position today (median)",
    "familiarity": "Position familiarity",
}
# Text columns and age read naturally smallest/first-first; everything that is
# a score or an amount of information reads best largest-first.
_ASCENDING_BY_DEFAULT = frozenset({"age", "name", "role"})


def default_descending(sort: str) -> bool:
    return sort not in _ASCENDING_BY_DEFAULT


@dataclass(frozen=True)
class PositionRanking:
    """One player's score range for a position, by the role that suits him best.

    ``minimum``/``maximum`` come from the visible ranges alone (an unknown
    attribute spans the whole scale), so they are the honest bounds on what
    the player could be worth; ``median`` puts every range at its midpoint and
    every unknown mid-scale. A wide gap between them is exactly where more
    scouting would change the decision.
    """

    candidate: ScoutingCandidate
    role_key: str
    role_name: str
    minimum: float
    median: float
    maximum: float
    known_attributes: int
    ranged_attributes: int
    unknown_attributes: int
    # Set only when the caller opted into position ratings AND this player has
    # them: the rating (0-20) for the position he would play this role at, the
    # multiplier the tactics page would apply for it, and the three scores after
    # that multiplier -- "what he is worth in that position today".
    familiarity: int | None = None
    multiplier: float | None = None
    adjusted_minimum: float | None = None
    adjusted_median: float | None = None
    adjusted_maximum: float | None = None

    @property
    def upside(self) -> float:
        return self.maximum - self.median


# The attributes FM only shows for goalkeepers (they are absent, not unknown,
# for an outfield player).
_GOALKEEPING_ATTRIBUTES = frozenset({
    "aerialReach", "commandOfArea", "communication", "handling", "kicking",
    "oneOnOnes", "reflexes", "rushingOut", "throwing",
})


def _role_rating(role, position: str | None, ratings: Mapping[str, int] | None) -> int | None:
    """His familiarity for the position this role would be played at."""
    if not ratings:
        return None
    positions = [position] if position else list(role.eligible_positions)
    found = [ratings[name] for name in positions if name in ratings]
    return max(found) if found else None


def rank_for_position(
    candidates: Sequence[ScoutingCandidate],
    catalogue: FootballCatalogue,
    position: str | None = None,
    *,
    sort: str = "median",
    descending: bool | None = None,
    include_raw_external_positions: bool = False,
    familiarity_policy: FamiliarityPolicy | None = None,
) -> tuple[PositionRanking, ...]:
    """Rank candidates, each by whichever role suits him best.

    With a ``position`` only roles for that position are tried. With none, each
    player is tried in the roles for his own positions (raw ones only if opted
    in), and in every role if his positions are not known -- so the list is
    still ranked before anyone has chosen or verified a position. Position
    eligibility itself is the caller's concern (``filter_scouting_candidates``
    already applied it); this only scores. The role is chosen per player on the
    median, so one player can be shown as a Ball-Winning Midfielder and another
    as a Deep-Lying Playmaker in the same list.

    With a ``familiarity_policy`` and a player who has position ratings, each
    role's three scores are also multiplied by the same familiarity multiplier
    the tactics page applies, using his rating for the chosen position (or, with
    none chosen, his best rating among the positions that role is played at),
    and the role is then chosen on that adjusted median: the best role he could
    actually play today, not merely the one that suits his attributes. Callers
    pass the policy only when the raw-positions opt-in is ticked. A player
    without ratings is left unadjusted rather than assumed unfamiliar.

    ``sort`` may be any key of ``RANKING_SORTS``; ``descending`` defaults to
    the natural direction for that column. A player missing the sorted value
    (no age, never scouted) always goes last, whichever direction is chosen.
    """
    if sort not in RANKING_SORTS:
        raise ValueError(f"sort must be one of {sorted(RANKING_SORTS)}")
    if descending is None:
        descending = default_descending(sort)
    all_roles = list(catalogue.roles.values())
    rankings: list[PositionRanking] = []
    for candidate in candidates:
        if position:
            roles = [role for role in all_roles if position in role.eligible_positions]
        else:
            roles = all_roles
            if candidate.attributes:
                # FM's visibility formula only produces the goalkeeping
                # attributes (Handling, Reflexes, ...) for a goalkeeper, and
                # only produces the outfield-only ones (Heading, Marking,
                # Tackling, ...) for everyone else. Which set a player carries
                # therefore says which kind of player he is, and it is applied
                # first because it comes from the formula, not from a position
                # label. Scoring the absent set as "unknown, so mid-scale"
                # otherwise let a goalkeeper role win for a defender on paper.
                keeper = any(name in candidate.attributes for name in _GOALKEEPING_ATTRIBUTES)
                roles = [role for role in roles if ("GK" in role.eligible_positions) == keeper] or roles
            own = set(candidate.positions_for(
                include_raw_external_positions=include_raw_external_positions
            ))
            roles = [role for role in roles if own.intersection(role.eligible_positions)] or roles
        if not roles:
            continue
        ratings = candidate.raw_position_familiarity if familiarity_policy else None
        scored = []
        for role in roles:
            score = score_role(role, candidate.attributes)
            rating = _role_rating(role, position, ratings)
            multiplier = (
                familiarity_policy.multiplier(max(rating, familiarity_policy.scale_minimum))
                if familiarity_policy is not None and rating is not None else None
            )
            scored.append((score, rating, multiplier))
        best, best_rating, best_multiplier = max(
            scored,
            key=lambda item: (
                item[0].median * (item[2] if item[2] is not None else 1.0),
                item[0].score.upper, item[0].role_key,
            ),
        )
        visibilities = [item.observation.visibility for item in best.contributions]
        known = sum(v is Visibility.KNOWN for v in visibilities)
        ranged = sum(v is Visibility.RANGE for v in visibilities)
        rankings.append(
            PositionRanking(
                candidate=candidate,
                role_key=best.role_key,
                role_name=best.role_name,
                minimum=best.score.lower,
                median=best.median,
                maximum=best.score.upper,
                known_attributes=known,
                ranged_attributes=ranged,
                unknown_attributes=len(visibilities) - known - ranged,
                familiarity=best_rating if best_multiplier is not None else None,
                multiplier=best_multiplier,
                adjusted_minimum=None if best_multiplier is None else round(best.score.lower * best_multiplier, 6),
                adjusted_median=None if best_multiplier is None else round(best.median * best_multiplier, 6),
                adjusted_maximum=None if best_multiplier is None else round(best.score.upper * best_multiplier, 6),
            )
        )
    value = {
        "median": lambda r: r.median,
        "minimum": lambda r: r.minimum,
        "ceiling": lambda r: r.maximum,
        "upside": lambda r: r.upside,
        "age": lambda r: r.candidate.age,
        "scouted": lambda r: r.candidate.scouting_knowledge,
        "known": lambda r: r.known_attributes + r.ranged_attributes,
        "name": lambda r: r.candidate.name.casefold(),
        "role": lambda r: r.role_name.casefold(),
        "adjusted": lambda r: r.adjusted_median,
        "familiarity": lambda r: r.familiarity,
    }[sort]
    # Three stable passes so ties fall back to a sensible order in either
    # direction: name, then median (best first), then the chosen column.
    ordered = sorted(rankings, key=lambda r: (r.candidate.name.casefold(), r.candidate.id))
    ordered.sort(key=lambda r: -r.median)
    present = [r for r in ordered if value(r) is not None]
    missing = [r for r in ordered if value(r) is None]
    present.sort(key=value, reverse=descending)
    return tuple(present + missing)


def filter_scouting_candidates(
    candidates: Sequence[ScoutingCandidate],
    filters: ScoutingFilters,
) -> tuple[ScoutingCandidate, ...]:
    """Browse candidates by position and visible factual filters, without a role.

    Score, visibility, and ceiling filters intentionally require a role model,
    so this function does not apply them. It exists for the valid first step of
    recruitment: "who can play DR?" before deciding which DR role is wanted.
    """
    filtered: list[ScoutingCandidate] = []
    for candidate in candidates:
        positions = candidate.positions_for(
            include_raw_external_positions=filters.include_raw_external_positions
        )
        if filters.position and filters.position not in positions:
            continue
        if not _matches_visible_filters(candidate, filters):
            continue
        filtered.append(candidate)
    return tuple(sorted(filtered, key=lambda item: (item.name.casefold(), item.id)))


def available_fact_values(candidates: Sequence[ScoutingCandidate]) -> dict[str, tuple[str, ...]]:
    """Dynamic filter choices supplied by the capture, e.g. FM search facts."""
    values: dict[str, set[str]] = {}
    for candidate in candidates:
        for key, value in (candidate.facts or {}).items():
            if value:
                values.setdefault(key, set()).add(value)
    return {key: tuple(sorted(items, key=str.casefold)) for key, items in sorted(values.items())}


def _matches_visible_filters(candidate: ScoutingCandidate, filters: ScoutingFilters) -> bool:
    if filters.scouted_only and not candidate.is_scouted():
        return False
    if not _matches_market(candidate, filters):
        return False
    if filters.minimum_age is not None and (candidate.age is None or candidate.age < filters.minimum_age):
        return False
    if filters.maximum_age is not None and (candidate.age is None or candidate.age > filters.maximum_age):
        return False
    if filters.name_contains and filters.name_contains.casefold() not in candidate.name.casefold():
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


def _string_list(
    raw: Mapping[str, Any], name: str, *, default: list[str] | None = None
) -> list[str]:
    value = raw.get(name, default)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise TypeError(f"scouting candidate {name} must be a string list")
    return value
