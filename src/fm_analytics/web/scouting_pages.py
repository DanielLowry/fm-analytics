"""Scouting page handlers, split out of ``handlers.py``.

A mixin so ``SquadWebHandler`` keeps a single route table. Everything here
reads the scouting feed through ``self.server`` and lays out numbers produced
by ``fm_analytics.analytics``; it computes no scores of its own.
"""

from __future__ import annotations

import html
import json
from http import HTTPStatus
from typing import Sequence

from urllib.parse import unquote

from fm_analytics.analytics import (
    DEFAULT_SORT_BY_MODE,
    FamiliarityPolicy,
    MARKET_FILTERS,
    MVP_CATALOGUE,
    RANKING_SORTS,
    SORTS_BY_MODE,
    ScoutingFilters,
    PlayerSelectionInput,
    rank_candidates_for_tactic,
    sort_tactic_assessments,
    assess_scouting_candidates,
    available_fact_values,
    default_descending,
    filter_position_rankings,
    filter_scouting_candidates,
    filter_tactic_assessments,
    rank_for_position,
    scouting_mode,
    sort_scouting_assessments,
)
from fm_analytics.web.scouting_script import _SCOUTING_LIVE_FILTER_SCRIPT
from fm_analytics.web.scouting_render import (
    ranking_results,
    role_results,
    tactic_ranking_results,
)
from fm_analytics.web.scouting_report import player_scouting_report, tactic_player_impact
from fm_analytics.web.rendering import (
    _MAX_SCOUTING_ROWS,
    _error_page,
    _input_value,
    _label,
    _layout,
    _options,
    _query_first,
    _raw_position_notice,
    _knowledge_notice,
    _refresh_notice,
    _scouting_filters,
    _scouting_limit,
    _scouting_tab_nav,
    _tactic_choices,
)


class ScoutingPagesMixin:
    def _scouting_page(self, path: str, query: dict[str, list[str]]) -> None:
        """A separate external-player workspace that retains uncertainty.

        This page intentionally does not call ``bundle()``: scouting remains
        useful while the owned squad is incomplete, and its candidate feed is
        evidence-bounded separately from the squad source.
        """
        try:
            candidates = self.server.scouting()  # type: ignore[attr-defined]
            filters = _scouting_filters(query)
        except (OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Scouting", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return

        self._send(_layout("Scouting", path, self._scouting_body(query, candidates, filters), wide=True))

    def _scouting_body(self, query, candidates, filters: ScoutingFilters) -> str:
        limit = _scouting_limit(query)
        return (
            _scouting_tab_nav(query)
            + "<p class='intro'>Only players in the manager-visible discovery feed are shown. "
            "Attribute-based role scores preserve their <b>floor / estimate / ceiling</b>; a player with "
            "no known role attributes is a reason to scout, not a claim that they are good.</p>"
            + _refresh_notice(_query_first(query, "refreshed"))
            + _knowledge_notice(self.server.knowledge_note)  # type: ignore[attr-defined]
            + _scouting_refresh_panel(filters.scouted_only)
            + self._scouting_filters_form(
                filters, candidates, self.server.pinned_tactics, limit  # type: ignore[attr-defined]
            )
            + "<div id='scouting-results' aria-live='polite'>"
            + self._scouting_results_block(candidates, filters, limit)
            + "</div>"
            + _SCOUTING_LIVE_FILTER_SCRIPT
        )

    def _scouting_results_fragment(self, _path: str, query: dict[str, list[str]]) -> None:
        """The results half of ``/scouting``, alone, for the page's own live filtering.

        Computed by the exact same call as the full page -- ``_scouting_results_block``
        -- so a number that updates as you type is never a second, divergent
        computation from the one the full page shows on load.
        """
        try:
            candidates = self.server.scouting()  # type: ignore[attr-defined]
            filters = _scouting_filters(query)
        except (OSError, ValueError, KeyError) as exc:
            self._send(
                f"<p class='warn'>{html.escape(str(exc))}</p>", HTTPStatus.SERVICE_UNAVAILABLE
            )
            return
        self._send(self._scouting_results_block(candidates, filters, _scouting_limit(query)))

    def _scouting_player_page(self, path: str, query: dict[str, list[str]]) -> None:
        """Show the exhaustive, evidence-bounded report for one scouted player."""
        player_id = unquote(path.removeprefix("/scouting/player/"))
        try:
            candidate = next(
                (item for item in self.server.scouting() if item.id == player_id),  # type: ignore[attr-defined]
                None,
            )
        except (OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Scouting report", str(exc), "/scouting"), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if candidate is None:
            self._send(
                _error_page("Scouting report", "That player is not in the current scouting capture.", "/scouting"),
                HTTPStatus.NOT_FOUND,
            )
            return
        tactic_key = _query_first(query, "tactic")
        include_raw_positions = _query_first(query, "includeRawPositions") == "1"
        tactic_options = _options(
            _tactic_choices(
                (
                    (key, tactic.name)
                    for key, tactic in sorted(
                        MVP_CATALOGUE.tactics.items(), key=lambda item: item[1].name
                    )
                ),
                self.server.pinned_tactics,  # type: ignore[attr-defined]
            ),
            tactic_key,
            "Choose a tactic",
        )
        impact = (
            "<h2>Tactic impact</h2>"
            f"<form class='filters' method='get' action='{html.escape(path, quote=True)}'>"
            f"<label>Tactic<select name='tactic'>{tactic_options}</select></label>"
            "<label class='check'><input name='includeRawPositions' type='checkbox' value='1'"
            + (" checked" if include_raw_positions else "")
            + "> Use raw external positions (accepted visibility gap)</label>"
            "<button type='submit'>Analyse player</button></form>"
        )
        if tactic_key:
            if tactic_key not in MVP_CATALOGUE.tactics:
                impact += "<p class='warn'>The selected tactic is not in the catalogue.</p>"
            else:
                try:
                    bundle = self.server.bundle()  # type: ignore[attr-defined]
                    tactic = MVP_CATALOGUE.tactics[tactic_key]
                    baseline = bundle.recommendation.by_tactic_key(tactic_key)
                    assessments = rank_candidates_for_tactic(
                        (candidate,),
                        tuple(
                            PlayerSelectionInput.from_player(player)
                            for player in bundle.squad.players
                        ),
                        tactic,
                        MVP_CATALOGUE,
                        baseline,
                        readiness_policy=bundle.policy.readiness,
                        familiarity_policy=bundle.policy.familiarity,
                        opponent=bundle.policy.opponent,
                        include_raw_external_positions=include_raw_positions,
                    )
                    impact += tactic_player_impact(
                        assessments[0] if assessments else None,
                        tactic=tactic,
                        baseline=baseline,
                    )
                except (OSError, RuntimeError, ValueError, KeyError) as exc:
                    impact += (
                        "<p class='warn'>Tactic analysis needs a complete current squad: "
                        + html.escape(str(exc))
                        + "</p>"
                    )
        self._send(
            _layout(
                f"Scouting report · {candidate.name}",
                "/scouting",
                player_scouting_report(
                    candidate,
                    MVP_CATALOGUE,
                    headline=impact,
                ),
            )
        )

    def _scouting_results_block(self, candidates, filters: ScoutingFilters, limit: int = _MAX_SCOUTING_ROWS) -> str:
        """Whichever table the filters call for.

        Every branch ends in the same sortable table, in the sort and direction
        the filters carry, so a column that can be sorted in one view can be
        sorted in all of them.
        """
        mode = scouting_mode(filters.tactic_key, filters.role_key)
        if mode == "tactic":
            return self._tactic_scouting_results(candidates, filters, limit)
        descending = (
            filters.ranking_descending
            if filters.ranking_descending is not None
            else default_descending(filters.ranking_sort)
        )
        common = dict(
            sort=filters.ranking_sort,
            sort_label=SORTS_BY_MODE[mode][filters.ranking_sort],
            descending=descending,
            raw_positions=filters.include_raw_external_positions,
            limit=limit,
            pool_size=len(candidates),
            scouted_only=filters.scouted_only,
        )
        notice = (
            _raw_position_notice(candidates) if filters.include_raw_external_positions else ""
        )
        if mode == "role":
            assessments = sort_scouting_assessments(
                assess_scouting_candidates(candidates, MVP_CATALOGUE, filters),
                sort=filters.ranking_sort, descending=descending,
            )
            role = MVP_CATALOGUE.roles.get(filters.role_key or "")
            return notice + role_results(
                assessments, role_name=role.name if role else "selected role", **common
            )
        rankings = rank_for_position(
            filter_scouting_candidates(candidates, filters), MVP_CATALOGUE, filters.position,
            sort=filters.ranking_sort, descending=descending,
            include_raw_external_positions=filters.include_raw_external_positions,
            # The same opt-in as the raw positions: ticking it accepts the raw
            # position data, ratings included.
            familiarity_policy=(
                FamiliarityPolicy() if filters.include_raw_external_positions else None
            ),
            cache=self.server.scouting_rank_cache,  # type: ignore[attr-defined]
        )
        return notice + ranking_results(
            filter_position_rankings(rankings, filters), position=filters.position, **common
        )

    def _tactic_scouting_results(
        self, candidates, filters: ScoutingFilters, limit: int = _MAX_SCOUTING_ROWS
    ) -> str:
        if filters.tactic_key not in MVP_CATALOGUE.tactics:
            return "<p class='warn'>The selected tactic is not in the catalogue.</p>"
        try:
            bundle = self.server.bundle()  # type: ignore[attr-defined]
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            return (
                "<p class='warn'>Tactic-based scouting needs a complete current squad: "
                + html.escape(str(exc))
                + "</p>"
            )
        pool = filter_scouting_candidates(candidates, filters)
        tactic = MVP_CATALOGUE.tactics[filters.tactic_key]
        baseline = bundle.recommendation.by_tactic_key(filters.tactic_key)
        assessments = filter_tactic_assessments(
            rank_candidates_for_tactic(
                pool,
                tuple(PlayerSelectionInput.from_player(player) for player in bundle.squad.players),
                tactic,
                MVP_CATALOGUE,
                baseline,
                readiness_policy=bundle.policy.readiness,
                familiarity_policy=bundle.policy.familiarity,
                opponent=bundle.policy.opponent,
                include_raw_external_positions=filters.include_raw_external_positions,
                position=filters.position,
                role_key=filters.role_key,
            ),
            filters,
        )
        descending = (
            filters.ranking_descending
            if filters.ranking_descending is not None
            else default_descending(filters.ranking_sort)
        )
        return (
            (_raw_position_notice(pool) if filters.include_raw_external_positions else "")
            + tactic_ranking_results(
                sort_tactic_assessments(
                    assessments, sort=filters.ranking_sort, descending=descending
                ),
                tactic=tactic,
                baseline=baseline,
                sort=filters.ranking_sort,
                sort_label=SORTS_BY_MODE["tactic"][filters.ranking_sort],
                descending=descending,
                raw_positions=filters.include_raw_external_positions,
                limit=limit,
                pool_size=len(candidates),
                scouted_only=filters.scouted_only,
            )
        )

    @staticmethod
    def _scouting_filters_form(
        filters: ScoutingFilters,
        candidates: Sequence[object],
        pinned_tactics: tuple[str, ...],
        limit: int = _MAX_SCOUTING_ROWS,
    ) -> str:
        def values(name: str) -> tuple[str, ...]:
            return tuple(sorted({str(getattr(item, name)) for item in candidates if getattr(item, name) is not None}))

        def select(label: str, name: str, options: str) -> str:
            return f"<label>{label}<select name='{name}'>{options}</select></label>"

        def number(label: str, name: str, value: object, **attrs: object) -> str:
            extra = "".join(f" {key}='{val}'" for key, val in attrs.items())
            return f"<label>{label}<input name='{name}' type='number'{extra} value='{_input_value(value)}'></label>"

        def text(label: str, name: str, value: str | None) -> str:
            return f"<label>{label}<input name='{name}' value='{html.escape(value or '', quote=True)}'></label>"

        def group(title: str, active: int, controls: str) -> str:
            badge = f" <span class='filter-count'>{active} set</span>" if active else ""
            return (
                f"<details class='filter-group'{' open' if active else ''}>"
                f"<summary>{title}{badge}</summary><div class='filter-grid'>{controls}</div></details>"
            )

        def fact_options(name: str, selected: str | None) -> str:
            return _options(((value, value) for value in values(name)), selected, "Any")

        mode = scouting_mode(filters.tactic_key, filters.role_key)
        positions = sorted({
            position for role in MVP_CATALOGUE.roles.values() for position in role.eligible_positions
        })
        # Structural fact from the catalogue (which roles are eligible for
        # which position) -- not a score, so embedding it for the client-side
        # role-narrowing script does not duplicate any analytics computation.
        roles_by_position = {
            position: sorted(
                ((key, role.name) for key, role in MVP_CATALOGUE.roles.items()
                 if position in role.eligible_positions),
                key=lambda item: item[1],
            )
            for position in positions
        }
        every_role = sorted(
            ((key, role.name) for key, role in MVP_CATALOGUE.roles.items()), key=lambda item: item[1]
        )
        roles_by_position[""] = every_role
        tactic_options = _options(
            _tactic_choices(
                ((key, tactic.name) for key, tactic in sorted(
                    MVP_CATALOGUE.tactics.items(), key=lambda item: item[1].name)),
                pinned_tactics,
            ),
            filters.tactic_key,
            "Generic position / role ranking",
        )
        role_options = _options(
            roles_by_position.get(filters.position or "", every_role), filters.role_key, "Any role"
        )
        direction = (
            filters.ranking_descending
            if filters.ranking_descending is not None
            else default_descending(filters.ranking_sort)
        )
        facts = available_fact_values(candidates)

        primary = (
            select("Tactic", "tactic", tactic_options)
            + select("Position", "position", _options(((p, p) for p in positions), filters.position, "Any position"))
            + select("Role", "role", role_options)
            + text("Player name", "name", filters.name_contains)
            + "<label>Sort by<select name='sort' data-defaults='"
            + html.escape(json.dumps(DEFAULT_SORT_BY_MODE), quote=True) + "'>"
            + _sort_options(filters.ranking_sort, mode, filters.include_raw_external_positions)
            + "</select></label>"
        )
        player = (
            text("Club contains", "club", filters.club_contains)
            + select("Nationality", "nationality", fact_options("nationality", filters.nationality))
            + select("Footedness", "footedness", fact_options("footedness", filters.footedness))
            + number("Minimum age", "minAge", filters.minimum_age, min=0)
            + number("Maximum age", "maxAge", filters.maximum_age, min=0)
        )
        market = (
            select("Contract / listing", "market", _options(MARKET_FILTERS.items(), filters.market, ""))
            + number("Expiring within (months)", "expiringMonths", filters.expiring_months, min=0)
            + number("Max value (&pound;)", "maxValue", filters.maximum_value, min=0, step=500)
            + select("Transfer status", "transferStatus", fact_options("transfer_status", filters.transfer_status))
            + select("Availability", "availability", fact_options("availability", filters.availability))
            + select("FM search match", "searchMatch", _options(
                (("any", "Any"), ("matched", "Matched your FM search"), ("unmatched", "Did not match")),
                filters.search_match, ""))
        )
        knowledge = (
            select("Visibility", "visibility", _options(
                (("any", "Any"), ("known", "Fully known"), ("partial", "Has a range"),
                 ("unknown", "Nothing known")), filters.visibility, ""))
            + number("Minimum floor", "minFloor", filters.minimum_floor, min=0, max=100, step=0.1)
            + number("Minimum ceiling", "minCeiling", filters.minimum_ceiling, min=0, max=100, step=0.1)
            + "<label class='check'><input name='includeUnlikely' type='checkbox' value='1'"
            + (" checked" if filters.include_unlikely else "")
            + "> Keep players below the ceiling</label>"
        )
        fact_controls = "".join(
            select(html.escape(_label(key)), "fact." + html.escape(key, quote=True),
                   _options(((value, value) for value in choices), (filters.facts or {}).get(key), "Any"))
            for key, choices in facts.items()
        )
        view = "scouted" if filters.scouted_only else "all"
        return (
            "<form class='filters scouting-filters' method='get' action='/scouting'>"
            # A hidden field, not a JS special-case: FormData already reads
            # every form field for the live-filter fetch, so this is what
            # keeps the active tab from reverting to "all" on the very next
            # keystroke -- "view" is otherwise carried by the tab link only,
            # not by anything inside the form itself.
            f"<input type='hidden' name='view' value='{view}'>"
            # The direction the results are currently sorted in; the header
            # buttons flip it, and an empty value means "that column's default".
            f"<input type='hidden' name='dir' value='{'desc' if direction else 'asc'}'>"
            # How many rows the "Show more" button has asked for; empty is the default page.
            f"<input type='hidden' name='limit' value='{'' if limit == _MAX_SCOUTING_ROWS else limit}'>"
            "<fieldset class='filter-primary'><legend>Find a target</legend>"
            f"<div class='filter-grid'>{primary}</div></fieldset>"
            + group("Player", _count(
                filters.club_contains, filters.nationality, filters.footedness,
                filters.minimum_age, filters.maximum_age), player)
            + group("Contract, cost &amp; availability", _count(
                filters.market != "any" or None, filters.maximum_value, filters.transfer_status,
                filters.availability, filters.search_match != "any" or None), market)
            + group("What scouting shows", _count(
                filters.visibility != "any" or None, filters.minimum_floor, filters.minimum_ceiling,
                filters.include_unlikely or None), knowledge)
            + (group("Captured Player Search facts", _count(*(filters.facts or {}).values()), fact_controls)
               if fact_controls else "")
            + "<div class='filter-actions'>"
            "<label class='check'><input name='includeRawPositions' type='checkbox' value='1'"
            + (" checked" if filters.include_raw_external_positions else "")
            + "> Use raw external positions (accepted visibility gap)</label>"
            "<span class='spacer'></span>"
            f"<a class='reset' href='/scouting?view={view}'>Reset filters</a>"
            "<button type='submit'>Apply filters</button></div>"
            "</form>"
            "<script id='position-roles-data' type='application/json'>"
            + json.dumps(roles_by_position).replace("</", "<\\/")
            + "</script>"
        )


def _count(*values: object) -> int:
    """How many of a group's filters are set, for its summary line."""
    return sum(value is not None and value != "" and value is not False for value in values)


def _sort_options(selected: str, mode: str, include_raw: bool) -> str:
    """Every sort, with the ones this mode's table has left enabled.

    The page's script re-evaluates ``data-modes`` when the tactic or role
    changes (which changes the table), so the list never offers a column the
    table does not have. The two position-rating sorts also need the raw
    positions box.
    """
    options = []
    for key, label in RANKING_SORTS.items():
        modes = " ".join(name for name, sorts in SORTS_BY_MODE.items() if key in sorts)
        needs_raw = key in {"adjusted", "familiarity"}
        available = key in SORTS_BY_MODE[mode] and (include_raw or not needs_raw)
        options.append(
            f"<option value='{key}' data-modes='{modes}'"
            + (" data-raw='1'" if needs_raw else "")
            + (" selected" if key == selected else "")
            + ("" if available else " hidden disabled")
            + f">{html.escape(label)}</option>"
        )
    return "".join(options)


def _scouting_refresh_panel(scouted_only: bool) -> str:
    """Refreshing the capture. The main button on either tab only reads FM's memory.

    Asking FM for unscouted players' attributes runs FM's own code inside the
    running game, and is the prime suspect for the saves that broke again on
    26 September 2026, the evening that became this button's default. It is a
    separate, collapsed, explicitly-worded action -- the same footing as the
    pool rebuild in ``_pool_not_built_page`` -- and never the default.
    """
    if scouted_only:
        return (
            "<section class='refresh-panel'>"
            "<form class='refresh' method='post' action='/scouting/refresh'>"
            "<input type='hidden' name='return_view' value='scouted'>"
            "<button type='submit'>Refresh scouted players</button>"
            "<span class='muted'>Reads current scout reports and their visible "
            "attributes from FM's memory. Nothing is sent to FM.</span></form></section>"
        )
    return (
        "<section class='refresh-panel'>"
        "<form class='refresh' method='post' action='/scouting/refresh'>"
        "<input type='hidden' name='return_view' value='all'>"
        "<button type='submit'>Refresh scouting data</button>"
        "<span class='muted'>Reads FM's memory only; nothing is sent to FM. Updates the "
        "player list, scouted players' attributes, and which players match the search "
        "open in FM.</span></form>"
        "<details><summary>Attributes for players you haven't scouted</summary>"
        "<p>FM shows some attributes for players you have never scouted, from what "
        "your staff already know about them. This app cannot work those out by itself "
        "yet, so after a normal refresh those players read <b>Not captured from FM</b>.</p>"
        "<p class='warn'>The only way to get them today is to ask FM, which runs FM's "
        "own code inside your running game. That is the step suspected of breaking "
        "saves on 26 September 2026: they saved without an error, then would not "
        "load. <b>Only do this on a save you would not mind losing</b>, or after "
        "taking a copy of your save file.</p>"
        "<p class='muted'>Leave the Player Search you want open in FM first. Up to 256 "
        "results.</p>"
        "<form class='refresh' method='post' action='/scouting/refresh'>"
        "<input type='hidden' name='hydrate_active_search' value='1'>"
        "<input type='hidden' name='return_view' value='all'>"
        "<button type='submit' class='danger'>Ask FM for these attributes "
        "(risks this save)</button></form></details></section>"
    )
