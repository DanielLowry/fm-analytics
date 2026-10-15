"""FM20 defensive free-kick availability and reviewable coverage rules.

Instruction availability was supplied from the manager's in-game menus on
14 October 2026. Tactical coverage limits below are our authored policy;
they do not claim that FM prohibits other counts or combinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


_COMMON = {
    "forward": "Stay forward", "wall": "Wall", "edge": "Edge of area",
    "back": "Go back", "mark": "Man mark",
}
_TALL = {"tall": "Man mark tall player"}
_ZONAL = {
    "zonal_near": "Zonally mark 6 yard box near post",
    "zonal_centre": "Zonally mark 6 yard box centre",
    "zonal_far": "Zonally mark 6 yard box far post",
}
DEFENSIVE_FREE_KICK_JOBS = MappingProxyType({
    "direct_free_kick": MappingProxyType(_COMMON),
    "direct_small_chance": MappingProxyType({**_COMMON, **_TALL}),
    "indirect_wide": MappingProxyType({**_COMMON, **_TALL, **_ZONAL}),
    "indirect_deep": MappingProxyType({**_COMMON, **_TALL, **_ZONAL}),
})
FLEXIBLE_DEFENSIVE_FREE_KICKS = frozenset(DEFENSIVE_FREE_KICK_JOBS) - {"direct_free_kick"}
DEFENSIVE_JOBS = frozenset(DEFENSIVE_FREE_KICK_JOBS["indirect_wide"])
BOX_DEFENCE_JOBS = frozenset(("back", "mark", "tall", *_ZONAL))
DEFENSIVE_RESPONSIBILITIES = MappingProxyType({
    "keeper": ("keeper",),
    "delivery": ("back", "tall", *_ZONAL),
    "marking": ("mark",),
    "perimeter": ("wall", "edge"),
    "outlet": ("forward",),
})


@dataclass(frozen=True)
class DefensiveTemplate:
    key: str
    name: str
    description: str
    jobs: Mapping[str, int]
    variant: str = "indirect_wide"

    @property
    def box_defenders(self) -> int:
        return sum(self.jobs.get(job, 0) for job in BOX_DEFENCE_JOBS)

    @property
    def zonal_defenders(self) -> int:
        return sum(self.jobs.get(job, 0) for job in _ZONAL)


@dataclass(frozen=True)
class DefensiveApproach:
    minimum_box_defenders: int
    minimum_outlets: int
    maximum_outlets: int
    minimum_small_chance_box_defenders: int = 4

    def accepts(self, template: DefensiveTemplate) -> bool:
        minimum = self.minimum_small_chance_box_defenders if template.variant == "direct_small_chance" else self.minimum_box_defenders
        return (
            template.box_defenders >= minimum
            and self.minimum_outlets <= template.jobs["forward"] <= self.maximum_outlets
        )


def validate_defensive_counts(kind: str, jobs: Mapping[str, int]) -> None:
    """Validate sensible authored shapes after exact availability/type checks."""
    small = kind == "direct_small_chance"
    box = sum(jobs.get(job, 0) for job in BOX_DEFENCE_JOBS)
    aerial = jobs.get("tall", 0) + sum(jobs.get(job, 0) for job in _ZONAL)
    wall_min, wall_max = (2, 4) if small else (1, 2) if kind == "indirect_wide" else (0, 2)
    if (
        box < (4 if small else 6)
        or not 1 <= jobs["mark"] <= 4 or not 1 <= jobs["back"] <= 3
        or jobs["mark"] + jobs.get("tall", 0) < 2
        or not 0 <= jobs.get("tall", 0) <= 2
        or any(jobs.get(job, 0) > 1 for job in _ZONAL)
        or (not small and aerial < 2)
        or not 1 <= jobs["edge"] <= 2 or not 1 <= jobs["forward"] <= 2
        or not wall_min <= jobs["wall"] <= wall_max
    ):
        raise ValueError("inadequate balance of aerial defence, runner marking, spare cover, second balls, wall and outlets")


def responsibility_importances(counts, importance, budgets):
    """Keep group budgets constant; repeated jobs share their type's allocation.

    Relative job importance divides a group's budget among its active job types.
    For example, central zonal cover can carry more than spare cover. Repeating
    the same job splits its allocation. A wall-free plan transfers the perimeter
    budget to its edge guards, rather than changing the comparison denominator.
    """
    result = {}
    for group, jobs in DEFENSIVE_RESPONSIBILITIES.items():
        active = [job for job in jobs if counts.get(job, 0)]
        total = sum(importance[job] for job in active)
        if not active:
            raise ValueError(f"missing defensive responsibility: {group}")
        for job in active:
            result[job] = budgets[group] * (importance[job] / total) / counts[job]
    return result
