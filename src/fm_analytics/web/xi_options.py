"""Bookmarkable options for re-optimising a tactic's starting XI."""
from __future__ import annotations

import html
from urllib.parse import parse_qsl, urlencode

from fm_analytics.web.opponent_controls import opponent_query
from fm_analytics.web.rendering import _query_first


_OPTIONS = (("ignore_form", "ignoreForm", "Ignore form"),
            ("ignore_condition", "ignoreCondition", "Ignore condition"))


def selection_options_from_query(query):
    options = {}
    for key, parameter, label in _OPTIONS:
        value = _query_first(query, parameter)
        if value not in (None, "0", "1"):
            raise ValueError(f"{label} must be 0 or 1")
        options[key] = value == "1"
    return options


def selection_options_query(*, ignore_form=False, ignore_condition=False):
    options = {"ignore_form": ignore_form, "ignore_condition": ignore_condition}
    return {parameter: "1" for key, parameter, _label in _OPTIONS if options[key]}


def tactic_query(opponent, *, ignore_form=False, ignore_condition=False):
    return "&".join(part for part in (
        opponent_query(opponent),
        urlencode(selection_options_query(ignore_form=ignore_form, ignore_condition=ignore_condition)),
    ) if part)


def selection_controls(action, opponent, *, ignore_form=False, ignore_condition=False):
    options = {"ignore_form": ignore_form, "ignore_condition": ignore_condition}
    hidden = "".join(
        f"<input type='hidden' name='{html.escape(key, quote=True)}' value='{html.escape(value, quote=True)}'>"
        for key, value in parse_qsl(opponent_query(opponent))
    )
    switches = "".join(
        f"<label><input type='checkbox' name='{parameter}' value='1'"
        + (" checked" if options[key] else "") + f">{label}</label>"
        for key, parameter, label in _OPTIONS
    )
    return (
        f"<form class='fm-table-toolbar fm-xi-options' method='get' action='{html.escape(action, quote=True)}' data-xi-options>"
        "<strong>XI selection</strong>" + hidden + switches
        + "<span role='status' aria-live='polite' data-xi-status></span>"
        "<p class='muted'>Ignore condition removes its selection cutoff and score penalty. Match fitness still applies.</p>"
        "<noscript><button type='submit'>Re-optimize XI</button></noscript></form>"
    )
