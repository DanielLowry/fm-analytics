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
from fm_analytics.web.instruction_pills import instruction_pill, toggle_pill

_FIXED_SCALES: tuple[tuple[str, str], ...] = (
    ("Attacking width", "attacking_width"),
    ("Passing directness", "passing_directness"),
    ("Tempo", "tempo"),
)


def in_possession_section(tactic: TacticDefinition) -> str:
    settings = tactic.in_possession if tactic.in_possession is not None else InPossessionSettings()
    missing = tactic.in_possession_missing_fields
    locked = settings.unavailable
    fixed_pills = "".join(
        instruction_pill(label, getattr(settings, attribute)) for label, attribute in _FIXED_SCALES
    ) + "".join(toggle_pill(name, settings.fixed_selected, locked) for name in FIXED_TOGGLES)
    missing_note = (
        "<p class='warn'>Not yet set: " + html.escape(", ".join(missing)) + ".</p>"
        if missing else "<p class='muted'>Every fixed in-possession setting is specified.</p>"
    )
    dependent_pills = instruction_pill("Crossing type", settings.crossing_type, state="fallback") + "".join(
        toggle_pill(name, settings.player_selected, locked, state="fallback")
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
