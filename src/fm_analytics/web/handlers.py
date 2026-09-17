"""HTTP request handlers for the read-only squad decision-support view."""

from __future__ import annotations

import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Sequence
from urllib.parse import parse_qs, urlparse

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    ScoutRecommendation,
    ScoutingFilters,
    assess_scouting_candidates,
    available_fact_values,
    filter_scouting_candidates,
)
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.domain import Squad
from fm_analytics.reporting import (
    RecommendationBundle,
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
)
from fm_analytics.web.rendering import (
    _MAX_SCOUTING_ROWS,
    _band,
    _error_page,
    _injury_risk_count,
    _input_value,
    _label,
    _layout,
    _options,
    _position_display,
    _query_first,
    _raw_position_notice,
    _scouting_filters,
    _tactic_notes,
    _tactical_shortfalls,
)


class SquadWebHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        routes = {
            "/": self._dashboard,
            "/squad": self._squad_page,
            "/roles": self._roles_page,
            "/tactics": self._tactics_page,
            "/depth": self._depth_page,
            "/scouting": self._scouting_page,
            "/data": self._data_page,
        }
        handler = routes.get(path)
        if handler is None:
            self._send(
                _error_page("Not found", f"No page exists at '{path}'."),
                HTTPStatus.NOT_FOUND,
            )
            return
        handler(path, parse_qs(parsed.query))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/scouting/refresh":
            self._send(
                _error_page("Not found", "No such action.", parsed.path),
                HTTPStatus.NOT_FOUND,
            )
            return
        try:
            self.server.refresh_scouting()  # type: ignore[attr-defined]
        except (OSError, RuntimeError, ValueError) as exc:
            self._send(
                _error_page("Scouting refresh", str(exc), "/scouting"),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/scouting?refreshed=1")
        self.end_headers()

    def _dashboard(self, path: str, _query: dict[str, list[str]]) -> None:
        try:
            game, squad = self.server.read()  # type: ignore[attr-defined]
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Dashboard", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        club = squad.club.name if squad.club else "No controlled club"
        complete = has_complete_role_attributes(squad)
        body = (
            "<table>"
            f"<tr><th>Club</th><td>{html.escape(club)}</td></tr>"
            f"<tr><th>Date</th><td>{game.game_date.isoformat()}</td></tr>"
            f"<tr><th>Manager</th><td>{html.escape(game.human_manager.name)}</td></tr>"
            f"<tr><th>Squad size</th><td>{len(squad.players)}</td></tr>"
            "<tr><th>Attribute coverage</th><td>"
            + ("complete" if complete else "<span class='warn'>incomplete — see Data</span>")
            + "</td></tr></table>"
            "<p class='muted'>Squad, Roles, Tactics, and Depth need complete role-scoring "
            "attributes; Data works regardless and shows exactly what is missing.</p>"
        )
        self._send(_layout("Dashboard", path, body))

    def _bundle_or_error(self, path: str, title: str) -> RecommendationBundle | None:
        try:
            return self.server.bundle()  # type: ignore[attr-defined]
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page(title, str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return None

    def _squad_page(self, path: str, _query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Squad")
        if bundle is None:
            return
        rows = []
        for player in bundle.squad.players:
            profile = bundle.role_matrix.player_profiles.get(player.id)
            best = profile.best if profile else None
            best_text = (
                f"{html.escape(best.role_name)} ({_band(best.role_score.score)})"
                if best is not None
                else "<span class='muted'>no eligible role</span>"
            )
            rows.append(
                "<tr>"
                f"<td>{html.escape(player.name)}</td>"
                f"<td>{', '.join(player.positions)}</td>"
                f"<td>{player.condition_percent if player.condition_percent is not None else '?'}%</td>"
                f"<td>{player.match_fitness_percent if player.match_fitness_percent is not None else '?'}%</td>"
                f"<td>{html.escape(player.availability)}</td>"
                f"<td>{best_text}</td>"
                "</tr>"
            )
        body = (
            "<h2>Roster</h2>"
            "<table><tr><th>Player</th><th>Positions</th><th>Condition</th>"
            "<th>Match fitness</th><th>Availability</th><th>Best eligible role</th></tr>"
            + "".join(rows)
            + "</table>"
            + self._other_teams_section(bundle.squad)
        )
        self._send(_layout("Squad", path, body))

    @staticmethod
    def _other_teams_section(squad: Squad) -> str:
        """The club's other squads (youth, reserves, ...), listed but not scored.

        These players are deliberately outside role/tactic/XI selection here:
        that machinery was designed and tuned for senior first-team selection,
        and folding in youth players without a considered policy (age-adjusted
        expectations, development context) would be a football judgement call
        this page should not make silently. FM's own name for each squad is
        not decoded yet -- see docs/property-discovery-playbook.md -- so each
        is labelled by FM's own raw marker rather than a guessed name.
        """
        if not squad.other_teams:
            return ""
        sections = []
        for team in squad.other_teams:
            rows = [
                "<tr>"
                f"<td>{html.escape(player.name)}</td>"
                f"<td>{player.age if player.age is not None else '?'}</td>"
                f"<td>{', '.join(player.positions)}</td>"
                f"<td>{html.escape(player.availability)}</td>"
                "</tr>"
                for player in team.players
            ]
            sections.append(
                f"<h3>Other squad (FM team marker {team.marker})</h3>"
                "<table><tr><th>Player</th><th>Age</th><th>Positions</th>"
                "<th>Availability</th></tr>" + "".join(rows) + "</table>"
            )
        return (
            "<p class='muted'>Other squads are listed for visibility only; they are "
            "not included in role or tactic selection.</p>" + "".join(sections)
        )

    def _roles_page(self, path: str, _query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Roles")
        if bundle is None:
            return
        rows = []
        for role_key, comparison in sorted(
            bundle.role_matrix.role_rankings.items(),
            key=lambda item: item[1].candidates[0].role_score.role_name,
        ):
            best = comparison.selected
            certainty = "certain" if comparison.decision_certain else "uncertain"
            rows.append(
                "<tr>"
                f"<td>{html.escape(best.role_score.role_name)}</td>"
                f"<td>{html.escape(best.player_name)}</td>"
                f"<td>{_band(best.role_score.score)}</td>"
                f"<td>{len(comparison.candidates)}</td>"
                f"<td>{certainty}</td>"
                "</tr>"
            )
        uncovered = (
            "<p class='muted'>No eligible squad member for: "
            + ", ".join(sorted(bundle.role_matrix.uncovered_roles))
            + "</p>"
            if bundle.role_matrix.uncovered_roles
            else ""
        )
        body = (
            "<h2>Best player per role</h2>"
            "<ul class='legend'>"
            "<li><b>Score</b>: attributes weighted for this specific role and duty, "
            "discounted for match readiness and adjusted for position familiarity. "
            "The weighting is fixed per role/duty — it does not vary by tactic.</li>"
            "<li><b>Uncertain</b>: a rival could still overtake once scouted</li>"
            "</ul>"
            "<table><tr><th>Role</th><th>Best player</th><th>Score</th>"
            "<th>Eligible candidates</th><th>Decision</th></tr>"
            + "".join(rows)
            + "</table>"
            + uncovered
        )
        self._send(_layout("Roles", path, body))

    def _tactics_page(self, path: str, _query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Tactics")
        if bundle is None:
            return
        rows = []
        details = []
        for evaluation in bundle.recommendation.evaluations:
            tactic_key = evaluation.tactic.key
            status = (
                "✓"
                if evaluation.has_legal_xi
                else "✗ " + ", ".join(slot.key for slot in evaluation.unfilled_slots)
            )
            risk = _injury_risk_count(bundle.squad_depth.per_tactic[tactic_key])
            risk_class = "badge-persistent" if risk else "badge-ok"
            concerns = []
            if not evaluation.has_legal_xi:
                concerns.append("cannot fill every position")
            if evaluation.coherence.shortfalls:
                concerns.append(
                    "balance: " + _tactical_shortfalls(evaluation.coherence.shortfalls)
                )
            if evaluation.instruction_suitability.shortfalls:
                concerns.append(
                    "game plan: "
                    + _tactical_shortfalls(evaluation.instruction_suitability.shortfalls)
                )
            summary = " · ".join(concerns) if concerns else "no structural warning"
            rows.append(
                "<tr>"
                f"<td>{html.escape(evaluation.tactic.name)}</td>"
                f"<td>{html.escape(evaluation.tactic.formation)}</td>"
                f"<td>{_band(evaluation.score)}</td>"
                f"<td>{html.escape(summary)}</td>"
                f"<td>{status}</td>"
                f"<td><span class='badge {risk_class}'>{risk}</span></td>"
                "</tr>"
            )
            assignment_rows = "".join(
                "<tr>"
                f"<td>{html.escape(assignment.slot.key)}</td>"
                f"<td>{html.escape(assignment.slot.position)}</td>"
                f"<td>{html.escape(assignment.intrinsic_role_score.role_name)}</td>"
                f"<td>{html.escape(assignment.player_name)}</td>"
                f"<td>{assignment.selection_score.central:.1f}</td>"
                "</tr>"
                for assignment in sorted(evaluation.assignments, key=lambda item: item.slot.key)
            )
            unfilled_note = (
                "<p class='warn'>Unfilled: "
                + ", ".join(
                    f"{slot.key} ({slot.position})" for slot in evaluation.unfilled_slots
                )
                + "</p>"
                if evaluation.unfilled_slots
                else ""
            )
            details.append(
                f"<details><summary>{html.escape(evaluation.tactic.name)} "
                f"({html.escape(evaluation.tactic.formation)})</summary>"
                + _tactic_notes(evaluation.tactic)
                + "<p><b>Play now:</b> "
                f"{_band(evaluation.score)}. <b>Player-role fit:</b> "
                f"{evaluation.xi_score.central:.1f}. <b>Team balance:</b> "
                f"{evaluation.coherence.score:.1f}. <b>Game-plan support:</b> "
                f"{evaluation.instruction_suitability.score:.1f}.</p>"
                "<p class='muted'><b>Team balance</b> asks whether the selected roles "
                "cover the jobs a functioning XI needs — for example width, defensive "
                "cover, progression and runners. <b>Game-plan support</b> asks whether "
                "those roles suit this tactic's instructions, such as pressing, playing "
                "out, or countering.</p>"
                + (
                    "<p class='warn'><b>Balance concerns:</b> "
                    + html.escape(_tactical_shortfalls(evaluation.coherence.shortfalls))
                    + ".</p>"
                    if evaluation.coherence.shortfalls
                    else ""
                )
                + (
                    "<p class='warn'><b>Game-plan concerns:</b> "
                    + html.escape(
                        _tactical_shortfalls(evaluation.instruction_suitability.shortfalls)
                    )
                    + ".</p>"
                    if evaluation.instruction_suitability.shortfalls
                    else ""
                )
                + "<p><b>Instructions:</b> "
                + html.escape(
                    ", ".join(evaluation.tactic.instructions) or "No special instructions"
                )
                + ".</p>"
                "<table><tr><th>Slot</th><th>Position</th><th>Role</th>"
                "<th>Player</th><th>Score</th></tr>"
                + assignment_rows
                + "</table>"
                + unfilled_note
                + "</details>"
            )
        targets_rows = "".join(
            "<tr>"
            f"<td>{html.escape(target.tactic_name)}</td>"
            f"<td>{target.effective_score.central:.1f}</td>"
            f"<td>{target.potential_score.central:.1f}</td>"
            f"<td>+{target.score_gap:.1f}</td>"
            "</tr>"
            for target in bundle.training_targets
        )
        targets_body = (
            (
                "<h2>Training targets</h2>"
                "<p class='muted'>These are setups improved by positional training, "
                "not predictions of player development.</p>"
                "<table><tr><th>Tactic</th><th>Play now</th><th>After positional training</th>"
                "<th>Gain</th></tr>"
                + targets_rows
                + "</table>"
            )
            if bundle.training_targets
            else "<h2>Training targets</h2><p class='muted'>None — familiarity isn't holding any tactic back.</p>"
        )
        body = (
            "<h2>What can this squad play now?</h2>"
            "<p class='muted'>The score is a squad-fit estimate, not a match prediction "
            "and not an opponent-specific recommendation.</p>"
            "<ul class='legend'>"
            "<li><b>Play now</b>: how well the available squad fits this setup today.</li>"
            "<li><b>Score</b> (per slot, below): the player's attributes weighted for "
            "that specific role and duty, discounted for match readiness and adjusted "
            "for position familiarity. A role is weighted the same wherever it appears "
            "— today, a Deep-Lying Playmaker is scored identically in every tactic that "
            "uses one; the tactic can choose a different role for a slot, but not yet "
            "ask more of the same role.</li>"
            "<li><b>Team balance</b>: whether the chosen roles form a workable whole. "
            "It is not a measure of player attributes.</li>"
            "<li><b>Game-plan support</b>: whether the chosen roles support this tactic's "
            "instructions. It is currently role-based; attribute-aware instruction "
            "scoring is planned work.</li>"
            "<li><b>After positional training</b>: the same recommendation with every "
            "eligible selected player's positional familiarity treated as 20/20. It does "
            "not project attribute growth, hidden potential, or whole-tactic familiarity.</li>"
            "<li><b>XI</b>: ✓ full XI available, ✗ lists unfillable slots</li>"
            "<li><b>Cover risk</b>: starting slots without adequate cover</li>"
            "</ul>"
            "<table><tr><th>Tactic</th><th>Shape</th><th>Play now</th><th>What needs "
            "attention</th><th>XI</th><th>Cover risk</th></tr>"
            + "".join(rows)
            + "</table>"
            + targets_body
            + "<h2>XI by tactic</h2>"
            + "".join(details)
        )
        self._send(_layout("Tactics", path, body))

    def _depth_page(self, path: str, _query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Depth")
        if bundle is None:
            return
        persistent = bundle.squad_depth.persistent_weaknesses
        occasional = bundle.squad_depth.occasional_weaknesses
        flagged = {depth.position for depth in persistent} | {depth.position for depth in occasional}

        conclusions = []
        if persistent:
            conclusions.append(
                "<li><strong>Persistent</strong> -- weak regardless of tactic: "
                + ", ".join(depth.position for depth in persistent)
                + "</li>"
            )
        if occasional:
            conclusions.append(
                "<li><strong>Occasional</strong> -- weak only in some evaluated tactics: "
                + ", ".join(depth.position for depth in occasional)
                + "</li>"
            )
        if not conclusions:
            conclusions.append("<li>No systemic gaps across the evaluated tactics.</li>")

        def _row(depth, status_label: str, badge_class: str) -> str:
            kinds = sorted({tagged.weakness.kind.value for tagged in depth.weaknesses})
            return (
                "<tr>"
                f"<td>{html.escape(depth.position)}</td>"
                f"<td><span class='badge {badge_class}'>{status_label}</span></td>"
                f"<td>{len(depth.tactics_with_a_weakness)} / {len(depth.tactics_with_this_position)}</td>"
                f"<td>{html.escape(', '.join(kinds)) if kinds else '—'}</td>"
                "</tr>"
            )

        rows = "".join(_row(depth, "persistent", "badge-persistent") for depth in persistent)
        rows += "".join(_row(depth, "occasional", "badge-occasional") for depth in occasional)
        rows += "".join(
            _row(depth, "ok", "badge-ok")
            for position, depth in sorted(bundle.squad_depth.positions.items())
            if position not in flagged
        )
        body = (
            "<h2>Conclusions</h2><ul>" + "".join(conclusions) + "</ul>"
            "<h2>By position</h2>"
            "<ul class='legend'>"
            "<li>Relative to your own squad: weak link = well below the XI median; "
            "weak cover = sharp drop-off from the starter</li>"
            "<li><b>Weak in</b>: tactics flagging it / tactics using the position</li>"
            "</ul>"
            "<table><tr><th>Position</th><th>Status</th><th>Weak in</th>"
            "<th>Reasons</th></tr>"
            + rows
            + "</table>"
        )
        self._send(_layout("Depth", path, body))

    def _scouting_page(self, path: str, query: dict[str, list[str]]) -> None:
        """A separate external-player workspace that retains uncertainty.

        This page intentionally does not call ``bundle()``: scouting remains
        useful while the owned squad is incomplete, and its candidate feed is
        evidence-bounded separately from the squad source.
        """
        try:
            candidates = self.server.scouting()  # type: ignore[attr-defined]
            filters = _scouting_filters(query)
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
        fact_controls = "".join(
            "<label>" + html.escape(_label(key))
            + "<select name='fact." + html.escape(key, quote=True) + "'>"
            + _options(((value, value) for value in values), (filters.facts or {}).get(key), "Any")
            + "</select></label>"
            for key, values in facts.items()
        )
        body = (
            "<p>Only players in the manager-visible discovery feed are shown. "
            "Scores preserve their <b>floor / estimate / ceiling</b>; a player with "
            "no known role attributes is a reason to scout, not a claim that they are good.</p>"
            + (
                "<p class='muted'>Scouting data refreshed. The current capture is now "
                "being used.</p>"
                if _query_first(query, "refreshed") == "1"
                else ""
            )
            + "<form class='refresh' method='post' action='/scouting/refresh'>"
            "<button type='submit'>Refresh scouting data</button>"
            "<span class='muted'>Reads the current FM Player Search pool; this can take "
            "a little while.</span></form>"
            + self._scouting_filters_form(filters, role_options, position_options, candidates, fact_controls)
            + (
                _raw_position_notice(candidates)
                if filters.include_raw_external_positions
                else ""
            )
            + (
                self._scouting_results(
                    assessments,
                    selected_role,
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
        self._send(_layout("Scouting", path, body))

    @staticmethod
    def _scouting_filters_form(
        filters: ScoutingFilters,
        role_options: str,
        position_options: str,
        candidates: Sequence[object],
        fact_controls: str,
    ) -> str:
        def values(name: str) -> tuple[str, ...]:
            return tuple(sorted({str(getattr(item, name)) for item in candidates if getattr(item, name) is not None}))

        return (
            "<h2>Find a target</h2><form class='filters' method='get' action='/scouting'>"
            f"<label>Position<select name='position'>{position_options}</select></label>"
            f"<label>Role (optional)<select name='role'>{role_options}</select></label>"
            f"<label>Minimum age<input name='minAge' type='number' min='0' value='{_input_value(filters.minimum_age)}'></label>"
            f"<label>Maximum age<input name='maxAge' type='number' min='0' value='{_input_value(filters.maximum_age)}'></label>"
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
                f"<td>{html.escape(candidate.name)}<br><span class='muted'>{html.escape(candidate.nationality or 'Nationality not known')}</span></td>"
                f"<td>{html.escape(candidate.club or '—')}</td><td>{candidate.age if candidate.age is not None else '—'}</td>"
                f"<td>{html.escape(', '.join(positions) or 'Not yet captured')}</td>"
                f"<td>{_band(item.role_score.score)}</td>"
                f"<td>{html.escape(item.visibility_summary)}</td>"
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
                f"<details><summary>{html.escape(candidate.name)} — {label}; score {_band(item.role_score.score)}</summary>"
                f"<p>{html.escape(meta_text or 'No additional manager-visible facts captured.')}<br>"
                f"<b>Scout next:</b> {html.escape(next_scout)}</p>"
                "<div class='attribute-grid'>" + attribute_cells + "</div></details>"
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
            "<li><b>Floor / estimate / ceiling</b>: the best and worst role score supported by visible information.</li></ul>"
            "<table><tr><th>Player</th><th>Club</th><th>Age</th><th>Positions"
            + (" (raw external data)" if include_raw_external_positions else "")
            + "</th><th>Role score</th><th>Visibility</th><th>Recommendation</th></tr>"
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
            f"<td>{html.escape(candidate.name)}</td>"
            f"<td>{html.escape(candidate.club or '—')}</td>"
            f"<td>{candidate.age if candidate.age is not None else '—'}</td>"
            f"<td>{_position_display(candidate, include_raw_external_positions=include_raw_external_positions)}</td>"
            f"<td>{html.escape(candidate.footedness or '—')}</td>"
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
            + "</th><th>Footedness</th></tr>"
            + rows
            + "</table>"
        )

    def _data_page(self, path: str, _query: dict[str, list[str]]) -> None:
        """Field coverage and provenance -- works even on an incomplete squad.

        This is deliberately the one page that does not require a complete,
        scorable squad: its entire purpose is showing what is still missing
        so a manual import or a probe change knows what to fill in next.
        """
        try:
            game, squad = self.server.read()  # type: ignore[attr-defined]
            validate_recommendation_snapshot(game, squad)
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Data", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        required = required_role_attributes()
        rows = []
        for player in squad.players:
            missing = sorted(required.difference(player.attributes))
            familiarity_count = len(player.position_familiarity)
            rows.append(
                "<tr>"
                f"<td>{html.escape(player.name)}</td>"
                f"<td>{len(required) - len(missing)} / {len(required)}</td>"
                f"<td>{'<span class=\"warn\">' + html.escape(', '.join(missing)) + '</span>' if missing else 'complete'}</td>"
                f"<td>{familiarity_count} position(s)"
                + ("" if familiarity_count else " <span class='muted'>(none read yet)</span>")
                + "</td></tr>"
            )
        other_team_players = [player for team in squad.other_teams for player in team.players]
        other_coverage = (
            f"<p>Other club squads: {len(other_team_players)} player(s) across "
            f"{len(squad.other_teams)} team(s), "
            f"{sum(1 for player in other_team_players if not required.difference(player.attributes))} "
            "with complete role-scoring attribute coverage. Not shown per-player here or "
            "included in role/tactic selection -- see the Squad page.</p>"
            if squad.other_teams
            else "<p class='muted'>No other club squads (youth, reserves, ...) were read.</p>"
        )
        body = (
            f"<p>Required role-scoring attributes: {len(required)}. "
            f"<code>positionFamiliarity</code> is additive and optional -- absence means "
            "no reading is available yet, not that a player is unfamiliar everywhere.</p>"
            "<table><tr><th>Player</th><th>Attribute coverage</th>"
            "<th>Missing attributes</th><th>Position familiarity</th></tr>"
            + "".join(rows)
            + "</table>"
            + other_coverage
        )
        self._send(_layout("Data", path, body))

    def _send(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        return
