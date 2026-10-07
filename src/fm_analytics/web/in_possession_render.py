"""In-possession settings presentation for the tactic detail page.

What to actually click on FM's tactics screen, and -- since only a few
tactics have been given these settings so far -- what has not been set yet.
Always visible, unlike `_tactic_notes`'s optional commentary in `rendering.py`:
a manager needs to know either what to click, or that this tactic has not
been given these settings (see `analytics/CLAUDE.md` and
`InPossessionSettings`). Not scoring input.
"""

from __future__ import annotations

import html

from fm_analytics.analytics import InPossessionSettings, TacticDefinition
from fm_analytics.analytics.in_possession import FIXED_TOGGLES, PLAYER_DEPENDENT_TOGGLES

_FIXED_SCALES: tuple[tuple[str, str], ...] = (
    ("Attacking width", "attacking_width"),
    ("Passing directness", "passing_directness"),
    ("Tempo", "tempo"),
)


def _pill(label: str, value: str | None, *, state: str = "", note: str = "") -> str:
    classes = " ".join(part for part in ("instruction-pill", state, "unset" if value is None else "") if part)
    return (
        f"<div class='{classes}'><span>{html.escape(label)}</span>"
        f"<b>{html.escape('Not set' if value is None else value)}</b>"
        + (f"<small>{html.escape(note)}</small>" if note else "")
        + "</div>"
    )


def _toggle_pill(name: str, settings: InPossessionSettings, selected, *, state: str = "") -> str:
    """One FM toggle: selected, not selected (FM's default), or locked by another."""
    label = name.capitalize()
    if selected is None:
        return _pill(label, None)
    if name in selected:
        return _pill(label, "Selected", state=f"{state} selected".strip())
    locked_by = settings.unavailable.get(name)
    if locked_by:
        return _pill(
            label, "Unavailable", state=f"{state} locked".strip(),
            note=" and ".join(locked_by) + (" is" if len(locked_by) == 1 else " are") + " selected",
        )
    return _pill(label, "Not selected", state=f"{state} off".strip())


def in_possession_section(tactic: TacticDefinition) -> str:
    settings = tactic.in_possession if tactic.in_possession is not None else InPossessionSettings()
    missing = tactic.in_possession_missing_fields
    fixed_pills = "".join(
        _pill(label, getattr(settings, attribute)) for label, attribute in _FIXED_SCALES
    ) + "".join(_toggle_pill(name, settings, settings.fixed_selected) for name in FIXED_TOGGLES)
    missing_note = (
        "<p class='warn'>Not yet set: " + html.escape(", ".join(missing)) + ".</p>"
        if missing else "<p class='muted'>Every fixed in-possession setting is specified.</p>"
    )
    dependent_pills = _pill("Crossing type", settings.crossing_type, state="fallback") + "".join(
        _toggle_pill(name, settings, settings.player_selected, state="fallback")
        for name in PLAYER_DEPENDENT_TOGGLES
    )
    return (
        "<section class='in-possession-section'>"
        "<h3>In possession — fixed</h3>"
        "<p class='subhead'>What makes this tactic this tactic; set directly on the tactics screen. "
        "Not selected is FM's default; an unavailable instruction is locked by one that is selected.</p>"
        f"<div class='instruction-grid'>{fixed_pills}</div>"
        f"{missing_note}"
        "<details><summary>In possession — depends on players</summary>"
        "<p class='subhead'>A real manager sets these by looking at who is on the pitch, not the "
        "formation. They are not picked from your players' attributes yet, so each shows this "
        f"tactic's fallback.</p><div class='instruction-grid'>{dependent_pills}</div></details>"
        "</section>"
    )
