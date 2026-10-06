"""Bookmarkable options for re-optimising a tactic's starting XI."""
from __future__ import annotations

import html
from urllib.parse import parse_qsl, urlencode

from fm_analytics.web.opponent_controls import opponent_query
from fm_analytics.web.rendering import _query_first


_OPTIONS = (("ignore_form", "ignoreForm", "Ignore form"),
            ("ignore_condition", "ignoreCondition", "Ignore condition"))
# Players ruled out of one tactic's XI, comma-separated in the order excluded.
_EXCLUDE = "exclude"


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


def excluded_from_query(query):
    excluded = []
    for player_id in (_query_first(query, _EXCLUDE) or "").split(","):
        player_id = player_id.strip()
        if player_id and player_id not in excluded:
            excluded.append(player_id)
    return tuple(excluded)


def exclusion_query(excluded):
    return {_EXCLUDE: ",".join(excluded)} if excluded else {}


def xi_href(path, opponent, excluded, *, anchor="#starting-xi", ignore_form=False, ignore_condition=False):
    """This tactic page with these players excluded, every other option kept."""
    query = "&".join(part for part in (
        tactic_query(opponent, ignore_form=ignore_form, ignore_condition=ignore_condition),
        urlencode(exclusion_query(excluded), safe=","),
    ) if part)
    return path + (f"?{query}" if query else "") + anchor


def exclude_link(href, name):
    return (
        f"<a class='fm-xi-exclude' href='{html.escape(href, quote=True)}' data-xi-exclusion "
        f"title='{html.escape(f'Pick the best team without {name}', quote=True)}'>Exclude</a>"
    )


def exclusion_panel(path, opponent, excluded_players, score, full_squad_score, **selection_options):
    """Who is ruled out of this XI, what it costs, and a way back for each."""
    if not excluded_players:
        return ""
    ids = tuple(player.id for player in excluded_players)
    restores = "".join(
        f"<li><b>{html.escape(player.name)}</b><a href='"
        + html.escape(xi_href(path, opponent, tuple(item for item in ids if item != player.id), **selection_options), quote=True)
        + f"' data-xi-exclusion aria-label='{html.escape(f'Restore {player.name}', quote=True)}'>Restore</a></li>"
        for player in excluded_players
    )
    change = score - full_squad_score
    return (
        "<div class='fm-xi-excluded' role='region' aria-label='Excluded players'>"
        f"<div class='fm-xi-excluded-heading'><b>Excluded ({len(excluded_players)})</b>"
        f"<a href='{html.escape(xi_href(path, opponent, (), **selection_options), quote=True)}' data-xi-exclusion>"
        "Restore all</a></div>"
        f"<ul>{restores}</ul>"
        f"<p>Tactic score <b>{score:.1f}</b> without them ({change:+.1f} against the full-squad XI). "
        "The XI, bench and cover below are picked from everyone else; the tactic ranking still uses the full squad.</p>"
        "</div>"
    )


def selection_controls(action, opponent, *, ignore_form=False, ignore_condition=False, excluded=()):
    options = {"ignore_form": ignore_form, "ignore_condition": ignore_condition}
    hidden = "".join(
        f"<input type='hidden' name='{html.escape(key, quote=True)}' value='{html.escape(value, quote=True)}'>"
        for key, value in (*parse_qsl(opponent_query(opponent)), *exclusion_query(excluded).items())
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
