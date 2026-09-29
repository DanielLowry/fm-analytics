"""HTTP request handlers for the read-only squad decision-support view."""

from __future__ import annotations

import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from importlib import resources
from urllib.parse import parse_qs, quote, unquote, urlparse

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
from fm_analytics.web.auxiliary_pages import AuxiliaryPagesMixin
from fm_analytics.web.match_pages import MatchPagesMixin
from fm_analytics.web.scouting_pages import ScoutingPagesMixin
from fm_analytics.web.tactic_pages import TacticPagesMixin
from fm_analytics.web.scouting_render import squad_player_link
from fm_analytics.web.scouting_report import squad_player_report
from fm_analytics.web.rendering import (
    ScoutingPoolNotBuilt,
    _SORTABLE_TABLE_SCRIPT,
    _band,
    _error_page,
    _layout,
    _options,
    _query_first,
    _pool_not_built_page,
    role_score_cells,
)

class SquadWebHandler(
    AuxiliaryPagesMixin,
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
            "/scouting": self._scouting_page,
            "/scouting/results": self._scouting_results_fragment,
            "/matches": self._matches_page,
            "/api/export": self._export_api,
            "/data": self._data_page,
        }
        handler = routes.get(path)
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
        if parsed.path == "/scouting/verdict":
            self._post_scouting_verdict()
            return
        match_posts = {
            "/matches/capture": self._post_match_capture,
            "/matches/note": self._post_match_note,
            "/matches/role-code": self._post_role_code,
        }
        if parsed.path in match_posts:
            match_posts[parsed.path]()
            return
        if parsed.path != "/scouting/refresh":
            self._send(
                _error_page("Not found", "No such action.", parsed.path),
                HTTPStatus.NOT_FOUND,
            )
            return
        form = self._read_form()
        allow_rebuild = form.get("allow_rebuild", [""])[0] == "1"
        return_view = form.get("return_view", [""])[0]
        if return_view not in {"all", "scouted"}:
            return_view = ""
        try:
            self.server.refresh_scouting(allow_rebuild=allow_rebuild)  # type: ignore[attr-defined]
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
        refresh_kind = "rebuilt" if allow_rebuild else "1"
        self.send_header(
            "Location",
            "/scouting?"
            + (f"view={return_view}&" if return_view else "")
            + "refreshed=" + refresh_kind,
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
            "</div>"
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
                f"<td>{player.condition_percent if player.condition_percent is not None else '?'}%</td>"
                f"<td>{player.match_fitness_percent if player.match_fitness_percent is not None else '?'}%</td>"
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
            + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
            "<h2>Roster overview</h2>"
            "<p><b>Attribute-based role score</b> uses role fit only; <b>in-position</b> adds familiarity; "
            "<b>today’s selection</b> also adds match readiness.</p></div>"
            f"<span class='fm-panel-count'>{len(squad.players)} players</span></div>"
            "<p class='muted'>Click a column heading to sort. Each score names the player’s strongest role by that measure.</p>"
            "<div class='fm-table-card'><table class='sortable'><tr><th>Player</th><th>Positions</th><th>Condition</th>"
            "<th>Match fitness</th><th>Availability</th>"
            "<th>Attribute-based role score (best role)</th>"
            "<th>In-position role score (best role)</th>"
            "<th>Today’s selection score (best role)</th></tr>"
            + "".join(rows)
            + "</table></div></section>"
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
            "<section class='fm-workspace-panel fm-compare-panel'><div class='fm-panel-heading'><div>"
            "<h2>Compare a position</h2>"
            "<p>Choose a position to compare like-for-like. Pinning a role is optional; "
            "otherwise each player is shown in their best compatible role there.</p></div></div>"
            "<form class='filters' method='get' action='/squad'>"
            "<label>Position<select name='position'>"
            + _options(((item, item) for item in positions), position, "Choose a position")
            + "</select></label><label>Role (optional)<select name='role'>"
            + _options(role_options, role_key, "Best role at this position")
            + "</select></label><button type='submit'>Compare</button></form></section>"
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
            + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
            + f"<h2>{html.escape(comparison.position)} comparison</h2>"
            + f"<p>Role: {role_description}. {len(comparison.entries)} players are captured as eligible for "
            + f"{html.escape(comparison.position)}; {comparison.players_not_captured_for_position} are not assessed for this position. "
            + "Sorted by in-position estimate. ‘Today’ adds readiness and is suppressed when the player cannot be selected.</p>"
            + "</div></div><div class='fm-table-card'><table class='sortable'><tr><th>Rank</th><th>Player</th><th>Role</th><th>Familiarity</th>"
            + "<th>Attribute role score</th><th>In-position estimate</th><th>Condition</th><th>Match fitness</th>"
            + "<th>Today’s score</th><th>Status</th></tr>"
            + "".join(rows) + "</table></div></section>"
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
