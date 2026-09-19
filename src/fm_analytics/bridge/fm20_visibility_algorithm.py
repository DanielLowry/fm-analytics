"""Pure, read-only portions of FM20's visible-attribute algorithm.

These functions mirror the supported executable's classification comparison
and ranged-bound construction. They do not discover manager knowledge and must
not be used until the caller has sourced every required input through a verified
manager-visible path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Mapping, Sequence

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from fm_analytics.domain.models import AttributeObservation, Visibility


@dataclass(frozen=True)
class RangeWidths:
    wide: int
    medium: int
    narrow: int


class PositionFamily(StrEnum):
    """FM20's four attribute-visibility threshold profiles."""

    GOALKEEPER = "goalkeeper"
    DEFENDER = "defender"
    MIDFIELDER = "midfielder"
    ATTACKER = "attacker"


@dataclass(frozen=True)
class VisibilityThresholds:
    range: int
    exact: int


# Values recovered from the supported FM20 20.4.4 executable's four pure
# threshold lookup functions. A zero/default branch is deliberately omitted:
# it denotes an attribute outside that position family's supported profile and
# is not evidence that the attribute is publicly exact.
_RANGE_THRESHOLDS: Final[Mapping[PositionFamily, Mapping[str, int]]] = {
    PositionFamily.GOALKEEPER: {
        "aerialReach": 8,
        "commandOfArea": 4,
        "communication": 17,
        "handling": 3,
        "kicking": 5,
        "reflexes": 9,
        "rushingOut": 10,
        "throwing": 6,
        "oneOnOnes": 11,
        "passing": 24,
        "technique": 31,
        "firstTouch": 23,
        "aggression": 30,
        "anticipation": 18,
        "bravery": 16,
        "vision": 37,
        "decisions": 19,
        "determination": 34,
        "flair": 38,
        "offTheBall": 36,
        "positioning": 14,
        "teamwork": 32,
        "workRate": 29,
        "composure": 22,
        "concentration": 15,
        "acceleration": 26,
        "agility": 13,
        "balance": 20,
        "pace": 27,
        "stamina": 33,
        "strength": 25,
        "jumpingReach": 28,
        "naturalFitness": 35,
    },
    PositionFamily.DEFENDER: {
        "crossing": 36,
        "dribbling": 26,
        "finishing": 38,
        "heading": 4,
        "longShots": 29,
        "marking": 6,
        "passing": 11,
        "tackling": 3,
        "technique": 18,
        "firstTouch": 9,
        "corners": 34,
        "aggression": 17,
        "anticipation": 14,
        "bravery": 25,
        "vision": 31,
        "decisions": 15,
        "determination": 8,
        "flair": 32,
        "offTheBall": 30,
        "positioning": 7,
        "teamwork": 19,
        "workRate": 16,
        "composure": 22,
        "concentration": 23,
        "acceleration": 12,
        "agility": 28,
        "balance": 27,
        "pace": 13,
        "stamina": 20,
        "strength": 10,
        "jumpingReach": 5,
        "naturalFitness": 24,
    },
    PositionFamily.MIDFIELDER: {
        "crossing": 23,
        "dribbling": 25,
        "finishing": 20,
        "heading": 13,
        "longShots": 9,
        "marking": 32,
        "passing": 6,
        "tackling": 4,
        "technique": 16,
        "firstTouch": 3,
        "corners": 36,
        "aggression": 15,
        "anticipation": 33,
        "bravery": 27,
        "vision": 7,
        "decisions": 34,
        "determination": 21,
        "flair": 8,
        "offTheBall": 29,
        "positioning": 24,
        "teamwork": 11,
        "workRate": 10,
        "composure": 30,
        "concentration": 31,
        "acceleration": 18,
        "agility": 28,
        "balance": 26,
        "pace": 19,
        "stamina": 12,
        "strength": 5,
        "jumpingReach": 14,
        "naturalFitness": 22,
    },
    PositionFamily.ATTACKER: {
        "crossing": 21,
        "dribbling": 15,
        "finishing": 10,
        "heading": 3,
        "longShots": 12,
        "marking": 38,
        "passing": 9,
        "tackling": 33,
        "technique": 11,
        "firstTouch": 7,
        "corners": 35,
        "aggression": 20,
        "anticipation": 32,
        "bravery": 28,
        "vision": 16,
        "decisions": 23,
        "determination": 19,
        "flair": 17,
        "offTheBall": 13,
        "positioning": 37,
        "teamwork": 25,
        "workRate": 14,
        "composure": 24,
        "concentration": 31,
        "acceleration": 5,
        "agility": 29,
        "balance": 27,
        "pace": 6,
        "stamina": 18,
        "strength": 8,
        "jumpingReach": 4,
        "naturalFitness": 26,
    },
}


def thresholds_for_attribute(
    position_family: PositionFamily,
    attribute: str,
) -> VisibilityThresholds:
    """Return the supported build's thresholds, failing closed on gaps.

    Position-family selection is intentionally an explicit input for this
    low-level lookup. Use :func:`select_position_family` with FM's raw position
    ratings rather than guessing from its display labels.
    """

    if not isinstance(position_family, PositionFamily):
        raise TypeError("position family must be a PositionFamily")
    if type(attribute) is not str or not attribute:
        raise ValueError("attribute must be a non-empty string")
    try:
        range_threshold = _RANGE_THRESHOLDS[position_family][attribute]
    except KeyError as error:
        raise ValueError(
            f"attribute {attribute!r} is unsupported for {position_family.value}"
        ) from error
    return VisibilityThresholds(
        range=range_threshold,
        exact=range_threshold + 38,
    )


def calculate_effective_knowledge(
    *,
    explicit_knowledge: int,
    baseline_knowledge: int,
    report_knowledge: int | None,
) -> int:
    """Combine the three knowledge inputs used by FM20's final comparison."""

    _bounded(explicit_knowledge, "explicit knowledge", 0, 100)
    _bounded(baseline_knowledge, "baseline knowledge", 0, 100)
    if report_knowledge is not None:
        _bounded(report_knowledge, "report knowledge", 0, 100)
    return max(
        explicit_knowledge,
        baseline_knowledge,
        report_knowledge or 0,
    )


def select_position_family(position_ratings: Sequence[int]) -> PositionFamily:
    """Select FM20's threshold profile from its 15 position ratings.

    The supported executable checks Goalkeeper first, then Striker and the
    three Attacking Midfielder ratings, then the three Defender ratings. A
    player that clears none of those checks uses the midfield profile. The
    threshold is 18, which is intentionally stricter than the UI position
    label threshold used elsewhere in the bridge.
    """

    if len(position_ratings) != 15:
        raise ValueError("position ratings must contain exactly 15 values")
    for rating in position_ratings:
        _bounded(rating, "position rating", 1, 20)

    if position_ratings[0] >= 18:
        return PositionFamily.GOALKEEPER
    if position_ratings[12] >= 18 or max(position_ratings[9:12]) >= 18:
        return PositionFamily.ATTACKER
    if max(position_ratings[2:5]) >= 18:
        return PositionFamily.DEFENDER
    return PositionFamily.MIDFIELDER


def build_visible_observation(
    *,
    attribute: str,
    exact_value: int,
    player_row_id: int,
    display_attribute_id: int,
    position_ratings: Sequence[int],
    age: int,
    effective_knowledge: int,
    report_quality_sum: int | None,
) -> AttributeObservation:
    """Compose the verified FM20 visibility steps into one public result."""

    _bounded(exact_value, "exact value", 1, 20)
    family = select_position_family(position_ratings)
    thresholds = thresholds_for_attribute(family, attribute)
    visibility = classify_visibility(
        effective_knowledge,
        thresholds.range,
        thresholds.exact,
    )
    if visibility is Visibility.UNKNOWN:
        return AttributeObservation(visibility=Visibility.UNKNOWN)
    if visibility is Visibility.KNOWN:
        return AttributeObservation(
            visibility=Visibility.KNOWN,
            value=exact_value,
        )
    widths = calculate_range_widths(
        age=age,
        effective_knowledge=effective_knowledge,
        report_quality_sum=report_quality_sum,
    )
    return build_ranged_observation(
        exact_value=exact_value,
        player_row_id=player_row_id,
        display_attribute_id=display_attribute_id,
        widths=widths,
    )


def classify_visibility(
    effective_knowledge: int,
    range_threshold: int,
    exact_threshold: int,
) -> Visibility:
    """Mirror FM20's final two-threshold comparison."""

    _bounded(effective_knowledge, "effective knowledge", 0, 100)
    _bounded(range_threshold, "range threshold", 1, 100)
    _bounded(exact_threshold, "exact threshold", 1, 100)
    if range_threshold > exact_threshold:
        raise ValueError("range threshold cannot exceed exact threshold")
    if effective_knowledge >= exact_threshold:
        return Visibility.KNOWN
    if effective_knowledge >= range_threshold:
        return Visibility.RANGE
    return Visibility.UNKNOWN


def calculate_range_widths(
    *,
    age: int,
    effective_knowledge: int,
    report_quality_sum: int | None,
) -> RangeWidths:
    """Calculate FM20's three uncertainty widths for a ranged attribute.

    ``report_quality_sum`` is the sum of the two normalized 1--20 rating
    bytes FM reads from the object its report hands back (see
    ``tools.fm20_scouted_attributes`` for where those live). ``None`` means no
    report object, which FM treats as a sum of zero -- so knowledge alone then
    decides the bracket.

    Corrected 19 September 2026. The four brackets were previously written as
    ``quality <= X **or** knowledge <= Y``, which is the opposite of what the
    executable does. The comparisons at RVA 0x15a4c86-0x15a4cd8 skip a bracket
    when *either* value is over its limit, so a bracket applies only when
    *both* are within it: the effective bracket is the tighter of the one the
    quality picks and the one the knowledge picks. Checked against FM's own
    exported ranges for four real scouted players (44 attributes): with the
    right inputs the widths below reproduce every one of them exactly.
    """

    _bounded(age, "age", 0, 100)
    _bounded(effective_knowledge, "effective knowledge", 0, 100)
    if report_quality_sum is not None:
        _bounded(report_quality_sum, "report quality sum", 2, 40)

    if age < 18:
        wide, medium = 4, 2
    elif age < 21:
        wide, medium = 3, 2
    else:
        wide, medium = 2, 1
    narrow = 1
    quality = report_quality_sum or 0

    if quality <= 11 and effective_knowledge <= 20:
        wide, medium, narrow = wide + 4, medium + 2, 2
    elif quality <= 19 and effective_knowledge <= 30:
        wide, medium, narrow = wide + 3, medium + 2, 2
    elif quality <= 24 and effective_knowledge <= 40:
        wide, medium, narrow = wide + 2, medium + 1, 2
    elif quality <= 29 and effective_knowledge <= 50:
        wide, medium = wide + 1, medium + 1
    return RangeWidths(wide=wide, medium=medium, narrow=narrow)


def build_ranged_observation(
    *,
    exact_value: int,
    player_row_id: int,
    display_attribute_id: int,
    widths: RangeWidths,
) -> AttributeObservation:
    """Build the public bounds FM uses after classifying an attribute ranged."""

    _bounded(exact_value, "exact value", 1, 20)
    _bounded(player_row_id, "player row ID", 0, 0x7FFFFFFF)
    _bounded(display_attribute_id, "display attribute ID", 0, 0x7F)
    for name, value in vars(widths).items():
        _bounded(value, f"{name} width", 1, 20)

    patterns = (
        (-widths.wide, widths.narrow),
        (-widths.narrow, widths.wide),
        (-widths.wide, 0),
        (0, widths.wide),
        (-widths.medium, widths.medium),
        (-widths.medium, widths.narrow),
        (-widths.narrow, widths.medium),
    )
    lower_delta, upper_delta = patterns[
        (player_row_id + display_attribute_id) % len(patterns)
    ]
    lower = max(1, exact_value + lower_delta)
    upper = min(20, exact_value + upper_delta)
    return decode_visible_bound_bytes(lower, upper)


def _bounded(value: int, name: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
