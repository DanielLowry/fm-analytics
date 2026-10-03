"""The scouting candidate: one discoverable player, as the scouting feed describes him.

Split out of ``analytics/scouting.py`` on 27 September 2026, when the
Scouted-tab fix pushed that module past the line-size targets. This half is
the record and its reading from the feed's JSON contract (written by
``tools/fm20_scouting_feed_contract.py``); ranking and filtering the records
stays in ``scouting.py``, which re-exports ``ScoutingCandidate`` so existing
imports keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from fm_analytics.domain import AttributeObservation, Visibility


# The attributes FM only shows for goalkeepers, and the ones it only shows for
# outfield players (FM20's goalkeeper visibility profile has none of these).
GOALKEEPING_ATTRIBUTES = frozenset({
    "aerialReach", "commandOfArea", "communication", "handling", "kicking",
    "oneOnOnes", "reflexes", "rushingOut", "throwing",
})
OUTFIELD_ONLY_ATTRIBUTES = frozenset({
    "corners", "crossing", "dribbling", "finishing", "heading", "longShots",
    "marking", "tackling",
})


def plays_in_goal(attributes: Mapping[str, object]) -> bool | None:
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

    keeper = shown(GOALKEEPING_ATTRIBUTES) or missing(OUTFIELD_ONLY_ATTRIBUTES)
    outfield = shown(OUTFIELD_ONLY_ATTRIBUTES) or missing(GOALKEEPING_ATTRIBUTES)
    return keeper if keeper != outfield else None


@dataclass(frozen=True)
class HistoricalReading:
    """When the manager last saw an attribute value FM no longer shows.

    ``observed_on`` is when the value was first recorded and ``last_seen_on``
    the last in-game day a capture still showed it, which is the date its age
    runs from. ``source`` is 'current' or 'last_known', as recorded.
    """

    observed_on: str
    last_seen_on: str
    source: str


@dataclass(frozen=True)
class CandidateHistory:
    """What the manager's own knowledge history added to a candidate.

    Set only by ``fm_analytics.candidate_pool``. ``attributes`` names every
    value in the candidate's ``attributes`` that came from history rather than
    the current feed; each fills a value FM currently shows as unknown or not
    at all, and is scored like any other visible value. ``profile`` is set only
    for a player missing from the current feed: his last recorded facts, for
    display. Club, contract, transfer status and value never leave it for the
    candidate's own fields, so no market filter can admit him on an old fact.

    Every date is an in-game ``YYYY-MM-DD``. A reading last seen before
    ``out_of_date_before`` is out of date.
    """

    as_of: str
    in_current_feed: bool
    out_of_date_before: str
    attributes: Mapping[str, HistoricalReading] = field(default_factory=dict)
    profile: Mapping[str, Any] | None = None
    profile_last_seen_on: str | None = None

    @property
    def oldest_seen_on(self) -> str | None:
        """The last-seen date of the stalest historical fact this candidate uses."""
        dates = [reading.last_seen_on for reading in self.attributes.values()]
        if self.profile_last_seen_on is not None:
            dates.append(self.profile_last_seen_on)
        return min(dates, default=None)

    def is_out_of_date(self, seen_on: str | None) -> bool:
        return seen_on is not None and seen_on < self.out_of_date_before

    @property
    def out_of_date(self) -> bool:
        return self.is_out_of_date(self.oldest_seen_on)


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
    # Whether the manager holds a scout report -- FM's own Scouted list. A
    # knowledge level alone (a trialist, a past opponent) is not one. None
    # for a feed older than schema 4, which could not tell the two apart.
    has_scout_report: bool | None = None
    dropped_from_scout_reports: bool = False
    # Whether FM's own Player Search lists him as of this capture; None when
    # the capture could not read Player Search (or predates schema 4).
    in_player_search: bool | None = None
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
    # "yes" (clears FM's own live interest cut-off), "maybe" (only clears the
    # product's relaxed margin below it -- see tools.fm20_sandbox_queries),
    # or None (not interested, or not captured this refresh). FM computes
    # this fresh from the manager's own reputation every time; it is never a
    # stored fact and never carried forward from an older capture.
    transfer_interest: str | None = None
    loan_interest: str | None = None
    # The game date the capture was taken at; contract expiry is measured from it.
    captured_game_date: str | None = None
    attributes_observed_at: str | None = None
    # A separately dated snapshot that was once manager-visible but is not
    # current anymore. It is presentation-only history: scoring and filters
    # always use ``attributes`` above.
    last_known_attributes: Mapping[str, AttributeObservation] | None = None
    last_known_attributes_observed_at: str | None = None
    # None for a candidate exactly as the feed describes him; see
    # ``CandidateHistory`` and ``fm_analytics.candidate_pool``.
    history: CandidateHistory | None = None

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
        if self.attributes_observed_at is not None:
            date.fromisoformat(self.attributes_observed_at)
        if self.last_known_attributes_observed_at is not None:
            date.fromisoformat(self.last_known_attributes_observed_at)
        if self.contract_end is not None:
            date.fromisoformat(self.contract_end)  # ValueError on a malformed date
        if self.transfer_interest not in (None, "yes", "maybe"):
            raise ValueError("scouting candidate transferInterest must be 'yes', 'maybe', or null")
        if self.loan_interest not in (None, "yes", "maybe"):
            raise ValueError("scouting candidate loanInterest must be 'yes', 'maybe', or null")
        if self.raw_position_familiarity is not None and any(
            not position or not isinstance(rating, int) or isinstance(rating, bool) or not 0 <= rating <= 20
            for position, rating in self.raw_position_familiarity.items()
        ):
            raise ValueError("position familiarity must map position codes to ratings from 0 to 20")
        if self.raw_position_familiarity and not any(self.raw_position_familiarity.values()):
            # FM rates every position at least 1, so all zeros is a record the
            # capture could not read, not a player who can play nowhere. Its
            # eligibility list was derived from those zeros and, before the
            # capture was fixed, always came out as GK: 403 of the 510 "raw
            # goalkeepers" in the 28 April 2020 capture were these.
            object.__setattr__(self, "raw_position_familiarity", None)
            object.__setattr__(self, "raw_positions", ())

    @property
    def in_current_feed(self) -> bool:
        """False for a player known only from the knowledge history: not currently realistic."""
        return self.history is None or self.history.in_current_feed

    def historical_reading(self, attribute: str) -> HistoricalReading | None:
        """Set when this attribute's value is history, not something FM shows now."""
        return None if self.history is None else self.history.attributes.get(attribute)

    def is_scouted(self) -> bool:
        """True for a player FM's own Scouted list would show: one with a scout report.

        This -- not a non-empty ``attributes`` -- is the correct test for
        "belongs on the Scouted tab": every candidate has attributes now, and
        a dropped player still belongs here with a warning, not with the
        general browse list. Until 27 September 2026 this was any knowledge
        level at all, which counted 714 players where FM's list showed 532;
        a feed from before then can only answer that older question.
        """
        if self.has_scout_report is not None:
            return self.has_scout_report
        return self.scouting_knowledge is not None

    @property
    def current_attributes_captured(self) -> bool:
        """Whether an empty current map is a real FM answer, not a missing read.

        A populated map is captured even in older files that predate per-field
        dates. Schema-2 captures date every attempted attribute read. A player
        dropped from current scout reports is also a known current absence;
        their older values live only in ``last_known_attributes``.
        """
        return bool(
            self.attributes
            or self.attributes_observed_at is not None
            or self.dropped_from_scout_reports
        )

    def positions_for(self, *, include_raw_external_positions: bool) -> tuple[str, ...]:
        """Return verified positions, plus accepted-gap raw positions if opted in.

        A raw position his attribute sheet contradicts is left out: FM shows the
        goalkeeping attributes only for a keeper and the outfield-only ones
        only for everyone else, so a keeper's sheet is not a DC and an
        outfielder's is not a GK, whatever the raw read says. Verified
        positions are FM's own and are never second-guessed.
        """
        if not include_raw_external_positions:
            return self.positions
        raw = self.raw_positions
        keeper = plays_in_goal(self.attributes) if raw else None
        if keeper is not None:
            raw = tuple(position for position in raw if (position == "GK") == keeper)
        return tuple(dict.fromkeys(self.positions + raw))

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScoutingCandidate":
        attributes_raw = raw.get("attributes", {})
        last_known_attributes_raw = raw.get("lastKnownAttributes", {})
        facts_raw = raw.get("facts", {})
        dropped = raw.get("droppedFromScoutReports", False)
        if not isinstance(dropped, bool):
            raise TypeError("scouting candidate droppedFromScoutReports must be a boolean")
        if (
            dropped and attributes_raw and not last_known_attributes_raw
        ):
            # Backward compatibility for schema-1 captures, which stored a
            # dropped player's stale sheet in ``attributes``. Treat it as
            # history immediately, even before the next refresh migrates the
            # JSON document itself.
            last_known_attributes_raw = attributes_raw
            attributes_raw = {}
        if (
            not isinstance(attributes_raw, Mapping)
            or not isinstance(last_known_attributes_raw, Mapping)
            or not isinstance(facts_raw, Mapping)
        ):
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
        has_scout_report = raw.get("scoutReport")
        in_player_search = raw.get("inPlayerSearch")
        for name, flag in (("scoutReport", has_scout_report), ("inPlayerSearch", in_player_search)):
            if flag is not None and not isinstance(flag, bool):
                raise TypeError(f"scouting candidate {name} must be a boolean")
        transfer_interest = raw.get("transferInterest")
        loan_interest = raw.get("loanInterest")
        for name, value in (("transferInterest", transfer_interest), ("loanInterest", loan_interest)):
            if value not in (None, "yes", "maybe"):
                raise TypeError(f"scouting candidate {name} must be 'yes', 'maybe', or null")
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
        if any(
            not isinstance(name, str) or not isinstance(value, Mapping)
            for name, value in last_known_attributes_raw.items()
        ):
            raise TypeError("last-known scouting attributes must map names to observations")
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
            attributes_observed_at=optional_text("attributesObservedAt"),
            last_known_attributes={
                str(name): AttributeObservation.from_dict(value)
                for name, value in last_known_attributes_raw.items()
            },
            last_known_attributes_observed_at=(
                optional_text("lastKnownAttributesObservedAt")
                or (
                    optional_text("attributesObservedAt")
                    if dropped and last_known_attributes_raw else None
                )
            ),
            facts=dict(facts_raw),
            scouting_knowledge=scouting_knowledge,
            has_scout_report=has_scout_report,
            dropped_from_scout_reports=dropped,
            in_player_search=in_player_search,
            raw_position_familiarity=dict(familiarity) if familiarity is not None else None,
            contract_end=optional_text("contractEnd"), contract_type=optional_text("contractType"),
            has_contract=has_contract, captured_game_date=optional_text("capturedGameDate"),
            value=raw.get("value"),
            transfer_interest=transfer_interest, loan_interest=loan_interest,
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
