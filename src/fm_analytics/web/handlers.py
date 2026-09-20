"""HTTP request handlers for the read-only squad decision-support view."""

from __future__ import annotations

import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlparse

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    DELIVERY_STYLES,
    recommend_set_pieces,
)
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.domain import Squad
from fm_analytics.reporting import (
    RecommendationBundle,
    build_player_role_scores,
    build_squad_role_matrix,
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
)
from fm_analytics.web.scouting_pages import ScoutingPagesMixin
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
    _query_first,
    _pool_not_built_page,
    role_score_cells,
    _tactic_notes,
    _tactical_shortfalls,
)


class SquadWebHandler(ScoutingPagesMixin, BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        routes = {
            "/": self._dashboard,
            "/squad": self._squad_page,
            "/roles": self._roles_page,
            "/tactics": self._tactics_page,
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

    def _bundle_or_error(self, path: str, title: str) -> RecommendationBundle | None:
        try:
            return self.server.bundle()  # type: ignore[attr-defined]
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
        body = (
            "<h2>Roster</h2>"
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
                f"<td>{_band(assignment.intrinsic_role_score.score)}</td>"
                f"<td>{_band(assignment.in_position_score)}</td>"
                f"<td><b>{_band(assignment.selection_score)}</b></td>"
                "</tr>"
                # XI assignments retain the catalogue's formation order:
                # goalkeeper, defence, midfield, then attack. Sorting by the
                # slot label made a right-sided role appear before the keeper.
                for assignment in evaluation.assignments
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
                f"{_band(evaluation.score)}. <b>Today’s player-role fit:</b> "
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
                "<table><tr><th>Slot</th><th>Position</th><th>Role</th><th>Player</th>"
                "<th>Attribute-based role score</th><th>In-position role score</th>"
                "<th>Today’s selection score</th></tr>"
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
                "<table><tr><th>Tactic</th><th>Today’s tactic score</th><th>After positional training</th>"
                "<th>Gain</th></tr>"
                + targets_rows
                + "</table>"
            )
            if bundle.training_targets
            else "<h2>Training targets</h2><p class='muted'>None — familiarity isn't holding any tactic back.</p>"
        )
        substitution_rows = []
        for target in bundle.substitution_board.targets:
            starter = target.starter
            starter_label = (
                f"{starter.slot.key} — {starter.player_name} "
                f"({starter.intrinsic_role_score.role_name})"
            )
            if not target.options:
                replacement_body = "<span class='warn'>No named substitute covers this role.</span>"
            else:
                replacement_body = "<br>".join(
                    f"<b>{html.escape(option.player_name)}</b> — "
                    f"{html.escape(option.assignment.intrinsic_role_score.role_name)} "
                    f"({_band(option.assignment.selection_score)})"
                    for option in target.options
                )
            warning_lines = [
                f"<b>{html.escape(option.player_name)}</b>: no named bench cover for "
                f"{html.escape(', '.join(option.sole_cover_slot_keys))} after this change."
                for option in target.options
                if option.sole_cover_slot_keys
            ]
            warning_body = (
                "<span class='warn'>" + "<br>".join(warning_lines) + "</span>"
                if warning_lines
                else "—"
            )
            substitution_rows.append(
                "<tr>"
                f"<td>{html.escape(starter_label)}</td>"
                f"<td>{replacement_body}</td>"
                f"<td>{warning_body}</td>"
                "</tr>"
            )
        substitutions_body = (
            "<h2>Matchday substitutions</h2>"
            "<p class='muted'>For the selected tactic only: named substitutes who can "
            "take each starter's exact role, ordered by today’s selection score. This is a "
            "replacement board, not a recommendation about timing or a player's live match rating.</p>"
            "<table><tr><th>Take off</th><th>Bring on (today’s selection score)</th><th>Cover after the change</th></tr>"
            + "".join(substitution_rows)
            + "</table>"
        )
        body = (
            "<h2>What can this squad play now?</h2>"
            "<p class='muted'>The score is a squad-fit estimate, not a match prediction "
            "and not an opponent-specific recommendation.</p>"
            "<ul class='legend'>"
            "<li><b>Play now</b>: how well the available squad fits this setup today.</li>"
            "<li><b>Attribute-based role score</b>: the player's attributes weighted for "
            "that specific role and duty. <b>In-position role score</b> applies positional "
            "familiarity. <b>Today’s selection score</b> then applies match readiness. "
            "A role is weighted the same wherever it appears "
            "— today, a Deep-Lying Playmaker is scored identically in every tactic that "
            "uses one; the tactic can choose a different role for a slot, but not yet "
            "ask more of the same role.</li>"
            "<li><b>Team balance</b>: whether the chosen roles form a workable whole. "
            "It is not a measure of player attributes.</li>"
            "<li><b>Game-plan support</b>: whether the chosen roles support this tactic's "
            "instructions. It is currently role-based; attribute-aware instruction "
            "scoring is planned work.</li>"
            "<li><b>After positional training</b>: the same today-score recommendation with every "
            "eligible selected player's positional familiarity treated as 20/20. It does "
            "not project attribute growth, hidden potential, or whole-tactic familiarity.</li>"
            "<li><b>XI</b>: ✓ full XI available, ✗ lists unfillable slots</li>"
            "<li><b>Cover risk</b>: starting slots without adequate cover</li>"
            "</ul>"
            "<table><tr><th>Tactic</th><th>Shape</th><th>Play-now tactic score</th><th>What needs "
            "attention</th><th>XI</th><th>Cover risk</th></tr>"
            + "".join(rows)
            + "</table>"
            + targets_body
            + substitutions_body
            + "<h2>XI by tactic</h2>"
            + "".join(details)
        )
        self._send(_layout("Tactics", path, body))

    def _set_pieces_page(self, path: str, _query: dict[str, list[str]]) -> None:
        """Recommend current-match set-piece assignments from visible attributes.

        This deliberately reads the squad directly instead of requiring the
        broader tactic bundle: set-piece suggestions remain useful while some
        unrelated role attributes are still being extracted.
        """
        try:
            game, squad = self.server.read()  # type: ignore[attr-defined]
            validate_recommendation_snapshot(game, squad)
            delivery_style = _query_first(_query, "delivery") or "inswinging"
            report = recommend_set_pieces(squad, delivery_style=delivery_style)
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(_error_page("Set pieces", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE)
            return

        labels = {
            "anticipation": "Anticipation", "bravery": "Bravery", "composure": "Composure",
            "corners": "Corners", "crossing": "Crossing", "finishing": "Finishing",
            "flair": "Flair", "heading": "Heading", "jumpingReach": "Jumping reach",
            "longShots": "Long shots", "marking": "Marking", "strength": "Strength",
            "technique": "Technique",
        }

        summary_rows = []
        details = []
        for recommendation in report.recommendations:
            task = recommendation.task
            suggested = recommendation.suggested
            if suggested is None:
                suggested_name = (
                    "No evidence-based suggestion" if recommendation.candidates else "No available player"
                )
                score, backups = "—", "—"
                side_fit = "—"
            else:
                suggested_name = html.escape(suggested.player.name)
                score = _band(suggested.score.score)
                side_fit = html.escape(suggested.side_fit_label)
                backups = ", ".join(
                    html.escape(candidate.player.name) for candidate in recommendation.candidates[1:3]
                ) or "—"
            note = (
                " <span class='warn'>Proxy — "
                + html.escape(task.proxy_for_unread_attribute)
                + " is not captured.</span>"
                if task.proxy_for_unread_attribute else ""
            )
            summary_rows.append(
                "<tr>"
                f"<td>{html.escape(recommendation.name)}{note}</td><td><b>{suggested_name}</b></td>"
                f"<td>{score}</td><td>{side_fit}</td><td>{backups}</td></tr>"
            )
            inputs = ", ".join(
                f"{html.escape(labels.get(attribute.name, attribute.name))} {attribute.weight:g}%"
                for attribute in task.attributes
            )
            candidate_rows = "".join(
                "<tr>"
                f"<td>{html.escape(candidate.player.name)}</td>"
                f"<td>{_band(candidate.score.score)}</td>"
                f"<td>{html.escape(candidate.side_fit_label)}</td>"
                f"<td>{' · '.join(html.escape(item.observation.display()) for item in candidate.score.contributions)}</td>"
                "</tr>"
                for candidate in recommendation.candidates[:5]
            )
            details.append(
                f"<details><summary>{html.escape(recommendation.name)} — {suggested_name}</summary>"
                f"<p>{html.escape(task.explanation)}</p>"
                + (
                    "<p class='muted'>The ranking applies a visible +4.0 preference for a "
                    f"{html.escape(recommendation.preferred_foot or '')}-footed taker; an Either-footed player receives +2.0.</p>"
                    if recommendation.preferred_foot else ""
                )
                + f"<p class='muted'><b>Weighted inputs:</b> {inputs}.</p>"
                + "<table><tr><th>Player</th><th>Attribute score</th><th>Side fit</th><th>Inputs (in weight order)</th></tr>"
                + candidate_rows
                + "</table></details>"
            )

        unavailable = (
            "<p class='muted'><b>Not proposed for this match:</b> "
            + ", ".join(html.escape(player.name) for player in report.unavailable_players)
            + ".</p>"
            if report.unavailable_players else ""
        )
        routine_picker = (
            "<nav class='scouting-tabs'><a class='"
            + ("tab-active" if report.delivery_style == "inswinging" else "tab")
            + "' href='/set-pieces?delivery=inswinging'>Inswingers</a><a class='"
            + ("tab-active" if report.delivery_style == "outswinging" else "tab")
            + "' href='/set-pieces?delivery=outswinging'>Outswingers</a></nav>"
        )
        body = (
            "<p>Suggested assignments for the current available senior squad. Enter these "
            "in FM if they fit your routine; this page does not change tactics in-game.</p>"
            + routine_picker
            + "<ul class='legend'>"
            "<li>Scores are a 0–100 weighted attribute comparison. Condition and match "
            "fitness do not alter set-piece skill; injury, suspension, and unavailable "
            "status exclude a player for this match.</li>"
            "<li><b>Set-piece attribute score</b> is task-specific; it is not a role score "
            "and does not use positional familiarity.</li>"
            "<li>Ranges and unknown values remain visible in the score. An unknown attribute "
            "cannot improve a player's current ranking.</li>"
            "<li>Delivery tasks are split left/right; choose the routine above to change the "
            "preferred foot. Opponent-specific match-ups are not modelled yet.</li></ul>"
            "<h2>Suggested assignments</h2>"
            "<table><tr><th>Assignment</th><th>Suggested</th><th>Attribute score</th><th>Side fit</th><th>Alternatives</th></tr>"
            + "".join(summary_rows)
            + "</table>"
            + "<h2>Why these players</h2>"
            + "".join(details)
            + "<h2>Not scoreable from the current feed</h2>"
            "<p><b>Long throws</b> cannot be ranked yet: the dedicated Long Throws attribute "
            "is not currently extracted. It is intentionally not guessed from unrelated attributes.</p>"
            + unavailable
        )
        self._send(_layout("Set pieces", path, body))

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
            preferred_foot = html.escape(player.preferred_foot) if player.preferred_foot else (
                "<span class='muted'>not captured</span>"
            )
            rows.append(
                "<tr>"
                f"<td>{html.escape(player.name)}</td>"
                f"<td>{len(required) - len(missing)} / {len(required)}</td>"
                f"<td>{'<span class=\"warn\">' + html.escape(', '.join(missing)) + '</span>' if missing else 'complete'}</td>"
                f"<td>{familiarity_count} position(s)"
                + ("" if familiarity_count else " <span class='muted'>(none read yet)</span>")
                + f"</td><td>{preferred_foot}</td></tr>"
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
            "<th>Missing attributes</th><th>Position familiarity</th><th>Preferred foot</th></tr>"
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
