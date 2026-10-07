"""Transition settings on the read-only tactic detail page."""

import html

from fm_analytics.analytics.catalogue import TacticDefinition
from fm_analytics.analytics.in_transition import SECTIONS, InTransitionSettings
from fm_analytics.web.instruction_pills import toggle_pill


def in_transition_section(tactic: TacticDefinition) -> str:
    settings = tactic.in_transition if tactic.in_transition is not None else InTransitionSettings()
    locked = settings.unavailable
    pills = "".join(
        toggle_pill(name, getattr(settings, attribute), locked)
        for attribute, _key, _label, options in SECTIONS for name in options
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
        "<p class='subhead'>Set these on the tactics screen. Not selected is FM's default; an unavailable "
        "instruction is locked by one that is selected. Each section allows one choice, except that centre-backs "
        "and full-backs can both be distribution targets.</p>"
        f"<div class='instruction-grid'>{pills}</div>{note}{legacy_note}</section>"
    )
