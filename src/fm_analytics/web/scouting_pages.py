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
    FamiliarityPolicy,
    MARKET_FILTERS,
    MVP_CATALOGUE,
    RANKING_SORTS,
    ScoutRecommendation,
    ScoutingFilters,
    PlayerSelectionInput,
    rank_candidates_for_tactic,
    sort_tactic_assessments,
    assess_scouting_candidates,
    available_fact_values,
    default_descending,
    filter_scouting_candidates,
    rank_for_position,
)
from fm_analytics.web.scouting_render import (
    attribute_sheet,
    past_knowledge_cell,
    player_scouting_report,
    ranking_results,
    scouting_player_link,
    tactic_player_impact,
    tactic_ranking_results,
)
from fm_analytics.web.rendering import (
    _MAX_SCOUTING_ROWS,
    _SCOUTING_LIVE_FILTER_SCRIPT,
    _band,
    _error_page,
    _input_value,
    _label,
    _layout,
    _options,
    _position_display,
    _query_first,
    _raw_position_notice,
    _refresh_notice,
    _scouting_filters,
    _scouting_knowledge_cell,
    _scouting_tab_nav,
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

        facts = available_fact_values(candidates)
        positions = sorted({position for role in MVP_CATALOGUE.roles.values() for position in role.eligible_positions})
        selected_role = filters.role_key or ""
        role_options = _options(
            ((key, role.name) for key, role in sorted(MVP_CATALOGUE.roles.items())), selected_role,
            "Choose a role",
        )
        position_options = _options(((item, item) for item in positions), filters.position, "Any position")
        tactic_options = _options(
            (
                (key, tactic.name)
                for key, tactic in sorted(
                    MVP_CATALOGUE.tactics.items(), key=lambda item: item[1].name
                )
            ),
            filters.tactic_key,
            "Generic position / role ranking",
        )
        # Structural fact from the catalogue (which roles are eligible for
        # which position) -- not a score, so embedding it for the client-side
        # role-narrowing script does not duplicate any analytics computation.
        position_role_options = {
            position: sorted(
                (
                    (key, role.name)
                    for key, role in MVP_CATALOGUE.roles.items()
                    if position in role.eligible_positions
                ),
                key=lambda item: item[1],
            )
            for position in positions
        }
        fact_controls = "".join(
            "<label>" + html.escape(_label(key))
            + "<select name='fact." + html.escape(key, quote=True) + "'>"
            + _options(((value, value) for value in values), (filters.facts or {}).get(key), "Any")
            + "</select></label>"
            for key, values in facts.items()
        )
        body = (
            _scouting_tab_nav(query)
            + "<p>Only players in the manager-visible discovery feed are shown. "
            "Attribute-based role scores preserve their <b>floor / estimate / ceiling</b>; a player with "
            "no known role attributes is a reason to scout, not a claim that they are good.</p>"
            + _refresh_notice(_query_first(query, "refreshed"))
            + "<form class='refresh' method='post' action='/scouting/refresh'>"
            "<button type='submit'>Refresh scouting data</button>"
            "<span class='muted'>Reads the current FM Player Search pool; this can take "
            "a little while.</span></form>"
            + self._scouting_filters_form(
                filters,
                tactic_options,
                role_options,
                position_options,
                candidates,
                fact_controls,
            )
            + "<script id='position-roles-data' type='application/json'>"
            + json.dumps(position_role_options).replace("</", "<\\/")
            + "</script>"
            + "<div id='scouting-results'>"
            + self._scouting_results_block(candidates, filters)
            + "</div>"
            + _SCOUTING_LIVE_FILTER_SCRIPT
        )
        self._send(_layout("Scouting", path, body))

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
        self._send(self._scouting_results_block(candidates, filters))

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
            (
                (key, tactic.name)
                for key, tactic in sorted(
                    MVP_CATALOGUE.tactics.items(), key=lambda item: item[1].name
                )
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

    def _scouting_results_block(self, candidates, filters: ScoutingFilters) -> str:
        if filters.tactic_key:
            return self._tactic_scouting_results(candidates, filters)
        assessments = (
            assess_scouting_candidates(candidates, MVP_CATALOGUE, filters)
            if filters.role_key
            else ()
        )

        position_candidates = (
            ()
            if filters.role_key
            else filter_scouting_candidates(candidates, filters)
        )
        if not filters.role_key and (filters.position or filters.scouted_only):
            # No role chosen: rank everyone by whichever role suits each best,
            # so "who should I scout next" has an answer without picking a
            # position first (the Scouted tab) or a role at all.
            descending = (
                filters.ranking_descending
                if filters.ranking_descending is not None
                else default_descending(filters.ranking_sort)
            )
            return (
                (_raw_position_notice(candidates) if filters.include_raw_external_positions else "")
                + ranking_results(
                    rank_for_position(
                        position_candidates, MVP_CATALOGUE, filters.position,
                        sort=filters.ranking_sort, descending=descending,
                        include_raw_external_positions=filters.include_raw_external_positions,
                        # The same opt-in as the raw positions: ticking it accepts
                        # the raw position data, ratings included.
                        familiarity_policy=(
                            FamiliarityPolicy() if filters.include_raw_external_positions else None
                        ),
                    ),
                    position=filters.position,
                    sort=filters.ranking_sort,
                    sort_label=RANKING_SORTS[filters.ranking_sort],
                    descending=descending,
                    raw_positions=filters.include_raw_external_positions,
                )
            )
        return (
            (
                _raw_position_notice(candidates)
                if filters.include_raw_external_positions
                else ""
            )
            + (
                self._scouting_results(
                    assessments,
                    filters.role_key or "",
                    len(candidates),
                    include_raw_external_positions=filters.include_raw_external_positions,
                )
                if filters.role_key
                else self._scouting_position_results(
                    position_candidates,
                    include_raw_external_positions=filters.include_raw_external_positions,
                )
            )
        )

    def _tactic_scouting_results(self, candidates, filters: ScoutingFilters) -> str:
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
        candidates = filter_scouting_candidates(candidates, filters)
        tactic = MVP_CATALOGUE.tactics[filters.tactic_key]
        baseline = bundle.recommendation.by_tactic_key(filters.tactic_key)
        assessments = rank_candidates_for_tactic(
            candidates,
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
        )

        def visible(item) -> bool:
            if filters.visibility == "known" and (
                item.ranged_attributes or item.unknown_attributes
            ):
                return False
            if filters.visibility == "partial" and not item.ranged_attributes:
                return False
            if filters.visibility == "unknown" and (
                item.known_attributes or item.ranged_attributes
            ):
                return False
            if (
                filters.minimum_floor is not None
                and item.player_fit.lower < filters.minimum_floor
            ):
                return False
            if (
                filters.minimum_ceiling is not None
                and item.player_fit.upper < filters.minimum_ceiling
                and not filters.include_unlikely
            ):
                return False
            return True

        assessments = tuple(item for item in assessments if visible(item))
        descending = (
            filters.ranking_descending
            if filters.ranking_descending is not None
            else default_descending(filters.ranking_sort)
        )
        ordered = sort_tactic_assessments(
            assessments, sort=filters.ranking_sort, descending=descending
        )
        return (
            (_raw_position_notice(candidates) if filters.include_raw_external_positions else "")
            + tactic_ranking_results(
                ordered,
                tactic=tactic,
                baseline=baseline,
                sort=filters.ranking_sort,
                sort_label=RANKING_SORTS[filters.ranking_sort],
                descending=descending,
            )
        )

    @staticmethod
    def _scouting_filters_form(
        filters: ScoutingFilters,
        tactic_options: str,
        role_options: str,
        position_options: str,
        candidates: Sequence[object],
        fact_controls: str,
    ) -> str:
        def values(name: str) -> tuple[str, ...]:
            return tuple(sorted({str(getattr(item, name)) for item in candidates if getattr(item, name) is not None}))

        return (
            "<h2>Find a target</h2><form class='filters' method='get' action='/scouting'>"
            # A hidden field, not a JS special-case: FormData already reads
            # every form field for the live-filter fetch, so this is what
            # keeps the active tab from reverting to "all" on the very next
            # keystroke -- "view" is otherwise carried by the tab link only,
            # not by anything inside the form itself.
            f"<input type='hidden' name='view' value='{'scouted' if filters.scouted_only else 'all'}'>"
            # The direction the results are currently sorted in; the header
            # buttons flip it, and an empty value means "that column's default".
            f"<input type='hidden' name='dir' value='{'desc' if (filters.ranking_descending if filters.ranking_descending is not None else default_descending(filters.ranking_sort)) else 'asc'}'>"
            f"<label>Tactic<select name='tactic'>{tactic_options}</select></label>"
            f"<label>Position<select name='position'>{position_options}</select></label>"
            f"<label>Role (optional)<select name='role'>{role_options}</select></label>"
            f"<label>Minimum age<input name='minAge' type='number' min='0' value='{_input_value(filters.minimum_age)}'></label>"
            f"<label>Maximum age<input name='maxAge' type='number' min='0' value='{_input_value(filters.maximum_age)}'></label>"
            "<label>Contract / listing<select name='market'>"
            + _options(MARKET_FILTERS.items(), filters.market, "")
            + "</select></label>"
            f"<label>Running out within (months)<input name='expiringMonths' type='number' min='0' value='{filters.expiring_months}'></label>"
            f"<label>Max value (&pound;)<input name='maxValue' type='number' min='0' step='500' value='{_input_value(filters.maximum_value)}'></label>"
            "<label>FM search match<select name='searchMatch'>"
            + _options((("any", "Any"), ("matched", "Matched your FM search"),
                        ("unmatched", "Did not match")), filters.search_match, "")
            + "</select></label>"
            f"<label>Player name<input name='name' value='{html.escape(filters.name_contains or '', quote=True)}'></label>"
            f"<label>Club contains<input name='club' value='{html.escape(filters.club_contains or '', quote=True)}'></label>"
            "<label>Nationality<select name='nationality'>"
            + _options(((value, value) for value in values("nationality")), filters.nationality, "Any")
            + "</select></label><label>Footedness<select name='footedness'>"
            + _options(((value, value) for value in values("footedness")), filters.footedness, "Any")
            + "</select></label><label>Transfer status<select name='transferStatus'>"
            + _options(((value, value) for value in values("transfer_status")), filters.transfer_status, "Any")
            + "</select></label><label>Availability<select name='availability'>"
            + _options(((value, value) for value in values("availability")), filters.availability, "Any")
            + "</select></label><label>Visibility<select name='visibility'>"
            + _options(((key, label) for key, label in (("any", "Any"), ("known", "Fully known"), ("partial", "Has a range"), ("unknown", "Nothing known"))), filters.visibility, "")
            + "</select></label>"
            + "<label>Rank by<select name='sort'>"
            + _options(RANKING_SORTS.items(), filters.ranking_sort, "")
            + "</select></label>"
            f"<label>Minimum floor<input name='minFloor' type='number' min='0' max='100' step='0.1' value='{_input_value(filters.minimum_floor)}'></label>"
            f"<label>Minimum ceiling<input name='minCeiling' type='number' min='0' max='100' step='0.1' value='{_input_value(filters.minimum_ceiling)}'></label>"
            + fact_controls
            + "<label class='check'><input name='includeUnlikely' type='checkbox' value='1'"
            + (" checked" if filters.include_unlikely else "")
            + "> Include players below the ceiling</label>"
            + "<label class='check'><input name='includeRawPositions' type='checkbox' value='1'"
            + (" checked" if filters.include_raw_external_positions else "")
            + "> Use raw external positions (accepted visibility gap)</label>"
            + "<button type='submit'>Apply filters</button></form>"
        )

    @staticmethod
    def _scouting_results(
        assessments,
        role_key: str,
        total_candidates: int,
        *,
        include_raw_external_positions: bool,
    ) -> str:
        if not assessments:
            return (
                "<h2>Targets</h2><p class='muted'>"
                + ("No manager-visible scouting candidates have been loaded yet. Supply a verified scouting capture with <code>--scouting-json</code>." if total_candidates == 0 else "No candidates match these filters.")
                + "</p>"
            )
        displayed = assessments[:_MAX_SCOUTING_ROWS]
        rows: list[str] = []
        details: list[str] = []
        labels = {
            ScoutRecommendation.PROVEN_FIT: ("Proven fit", "badge-proven", "All role inputs are known."),
            ScoutRecommendation.SCOUT_FIRST: ("Scout first", "badge-scout", "No role attributes are known yet."),
            ScoutRecommendation.SCOUT_TO_DECIDE: ("Scout to decide", "badge-scout", "Ranges or unknowns can still change this decision."),
            ScoutRecommendation.UNLIKELY: ("Unlikely", "badge-unlikely", "Even the visible ceiling misses your filter."),
        }
        for item in displayed:
            label, badge, reason = labels[item.recommendation]
            candidate = item.candidate
            positions = candidate.positions_for(
                include_raw_external_positions=include_raw_external_positions
            )
            rows.append(
                "<tr>"
                f"<td>{scouting_player_link(candidate)}<br><span class='muted'>{html.escape(candidate.nationality or 'Nationality not known')}</span></td>"
                f"<td>{html.escape(candidate.club or '—')}</td><td>{candidate.age if candidate.age is not None else '—'}</td>"
                f"<td>{html.escape(', '.join(positions) or 'Not yet captured')}</td>"
                f"<td>{_band(item.role_score.score)}</td>"
                f"<td><b>{item.role_score.median:.1f}</b></td>"
                f"<td>{html.escape(item.visibility_summary)}</td>"
                f"<td>{past_knowledge_cell(candidate)}</td>"
                f"<td>{_scouting_knowledge_cell(candidate)}</td>"
                f"<td><span class='badge {badge}'>{label}</span><br><span class='muted'>{html.escape(reason)}</span></td></tr>"
            )
            attribute_cells = "".join(
                "<div><b>" + html.escape(contribution.attribute) + "</b>"
                + html.escape(contribution.observation.display()) + "</div>"
                for contribution in item.role_score.contributions
            )
            meta = [
                ("Club", candidate.club), ("Nationality", candidate.nationality),
                ("Footedness", candidate.footedness), ("Transfer status", candidate.transfer_status),
                ("Availability", candidate.availability),
            ]
            meta_text = " · ".join(f"{name}: {value}" for name, value in meta if value)
            next_scout = ", ".join(item.scout_next) if item.scout_next else "Nothing role-critical is unknown."
            details.append(
                f"<details><summary>{html.escape(candidate.name)} — {label}; attribute-based role score {_band(item.role_score.score)}</summary>"
                f"<p>{html.escape(meta_text or 'No additional manager-visible facts captured.')}<br>"
                f"<b>Scout next:</b> {html.escape(next_scout)}</p>"
                "<div class='attribute-grid'>" + attribute_cells + "</div>"
                + attribute_sheet(candidate) + "</details>"
            )
        role_name = MVP_CATALOGUE.roles[role_key].name if role_key in MVP_CATALOGUE.roles else "selected role"
        return (
            f"<h2>Targets for {html.escape(role_name)} ({len(assessments)})</h2>"
            + (
                f"<p class='muted'>Showing the first {len(displayed)} targets. "
                "More precise position and visibility filters will narrow this list.</p>"
                if len(assessments) > len(displayed) else ""
            )
            + "<ul class='legend'><li><b>Scout first</b>: no relevant attributes are known.</li>"
            "<li><b>Scout to decide</b>: ranges or unknown values could still change the role fit.</li>"
            "<li><b>Attribute-based floor / estimate / ceiling</b>: the best and worst role score supported by visible information. "
            "This table does not apply positional familiarity.</li></ul>"
            "<table><tr><th>Player</th><th>Club</th><th>Age</th><th>Positions"
            + (" (raw external data)" if include_raw_external_positions else "")
            + "</th><th>Attribute-based role score (min / est. / max)</th><th>Median estimate</th><th>Visibility</th><th>Past knowledge</th><th>Scouted</th><th>Recommendation</th></tr>"
            + "".join(rows) + "</table><h2>Visible role data</h2>" + "".join(details)
        )

    @staticmethod
    def _scouting_position_results(
        candidates,
        *,
        include_raw_external_positions: bool,
    ) -> str:
        if not candidates:
            return (
                "<h2>Players matching filters</h2><p class='muted'>No candidates "
                "match these position and factual filters.</p>"
            )
        displayed = candidates[:_MAX_SCOUTING_ROWS]
        rows = "".join(
            "<tr>"
            f"<td>{scouting_player_link(candidate)}</td>"
            f"<td>{html.escape(candidate.club or '—')}</td>"
            f"<td>{candidate.age if candidate.age is not None else '—'}</td>"
            f"<td>{_position_display(candidate, include_raw_external_positions=include_raw_external_positions)}</td>"
            f"<td>{html.escape(candidate.footedness or '—')}</td>"
            f"<td>{_scouting_knowledge_cell(candidate)}</td>"
            f"<td>{past_knowledge_cell(candidate)}</td>"
            f"<td>{attribute_sheet(candidate)}</td>"
            "</tr>"
            for candidate in displayed
        )
        return (
            f"<h2>Players matching filters ({len(candidates)})</h2>"
            "<p class='muted'>This is position browsing. Choose an optional role to "
            "add role score, attribute uncertainty, and scouting priority. Role-score, "
            "visibility, and ceiling filters are ignored until then.</p>"
            + (
                f"<p class='muted'>Showing the first {len(displayed)} players.</p>"
                if len(candidates) > len(displayed)
                else ""
            )
            + "<table><tr><th>Player</th><th>Club</th><th>Age</th><th>Positions"
            + (" (raw external data)" if include_raw_external_positions else "")
            + "</th><th>Footedness</th><th>Scouted</th><th>Past knowledge</th><th>Attributes</th></tr>"
            + rows
            + "</table>"
        )
