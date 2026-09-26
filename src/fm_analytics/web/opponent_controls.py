"""Bookmarkable opponent-profile controls for tactic recommendations."""

from __future__ import annotations

import html
from urllib.parse import urlencode

from fm_analytics.analytics import AXIS_DEFINITIONS, OpponentProfile
from fm_analytics.web.rendering import _query_first


_QUERY_PREFIX = "opp_"


def opponent_from_query(query: dict[str, list[str]]) -> OpponentProfile:
    """Parse the tactic controls, rejecting malformed values."""
    values: dict[str, int] = {}
    for axis in AXIS_DEFINITIONS:
        raw = _query_first(query, _QUERY_PREFIX + axis.key)
        if raw is None:
            values[axis.key] = 0
            continue
        try:
            values[axis.key] = int(raw)
        except ValueError as exc:
            raise ValueError(
                f"{axis.label} must be a whole number from -2 to +2"
            ) from exc
    return OpponentProfile(**values)


def opponent_query(profile: OpponentProfile) -> str:
    """Return the compact query suffix used by drill-down and back links."""
    return urlencode(
        [
            (_QUERY_PREFIX + axis.key, str(getattr(profile, axis.key)))
            for axis in AXIS_DEFINITIONS
            if getattr(profile, axis.key)
        ]
    )


def opponent_value_label(axis, value: int) -> str:
    if value == -2:
        return axis.low.capitalize()
    if value == -1:
        return f"Leans {axis.low}"
    if value == 1:
        return f"Leans {axis.high}"
    if value == 2:
        return axis.high.capitalize()
    return "Neutral"


def opponent_controls(
    profile: OpponentProfile, *, action: str = "/tactics"
) -> str:
    """Render all axes as a GET form that remains on the supplied page."""
    sliders = []
    for axis in AXIS_DEFINITIONS:
        value = getattr(profile, axis.key)
        input_id = f"opponent-{axis.key.replace('_', '-')}"
        sliders.append(
            "<label class='opponent-slider' "
            f"for='{input_id}'><span><b>{html.escape(axis.label)}</b> "
            f"<output for='{input_id}'>{html.escape(opponent_value_label(axis, value))} "
            f"({value:+d})</output></span>"
            "<span class='opponent-range'>"
            f"<small>−2 {html.escape(axis.low)}</small>"
            f"<input id='{input_id}' name='{_QUERY_PREFIX + axis.key}' "
            f"type='range' min='-2' max='2' step='1' value='{value}'>"
            f"<small>+2 {html.escape(axis.high)}</small>"
            "</span></label>"
        )
    reset = (
        f"<a class='button-link secondary' href='{html.escape(action, quote=True)}'>"
        "Reset to neutral</a>"
        if not profile.is_neutral
        else ""
    )
    return (
        "<section class='opponent-panel'><h2>Opponent profile</h2>"
        "<p class='muted'>Your estimate of this opponent. These settings change player "
        "emphasis and opponent-fit checks; they are not inferred from hidden game data. "
        "The URL can be bookmarked or shared.</p>"
        f"<form class='opponent-form' method='get' action='{html.escape(action, quote=True)}'>"
        + "".join(sliders)
        + "<div class='opponent-actions'><button type='submit'>Apply opponent</button>"
        + reset
        + "</div></form></section>"
        "<script>(function(){document.querySelectorAll('.opponent-slider input').forEach(function(input){"
        "input.addEventListener('input',function(){var output=input.closest('label').querySelector('output');"
        "output.textContent=(input.value>0?'+':'')+input.value;});});})();</script>"
    )
