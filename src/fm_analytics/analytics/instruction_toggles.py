"""Instructions the manager either selects or leaves alone, as on FM's screen.

Most of FM's tactics-screen instructions are a focus: selected, or not. Not
selected is FM's own default, "no particular focus", never a deliberate "No",
so a tactic only ever lists what it selects. Selecting some instructions makes
others unavailable until it is cleared. FM applies that both ways (with Work
Ball Into Box selected, Hit Early Crosses cannot be, and the reverse), so each
clash is one unordered pair and a tactic can never select both. The two ends
of one setting, such as Dribble Less and Run At Defence, are simply a clash.
See docs/tactical-system-roadmap.md item 4c.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

Clash = tuple[str, str]


def check_names(selected: Sequence[str], allowed: Sequence[str], where: str) -> None:
    unknown = [name for name in selected if name not in allowed]
    if unknown:
        raise ValueError(f"{where}: unknown instruction(s) {unknown!r}; choose from {list(allowed)!r}")
    if len(set(selected)) != len(selected):
        raise ValueError(f"{where}: lists an instruction more than once")


def clashes_within(selected: Collection[str], clashes: Sequence[Clash]) -> tuple[Clash, ...]:
    return tuple((first, second) for first, second in clashes if first in selected and second in selected)


def check_clashes(selected: Collection[str], clashes: Sequence[Clash], where: str) -> None:
    for first, second in clashes_within(selected, clashes):
        raise ValueError(
            f"{where}: {first!r} and {second!r} cannot both be selected; "
            "in FM, selecting one makes the other unavailable"
        )


def unavailable(selected: Collection[str], clashes: Sequence[Clash]) -> dict[str, tuple[str, ...]]:
    """Each unselected instruction that a selection locks, with what locks it."""
    locked: dict[str, list[str]] = {}
    for pair in clashes:
        for chosen, other in (pair, pair[::-1]):
            if chosen in selected and other not in selected:
                locked.setdefault(other, []).append(chosen)
    return {name: tuple(by) for name, by in locked.items()}
