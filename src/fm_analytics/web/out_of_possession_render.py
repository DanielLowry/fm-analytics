"""Defensive settings on the read-only tactic detail page, grouped into cards."""

import html

from fm_analytics.analytics.catalogue import TacticDefinition
from fm_analytics.analytics.out_of_possession import (
    DEFENSIVE_WIDTH_OPTIONS,
    LEGACY_INSTRUCTIONS,
    LINE_OPTIONS,
    PRESSING_INTENSITY_OPTIONS,
)
from fm_analytics.web.instruction_controls import Flag, Group, Scale, group_cards

GROUPS = (
    Group("Defensive shape", (
        Scale("Line of engagement", "line_of_engagement", LINE_OPTIONS),
        Scale("Defensive line", "defensive_line", LINE_OPTIONS),
        Scale("Defensive width", "defensive_width", DEFENSIVE_WIDTH_OPTIONS),
    )),
    Group("Pressing and marking", (
        Scale("Pressing intensity", "pressing_intensity", PRESSING_INTENSITY_OPTIONS),
        Flag("Use tighter marking", "use_tighter_marking"),
        Flag("Prevent short GK distribution", "prevent_short_gk_distribution"),
    )),
)


def out_of_possession_section(tactic: TacticDefinition) -> str:
    settings = tactic.out_of_possession
    cards = group_cards(
        GROUPS, value_of=lambda attribute: getattr(settings, attribute) if settings is not None else None,
    )
    missing = tactic.out_of_possession_missing_fields
    note = (
        "<p class='warn'>Out-of-possession settings not yet specified: "
        + html.escape(", ".join(missing)) + ".</p>"
        if missing else "<p class='muted'>Every out-of-possession setting is specified.</p>"
    )
    legacy = [i for i in tactic.instructions if i in LEGACY_INSTRUCTIONS]
    legacy_note = (
        "<p class='muted'>Existing defensive instructions: " + html.escape("; ".join(legacy)) + ".</p>"
        if legacy else ""
    )
    return (
        "<section class='out-of-possession-section'><h3>Out of possession</h3>"
        "<p class='subhead'>Where the team defends and how hard it presses. Neutral leaves marking or "
        "preventing short goalkeeper distribution unselected.</p>"
        f"{cards}{note}{legacy_note}</section>"
    )
