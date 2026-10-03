"""Defensive settings on the read-only tactic detail page."""

import html

from fm_analytics.analytics.catalogue import TacticDefinition
from fm_analytics.analytics.out_of_possession import FIELD_LABELS, LEGACY_INSTRUCTIONS


def out_of_possession_section(tactic: TacticDefinition) -> str:
    settings = tactic.out_of_possession
    rows = []
    for attribute, label in FIELD_LABELS:
        value = getattr(settings, attribute) if settings is not None else None
        if value is None:
            display = "Not set"
        elif isinstance(value, bool):
            display = "Yes" if value else "No"
        else:
            display = value
        rows.append(
            f"<div class='instruction-pill{' unset' if value is None else ''}'>"
            f"<span>{html.escape(label[0].upper() + label[1:])}</span>"
            f"<b>{html.escape(display)}</b></div>"
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
        "<p class='subhead'>Set the lines and pressing intensity on the tactics screen. "
        "Neutral leaves marking or preventing short goalkeeper distribution unselected.</p>"
        f"<div class='instruction-grid'>{''.join(rows)}</div>{note}{legacy_note}</section>"
    )
