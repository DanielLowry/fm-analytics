"""Decode only the manager-visible portion of FM20's render result."""

from __future__ import annotations

from fm_analytics.domain.models import AttributeObservation, Visibility


UNKNOWN_BOUND = 0xFF
ATTRIBUTE_MINIMUM = 1
ATTRIBUTE_MAXIMUM = 20


def decode_visible_bound_bytes(lower: int, upper: int) -> AttributeObservation:
    """Map FM's visible bound bytes to the strict domain representation.

    The render structure also contains a third byte which can retain the true
    attribute even when FM displays no value. This API intentionally cannot
    accept that byte.
    """

    _validate_byte(lower, "lower")
    _validate_byte(upper, "upper")

    if lower == UNKNOWN_BOUND and upper == UNKNOWN_BOUND:
        return AttributeObservation(visibility=Visibility.UNKNOWN)
    if UNKNOWN_BOUND in (lower, upper):
        raise ValueError("visible bounds must use two unknown sentinels")
    if not ATTRIBUTE_MINIMUM <= lower <= ATTRIBUTE_MAXIMUM:
        raise ValueError("visible lower bound must be between 1 and 20")
    if not ATTRIBUTE_MINIMUM <= upper <= ATTRIBUTE_MAXIMUM:
        raise ValueError("visible upper bound must be between 1 and 20")
    if lower > upper:
        raise ValueError("visible lower bound cannot exceed upper bound")
    if lower == upper:
        return AttributeObservation(visibility=Visibility.KNOWN, value=lower)
    return AttributeObservation(
        visibility=Visibility.RANGE,
        minimum=lower,
        maximum=upper,
    )


def _validate_byte(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= 0xFF:
        raise ValueError(f"visible {name} bound must be a byte")
