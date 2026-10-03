"""Presentation conventions shared by the web views (never football scoring)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from fm_analytics.analytics.catalogue import FootballCatalogue

# Defensive line to attacking line, left to right within each line.
POSITION_ORDER = (
    "GK", "DL", "DCL", "DC", "DCR", "DR", "WBL", "DMCL", "DMC", "DM", "DMCR", "WBR",
    "ML", "MCL", "MC", "MCR", "MR", "AML", "AMCL", "AMC", "AMCR", "AMR",
    "STL", "STCL", "STC", "ST", "STCR", "STR",
)


def position_key(position: str) -> tuple[int, str]:
    """Unknown positions remain visible, after the recognised pitch positions."""
    key = position.strip().upper().replace("_", "").replace("-", "")
    return (POSITION_ORDER.index(key) if key in POSITION_ORDER else len(POSITION_ORDER), key)


def ordered_positions(positions: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(positions, key=position_key))


def position_role_choices(catalogue: FootballCatalogue) -> dict[str, tuple[tuple[str, str], ...]]:
    """Catalogue eligibility for dependent selectors, with no player scoring."""
    roles = tuple(sorted(((key, role.name) for key, role in catalogue.roles.items()), key=lambda item: item[1]))
    positions = ordered_positions({position for role in catalogue.roles.values() for position in role.eligible_positions})
    return {
        "": roles,
        **{position: tuple((key, name) for key, name in roles if position in catalogue.roles[key].eligible_positions)
           for position in positions},
    }


def cell_details(summary: str, text: str | Iterable[str]) -> str:
    """A short, keyboard-accessible label with the full evidence on demand."""
    points = [text] if isinstance(text, str) else list(text)
    return (
        "<details class='fm-cell-details'><summary>" + html.escape(summary) + "</summary>"
        "<ul>" + "".join("<li>" + html.escape(point) + "</li>" for point in points if point)
        + "</ul></details>"
    )
