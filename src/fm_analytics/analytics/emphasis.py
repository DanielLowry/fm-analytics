"""Apply tactic and opponent attribute-emphasis deltas to role definitions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Mapping

from fm_analytics.analytics.role_scoring import RoleAttribute, RoleDefinition
from fm_analytics.analytics.role_weights import MAX_EFFECTIVE_WEIGHT


def sum_emphasis(*emphases: Mapping[str, int]) -> dict[str, int]:
    total: dict[str, int] = {}
    for emphasis in emphases:
        for attribute, delta in emphasis.items():
            total[attribute] = total.get(attribute, 0) + delta
    return {attribute: delta for attribute, delta in total.items() if delta}


def introduced_emphasis(blocks: Iterable[Any]) -> dict[str, int]:
    """Positive deltas explicitly allowed to create absent role weights."""
    return sum_emphasis(
        *(
            {name: block.attributes[name] for name in block.introduce_attributes}
            for block in blocks
        )
    )


def emphasised(
    role: RoleDefinition,
    emphasis: Mapping[str, int],
    introduced: Mapping[str, int] | None = None,
) -> RoleDefinition:
    """Return `role` with its existing and explicitly introduced weights shifted."""
    if not emphasis:
        return role
    weights = {attribute.name: attribute.weight for attribute in role.attributes}
    for name, delta in emphasis.items():
        if name in weights:
            weights[name] = min(MAX_EFFECTIVE_WEIGHT, max(0, weights[name] + delta))
    for name, delta in (introduced or {}).items():
        if name not in weights:
            weights[name] = min(MAX_EFFECTIVE_WEIGHT, delta)
    attributes = tuple(
        RoleAttribute(name=name, weight=weight)
        for name, weight in weights.items()
        if weight > 0
    )
    if not attributes:
        raise ValueError(
            f"attribute emphasis leaves role {role.key!r} with no weighted attributes"
        )
    return replace(role, attributes=attributes)
