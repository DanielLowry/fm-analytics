"""One FM tactics-screen setting as a pill on the tactic detail page."""

from __future__ import annotations

import html
from collections.abc import Collection, Mapping


def instruction_pill(label: str, value: str | None, *, state: str = "", note: str = "") -> str:
    classes = " ".join(part for part in ("instruction-pill", state, "unset" if value is None else "") if part)
    return (
        f"<div class='{classes}'><span>{html.escape(label)}</span>"
        f"<b>{html.escape('Not set' if value is None else value)}</b>"
        + (f"<small>{html.escape(note)}</small>" if note else "")
        + "</div>"
    )


def toggle_pill(
    name: str, selected: Collection[str] | None, unavailable: Mapping[str, tuple[str, ...]], *, state: str = "",
) -> str:
    """One FM toggle: selected, not selected (FM's default), or locked by another; None is unauthored."""
    label = name.capitalize()
    if selected is None:
        return instruction_pill(label, None)
    if name in selected:
        return instruction_pill(label, "Selected", state=f"{state} selected".strip())
    locked_by = unavailable.get(name)
    if locked_by:
        return instruction_pill(
            label, "Unavailable", state=f"{state} locked".strip(),
            note=" and ".join(locked_by) + (" is" if len(locked_by) == 1 else " are") + " selected",
        )
    return instruction_pill(label, "Not selected", state=f"{state} off".strip())
