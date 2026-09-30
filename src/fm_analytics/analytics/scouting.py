"""Visibility-aware ranking and filtering for external scouting candidates.

Manager-visible observations are the default. The sole exception is an
explicitly labelled raw external-position path, enabled only after the product
owner accepted its documented short-term visibility gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Mapping, MutableMapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.role_scoring import RoleScore, score_role
from fm_analytics.analytics.scouting_candidate import ScoutingCandidate
from fm_analytics.analytics.xi_models import FamiliarityPolicy
from fm_analytics.domain import Visibility


class ScoutRecommendation(StrEnum):
    PROVEN_FIT = "proven-fit"
    SCOUT_TO_DECIDE = "scout-to-decide"
    SCOUT_FIRST = "scout-first"
    UNLIKELY = "unlikely"


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


def is_realistic_trial_candidate(candidate: "ScoutingCandidate") -> bool:
    """Whether today's capture gives a concrete reason a trial is attainable."""
    months = contract_months_left(candidate)
    return bool(
        candidate.in_current_feed
        and candidate.in_player_search is True
        and (
            candidate.transfer_interest is not None
            or candidate.loan_interest is not None
            or is_free_agent(candidate)
            or is_transfer_listed(candidate)
            or (months is not None and months <= 6)
        )
    )


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
    tactic_key: str | None = None
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
    # Off by default, so both tabs show what FM shows today. On, it adds back
    # every player who has dropped off the scouting list since the app first
    # saw him -- "everyone ever scouted" (product owner, 27 September 2026).
    include_former_scouted: bool = False
    market: str = "any"
    expiring_months: int = 6
    # Real, manager-visible transfer value (FM's own Value column). Not a
    # stand-in for interest -- docs/frida-discoverability.md found value alone
    # does not separate FM's interested players from the rest -- kept because
    # value itself is worth filtering on regardless.
    maximum_value: int | None = None
    # "any" | "interested" | "not_interested" against FM's own transfer/loan
    # interest rules, run read-only in the sandbox (tools.fm20_sandbox_queries).
    # "interested" includes both "yes" and the relaxed-margin "maybe".
    transfer_interest: str = "any"
    loan_interest: str = "any"
    ranking_sort: str = "median"
    ranking_descending: bool | None = None
    facts: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        for name, value in (("transfer interest", self.transfer_interest), ("loan interest", self.loan_interest)):
            if value not in {"any", "interested", "not_interested"}:
                raise ValueError(f"{name} filter is invalid")
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
    def median(self) -> float:
        return self.role_score.median

    @property
    def visibility_summary(self) -> str:
        if not self.candidate.current_attributes_captured:
            return "Not captured from FM"
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
        if not matches_information_filters(
            filters,
            captured=candidate.current_attributes_captured,
            known=known, ranged=ranged, unknown=unknown,
            floor=score.score.lower, ceiling=score.score.upper,
        ):
            continue
        recommendation = _recommendation(score, known, ranged, unknown, filters)
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


POSITION_RANKING_SORTS = {
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
    "value": "Transfer value",
}
TACTIC_RANKING_SORTS = {
    "tactic_gain": "XI gain (estimate)",
    "tactic_floor_gain": "XI gain (floor)",
    "tactic_ceiling_gain": "XI gain (ceiling)",
    "tactic_score": "Projected tactic score",
    "tactic_fit": "Player fit in tactic",
    "trial_priority": "Trial priority",
}
# With a role chosen the table is one role's targets, so "best role" and the
# position-familiarity columns do not exist; "priority" is the scouting order
# (proven fits, then scout-first, then scout-to-decide, best floor first).
ROLE_TARGET_SORTS = {
    "priority": "Scouting priority",
    **{
        key: label
        for key, label in POSITION_RANKING_SORTS.items()
        if key not in {"role", "adjusted", "familiarity"}
    },
}
# Only the sorts that have a column in the tactic table: the tactic-specific
# ones plus the columns every view shares.
TACTIC_MODE_SORTS = TACTIC_RANKING_SORTS | {
    key: label
    for key, label in POSITION_RANKING_SORTS.items()
    if key in {"age", "scouted", "known", "name", "role", "value"}
}
RANKING_SORTS = POSITION_RANKING_SORTS | TACTIC_RANKING_SORTS | ROLE_TARGET_SORTS

# Which table the scouting page shows decides which columns exist, and so which
# sorts are meaningful. Every mode's table is sortable on every column it shows.
SORTS_BY_MODE: dict[str, dict[str, str]] = {
    "ranking": POSITION_RANKING_SORTS,
    "role": ROLE_TARGET_SORTS,
    "tactic": TACTIC_MODE_SORTS,
}
DEFAULT_SORT_BY_MODE = {"ranking": "median", "role": "priority", "tactic": "tactic_gain"}
# Text columns and age read naturally smallest/first-first; everything that is
# a score or an amount of information reads best largest-first.
_ASCENDING_BY_DEFAULT = frozenset({"age", "name", "role", "value"})


def default_descending(sort: str) -> bool:
    return sort not in _ASCENDING_BY_DEFAULT


def scouting_mode(tactic_key: str | None, role_key: str | None) -> str:
    """Which table a set of filters produces: ``tactic``, ``role`` or ``ranking``."""
    return "tactic" if tactic_key else "role" if role_key else "ranking"


def sort_for_mode(sort: str | None, mode: str) -> str:
    """``sort`` if that column exists in this mode's table, else the mode's default."""
    return sort if sort in SORTS_BY_MODE[mode] else DEFAULT_SORT_BY_MODE[mode]


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


# The attributes FM only shows for goalkeepers, and the ones it only shows for
# outfield players (FM20's goalkeeper visibility profile has none of these).
_GOALKEEPING_ATTRIBUTES = frozenset({
    "aerialReach", "commandOfArea", "communication", "handling", "kicking",
    "oneOnOnes", "reflexes", "rushingOut", "throwing",
})
_OUTFIELD_ONLY_ATTRIBUTES = frozenset({
    "corners", "crossing", "dribbling", "finishing", "heading", "longShots",
    "marking", "tackling",
})


def _plays_in_goal(attributes: Mapping[str, object]) -> bool | None:
    """Whether his attribute sheet is a goalkeeper's; None when it cannot say.

    A set speaks for him when FM shows a value from it, and against him when
    its attributes are missing altogether (the formula-based capture omitted
    the other family's set). A set that is present but entirely unknown says
    nothing: FM's own sandboxed answer returns the other family's attributes
    as unknown, exactly like an unscouted one, so an outfielder's sheet
    carries every goalkeeping name. A well-scouted player can show both sets
    (an outfielder's Handling of 3); then neither wins and the scores decide.
    """
    def shown(names: frozenset[str]) -> bool:
        return any(
            name in attributes and attributes[name].visibility is not Visibility.UNKNOWN
            for name in names
        )

    def missing(names: frozenset[str]) -> bool:
        return not any(name in attributes for name in names)

    keeper = shown(_GOALKEEPING_ATTRIBUTES) or missing(_OUTFIELD_ONLY_ATTRIBUTES)
    outfield = shown(_OUTFIELD_ONLY_ATTRIBUTES) or missing(_GOALKEEPING_ATTRIBUTES)
    return keeper if keeper != outfield else None


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
    cache: MutableMapping[tuple[object, ...], tuple[ScoutingCandidate, PositionRanking | None]] | None = None,
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

    ``sort`` may be any key of ``POSITION_RANKING_SORTS``; ``descending``
    defaults to the natural direction for that column. A player missing the
    sorted value (no age, never scouted) always goes last, whichever direction
    is chosen.

    Scoring a player against every role is the expensive part and depends only
    on the player and the arguments above, never on the sort or on who else is
    in the list. A caller that re-ranks the same pool as filters and sorts
    change can pass one ``cache`` mapping (used with a single catalogue) and
    each player is then scored once per argument set. An entry is reused only
    for the very same candidate object, so a fresh capture is never served a
    stale score.
    """
    if sort not in POSITION_RANKING_SORTS:
        raise ValueError(f"sort must be one of {sorted(POSITION_RANKING_SORTS)}")
    if descending is None:
        descending = default_descending(sort)
    all_roles = list(catalogue.roles.values())
    # A player with no visible attributes scores identically in a role whoever
    # he is, and most of a Player Search pool is exactly that.
    empty_scores: dict[str, RoleScore] = {}
    rankings: list[PositionRanking] = []
    for candidate in candidates:
        key = (candidate.id, position, include_raw_external_positions, familiarity_policy)
        cached = cache.get(key) if cache is not None else None
        if cached is not None and cached[0] is candidate:
            ranking = cached[1]
        else:
            ranking = _rank_one(
                candidate, all_roles, position, empty_scores,
                include_raw_external_positions=include_raw_external_positions,
                familiarity_policy=familiarity_policy,
            )
            if cache is not None:
                if len(cache) >= _RANK_CACHE_LIMIT:
                    cache.clear()
                cache[key] = (candidate, ranking)
        if ranking is not None:
            rankings.append(ranking)
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
        "value": lambda r: r.candidate.value,
    }[sort]
    return _order(rankings, value, descending)


# Roughly 84 roles per player per position; enough for a whole Player Search
# pool at the handful of positions a manager actually looks at.
_RANK_CACHE_LIMIT = 150_000


def _order(items, value, descending: bool):
    """Order by ``value``: ties by name then best median, missing values last.

    Three stable passes so ties fall back to a sensible order in either
    direction. ``items`` need ``candidate`` and ``median``.
    """
    ordered = sorted(items, key=lambda r: (r.candidate.name.casefold(), r.candidate.id))
    ordered.sort(key=lambda r: -r.median)
    present = [r for r in ordered if value(r) is not None]
    missing = [r for r in ordered if value(r) is None]
    present.sort(key=value, reverse=descending)
    return tuple(present + missing)


def _rank_one(
    candidate: ScoutingCandidate,
    all_roles: list,
    position: str | None,
    empty_scores: dict[str, RoleScore],
    *,
    include_raw_external_positions: bool,
    familiarity_policy: FamiliarityPolicy | None,
) -> PositionRanking | None:
    if position:
        roles = [role for role in all_roles if position in role.eligible_positions]
    else:
        roles = all_roles
        if candidate.attributes:
            # FM only shows the goalkeeping attributes (Handling, Reflexes,
            # ...) for a goalkeeper and the outfield-only ones (Heading,
            # Marking, Tackling, ...) for everyone else, so which set he has
            # values in says which kind of player he is. It is applied first
            # because it comes from FM's visibility, not from a position
            # label. Scoring the other set as "unknown, so mid-scale"
            # otherwise let a goalkeeper role win for a defender on paper.
            keeper = _plays_in_goal(candidate.attributes)
            if keeper is not None:
                roles = [role for role in roles if ("GK" in role.eligible_positions) == keeper] or roles
        own = set(candidate.positions_for(
            include_raw_external_positions=include_raw_external_positions
        ))
        roles = [role for role in roles if own.intersection(role.eligible_positions)] or roles
    if not roles:
        return None
    ratings = candidate.raw_position_familiarity if familiarity_policy else None
    scored = []
    for role in roles:
        if candidate.attributes:
            score = score_role(role, candidate.attributes)
        else:
            score = empty_scores.get(role.key) or empty_scores.setdefault(
                role.key, score_role(role, candidate.attributes)
            )
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
    return PositionRanking(
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


def matches_information_filters(
    filters: ScoutingFilters,
    *,
    captured: bool,
    known: int,
    ranged: int,
    unknown: int,
    floor: float,
    ceiling: float,
) -> bool:
    """The visibility / floor / ceiling filters, for one already-scored player.

    The one definition shared by every table that scores players, so a filter
    means the same thing whichever of them is showing. ``floor``/``ceiling``
    are that table's own lower and upper bound on the score.
    """
    if filters.visibility != "any":
        # "Nothing known" is a statement about FM's captured answer, not
        # a bucket for players whose attribute visibility was never read.
        if not captured:
            return False
        if filters.visibility == "known" and (ranged or unknown):
            return False
        if filters.visibility == "partial" and not ranged:
            return False
        if filters.visibility == "unknown" and known + ranged:
            return False
    if filters.minimum_floor is not None and floor < filters.minimum_floor:
        return False
    if (
        filters.minimum_ceiling is not None
        and ceiling < filters.minimum_ceiling
        and not filters.include_unlikely
    ):
        return False
    return True


def filter_position_rankings(
    rankings: Sequence[PositionRanking], filters: ScoutingFilters
) -> tuple[PositionRanking, ...]:
    """Apply the visibility, floor and ceiling filters to ranked players."""
    return tuple(
        item for item in rankings
        if matches_information_filters(
            filters,
            captured=item.candidate.current_attributes_captured,
            known=item.known_attributes, ranged=item.ranged_attributes,
            unknown=item.unknown_attributes,
            floor=item.minimum, ceiling=item.maximum,
        )
    )


def sort_scouting_assessments(
    assessments: Sequence[ScoutingAssessment],
    *,
    sort: str = "priority",
    descending: bool | None = None,
) -> tuple[ScoutingAssessment, ...]:
    """Order one role's targets by any column of its table.

    ``priority`` is the scouting order (``descending`` = best first). Like
    ``rank_for_position``, a player missing the sorted value goes last in
    either direction.
    """
    if sort not in ROLE_TARGET_SORTS:
        raise ValueError(f"sort must be one of {sorted(ROLE_TARGET_SORTS)}")
    if descending is None:
        descending = default_descending(sort)
    if sort == "priority":
        ordered = sorted(assessments, key=_sort_key)
        return tuple(ordered if descending else reversed(ordered))
    value = {
        "median": lambda a: a.median,
        "minimum": lambda a: a.role_score.score.lower,
        "ceiling": lambda a: a.role_score.score.upper,
        "upside": lambda a: a.role_score.score.upper - a.role_score.median,
        "age": lambda a: a.candidate.age,
        "scouted": lambda a: a.candidate.scouting_knowledge,
        "known": lambda a: a.known_attributes + a.ranged_attributes,
        "name": lambda a: a.candidate.name.casefold(),
        "value": lambda a: a.candidate.value,
    }[sort]
    return _order(assessments, value, descending)


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


def filter_trial_priority_candidates(
    candidates: Sequence[ScoutingCandidate], filters: ScoutingFilters
) -> tuple[ScoutingCandidate, ...]:
    """Keep the user's filters, adding the trial view's realistic/gettable rule."""
    return tuple(
        item for item in filter_scouting_candidates(candidates, filters)
        if is_realistic_trial_candidate(item)
    )


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
    # Known only from the manager's own history: not in any list FM shows
    # today, so he joins the "everyone ever scouted" view and no other.
    if not candidate.in_current_feed and not filters.include_former_scouted:
        return False
    if candidate.dropped_from_scout_reports and not filters.include_former_scouted:
        # Off FM's scouting list now. On the Scouted tab that settles it;
        # under All players he still belongs while FM's Player Search lists him.
        if filters.scouted_only or not candidate.in_player_search:
            return False
    if not _matches_market(candidate, filters):
        return False
    for expected, actual in (
        (filters.transfer_interest, candidate.transfer_interest),
        (filters.loan_interest, candidate.loan_interest),
    ):
        if expected == "interested" and actual is None:
            return False
        if expected == "not_interested" and actual is not None:
            return False
    if filters.maximum_value is not None and (
        candidate.value is None or candidate.value > filters.maximum_value
    ):
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
