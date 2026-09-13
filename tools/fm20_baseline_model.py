"""Research-only arithmetic from FM20's baseline-knowledge adjustment helper.

The relationship branch, the observer-side rating field, and the optional
bonus predicate are not mapped yet. This module must not source production
visibility decisions or infer any of those inputs from a player's club.
"""

from __future__ import annotations

import math
import struct
from enum import StrEnum


class PlayerScaleBand(StrEnum):
    """Unverified semantic bands from a player virtual 16-bit scale getter."""

    BELOW_3000 = "below-3000"
    FROM_3000 = "3000-3999"
    FROM_4000 = "4000-4999"
    FROM_5000 = "5000-or-more"


_DYNAMIC_COEFFICIENTS = {
    PlayerScaleBand.BELOW_3000: -0.05,
    PlayerScaleBand.FROM_3000: -0.10,
    PlayerScaleBand.FROM_4000: -0.15,
    PlayerScaleBand.FROM_5000: -0.20,
}


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def calculate_dynamic_relationship_base(
    *, knowledge_score: int, player_scale_band: PlayerScaleBand
) -> int:
    """Mirror the reached dynamic branch at RVA 0x15a5864--0x15a58cc.

    The branch is entered only after separate object and threshold checks.
    This function does not identify the score source or the virtual scale
    getter, and must not be used as a production visibility decision.
    """

    if type(knowledge_score) is not int or not 0 <= knowledge_score <= 100:
        raise ValueError("knowledge score must be an integer from 0 to 100")
    if not isinstance(player_scale_band, PlayerScaleBand):
        raise TypeError("player scale band must be a PlayerScaleBand")
    coefficient = _float32(_DYNAMIC_COEFFICIENTS[player_scale_band])
    product = _float32(float(knowledge_score) * coefficient)
    return 20 - math.trunc(product)


def select_observer_rating(
    *,
    player_selector: int,
    raw_at_2c: int,
    raw_at_2d: int,
) -> int:
    """Select and normalize the still-unidentified observer-side field.

    The player-side virtual selector is compared with 23 in the executable.
    This function deliberately does not name it or either rating byte.
    """

    if type(player_selector) is not int or not 0 <= player_selector <= 127:
        raise ValueError("player selector must be an integer from 0 to 127")
    for raw in (raw_at_2c, raw_at_2d):
        if type(raw) is not int or not -128 <= raw <= 127:
            raise ValueError("observer rating byte must be a signed byte")
    selected = raw_at_2c if player_selector >= 23 else raw_at_2d
    return max(1, min(20, (selected + 2) // 5))


def adjust_baseline_level(
    *,
    relationship_base: int,
    observer_rating: int,
    relationship_bonus: bool,
) -> int:
    """Mirror RVA 0x15a6210 after its unresolved inputs have been selected.

    The helper takes a relationship-derived starting level and normalizes one
    of two signed bytes on its observer-side object to a 1--20 rating. Ratings
    1--3 have a steeper penalty. A separate predicate can add 20 points.
    """

    if type(relationship_base) is not int or not 0 <= relationship_base <= 100:
        raise ValueError("relationship base must be an integer from 0 to 100")
    if type(observer_rating) is not int or not 1 <= observer_rating <= 20:
        raise ValueError("observer rating must be an integer from 1 to 20")
    if type(relationship_bonus) is not bool:
        raise TypeError("relationship bonus must be a boolean")

    delta = (observer_rating - 10) * (4 if observer_rating <= 3 else 2)
    adjusted = max(0, min(100, relationship_base + delta))
    if relationship_bonus:
        adjusted = min(100, adjusted + 20)
    return adjusted
