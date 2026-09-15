#!/usr/bin/env python3
"""Research-backed mapping from FM20's raw position-familiarity byte to its
in-game category label.

Empirically confirmed against the in-game position diagram, for the owned
squad only, by checking specific players' specific positions against what
FM's own UI showed (see docs/phases/03-information-visibility/
03.2-fm-representation-research.md, "Position familiarity"). This module
fails closed for any raw value outside the confirmed bands rather than
guessing a boundary -- when that happens, check that exact player's
position diagram in FM and extend the confirmed table below.

Standalone and deliberately not wired into the domain model or scoring
yet. Whether position familiarity is gated by manager knowledge the same
way attributes are, or always visible regardless of scouting (which is
the user's own experience of FM, not yet independently verified against
this build), is still open -- see the same doc section. This module only
turns a raw byte into a label; it makes no claim about when reading that
byte for an external, unscouted player is appropriate.
"""

from __future__ import annotations

from enum import StrEnum


class PositionFamiliarity(StrEnum):
    NATURAL = "natural"
    ACCOMPLISHED = "accomplished"
    COMPETENT = "competent"
    UNCONVINCING = "unconvincing"
    INEFFECTUAL = "ineffectual"


class UnconfirmedPositionRating(ValueError):
    """A raw position-familiarity byte has no confirmed category mapping.

    Known gaps, as of 14 September 2026: raw 2-8 (below the confirmed
    Unconvincing band) and raw 17-18 (between confirmed Accomplished and
    Natural). Resolve by checking this exact player's position diagram in
    FM, then add the confirmed value to _CONFIRMED_BANDS -- do not widen
    an existing band to cover it without checking.
    """

    def __init__(self, raw_value: int):
        super().__init__(
            f"raw position-familiarity value {raw_value} has no confirmed "
            "category (known gaps: 2-8, 17-18); check this player's "
            "position diagram in FM and extend the confirmed bands"
        )
        self.raw_value = raw_value


# Empirically confirmed raw-value -> category bands. Each entry's range is
# only as wide as what has actually been checked against the UI; the gaps
# above are deliberately absent rather than folded into a neighbouring band.
_CONFIRMED_BANDS: tuple[tuple[range, PositionFamiliarity], ...] = (
    (range(19, 21), PositionFamiliarity.NATURAL),        # 19-20
    (range(15, 17), PositionFamiliarity.ACCOMPLISHED),   # 15-16
    (range(12, 15), PositionFamiliarity.COMPETENT),      # 12-14
    (range(9, 12), PositionFamiliarity.UNCONVINCING),    # 9-11
    (range(1, 2), PositionFamiliarity.INEFFECTUAL),      # 1
)


def position_familiarity(raw_value: int) -> PositionFamiliarity:
    """Map a raw 1-20 position-familiarity byte to its confirmed category.

    Raises UnconfirmedPositionRating for any value not yet empirically
    checked against the in-game position diagram, rather than guessing.
    """
    if not 1 <= raw_value <= 20:
        raise ValueError(f"position-familiarity byte must be 1-20, got {raw_value}")
    for band, category in _CONFIRMED_BANDS:
        if raw_value in band:
            return category
    raise UnconfirmedPositionRating(raw_value)
