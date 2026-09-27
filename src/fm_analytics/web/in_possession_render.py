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

_FIXED_ROWS: tuple[tuple[str, str], ...] = (
    ("Attacking width", "attacking_width"),
    ("Passing directness", "passing_directness"),
    ("Tempo", "tempo"),
    ("Pass into space", "pass_into_space"),
    ("Play out of defence", "play_out_of_defence"),
    ("Focus play", "focus_play"),
    ("Work ball into box", "work_ball_into_box"),
)
_PLAYER_DEPENDENT_ROWS: tuple[tuple[str, str], ...] = (
    ("Overlap left", "overlap_left"),
    ("Overlap right", "overlap_right"),
    ("Underlap left", "underlap_left"),
    ("Underlap right", "underlap_right"),
    ("Crossing type", "crossing_type"),
    ("Shoot on sight", "shoot_on_sight"),
    ("Hit early crosses", "hit_early_crosses"),
    ("Play for set pieces", "play_for_set_pieces"),
    ("Dribble less", "dribble_less"),
    ("Run at defence", "run_at_defence"),
    ("Be more expressive", "be_more_expressive"),
    ("Be more disciplined", "be_more_disciplined"),
)


def _display_value(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def in_possession_section(tactic: TacticDefinition) -> str:
    settings = tactic.in_possession
    missing = tactic.in_possession_missing_fields
    fixed_rows = []
    for label, attribute in _FIXED_ROWS:
        value = getattr(settings, attribute) if settings is not None else None
        display = "Not set" if value is None else _display_value(value)
        fixed_rows.append(
            f"<div class='instruction-pill{' unset' if value is None else ''}'>"
            f"<span>{html.escape(label)}</span><b>{html.escape(display)}</b></div>"
        )
    fixed_pills = "".join(fixed_rows)
    missing_note = (
        "<p class='warn'>Not yet set: " + html.escape(", ".join(missing)) + ".</p>"
        if missing else "<p class='muted'>Every fixed in-possession setting is specified.</p>"
    )
    player_dependent = settings if settings is not None else InPossessionSettings()
    dependent_pills = "".join(
        f"<div class='instruction-pill fallback'>"
        f"<span>{html.escape(label)}</span>"
        f"<b>{html.escape(_display_value(getattr(player_dependent, attribute)))}</b>"
        "</div>"
        for label, attribute in _PLAYER_DEPENDENT_ROWS
    )
    return (
        "<section class='in-possession-section'>"
        "<h3>In possession — fixed</h3>"
        "<p class='subhead'>What makes this tactic this tactic; set directly on the tactics screen.</p>"
        f"<div class='instruction-grid'>{fixed_pills}</div>"
        f"{missing_note}"
        "<details><summary>In possession — depends on players</summary>"
        "<p class='subhead'>A real manager sets these by looking at who is on the pitch, not the "
        "formation. The app does not yet pick these from your squad's attributes, so each shows only "
        f"a fallback.</p><div class='instruction-grid'>{dependent_pills}</div></details>"
        "</section>"
    )
