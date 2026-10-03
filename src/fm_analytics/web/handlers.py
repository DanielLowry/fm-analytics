"""HTTP request handlers for the read-only squad decision-support view."""

from __future__ import annotations

import html
import json
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from importlib import resources
from urllib.parse import parse_qs, quote, unquote, urlparse

from fm_analytics.web.ui import ordered_positions, position_key, position_role_choices
from fm_analytics.analytics import MVP_CATALOGUE, OpponentProfile
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
from fm_analytics.web.actions import WebActionsMixin
from fm_analytics.web.auxiliary_pages import AuxiliaryPagesMixin
from fm_analytics.web.contract_pages import ContractPagesMixin
from fm_analytics.web.match_pages import MatchPagesMixin
from fm_analytics.web.scouting_pages import ScoutingPagesMixin
from fm_analytics.web.tactic_pages import TacticPagesMixin
from fm_analytics.web.league_pages import LeaguePagesMixin
from fm_analytics.web.scouting_render import squad_player_link
from fm_analytics.web.scouting_report import squad_player_report
from fm_analytics.web.rendering import (
    _band,
    _error_page,
    _layout,
    _options,
    _query_first,
    role_score_cells,
)

class SquadWebHandler(
    LeaguePagesMixin,
    WebActionsMixin,
    AuxiliaryPagesMixin,
    ContractPagesMixin,
    MatchPagesMixin,
    ScoutingPagesMixin,
    TacticPagesMixin,
    BaseHTTPRequestHandler,
):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/static/"):
            self._send_static(path)
            return
        routes = {
            "/": self._dashboard,
            "/squad": self._squad_page,
            "/roles": self._roles_page,
            "/tactics": self._tactics_page,
            "/tactic-checks": self._tactic_checks_page,
            "/set-pieces": self._set_pieces_page,
            "/depth": self._depth_page,
            "/contracts": self._contracts_page,
            "/scouting": self._scouting_page,
            "/scouting/results": self._scouting_results_fragment,
            "/matches": self._matches_page,
            "/league": self._league_page,
            "/api/export": self._export_api,
            "/data": self._data_page,
        }
        handler = routes.get(path)
        if handler is None and path.startswith("/league/teams/"):
            handler = self._league_team_page
        if handler is None and path.startswith("/scouting/player/") and path != "/scouting/player/":
            handler = self._scouting_player_page
        if handler is None and path.startswith("/squad/player/") and path != "/squad/player/":
            handler = self._squad_player_page
        if handler is None and path.startswith("/matches/") and path != "/matches/":
            handler = self._match_page
        if handler is None and path.startswith("/tactics/") and path != "/tactics/":
            handler = self._tactic_detail_page
        if handler is None:
            self._send(
                _error_page("Not found", f"No page exists at '{path}'."),
                HTTPStatus.NOT_FOUND,
            )
            return
        handler(path, parse_qs(parsed.query))

    def _send_static(self, path: str) -> None:
        """Serve only the bundled shell assets, never an arbitrary package file."""
        assets = {
            "/static/app.css": ("app.css", "text/css; charset=utf-8"),
            "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        asset = assets.get(path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown static asset")
            return
        filename, content_type = asset
        try:
            content = resources.files("fm_analytics.web").joinpath("static", filename).read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Frontend assets have not been built")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _dashboard(self, path: str, _query: dict[str, list[str]]) -> None:
        try:
            game, squad = self.server.read()  # type: ignore[attr-defined]
        except (BridgeSourceError, OSError, RuntimeError, ValueError, KeyError) as exc:
            self._send(_error_page("Dashboard", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        club = squad.club.name if squad.club else "No controlled club"
        complete = has_complete_role_attributes(squad)
        pinned_keys = self.server.pinned_tactics  # type: ignore[attr-defined]
        pinned_names = tuple(
            MVP_CATALOGUE.tactics[key].name
            for key in pinned_keys
            if key in MVP_CATALOGUE.tactics
        )

        def metric(label: str, value: str, note: str) -> str:
            return (
                "<section class='fm-card fm-metric'>"
                f"<span class='fm-metric-label'>{html.escape(label)}</span>"
                f"<strong class='fm-metric-value'>{html.escape(value)}</strong>"
                f"<span class='fm-metric-note'>{html.escape(note)}</span>"
                "</section>"
            )

        bundle: RecommendationBundle | None = None
        bundle_error = ""
        if complete:
            try:
                bundle = self.server.bundle()  # type: ignore[attr-defined]
            except (BridgeSourceError, OSError, RuntimeError, ValueError, KeyError) as exc:
                bundle_error = str(exc)

        primary_tactic = "Data required"
        primary_note = "Complete role attributes to calculate a recommendation"
        depth_value = "Data required"
        depth_note = "Depth checks appear once role scoring is ready"
        risk_items = ""
        if bundle is not None:
            primary_tactic = bundle.primary.tactic.name
            primary_note = f"Recommendation score {_band(bundle.primary.score)}"
            persistent = bundle.planning_depth.persistent_weaknesses
            depth_value = "No persistent risks" if not persistent else f"{len(persistent)} persistent risk(s)"
            depth_note = "Across your pinned tactics" if pinned_names else "Across the tactic catalogue"
            risk_items = "".join(
                "<li><b>"
                + html.escape(depth.position)
                + "</b> — "
                + html.escape(
                    ", ".join(
                        sorted(
                            {
                                tagged.weakness.kind.value.replace("_", " ")
                                for tagged in depth.weaknesses
                            }
                        )
                    )
                )
                + "</li>"
                for depth in persistent[:5]
            )

        tactic_value = ", ".join(pinned_names) if pinned_names else "No tactic pinned"
        tactic_note = "The first pinned tactic is your default" if pinned_names else "Pin tactics to focus planning depth"
        coverage_value = "Ready" if complete else "Incomplete data"
        coverage_note = "Role-scoring attributes are complete" if complete else "Some role-scoring attributes are missing"
        metrics = "".join(
            (
                metric("Senior squad", str(len(squad.players)), club),
                metric("Recommended tactic", primary_tactic, primary_note),
                metric("Planning depth", depth_value, depth_note),
                metric("Data coverage", coverage_value, coverage_note),
            )
        )
        risks = (
            "<ul class='fm-risk-list'>" + risk_items + "</ul>"
            if risk_items
            else "<p>There are no persistent depth risks in the tactics currently being planned.</p>"
        )
        pinned_panel = (
            "<section class='fm-card fm-command-card'><h2>My tactics</h2>"
            f"<p><b>{html.escape(pinned_names[0])}</b> is your primary tactic.</p>"
            "<p class='mt-3'>"
            + html.escape(", ".join(pinned_names[1:]) or "No additional tactics pinned")
            + "</p><a class='fm-command-action' href='/tactics'>Review my tactics</a></section>"
            if pinned_names
            else ""
        )
        diagnostic = (
            f"<p class='error'>{html.escape(bundle_error)}</p>" if bundle_error else ""
        )
        body = (
            "<div class='fm-command-grid'>" + metrics + "</div>"
            "<div class='fm-command-layout'>"
            "<section class='fm-card fm-command-card'><h2>Today’s decision frame</h2>"
            f"<p>{html.escape(club)} · {html.escape(game.game_date.isoformat())} · "
            f"{html.escape(game.human_manager.name)}</p>"
            "<p class='mt-3'>Start from the recommendation, then use the tactics view to inspect the XI, "
            "bench and matchday trade-offs.</p>"
            "<a class='fm-command-action' href='/tactics'>Open tactics workspace</a>"
            "</section>"
            "<section class='fm-card fm-command-card'><h2>Depth watchlist</h2>"
            + risks
            + "<a class='fm-command-action' href='/depth'>Review squad depth</a></section>"
            + pinned_panel
            + "</div>"
            + diagnostic
            + "<p class='muted'>Squad, Roles, Tactics, and Depth need complete role-scoring attributes; "
            "Data works regardless and shows exactly what is missing.</p>"
        )
        self._send(_layout("Command centre", path, body))

    def _bundle_or_error(
        self,
        path: str,
        title: str,
        opponent: OpponentProfile = OpponentProfile.neutral(),
    ) -> RecommendationBundle | None:
        try:
            return self.server.bundle(opponent)  # type: ignore[attr-defined]
        except (BridgeSourceError, OSError, RuntimeError, ValueError, KeyError) as exc:
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
            team_key = _query_first(_query, "team") or "first"
            team_choices = (("first", "First team"), ("all", "All club squads")) + tuple(
                (str(team.marker), f"Other squad · FM team marker {team.marker}")
                for team in squad.other_teams
            )
            if team_key not in dict(team_choices):
                raise ValueError("that club squad is not in the current capture")
            if team_key == "first":
                comparison_players = squad.players
            elif team_key == "all":
                comparison_players = squad.all_players()
            else:
                comparison_players = next(team.players for team in squad.other_teams if str(team.marker) == team_key)
            position = _query_first(_query, "position")
            role_key = _query_first(_query, "role")
            if role_key and not position:
                raise ValueError("choose a position before choosing a role")
            comparison = (
                build_squad_position_comparison(replace(squad, players=comparison_players, other_teams=()), position, role_key=role_key)
                if position
                else None
            )
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Squad", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        rows = []
        for player in sorted(squad.players, key=lambda item: (min((position_key(p) for p in item.positions), default=(99, "")), item.name.casefold())):
            scores = build_player_role_scores(player, role_matrix)
            rows.append(
                "<tr>"
                f"<td>{squad_player_link(player)}</td>"
                f"<td>{', '.join(ordered_positions(player.positions))}</td>"
                f"<td>{player.condition_percent if player.condition_percent is not None else '?'}%</td>"
                f"<td>{player.match_fitness_percent if player.match_fitness_percent is not None else '?'}%</td>"
                f"<td>{html.escape(player.availability)}</td>"
                f"{role_score_cells(scores)}"
                "</tr>"
            )
        positions = ordered_positions({position for role in MVP_CATALOGUE.roles.values() for position in role.eligible_positions})
        role_options = (
            tuple((key, MVP_CATALOGUE.roles[key].name) for key in comparison.available_role_keys)
            if comparison is not None
            else ()
        )
        comparison_body = self._position_comparison_section(
            comparison, position, role_key, positions, role_options,
            team_choices=team_choices if squad.other_teams else (), team_key=team_key,
            player_teams={
                **{player.id: "First team" for player in squad.players},
                **{player.id: f"Other squad · {team.marker}" for team in squad.other_teams for player in team.players},
            } if squad.other_teams and team_key == "all" else None,
        )
        body = (
            comparison_body
            + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
            + f"<h2>{'First-team roster' if squad.other_teams else 'Roster overview'}</h2>"
            "<p><b>Attribute-based role score</b> uses role fit only; <b>in-position</b> adds familiarity; "
            "<b>today’s selection</b> also adds match readiness.</p></div>"
            f"<span class='fm-panel-count'>{len(squad.players)} players</span></div>"
            "<p class='muted'>Click a column heading to sort. Each score names the player’s strongest role by that measure.</p>"
            "<div class='fm-table-card'><table class='sortable'><tr><th>Player</th><th>Positions</th><th>Condition</th>"
            "<th>Match fitness</th><th>Availability</th>"
            "<th title='Attribute-based role score (best role)'>Role fit</th>"
            "<th title='In-position role score (best role)'>In-position</th>"
            "<th title='Today’s selection score (best role)'>Today</th></tr>"
            + "".join(rows)
            + "</table></div></section>"
            + self._other_teams_section(squad)
        )
        self._send(_layout("Squad", path, body))

    @staticmethod
    def _position_comparison_section(
        comparison, position: str | None, role_key: str | None,
        positions: tuple[str, ...], role_options: tuple[tuple[str, str], ...],
        *, team_choices: tuple[tuple[str, str], ...] = (), team_key: str = "first",
        player_teams: dict[str, str] | None = None,
    ) -> str:
        form = (
            "<section class='fm-workspace-panel fm-compare-panel'><div class='fm-panel-heading'><div>"
            "<h2>Compare a position</h2>"
            "<p>Choose a position to compare like-for-like. Pinning a role is optional; "
            "otherwise each player is shown in their best compatible role there.</p></div></div>"
            "<form class='filters squad-filters' method='get' action='/squad'>"
            + ("<label>Squad<select name='team'>" + _options(team_choices, team_key, "") + "</select></label>" if team_choices else "")
            + "<label>Position<select name='position'>"
            + _options(((item, item) for item in positions), position, "Choose a position")
            + "</select></label><label>Role (optional)<select name='role'"
            + (" disabled" if not position else "") + ">"
            + _options(role_options, role_key, "Best role at this position")
            + "</select></label><button type='submit'>Compare</button></form>"
            "<script id='position-roles-data' type='application/json'>"
            + json.dumps(position_role_choices(MVP_CATALOGUE)).replace("</", "<\\/")
            + "</script></section>"
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
            team_cell = f"<td>{html.escape(player_teams.get(entry.player_id, 'Not captured'))}</td>" if player_teams else ""
            rows.append(
                "<tr>"
                f"<td>{rank}</td><td><a href='/squad/player/{quote(entry.player_id)}'>{html.escape(entry.player_name)}</a></td>"
                f"{team_cell}"
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
            + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
            + f"<h2>{html.escape(comparison.position)} comparison</h2>"
            + f"<p>Role: {role_description}. "
            + (f"Squad: {html.escape(dict(team_choices)[team_key])}. " if team_choices else "")
            + f"{len(comparison.entries)} players are captured as eligible for "
            + f"{html.escape(comparison.position)}; {comparison.players_not_captured_for_position} are not assessed for this position. "
            + "Sorted by in-position estimate. ‘Today’ adds readiness and is suppressed when the player cannot be selected.</p>"
            + "</div></div><div class='fm-table-card'><table class='sortable'><tr><th>Rank</th><th>Player</th>"
            + ("<th>Squad</th>" if player_teams else "")
            + "<th>Role</th><th>Familiarity</th>"
            + "<th>Attribute role score</th><th>In-position estimate</th><th>Condition</th><th>Match fitness</th>"
            + "<th>Today’s score</th><th>Status</th></tr>"
            + "".join(rows) + "</table></div></section>"
        )

    def _squad_player_page(self, path: str, _query: dict[str, list[str]]) -> None:
        """Show the detailed report for a player in any captured club squad."""
        player_id = unquote(path.removeprefix("/squad/player/"))
        try:
            _game, squad = self.server.read()  # type: ignore[attr-defined]
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Squad player report", str(exc), "/squad"), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        player = next((item for item in squad.all_players() if item.id == player_id), None)
        if player is None:
            self._send(
                _error_page("Squad player report", "That player is not in the current club squads.", "/squad"),
                HTTPStatus.NOT_FOUND,
            )
            return
        team = next((team for team in squad.other_teams if any(item.id == player_id for item in team.players)), None)
        self._send(
            _layout(
                f"Squad player · {player.name}", "/squad",
                squad_player_report(
                    player, MVP_CATALOGUE,
                    squad_label=f"Other squad · FM team marker {team.marker}" if team else "First team",
                    back_href="/squad#other-club-squads" if team else "/squad",
                    contract_panel=self._contract_panel_for(player.id),
                ),
            )
        )

    @staticmethod
    def _other_teams_section(squad: Squad) -> str:
        """Current estimates for other squads, using the shared score rules.

        Displaying estimates does not add these players to tactic/XI selection.
        FM squad names are not decoded, so retain the captured team marker.
        """
        if not squad.other_teams:
            return ""
        sections = []
        for team in squad.other_teams:
            role_matrix = build_squad_role_matrix(replace(squad, players=team.players, other_teams=()))
            rows = [
                "<tr>"
                f"<td>{squad_player_link(player)}</td>"
                f"<td>{player.age if player.age is not None else '?'}</td>"
                f"<td>{', '.join(ordered_positions(player.positions))}</td>"
                f"<td>{html.escape(player.availability)}</td>"
                f"{role_score_cells(build_player_role_scores(player, role_matrix))}"
                "</tr>"
                for player in sorted(team.players, key=lambda item: (min((position_key(p) for p in item.positions), default=(99, "")), item.name.casefold()))
            ]
            sections.append(
                "<section class='fm-other-team'>"
                f"<h3>Other squad <span>FM team marker {team.marker}</span></h3>"
                "<div class='fm-table-card'><table><tr><th>Player</th><th>Age</th><th>Positions</th>"
                "<th>Availability</th><th>Role fit</th><th>In-position</th><th>Today</th></tr>" + "".join(rows) + "</table></div></section>"
            )
        return (
            "<section class='fm-workspace-panel fm-other-teams-panel' id='other-club-squads'><div class='fm-panel-heading'><div>"
            "<h2>Other club squads</h2><p>Current estimates use the same scoring rules as the first team. "
            "Open a player for estimates at every position. Missing inputs retain their uncertainty.</p>"
            "<p class='muted'>Tactic and starting-XI plans use the first team.</p>"
            "</div></div>" + "".join(sections) + "</section>"
        )

    def _roles_page(self, path: str, _query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Roles")
        if bundle is None:
            return
        rows = []
        uncertain_count = 0
        for role_key, comparison in sorted(
            bundle.role_matrix.role_rankings.items(),
            key=lambda item: (min(position_key(p) for p in MVP_CATALOGUE.roles[item[0]].eligible_positions), item[1].candidates[0].role_score.role_name),
        ):
            best = comparison.selected
            certainty = "certain" if comparison.decision_certain else "uncertain"
            if not comparison.decision_certain:
                uncertain_count += 1
            rows.append(
                "<tr>"
                f"<td>{html.escape(best.role_score.role_name)}</td>"
                f"<td><a href='/squad/player/{quote(best.player_id, safe='')}'>{html.escape(best.player_name)}</a></td>"
                f"<td>{_band(best.role_score.score)}</td>"
                f"<td>{len(comparison.candidates)}</td>"
                f"<td><span class='fm-role-decision fm-role-decision-{certainty}'>{certainty}</span></td>"
                "</tr>"
            )
        uncovered = (
            "<section class='fm-role-uncovered'><b>No eligible squad member for:</b> "
            + ", ".join(sorted(bundle.role_matrix.uncovered_roles))
            + "</section>"
            if bundle.role_matrix.uncovered_roles
            else ""
        )
        body = (
            "<section class='fm-roles-hero'><span class='eyebrow'>Squad intelligence</span>"
            "<h2>Role coverage at a glance</h2>"
            "<p>See the current best fit for every role before taking a tactic into matchday selection.</p>"
            "<div class='fm-decision-grid fm-roles-summary'>"
            f"<section class='fm-decision-stat'><span>Roles covered</span><b>{len(rows)}</b><small>With an eligible player</small></section>"
            f"<section class='fm-decision-stat'><span>Uncertain calls</span><b>{uncertain_count}</b><small>A rival may overtake when scouted</small></section>"
            f"<section class='fm-decision-stat'><span>Uncovered roles</span><b>{len(bundle.role_matrix.uncovered_roles)}</b><small>No eligible squad member</small></section>"
            "</div></section>"
            "<section class='fm-workspace-panel fm-roles-panel'><div class='fm-panel-heading'><div>"
            "<h2>Best player per role</h2>"
            "<p>Attribute-based score measures role fit only; it excludes positional familiarity and match readiness.</p>"
            "</div></div>"
            "<details class='fm-roles-guide'><summary>How to read this table</summary><ul class='legend'>"
            "<li><b>Attribute-based role score</b>: attributes weighted for this specific role and duty. "
            "It deliberately excludes positional familiarity and match readiness, so it compares underlying "
            "role suitability only. The weighting is fixed per role/duty — it does not vary by tactic.</li>"
            "<li><b>Uncertain</b>: a rival could still overtake once scouted</li>"
            "</ul></details>"
            "<div class='fm-table-card'><table><tr><th>Role</th><th>Best player</th><th>Attribute-based role score</th>"
            "<th>Eligible candidates</th><th>Decision</th></tr>"
            + "".join(rows)
            + "</table></div></section>"
            + uncovered
        )
        self._send(_layout("Roles", path, body))

    def _send(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        status_html = self.server.status_html()  # type: ignore[attr-defined]
        body = body.replace("<!--FM_STATUS-->", status_html, 1)
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

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK, *, filename: str | None = None) -> None:
        encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        return
