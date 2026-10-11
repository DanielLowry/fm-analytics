"""FM tactics-screen settings on the tactic detail page, grouped into cards.

Each phase's section (`in_possession_render`, `in_transition_render`,
`out_of_possession_render`) declares its cards as data: a `Group` holds rows,
and a row is a `Scale` (one value on one of FM's sliders, or a dropdown), a
`Flag` (a yes/no/neutral setting) or a `Toggles` row of tick boxes.

Linked toggles, where selecting one makes another unavailable, always share one
`Toggles` row (`tests/test_instruction_controls.py` holds every phase to that),
and the row says in a sentence how they are linked. So Work Ball Into Box sits
next to the Hit Early Crosses that locks it, rather than in another panel.

Presentation only: nothing here is scoring input.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from fm_analytics.analytics.instruction_toggles import Clash

# What a setting depends on, when it is not part of the tactic's identity.
PLAYERS = "players"
SCORE = "score"

_CHECK = (
    "<svg viewBox='0 0 16 16' aria-hidden='true'><path d='M3.5 8.5l3 3 6-7' fill='none' "
    "stroke='currentColor' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/></svg>"
)
_LOCK = (
    "<svg viewBox='0 0 16 16' aria-hidden='true'><rect x='3' y='7' width='10' height='7.5' rx='1.6' "
    "fill='currentColor'/><path d='M5.4 7V5.2a2.6 2.6 0 0 1 5.2 0V7' fill='none' stroke='currentColor' "
    "stroke-width='1.7'/></svg>"
)
_PERSON = (
    "<svg viewBox='0 0 16 16' aria-hidden='true'><circle cx='8' cy='4.8' r='2.9' fill='currentColor'/>"
    "<path d='M2.4 14.6c0-3.3 2.5-5.2 5.6-5.2s5.6 1.9 5.6 5.2z' fill='currentColor'/></svg>"
)
_CLOCK = (
    "<svg viewBox='0 0 16 16' aria-hidden='true'><circle cx='8' cy='8' r='6.2' fill='none' "
    "stroke='currentColor' stroke-width='1.7'/><path d='M8 4.6V8l2.4 1.7' fill='none' stroke='currentColor' "
    "stroke-width='1.7' stroke-linecap='round'/></svg>"
)
# (icon, short name, what it means), for the marker and the legend.
_DEPENDS: dict[str, tuple[str, str, str]] = {
    PLAYERS: (
        _PERSON, "Depends on players",
        "A manager sets this by who is on the pitch. Our code does not pick it from your XI yet, "
        "so this is the tactic's starting choice.",
    ),
    SCORE: (
        _CLOCK, "Depends on the score",
        "A manager changes this with the score and the clock; this is the tactic's usual setting.",
    ),
}


@dataclass(frozen=True)
class Scale:
    """One setting with one value: a slider whose `options` run end to end, or a dropdown."""

    label: str
    attribute: str
    options: tuple[str, ...]
    depends: str | None = None
    dropdown: bool = False


@dataclass(frozen=True)
class Flag:
    """A setting authored as yes, no or neutral."""

    label: str
    attribute: str


@dataclass(frozen=True)
class Toggles:
    """Tick boxes shown side by side, by FM name; `shown` shortens them under a `label`."""

    names: tuple[str, ...]
    label: str | None = None
    shown: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.shown is not None and len(self.shown) != len(self.names):
            raise ValueError(f"{self.names!r}: give one shown name per toggle")

    def display(self, name: str) -> str:
        return name.capitalize() if self.shown is None else self.shown[self.names.index(name)]


@dataclass(frozen=True)
class Group:
    """One card. A `wide` card takes two columns when there is room, its rows side by side."""

    title: str
    rows: tuple[Scale | Flag | Toggles, ...]
    wide: bool = False


def toggle_rows(groups: Iterable[Group]) -> tuple[Toggles, ...]:
    return tuple(row for group in groups for row in group.rows if isinstance(row, Toggles))


def _and(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _mid_sentence(text: str) -> str:
    return text[:1].lower() + text[1:]


def clash_rule(row: Toggles, clashes: Sequence[Clash]) -> str:
    """How the row's toggles lock each other, in a sentence; empty when they don't."""
    names = row.names
    linked = {frozenset(pair) for pair in clashes if set(pair) <= set(names)}
    if not linked:
        return ""
    together = [pair for pair in combinations(names, 2) if frozenset(pair) not in linked]
    if not together:
        return "Pick one or neither." if len(names) == 2 else "Pick one at most."
    pairs = " ".join(
        f"{row.display(first)} and {_mid_sentence(row.display(second))} can be selected together."
        for first, second in together
    )
    # One toggle that locks every other, and is all that locks anything: say so by name.
    hubs = [name for name in names if all(frozenset((name, other)) in linked for other in names if other != name)]
    if len(hubs) == 1 and all(hubs[0] in pair for pair in linked):
        others = [_mid_sentence(row.display(other)) for other in names if other != hubs[0]]
        return f"{row.display(hubs[0])} rules out {_and(others)}. {pairs}"
    combinable = " ".join(
        f"{_mid_sentence(row.display(first))} and {_mid_sentence(row.display(second))}"
        for first, second in together
    )
    return f"Pick one at most, except that {combinable} can be selected together."


def _depends_marker(depends: str | None) -> str:
    if depends is None:
        return ""
    icon, short, meaning = _DEPENDS[depends]
    return (
        f"<span class='fm-depends' title='{html.escape(short + ': ' + meaning)}'>"
        f"{icon}<span class='fm-sr'>{html.escape(short)}</span></span>"
    )


def _toggle_chip(
    row: Toggles,
    name: str,
    selected: Collection[str] | None,
    unavailable: Mapping[str, tuple[str, ...]],
    depends: str | None,
) -> str:
    """One tick box: selected, not selected (FM's default), locked by another, or not set (None)."""
    title = ""
    if selected is None:
        state, word, box = "is-unset", "Not set", "?"
    elif name in selected:
        state, word, box = "is-selected", "Selected", _CHECK
    elif unavailable.get(name):
        locked_by = unavailable[name]
        state, word, box = "is-locked", "Unavailable", _LOCK
        title = (
            " title='Unavailable: " + html.escape(_and(list(locked_by)))
            + (" is" if len(locked_by) == 1 else " are") + " selected'"
        )
    else:
        state, word, box = "is-off", "Not selected", ""
    return (
        f"<li class='fm-toggle {state}'{title}><i class='fm-box' aria-hidden='true'>{box}</i>"
        f"<span>{html.escape(row.display(name))}</span><b>{word}</b>{_depends_marker(depends)}</li>"
    )


def _toggles_row(
    row: Toggles,
    selected_of: Callable[[str], Collection[str] | None],
    unavailable: Mapping[str, tuple[str, ...]],
    clashes: Sequence[Clash],
    depends_of: Callable[[str], str | None],
) -> str:
    depends = {depends_of(name) for name in row.names}
    # A labelled row whose toggles all depend on the same thing says so once, by its label.
    shared = depends.pop() if row.label and len(depends) == 1 else None
    chips = "".join(
        _toggle_chip(row, name, selected_of(name), unavailable, None if shared else depends_of(name))
        for name in row.names
    )
    rule = clash_rule(row, clashes)
    label = (
        f"<span class='fm-toggles-label'>{html.escape(row.label)}{_depends_marker(shared)}</span>"
        if row.label else ""
    )
    aria = f" aria-label='{html.escape(row.label)}'" if row.label else ""
    return (
        f"<div class='fm-toggle-row'>{label}<ul class='fm-toggles'{aria}>{chips}</ul>"
        + (f"<p class='fm-rule'>{html.escape(rule)}</p>" if rule else "")
        + "</div>"
    )


def _setting_head(label: str, display: str, depends: str | None = None) -> str:
    return (
        f"<div class='fm-setting-head'><span>{html.escape(label)}</span>"
        f"<b>{html.escape(display)}</b>{_depends_marker(depends)}</div>"
    )


_ON = " class='is-on'"


def _scale_row(row: Scale, value: str | None) -> str:
    head = _setting_head(row.label, "Not set" if value is None else value, row.depends)
    if row.dropdown:
        body = "<ul class='fm-dropdown' aria-hidden='true'>" + "".join(
            f"<li{_ON if option == value else ''}>{html.escape(option)}</li>"
            for option in row.options
        ) + "</ul>"
    else:
        body = (
            "<ol class='fm-scale' aria-hidden='true'>"
            + "".join(
                f"<li{_ON if option == value else ''} title='{html.escape(option)}'></li>"
                for option in row.options
            )
            + "</ol><div class='fm-scale-ends' aria-hidden='true'>"
            f"<span>{html.escape(row.options[0])}</span><span>{html.escape(row.options[-1])}</span></div>"
        )
    return f"<div class='fm-setting{' is-unset' if value is None else ''}'>{head}{body}</div>"


def _flag_row(row: Flag, value: bool | str | None) -> str:
    if value is None:
        display = "Not set"
    elif isinstance(value, bool):
        display = "Yes" if value else "No"
    else:
        display = value
    return f"<div class='fm-setting{' is-unset' if value is None else ''}'>{_setting_head(row.label, display)}</div>"


def group_cards(
    groups: Iterable[Group],
    *,
    value_of: Callable[[str], object],
    selected_of: Callable[[str], Collection[str] | None] = lambda _name: (),
    unavailable: Mapping[str, tuple[str, ...]] | None = None,
    clashes: Sequence[Clash] = (),
    depends_of: Callable[[str], str | None] = lambda _name: None,
) -> str:
    """Every card, each row read through `value_of(attribute)` or `selected_of(toggle)`."""

    def render(row: Scale | Flag | Toggles) -> str:
        if isinstance(row, Toggles):
            return _toggles_row(row, selected_of, unavailable or {}, clashes, depends_of)
        if isinstance(row, Flag):
            return _flag_row(row, value_of(row.attribute))
        return _scale_row(row, value_of(row.attribute))

    return "<div class='fm-instruction-groups'>" + "".join(
        f"<article class='fm-instruction-group{' is-wide' if group.wide else ''}'>"
        f"<h4>{html.escape(group.title)}</h4>"
        + "".join(render(row) for row in group.rows) + "</article>"
        for group in groups
    ) + "</div>"


def instruction_legend() -> str:
    """What each tick-box state and marker means, once above the three phases."""
    boxes = (
        ("is-selected", _CHECK, "Selected"),
        ("is-off", "", "Not selected (FM's default)"),
        ("is-locked", _LOCK, "Unavailable: a linked instruction is selected"),
        ("is-unset", "?", "Not set for this tactic yet"),
    )
    items = "".join(
        f"<li class='fm-legend-item {state}'><i class='fm-box' aria-hidden='true'>{box}</i>{html.escape(text)}</li>"
        for state, box, text in boxes
    ) + "".join(
        f"<li class='fm-legend-item'><span class='fm-depends'>{icon}</span>"
        f"<span><b>{html.escape(short)}</b> {html.escape(meaning)}</span></li>"
        for icon, short, meaning in _DEPENDS.values()
    )
    return f"<ul class='fm-instruction-legend' aria-label='Key'>{items}</ul>"
