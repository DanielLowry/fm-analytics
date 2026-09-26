"""HTTP request handlers for the read-only squad decision-support view."""

from __future__ import annotations

import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote, unquote, urlparse

from fm_analytics.analytics import AXIS_DEFINITIONS, MVP_CATALOGUE, OpponentProfile
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.domain import Squad
from fm_analytics.reporting import (
    RecommendationBundle,
    build_player_role_scores,
    build_squad_position_comparison,
    build_squad_role_matrix,
    has_complete_role_attributes,
    validate_recommendation_snapshot,
)
from fm_analytics.web.auxiliary_pages import AuxiliaryPagesMixin
from fm_analytics.web.bench_render import bench_priority_section
from fm_analytics.web.opponent_controls import (
    opponent_controls as _opponent_controls,
    opponent_from_query as _opponent_from_query,
    opponent_query as _opponent_query,
    opponent_value_label as _opponent_value_label,
)
from fm_analytics.web.scouting_pages import ScoutingPagesMixin
from fm_analytics.web.tactic_checks_page import tactic_checks_body
from fm_analytics.web.scouting_render import (
    squad_player_link,
    squad_player_report,
)
from fm_analytics.web.rendering import (
    ScoutingPoolNotBuilt,
    _SORTABLE_TABLE_SCRIPT,
    _band,
    _error_page,
    _injury_risk_count,
    _layout,
    _options,
    _query_first,
    _pool_not_built_page,
    role_score_cells,
    _slot_reasoning,
    _tactic_notes,
    _tactical_shortfalls,
)

class SquadWebHandler(AuxiliaryPagesMixin, ScoutingPagesMixin, BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        routes = {
            "/": self._dashboard,
            "/squad": self._squad_page,
            "/roles": self._roles_page,
            "/tactics": self._tactics_page,
            "/tactic-checks": self._tactic_checks_page,
            "/set-pieces": self._set_pieces_page,
            "/depth": self._depth_page,
            "/scouting": self._scouting_page,
            "/scouting/results": self._scouting_results_fragment,
            "/data": self._data_page,
        }
        handler = routes.get(path)
        if handler is None and path.startswith("/scouting/player/") and path != "/scouting/player/":
            handler = self._scouting_player_page
        if handler is None and path.startswith("/squad/player/") and path != "/squad/player/":
            handler = self._squad_player_page
        if handler is None and path.startswith("/tactics/") and path != "/tactics/":
            handler = self._tactic_detail_page
        if handler is None:
            self._send(
                _error_page("Not found", f"No page exists at '{path}'."),
                HTTPStatus.NOT_FOUND,
            )
            return
        handler(path, parse_qs(parsed.query))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health/refresh":
            started = self.server.request_health_check()  # type: ignore[attr-defined]
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/?health=" + ("started" if started else "running"))
            self.end_headers()
            return
        if parsed.path == "/refresh":
            started = self.server.request_refresh()  # type: ignore[attr-defined]
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/?refresh=" + ("started" if started else "running"))
            self.end_headers()
            return
        if parsed.path != "/scouting/refresh":
            self._send(
                _error_page("Not found", "No such action.", parsed.path),
                HTTPStatus.NOT_FOUND,
            )
            return
        form = self._read_form()
        allow_rebuild = form.get("allow_rebuild", [""])[0] == "1"
        try:
            self.server.refresh_scouting(  # type: ignore[attr-defined]
                allow_rebuild=allow_rebuild
            )
        except ScoutingPoolNotBuilt:
            # Nothing was written to FM. Let the manager pick between the
            # read-only route and the one that runs FM's code in the live save.
            self._send(_pool_not_built_page(), HTTPStatus.CONFLICT)
            return
        except (OSError, RuntimeError, ValueError) as exc:
            self._send(
                _error_page("Scouting refresh", str(exc), "/scouting"),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header(
            "Location",
            "/scouting?refreshed=" + ("rebuilt" if allow_rebuild else "1"),
        )
        self.end_headers()

    def _read_form(self) -> dict[str, list[str]]:
        """Parse a bounded form body; an unreadable body is simply no consent."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if not 0 < length <= 4096:
            return {}
        return parse_qs(self.rfile.read(length).decode("utf-8", "replace"))

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

    def _bundle_or_error(
        self,
        path: str,
        title: str,
        opponent: OpponentProfile = OpponentProfile.neutral(),
    ) -> RecommendationBundle | None:
        try:
            return self.server.bundle(opponent)  # type: ignore[attr-defined]
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page(title, str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return None

    def _squad_page(self, path: str, _query: dict[str, list[str]]) -> None:
        try:
            game, squad = self.server.read()  # type: ignore[attr-defined]
            validate_recommendation_snapshot(game, squad)
            if not has_complete_role_attributes(squad):
                raise ValueError(
                    "This source has not supplied every role-scoring attribute yet; "
                    "see the Data page for exactly what is missing."
                )
            role_matrix = build_squad_role_matrix(squad)
            position = _query_first(_query, "position")
            role_key = _query_first(_query, "role")
            if role_key and not position:
                raise ValueError("choose a position before choosing a role")
            comparison = (
                build_squad_position_comparison(squad, position, role_key=role_key)
                if position
                else None
            )
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Squad", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        rows = []
        for player in squad.players:
            scores = build_player_role_scores(player, role_matrix)
            rows.append(
                "<tr>"
                f"<td>{squad_player_link(player)}</td>"
                f"<td>{', '.join(player.positions)}</td>"
                f"<td>{player.condition_percent if player.condition_percent is not None else '?'}% / "
                f"{player.match_fitness_percent if player.match_fitness_percent is not None else '?'}%</td>"
                f"<td>{html.escape(player.availability)}</td>"
                f"{role_score_cells(scores)}"
                "</tr>"
            )
        positions = tuple(sorted({position for role in MVP_CATALOGUE.roles.values() for position in role.eligible_positions}))
        role_options = (
            tuple((key, MVP_CATALOGUE.roles[key].name) for key in comparison.available_role_keys)
            if comparison is not None
            else ()
        )
        comparison_body = self._position_comparison_section(
            comparison, position, role_key, positions, role_options
        )
        body = (
            comparison_body
            + "<h2>Roster overview</h2>"
            "<p class='muted'><b>Attribute-based role score</b> uses attributes and role fit only. "
            "<b>In-position role score</b> also applies positional familiarity. "
            "<b>Today’s selection score</b> then applies match readiness, using the same calculation as Tactics. "
            "Each column shows the player's strongest role by that measure.</p>"
            "<p class='muted'>Click a column heading to sort by it.</p>"
            "<table class='sortable'><tr><th>Player</th><th>Positions</th><th>Condition</th>"
            "<th>Match fitness</th><th>Availability</th>"
            "<th>Attribute-based role score (best role)</th>"
            "<th>In-position role score (best role)</th>"
            "<th>Today’s selection score (best role)</th></tr>"
            + "".join(rows)
            + "</table>"
            + self._other_teams_section(squad)
            + _SORTABLE_TABLE_SCRIPT
        )
        self._send(_layout("Squad", path, body))

    @staticmethod
    def _position_comparison_section(
        comparison, position: str | None, role_key: str | None,
        positions: tuple[str, ...], role_options: tuple[tuple[str, str], ...],
    ) -> str:
        form = (
            "<h2>Compare a position</h2>"
            "<p class='muted'>Choose a position to compare like-for-like. Pinning a role is optional; "
            "otherwise each player is shown in their best compatible role there.</p>"
            "<form class='filters' method='get' action='/squad'>"
            "<label>Position<select name='position'>"
            + _options(((item, item) for item in positions), position, "Choose a position")
            + "</select></label><label>Role (optional)<select name='role'>"
            + _options(role_options, role_key, "Best role at this position")
            + "</select></label><button type='submit'>Compare</button></form>"
        )
        if comparison is None:
            return form
        role_description = (
            html.escape(comparison.requested_role_name)
            if comparison.requested_role_name
            else f"best compatible role at {html.escape(comparison.position)}"
        )
        rows = []
        for rank, entry in enumerate(comparison.entries, start=1):
            assignment = entry.assignment
            familiarity = (
                f"{entry.familiarity_rating}/20 (×{assignment.familiarity_multiplier:.3f})"
                if entry.familiarity_known
                else f"unknown (assumed {entry.familiarity_rating}/20; ×{assignment.familiarity_multiplier:.3f})"
            )
            if entry.selectable_today:
                today = _band(assignment.selection_score)
                status = "Selectable"
            else:
                today = "<span class='warn'>Not selectable</span>"
                status = html.escape("; ".join(entry.unavailability_reasons))
            rows.append(
                "<tr>"
                f"<td>{rank}</td><td><a href='/squad/player/{quote(entry.player_id)}'>{html.escape(entry.player_name)}</a></td>"
                f"<td>{html.escape(assignment.intrinsic_role_score.role_name)}</td>"
                f"<td>{familiarity}</td>"
                f"<td data-sort='{assignment.intrinsic_role_score.score.central:.4f}'>{_band(assignment.intrinsic_role_score.score)}</td>"
                f"<td data-sort='{assignment.in_position_score.central:.4f}'><b>{_band(assignment.in_position_score)}</b></td>"
                f"<td>{entry.condition_percent if entry.condition_percent is not None else '?'}%</td>"
                f"<td>{entry.match_fitness_percent if entry.match_fitness_percent is not None else '?'}%</td>"
                f"<td data-sort='{assignment.selection_score.central:.4f}'>{today}</td><td>{status}</td></tr>"
            )
        return (
            form
            + f"<h2>{html.escape(comparison.position)} comparison</h2>"
            + f"<p class='muted'>Role: {role_description}. {len(comparison.entries)} players are captured as eligible for "
            + f"{html.escape(comparison.position)}; {comparison.players_not_captured_for_position} are not assessed for this position. "
            + "Sorted by in-position estimate. ‘Today’ adds readiness and is suppressed when the player cannot be selected.</p>"
            + "<table class='sortable'><tr><th>Rank</th><th>Player</th><th>Role</th><th>Familiarity</th>"
            + "<th>Attribute role score</th><th>In-position estimate</th><th>Condition</th><th>Match fitness</th>"
            + "<th>Today’s score</th><th>Status</th></tr>"
            + "".join(rows) + "</table>"
        )

    def _squad_player_page(self, path: str, _query: dict[str, list[str]]) -> None:
        """Show the detailed role, attribute, and familiarity report for one squad member."""
        player_id = unquote(path.removeprefix("/squad/player/"))
        try:
            _game, squad = self.server.read()  # type: ignore[attr-defined]
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Squad player report", str(exc), "/squad"), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        player = next((item for item in squad.players if item.id == player_id), None)
        if player is None:
            self._send(
                _error_page("Squad player report", "That player is not in the current senior squad.", "/squad"),
                HTTPStatus.NOT_FOUND,
            )
            return
        self._send(
            _layout(
                f"Squad player · {player.name}", "/squad",
                squad_player_report(player, MVP_CATALOGUE),
            )
        )

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
            "<li><b>Attribute-based role score</b>: attributes weighted for this specific role and duty. "
            "It deliberately excludes positional familiarity and match readiness, so it compares underlying "
            "role suitability only. The weighting is fixed per role/duty — it does not vary by tactic.</li>"
            "<li><b>Uncertain</b>: a rival could still overtake once scouted</li>"
            "</ul>"
            "<table><tr><th>Role</th><th>Best player</th><th>Attribute-based role score</th>"
            "<th>Eligible candidates</th><th>Decision</th></tr>"
            + "".join(rows)
            + "</table>"
            + uncovered
        )
        self._send(_layout("Roles", path, body))

    def _tactics_page(self, path: str, _query: dict[str, list[str]]) -> None:
        try:
            opponent = _opponent_from_query(_query)
        except ValueError as exc:
            self._send(_error_page("Tactics", str(exc), path), HTTPStatus.BAD_REQUEST)
            return
        bundle = self._bundle_or_error(path, "Tactics", opponent)
        if bundle is None:
            return
        neutral_bundle = (
            bundle
            if opponent.is_neutral
            else self._bundle_or_error(path, "Tactics", OpponentProfile.neutral())
        )
        if neutral_bundle is None:
            return
        selected = bundle.recommendation.selected
        neutral_by_key = {
            evaluation.tactic.key: (rank, evaluation)
            for rank, evaluation in enumerate(
                neutral_bundle.recommendation.evaluations, start=1
            )
        }
        opponent_query = _opponent_query(opponent)
        query_suffix = f"?{opponent_query}" if opponent_query else ""
        link_query_suffix = html.escape(query_suffix, quote=True)
        active_axes = [
            f"{axis.label}: {_opponent_value_label(axis, getattr(opponent, axis.key))}"
            for axis in AXIS_DEFINITIONS
            if getattr(opponent, axis.key)
        ]
        rows = []
        for rank, evaluation in enumerate(bundle.recommendation.evaluations, start=1):
            tactic_key = evaluation.tactic.key
            issue = self._tactic_headline(bundle, evaluation)
            neutral_rank, neutral_evaluation = neutral_by_key[tactic_key]
            recommendation = (
                " <span class='badge badge-ok'>Recommended</span>"
                if tactic_key == selected.tactic.key
                else ""
            )
            opponent_columns = ""
            if not opponent.is_neutral:
                rank_change = neutral_rank - rank
                rank_delta = (
                    f"↑{rank_change}"
                    if rank_change > 0
                    else f"↓{abs(rank_change)}"
                    if rank_change < 0
                    else "—"
                )
                score_change = evaluation.score.central - neutral_evaluation.score.central
                if evaluation.opponent_fit.active:
                    opponent_fit = f"<b>{evaluation.opponent_fit.score:.1f}</b>"
                    opponent_fit_note = (
                        _tactical_shortfalls(evaluation.opponent_fit.shortfalls)
                        if evaluation.opponent_fit.shortfalls
                        else "Meets profile"
                    )
                else:
                    opponent_fit = "<b>—</b>"
                    opponent_fit_note = "Player emphasis only; no system check"
                opponent_columns = (
                    f"<td><b>{rank_delta}</b><br><span class='muted'>"
                    f"score {score_change:+.1f}</span></td>"
                    f"<td>{opponent_fit}<br>"
                    f"<span class='muted'>{html.escape(opponent_fit_note)}</span></td>"
                )
            rows.append(
                "<tr>"
                f"<td>{rank}</td>"
                f"<td><b>{html.escape(evaluation.tactic.name)}</b>{recommendation}"
                + (
                    f"<br><span class='muted'>{html.escape(evaluation.tactic.when_to_use)}</span>"
                    if evaluation.tactic.when_to_use else ""
                )
                + "</td>"
                f"<td>{html.escape(evaluation.tactic.formation)}</td>"
                f"<td><b>{_band(evaluation.score)}</b></td>"
                f"<td>{'Full XI' if evaluation.has_legal_xi else 'Incomplete XI'}</td>"
                f"<td>{html.escape(issue)}</td>"
                + opponent_columns
                + f"<td><a class='tactic-link' href='/tactics/{quote(tactic_key, safe='')}{link_query_suffix}'>"
                "View tactic →</a></td>"
                "</tr>"
            )
        opponent_headers = (
            "<th>Change vs neutral</th><th>Opponent fit</th>"
            if not opponent.is_neutral
            else ""
        )
        profile_summary = (
            "<p class='opponent-summary'><b>Active opponent assumptions:</b> "
            + html.escape(" · ".join(active_axes))
            + ". Changes below compare this profile with neutral.</p>"
            if active_axes
            else ""
        )
        body = (
            _opponent_controls(opponent)
            + profile_summary
            + "<section class='tactic-hero'>"
            f"<span class='eyebrow'>Recommended {'for this opponent' if active_axes else 'for today'}</span>"
            f"<h2>{html.escape(selected.tactic.name)}</h2>"
            f"<p>{html.escape(selected.tactic.formation)} · Play-now tactic score "
            f"<b>{_band(selected.score)}</b></p>"
            f"<p><a class='button-link' href='/tactics/{quote(selected.tactic.key, safe='')}{link_query_suffix}'>"
            "Open recommended tactic →</a></p></section>"
            "<h2>Compare tactics</h2>"
            "<p class='muted'>A quick squad-fit comparison. Open a tactic to inspect its "
            f"XI, why each player was selected, and a {bundle.policy.bench_size}-player "
            "matchday bench.</p>"
            "<table><tr><th>Rank</th><th>Tactic</th><th>Shape</th>"
            "<th>Play-now score</th><th>Line-up</th><th>Key issue</th>"
            + opponent_headers
            + "<th></th></tr>"
            + "".join(rows)
            + "</table>"
            "<details><summary>How tactics are ranked</summary>"
            "<p class='muted'>The play-now score is the balanced player score multiplied "
            "by the selected roles’ tactic-balance factor. Player fit includes position "
            "familiarity, condition and match fitness. The balance factor is 1.0 only when "
            "the roles meet every structural and instruction requirement. Opponent fit is "
            "reported separately: it does not silently discount the tactic score.</p></details>"
        )
        self._send(_layout("Tactics", path, body))

    def _tactic_checks_page(self, path: str, _query: dict[str, list[str]]) -> None:
        self._send(_layout("Tactic checks", path, tactic_checks_body()))

    @staticmethod
    def _tactic_headline(bundle: RecommendationBundle, evaluation) -> str:
        if evaluation.unfilled_slots:
            slots = ", ".join(slot.key for slot in evaluation.unfilled_slots)
            return f"Cannot fill {slots}"
        risk = _injury_risk_count(bundle.squad_depth.per_tactic[evaluation.tactic.key])
        if risk:
            return f"{risk} starting slot{'s' if risk != 1 else ''} lack reliable cover"
        if evaluation.weakest_slot_keys:
            return "Weakest starting slot: " + ", ".join(evaluation.weakest_slot_keys)
        return "No immediate issue"

    def _tactic_detail_page(self, path: str, _query: dict[str, list[str]]) -> None:
        tactic_key = unquote(path.removeprefix("/tactics/"))
        if "/" in tactic_key or tactic_key not in MVP_CATALOGUE.tactics:
            self._send(
                _error_page("Tactic", "That tactic is not in the current catalogue.", "/tactics"),
                HTTPStatus.NOT_FOUND,
            )
            return
        try:
            opponent = _opponent_from_query(_query)
        except ValueError as exc:
            self._send(_error_page("Tactic", str(exc), "/tactics"), HTTPStatus.BAD_REQUEST)
            return
        opponent_query = _opponent_query(opponent)
        query_suffix = f"?{opponent_query}" if opponent_query else ""
        tactics_href = "/tactics" + query_suffix
        bundle = self._bundle_or_error(tactics_href, "Tactic", opponent)
        if bundle is None:
            return
        try:
            report = self.server.tactic_report(  # type: ignore[attr-defined]
                tactic_key, opponent=opponent
            )
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            self._send(_error_page("Tactic", str(exc), tactics_href), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        evaluation = report.evaluation
        players_by_id = {player.id: player for player in bundle.squad.players}
        explanation_by_slot = {
            item.starter.slot.key: item for item in report.selection_explanation.slots
        }
        xi_rows = []
        for assignment in evaluation.assignments:
            player = players_by_id[assignment.player_id]
            explanation = explanation_by_slot[assignment.slot.key]
            alternatives = "".join(
                self._selection_alternative_row(option, players_by_id, assignment)
                for option in explanation.alternatives
            ) or "<tr><td colspan='6' class='muted'>No other eligible player for this exact role.</td></tr>"
            warning_text = ", ".join(
                assignment.readiness_warnings + assignment.familiarity_warnings
            )
            warnings = (
                f"<p class='warn'>{html.escape(warning_text)}</p>" if warning_text else ""
            )
            if assignment.taper_notes:
                warnings += (
                    "<p class='warn'>Below this tactic's attribute levels: "
                    + html.escape("; ".join(assignment.taper_notes))
                    + ". Fit tapers off gradually, so he can still be the best choice.</p>"
                )
            taper_card = (
                "<div><span>Tactic demands</span>"
                f"<b>×{assignment.taper_multiplier.central:.2f}</b><small>attribute taper</small></div>"
                if assignment.taper_notes
                else ""
            )
            selection_path = (
                "<div class='selection-flow'>"
                "<div><span>Role fit</span>"
                f"<b>{_band(assignment.intrinsic_role_score.score)}</b><small>attribute-based</small></div>"
                "<div><span>Position</span>"
                f"<b>×{assignment.familiarity_multiplier:.2f}</b><small>in-position familiarity</small></div>"
                + taper_card
                + "<div><span>readiness</span>"
                f"<b>−{explanation.readiness_score_cost:.1f}</b><small>condition + fitness</small></div>"
                "<div class='selection-result'><span>Today</span>"
                f"<b>{_band(assignment.selection_score)}</b><small>selection score</small></div>"
                "</div>"
            )
            xi_rows.append(
                "<tr>"
                f"<td>{html.escape(assignment.slot.key)}</td>"
                f"<td>{html.escape(assignment.slot.position)}</td>"
                f"<td>{html.escape(assignment.intrinsic_role_score.role_name)}</td>"
                f"<td>{squad_player_link(player)}</td>"
                f"<td>{player.condition_percent if player.condition_percent is not None else '?'}% / "
                f"{player.match_fitness_percent if player.match_fitness_percent is not None else '?'}%</td>"
                f"<td><b>{_band(assignment.selection_score)}</b></td>"
                "</tr>"
                "<tr class='explanation-row'><td colspan='6'>"
                + _slot_reasoning(
                    assignment.slot,
                    assignment.intrinsic_role_score.role_key,
                    assignment.intrinsic_role_score.role_name,
                )
                + f"<details><summary>Why {html.escape(assignment.player_name)}?</summary>"
                f"{selection_path}{warnings}"
                "<p class='muted'>Alternatives use this exact role; the other ten slots are "
                "re-optimised for each comparison.</p>"
                "<table><tr><th>Alternative</th><th>Role fit</th><th>In-position</th>"
                "<th>Condition / sharpness</th><th>Today</th><th>Why not selected</th></tr>"
                + alternatives
                + "</table></details></td></tr>"
            )
        if evaluation.unfilled_slots:
            xi_rows.append(
                "<tr><td colspan='6' class='warn'>Unfilled: "
                + html.escape(", ".join(slot.key for slot in evaluation.unfilled_slots))
                + "</td></tr>"
            )

        bench_section = bench_priority_section(
            evaluation, report.bench, players_by_id, bundle.policy.bench_size
        )

        targets = {target.starter.slot.key: target for target in report.substitution_board.targets}
        coverage_cards = []
        for slot in evaluation.tactic.slots:
            target = targets.get(slot.key)
            if target is None:
                cover = "<span class='warn'>Starting slot is unfilled</span>"
                starter = "—"
            else:
                starter = squad_player_link(players_by_id[target.starter.player_id])
                if target.options:
                    cover = "<br>".join(
                        f"{squad_player_link(players_by_id[option.player_id])} "
                        f"<span class='muted'>({_band(option.assignment.selection_score)})</span>"
                        + (
                            " <span class='warn'>uses sole cover elsewhere</span>"
                            if option.sole_cover_slot_keys else ""
                        )
                        for option in target.options
                    )
                else:
                    cover = "<span class='warn'>No bench cover</span>"
            coverage_cards.append(
                "<article class='coverage-card'>"
                f"<b>{html.escape(slot.key)}</b><span>{html.escape(slot.position)}</span>"
                f"<div><small>Starter</small>{starter}</div>"
                f"<div><small>Cover</small>{cover}</div></article>"
            )

        issue = self._tactic_headline(bundle, evaluation)
        target = next(
            (item for item in bundle.training_targets if item.tactic_key == tactic_key), None
        )
        training = (
            "<p class='muted'><b>Positional-training upside:</b> "
            f"{target.effective_score.central:.1f} → {target.potential_score.central:.1f} "
            f"(+{target.score_gap:.1f}). This changes positional familiarity only.</p>"
            if target else ""
        )
        score_summary = self._tactic_score_summary(evaluation)
        score_breakdown = self._tactic_score_breakdown(evaluation)
        tactic_notes = _tactic_notes(evaluation.tactic)
        rationale = (
            "<details class='tactic-rationale'><summary>Tactic rationale and requirements</summary>"
            + tactic_notes
            + "</details>"
            if tactic_notes
            else ""
        )
        structural_problems = tuple(evaluation.coherence.shortfalls) + tuple(
            evaluation.instruction_suitability.shortfalls
        )
        structural_warning = (
            "<div class='advisory-banner'><b>Selected roles miss a structural check</b>"
            "Falls short on "
            + html.escape(_tactical_shortfalls(structural_problems))
            + f". This reduces the tactic-balance factor to "
            f"{evaluation.tactic_balance_multiplier:.3f}. "
            f"<a href='/tactic-checks#{quote(tactic_key, safe='')}'>Review tactic checks →</a>"
            "</div>"
            if structural_problems
            else ""
        )
        active_axes = [
            f"{axis.label}: {_opponent_value_label(axis, getattr(opponent, axis.key))}"
            for axis in AXIS_DEFINITIONS
            if getattr(opponent, axis.key)
        ]
        opponent_context = ""
        if active_axes:
            if evaluation.opponent_fit.active:
                opponent_score = f"Opponent fit {evaluation.opponent_fit.score:.1f}"
                opponent_shortfalls = (
                    _tactical_shortfalls(evaluation.opponent_fit.shortfalls)
                    if evaluation.opponent_fit.shortfalls
                    else "Meets every opponent-specific system requirement"
                )
            else:
                opponent_score = "Opponent fit"
                opponent_shortfalls = (
                    "No system check for this profile; it changes player emphasis only"
                )
            opponent_context = (
                "<div class='opponent-summary'><b>Opponent profile:</b> "
                + html.escape(" · ".join(active_axes))
                + f".<br><b>{opponent_score}:</b> "
                + html.escape(opponent_shortfalls)
                + ".</div>"
            )
        body = (
            f"<p><a href='{html.escape(tactics_href, quote=True)}'>← Back to tactics</a></p>"
            + _opponent_controls(opponent, action=path)
            + opponent_context
            + "<section class='tactic-hero'>"
            f"<span class='eyebrow'>{html.escape(evaluation.tactic.formation)}</span>"
            f"<h2>{html.escape(evaluation.tactic.name)}</h2>"
            f"<p class='tactic-headline'>{html.escape(issue)}</p></section>"
            + score_summary
            + structural_warning
            + score_breakdown
            + rationale
            + training
            + "<h2>Starting XI</h2>"
            "<p class='muted'>Best available XI for this tactic today. Open a player for "
            "alternatives and the selection reasoning.</p>"
            "<table><tr><th>Slot</th><th>Position</th><th>Role</th><th>Player</th>"
            "<th>Condition / fitness</th><th>Today</th></tr>"
            + "".join(xi_rows)
            + "</table>"
            + bench_section
            + "<h2>Substitution coverage</h2>"
            "<details><summary>View cover for every position</summary>"
            "<p class='muted'>Scores are for the exact replacement role, today.</p>"
            "<div class='coverage-grid'>" + "".join(coverage_cards) + "</div></details>"
            "<details class='score-guide'><summary>Score guide</summary>"
            "<div class='score-guide-grid'>"
            "<article><b>Role fit</b><span>How well a player’s visible attributes suit the role.</span></article>"
            "<article><b>Position</b><span>Role fit adjusted for positional familiarity.</span></article>"
            "<article><b>Today</b><span>Position score adjusted for condition and match fitness.</span></article>"
            "</div></details>"
        )
        self._send(_layout(evaluation.tactic.name, "/tactics", body))

    @staticmethod
    def _tactic_score_summary(evaluation) -> str:
        """Summarise the player and role-balance parts of the tactic score."""
        drivers = [
            ("XI average", evaluation.mean_score.central),
            ("Weakest position", evaluation.weakest_score.central),
            ("Balanced player score", evaluation.xi_score.central),
            ("Tactic balance", evaluation.tactic_balance_multiplier * 100),
        ]
        driver_cards = "".join(
            "<div class='score-driver'>"
            f"<span>{html.escape(name)}</span><b>{score:.1f}</b>"
            f"<i><em style='width: {score:.1f}%'></em></i></div>"
            for name, score in drivers
        )
        return (
            "<section class='score-summary'><div class='overall-score'>"
            "<span>Tactic score</span>"
            f"<b>{evaluation.score.central:.1f}</b><small>out of 100</small></div>"
            "<div class='score-drivers'><div class='score-drivers-title'>"
            f"<b>Player scores</b></div>{driver_cards}</div></section>"
        )

    @staticmethod
    def _tactic_score_breakdown(evaluation) -> str:
        """Keep score methodology available without making it the primary view."""
        xi_formula = (
            "square of the average square root of each player score "
            f"= <b>{evaluation.xi_score.central:.1f}</b>; then × "
            f"<b>{evaluation.tactic_balance_multiplier:.3f}</b> tactic balance "
            f"= <b>{evaluation.score.central:.1f}</b>"
        )
        return (
            "<details class='score-breakdown'><summary>Score details</summary>"
            "<p>The player calculation rewards an even XI while remaining proportional: "
            "if every player score rises by 2%, the player score rises by exactly 2%. "
            "The tactic-balance factor is 1.0 only when the roles meet all balance and "
            "instruction requirements.</p>"
            f"<p>{xi_formula}.</p></details>"
        )

    @staticmethod
    def _selection_alternative_row(option, players_by_id, starter) -> str:
        player = players_by_id[option.player_id]
        if not option.counterfactual_has_legal_xi:
            reason = "Cannot form a complete XI with this player here"
        elif abs(option.tactic_score_change) < 0.05:
            reason = (
                f"Starts at {option.current_slot_key}; the two XIs are effectively tied"
                if option.current_slot_key
                else "The two XIs are effectively tied; stable tie-break retained the starter"
            )
        else:
            sign = "+" if option.tactic_score_change > 0 else "−"
            effect = f"{sign}{abs(option.tactic_score_change):.1f} tactic score"
            if option.current_slot_key:
                reason = f"Starts at {option.current_slot_key}; moving them here gives {effect}"
            elif option.assignment.selection_score.central < starter.selection_score.central:
                reason = f"Lower score in this exact role; forcing the change gives {effect}"
            else:
                reason = f"Reallocating the rest of the XI gives {effect}"
        condition = player.condition_percent if player.condition_percent is not None else "?"
        sharpness = (
            player.match_fitness_percent
            if player.match_fitness_percent is not None
            else "?"
        )
        return (
            "<tr>"
            f"<td>{squad_player_link(player)}</td>"
            f"<td>{_band(option.assignment.intrinsic_role_score.score)}</td>"
            f"<td>{_band(option.assignment.in_position_score)}</td>"
            f"<td>{condition}% / {sharpness}%</td>"
            f"<td>{_band(option.assignment.selection_score)}</td>"
            f"<td>{html.escape(reason)}</td>"
            "</tr>"
        )

    def _send(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        status_html = self.server.status_html()  # type: ignore[attr-defined]
        body = body.replace("</nav>", status_html + "</nav>", 1)
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
