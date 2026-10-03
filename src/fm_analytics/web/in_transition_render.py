"""Transition settings on the read-only tactic detail page."""

import html

from fm_analytics.analytics.catalogue import TacticDefinition
from fm_analytics.analytics.in_transition import FIELD_LABELS


def in_transition_section(tactic: TacticDefinition) -> str:
    settings = tactic.in_transition
    rows = []
    for attribute, label in FIELD_LABELS:
        value = getattr(settings, attribute) if settings is not None else None
        if value is None:
            display = "Not set"
        elif isinstance(value, tuple):
            display = "; ".join(value) if value else "None selected"
        else:
            display = "Neither selected" if value == "Neither" else value
        rows.append(
            f"<div class='instruction-pill{' unset' if value is None else ''}'>"
            f"<span>{html.escape(label.capitalize())}</span><b>{html.escape(display)}</b></div>"
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
        "<p class='subhead'>Set these on the tactics screen. The possession-loss and goalkeeper-pace "
        "choices, and Counter or Hold Shape, each allow one option or neither. "
        "Distribution targets and types allow multiple choices.</p>"
        f"<div class='instruction-grid'>{''.join(rows)}</div>{note}{legacy_note}</section>"
    )
