"""In-possession settings on the tactic detail page.

What to click on FM's tactics screen, grouped so linked instructions sit
together, and -- since only some tactics have been given these settings so
far -- what has not been set yet. Always visible: a manager needs to know
either what to click, or that this tactic has not been given these settings
(see `analytics/CLAUDE.md` and `InPossessionSettings`). Settings a manager
picks by who is playing are shown in the same cards, marked as depending on
players, so Hit Early Crosses sits beside the Work Ball Into Box it locks.
Not scoring input.
"""

from __future__ import annotations

import html

from fm_analytics.analytics import InPossessionSettings, TacticDefinition
from fm_analytics.analytics.in_possession import (
    ATTACKING_WIDTH_OPTIONS,
    CROSSING_TYPE_OPTIONS,
    FIXED_TOGGLES,
    IN_POSSESSION_CLASHES,
    PASSING_DIRECTNESS_OPTIONS,
    PLAYER_DEPENDENT_TOGGLES,
    TEMPO_OPTIONS,
    TIME_WASTING_OPTIONS,
)
from fm_analytics.web.instruction_controls import PLAYERS, SCORE, Group, Scale, Toggles, group_cards

GROUPS = (
    Group("Width and focus", (
        Scale("Attacking width", "attacking_width", ATTACKING_WIDTH_OPTIONS),
        Toggles(
            ("Focus Play Through The Middle", "Focus Play Down The Left", "Focus Play Down The Right"),
            label="Focus play", shown=("Through the middle", "Down the left", "Down the right"),
        ),
    )),
    Group("Approach play", (
        Scale("Passing directness", "passing_directness", PASSING_DIRECTNESS_OPTIONS),
        Scale("Tempo", "tempo", TEMPO_OPTIONS),
        Toggles(("Play Out Of Defence", "Pass Into Space")),
        Scale("Time wasting", "time_wasting", TIME_WASTING_OPTIONS, depends=SCORE),
    )),
    Group("Final third", (
        Toggles(("Work Ball Into Box", "Hit Early Crosses", "Shoot On Sight")),
        Scale("Crossing type", "crossing_type", CROSSING_TYPE_OPTIONS, depends=PLAYERS, dropdown=True),
        Toggles(("Play For Set Pieces",)),
    )),
    Group("Overlaps and underlaps", (
        Toggles(("Overlap Left", "Underlap Left"), label="Left flank", shown=("Overlap", "Underlap")),
        Toggles(("Overlap Right", "Underlap Right"), label="Right flank", shown=("Overlap", "Underlap")),
    )),
    Group("Dribbling and creative freedom", (
        Toggles(("Dribble Less", "Run At Defence"), label="Dribbling"),
        Toggles(("Be More Expressive", "Be More Disciplined"), label="Creative freedom"),
    )),
)


def in_possession_section(tactic: TacticDefinition) -> str:
    settings = tactic.in_possession if tactic.in_possession is not None else InPossessionSettings()
    missing = tactic.in_possession_missing_fields
    missing_note = (
        "<p class='warn'>Not yet set: " + html.escape(", ".join(missing)) + ".</p>"
        if missing else "<p class='muted'>Every in-possession setting that defines this tactic is specified.</p>"
    )
    cards = group_cards(
        GROUPS,
        value_of=lambda attribute: getattr(settings, attribute),
        selected_of=lambda name: settings.fixed_selected if name in FIXED_TOGGLES else settings.player_selected,
        unavailable=settings.unavailable,
        clashes=IN_POSSESSION_CLASHES,
        depends_of=lambda name: PLAYERS if name in PLAYER_DEPENDENT_TOGGLES else None,
    )
    return (
        "<section class='in-possession-section'><h3>In possession</h3>"
        "<p class='subhead'>Linked instructions sit together: selecting one can make another unavailable, "
        "as on FM's screen.</p>"
        f"{cards}{missing_note}</section>"
    )
