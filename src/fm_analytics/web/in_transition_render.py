"""Transition settings on the read-only tactic detail page, one card per FM section."""

import html

from fm_analytics.analytics.catalogue import TacticDefinition
from fm_analytics.analytics.in_transition import (
    DISTRIBUTION_TARGET_OPTIONS,
    DISTRIBUTION_TYPE_OPTIONS,
    GOALKEEPER_PACE_OPTIONS,
    IN_TRANSITION_CLASHES,
    POSSESSION_LOST_OPTIONS,
    POSSESSION_WON_OPTIONS,
    SECTIONS,
    InTransitionSettings,
)
from fm_analytics.web.instruction_controls import Group, Toggles, group_cards

GROUPS = (
    Group("When possession changes", (
        Toggles(POSSESSION_LOST_OPTIONS, label="When possession is lost"),
        Toggles(POSSESSION_WON_OPTIONS, label="When possession is won"),
    )),
    Group("Goalkeeper in possession", wide=True, rows=(
        Toggles(GOALKEEPER_PACE_OPTIONS, label="Pace"),
        Toggles(
            DISTRIBUTION_TARGET_OPTIONS, label="Distribute to",
            shown=("Centre backs", "Full backs", "Playmaker", "Target man", "Flanks", "Over opposition defence"),
        ),
        Toggles(DISTRIBUTION_TYPE_OPTIONS, label="Distribution type"),
    )),
)
_ATTRIBUTE_OF = {name: attribute for attribute, _key, _label, options in SECTIONS for name in options}


def in_transition_section(tactic: TacticDefinition) -> str:
    settings = tactic.in_transition if tactic.in_transition is not None else InTransitionSettings()
    cards = group_cards(
        GROUPS,
        value_of=lambda attribute: getattr(settings, attribute),
        selected_of=lambda name: getattr(settings, _ATTRIBUTE_OF[name]),
        unavailable=settings.unavailable,
        clashes=IN_TRANSITION_CLASHES,
    )
    missing = tactic.in_transition_missing_fields
    note = (
        "<p class='warn'>Transition settings not yet specified: "
        + html.escape(", ".join(missing)) + ".</p>"
        if missing else "<p class='muted'>Every in-transition setting is specified.</p>"
    )
    legacy = [i for i in tactic.instructions if i in ("Counter-Press", "Regroup", "Counter", "Hold Shape")]
    legacy_note = (
        "<p class='muted'>Existing transition instructions: " + html.escape("; ".join(legacy)) + ".</p>"
        if legacy else ""
    )
    return (
        "<section class='in-transition-section'><h3>In transition</h3>"
        "<p class='subhead'>What the team does the moment the ball changes hands, and how the goalkeeper "
        "restarts play.</p>"
        f"{cards}{note}{legacy_note}</section>"
    )
