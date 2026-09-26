"""Bookmarkable opponent-profile controls for tactic recommendations."""

from __future__ import annotations

import html
from urllib.parse import urlencode

from fm_analytics.analytics import (
    AXIS_DEFINITIONS,
    FORMATION_DEFINITIONS,
    OpponentProfile,
)
from fm_analytics.analytics.opponent_details import (
    ATTRIBUTE_DEFINITIONS,
    ATTRIBUTE_GROUPS,
    ATTRIBUTES_BY_KEY,
    POSITION_DEFINITIONS,
)
from fm_analytics.web.rendering import _query_first


_QUERY_PREFIX = "opp_"


def _query_level(query: dict[str, list[str]], name: str, label: str) -> int:
    raw = _query_first(query, name)
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a whole number from -2 to +2") from exc


def opponent_from_query(query: dict[str, list[str]]) -> OpponentProfile:
    """Parse the tactic controls, rejecting malformed values."""
    values: dict[str, int] = {}
    for axis in AXIS_DEFINITIONS:
        values[axis.key] = _query_level(
            query, _QUERY_PREFIX + axis.key, axis.label
        )
    attributes = {
        item.key: _query_level(
            query, _QUERY_PREFIX + "attr_" + item.query_key, item.label
        )
        for item in ATTRIBUTE_DEFINITIONS
    }
    positions = {
        item.key: _query_level(
            query, _QUERY_PREFIX + "pos_" + item.key, item.label
        )
        for item in POSITION_DEFINITIONS
    }
    return OpponentProfile(
        formation=_query_first(query, _QUERY_PREFIX + "formation") or "unknown",
        attribute_levels=attributes,
        position_levels=positions,
        **values,
    )


def opponent_query(profile: OpponentProfile) -> str:
    """Return the compact query suffix used by drill-down and back links."""
    pairs = (
        [(_QUERY_PREFIX + "formation", profile.formation)]
        if profile.formation != "unknown"
        else []
    )
    pairs.extend(
        [
            (_QUERY_PREFIX + axis.key, str(getattr(profile, axis.key)))
            for axis in AXIS_DEFINITIONS
            if getattr(profile, axis.key)
        ]
    )
    pairs.extend(
        (_QUERY_PREFIX + "pos_" + key, str(value))
        for key, value in profile.position_levels
    )
    pairs.extend(
        (_QUERY_PREFIX + "attr_" + ATTRIBUTES_BY_KEY[key].query_key, str(value))
        for key, value in profile.attribute_levels
    )
    return urlencode(pairs)


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


def opponent_summary_items(profile: OpponentProfile) -> tuple[str, ...]:
    formations = {item.key: item.label for item in FORMATION_DEFINITIONS}
    items = (
        [f"Likely formation: {formations[profile.formation]}"]
        if profile.formation != "unknown"
        else []
    )
    items.extend(
        f"{axis.label}: {opponent_value_label(axis, getattr(profile, axis.key))}"
        for axis in AXIS_DEFINITIONS
        if getattr(profile, axis.key)
    )
    position_values = dict(profile.position_levels)
    attribute_values = dict(profile.attribute_levels)
    for heading, definitions, values in (
        ("Strong positions", POSITION_DEFINITIONS, position_values),
        ("Position weaknesses", POSITION_DEFINITIONS, position_values),
        ("Attribute strengths", ATTRIBUTE_DEFINITIONS, attribute_values),
        ("Attribute weaknesses", ATTRIBUTE_DEFINITIONS, attribute_values),
    ):
        positive = "weak" not in heading.lower()
        direction = 1 if positive else -1
        labels = [
            item.label
            for item in definitions
            if values.get(item.key, 0) * direction > 0
        ]
        if labels:
            items.append(f"{heading}: {', '.join(labels)}")
    return tuple(items)


def _detail_select(name: str, label: str, value: int) -> str:
    options = (
        (-2, "Major weakness"), (-1, "Weakness"), (0, "Not specified"),
        (1, "Strength"), (2, "Major strength"),
    )
    option_html = "".join(
        f"<option value='{level}'{' selected' if level == value else ''}>"
        f"{text}</option>"
        for level, text in options
    )
    input_id = name.replace("_", "-")
    return (
        f"<label class='opponent-detail' for='{input_id}'>"
        f"<span>{html.escape(label)}</span><select id='{input_id}' "
        f"name='{html.escape(name, quote=True)}'>{option_html}</select></label>"
    )


def _detailed_controls(profile: OpponentProfile) -> str:
    position_values = dict(profile.position_levels)
    attribute_values = dict(profile.attribute_levels)
    position_controls = "".join(
        _detail_select(
            _QUERY_PREFIX + "pos_" + item.key,
            f"{item.key} — {item.label}",
            position_values.get(item.key, 0),
        )
        for item in POSITION_DEFINITIONS
    )
    groups = []
    for group, keys in ATTRIBUTE_GROUPS:
        controls = "".join(
            _detail_select(
                _QUERY_PREFIX + "attr_" + ATTRIBUTES_BY_KEY[key].query_key,
                ATTRIBUTES_BY_KEY[key].label,
                attribute_values.get(key, 0),
            )
            for key in keys
        )
        groups.append(
            f"<fieldset><legend>{html.escape(group)}</legend>"
            f"<div class='opponent-detail-grid'>{controls}</div></fieldset>"
        )
    open_text = " open" if profile.attribute_levels or profile.position_levels else ""
    return (
        f"<details class='opponent-details'{open_text}>"
        "<summary>Detailed strengths and weaknesses</summary>"
        "<p class='muted'>Use these when the scout report names a position or "
        "attribute. A detailed Pace, Dribbling, or Finishing observation replaces "
        "the equivalent broad slider above.</p>"
        "<fieldset><legend>Positions</legend>"
        f"<div class='opponent-detail-grid'>{position_controls}</div></fieldset>"
        + "".join(groups)
        + "</details>"
    )


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
    formation_options = "".join(
        f"<option value='{html.escape(item.key, quote=True)}'"
        + (" selected" if item.key == profile.formation else "")
        + f">{html.escape(item.label)}</option>"
        for item in FORMATION_DEFINITIONS
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
        "<label class='opponent-choice' for='opponent-formation'><span>"
        "<b>Likely formation</b></span><select id='opponent-formation' "
        f"name='{_QUERY_PREFIX}formation'>{formation_options}</select></label>"
        + "".join(sliders)
        + _detailed_controls(profile)
        + "<div class='opponent-actions'><button type='submit'>Apply opponent</button>"
        + reset
        + "</div></form></section>"
        "<script>(function(){document.querySelectorAll('.opponent-slider input').forEach(function(input){"
        "input.addEventListener('input',function(){var output=input.closest('label').querySelector('output');"
        "output.textContent=(input.value>0?'+':'')+input.value;});});})();</script>"
    )
