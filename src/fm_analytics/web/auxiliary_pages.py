"""Set-piece, squad-depth, and data-coverage web pages."""

from __future__ import annotations

import html
from http import HTTPStatus
from urllib.parse import urlencode

from fm_analytics.analytics import ATTACKING_RISKS, DELIVERY_STYLES, recommend_set_pieces
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.reporting import (
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
)
from fm_analytics.web.rendering import (
    _band,
    _error_page,
    _layout,
    _options,
    _query_first,
    _tactic_choices,
)
from fm_analytics.web.set_piece_render import (
    _set_piece_assignment_cards,
    _set_piece_choice,
    _set_piece_routine_plan,
    _set_piece_routine_switcher,
    _routine_taker,
)


class AuxiliaryPagesMixin:
    """Pages that support, but do not define, the core squad/tactic views."""

    def _set_pieces_page(self, path: str, _query: dict[str, list[str]]) -> None:
        """Build a taker order and complete set-piece plan for the match XI."""
        try:
            game, squad = self.server.read()  # type: ignore[attr-defined]
            validate_recommendation_snapshot(game, squad)
            delivery_style = _query_first(_query, "delivery") or "inswinging"
            attacking_risk = _query_first(_query, "risk") or "balanced"
            tactic_key = _query_first(_query, "tactic")
            tactic_options: tuple[tuple[str, str], ...] = ()
            selected_ids = None
            lineup_positions = None
            lineup_name = None
            selected_tactic_key = None
            if has_complete_role_attributes(squad):
                bundle = self.server.bundle()  # type: ignore[attr-defined]
                evaluation = (
                    bundle.recommendation.by_tactic_key(tactic_key)
                    if tactic_key else bundle.primary
                )
                selected_tactic_key = evaluation.tactic.key
                selected_ids = tuple(item.player_id for item in evaluation.assignments)
                lineup_positions = {
                    item.player_id: item.slot.position for item in evaluation.assignments
                }
                lineup_name = f"{evaluation.tactic.name} match XI"
                tactic_options = tuple(
                    _tactic_choices(
                        (
                            (item.tactic.key, item.tactic.name)
                            for item in bundle.recommendation.evaluations
                            if item.has_legal_xi
                        ),
                        bundle.policy.pinned_tactics,
                    )
                )
            elif tactic_key:
                raise ValueError(
                    "A tactic-specific set-piece plan needs complete role attributes; "
                    "clear the tactic filter or complete the Data page first."
                )
            report = recommend_set_pieces(
                squad, delivery_style=delivery_style,
                attacking_risk=attacking_risk,
                selected_player_ids=selected_ids,
                lineup_positions=lineup_positions,
                lineup_name=lineup_name,
            )
        except (BridgeSourceError, OSError, RuntimeError, ValueError, KeyError) as exc:
            self._send(  # type: ignore[attr-defined]
                _error_page("Set pieces", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE
            )
            return

        labels = {
            "acceleration": "Acceleration", "aerialReach": "Aerial reach",
            "aggression": "Aggression", "agility": "Agility",
            "anticipation": "Anticipation", "balance": "Balance",
            "bravery": "Bravery", "commandOfArea": "Command of area",
            "communication": "Communication", "composure": "Composure",
            "concentration": "Concentration",
            "corners": "Corners", "crossing": "Crossing", "finishing": "Finishing",
            "firstTouch": "First touch", "flair": "Flair",
            "freeKickTaking": "Free Kick Taking", "handling": "Handling",
            "heading": "Heading", "jumpingReach": "Jumping reach",
            "longShots": "Long shots", "longThrows": "Long Throws",
            "marking": "Marking", "offTheBall": "Off the ball", "pace": "Pace",
            "passing": "Passing", "penaltyTaking": "Penalty Taking",
            "positioning": "Positioning", "strength": "Strength",
            "tackling": "Tackling", "technique": "Technique", "workRate": "Work rate",
        }

        summary_rows = []
        details = []
        for recommendation in report.recommendations:
            task = recommendation.task
            if task.key in {"attacking_aerial_target", "defensive_aerial_target"}:
                continue
            suggested = recommendation.suggested
            player_name, score, evidence_label, warning = _set_piece_choice(
                report, recommendation
            )
            routine, routine_assignment = _routine_taker(
                report, task.key, recommendation.side
            )
            side_fit = (
                routine_assignment.side_fit_label if routine_assignment is not None else
                suggested.side_fit_label if suggested is not None else "—"
            )
            backup_names = [
                html.escape(candidate.player.name)
                for candidate in recommendation.candidates
                if candidate.player.name != player_name
            ][:2]
            backups = ", ".join(backup_names) or "—"
            note = (
                "<small class='inline-warning'>" + html.escape(warning) + "</small>"
                if warning else ""
            )
            displayed_name = html.escape(player_name) if player_name else "No evidence-based recommendation"
            summary_rows.append(
                "<tr>"
                f"<th scope='row'>{html.escape(recommendation.name)}{note}</th>"
                f"<td><b>{displayed_name}</b></td><td>{score}</td>"
                f"<td>{html.escape(evidence_label)}</td>"
                f"<td>{html.escape(side_fit)}</td><td>{backups}</td></tr>"
            )
            displayed_inputs = (
                tuple(
                    (item.attribute, item.weight)
                    for item in suggested.score.contributions
                )
                if suggested is not None else
                tuple((item.name, item.weight) for item in task.attributes)
            )
            inputs = ", ".join(
                f"{html.escape(labels.get(name, name))} {weight:g}%"
                for name, weight in displayed_inputs
            )
            candidate_rows = "".join(
                "<tr>"
                f"<th scope='row'>{html.escape(candidate.player.name)}</th>"
                f"<td>{_band(candidate.score.score)}</td>"
                f"<td>{html.escape(candidate.evidence_label)}</td>"
                f"<td>{html.escape(candidate.side_fit_label)}</td>"
                f"<td>{' · '.join(html.escape(item.observation.display()) for item in candidate.score.contributions)}</td>"
                "</tr>"
                for candidate in recommendation.candidates[:5]
            )
            details.append(
                f"<details><summary>{html.escape(recommendation.name)} — {displayed_name}</summary>"
                f"<p>{html.escape(task.explanation)}</p>"
                + (
                    "<p class='muted'>The ranking applies a visible +4.0 preference for a "
                    f"{html.escape(recommendation.preferred_foot or '')}-footed taker; an Either-footed player receives +2.0.</p>"
                    if recommendation.preferred_foot else ""
                )
                + f"<p class='muted'><b>Weighted inputs:</b> {inputs}.</p>"
                + "<div class='table-scroll'><table><thead><tr><th scope='col'>Player</th>"
                "<th scope='col'>Attribute score</th><th scope='col'>Evidence</th>"
                "<th scope='col'>Side fit</th><th scope='col'>Inputs (in weight order)</th>"
                "</tr></thead><tbody>"
                + candidate_rows
                + "</tbody></table></div></details>"
            )

        unavailable = (
            "<p class='muted'><b>Not proposed for this match:</b> "
            + ", ".join(html.escape(player.name) for player in report.unavailable_players)
            + ".</p>"
            if report.unavailable_players else ""
        )
        routine_keys = {routine.key for routine in report.routines}
        selected_routine_key = _query_first(_query, "routine") or "attacking_corner_left"
        selected_routine_key = {
            "attacking_wide_free_kick_left": "attacking_indirect_wide_left",
            "attacking_wide_free_kick_right": "attacking_indirect_wide_right",
            "defending_wide_free_kick": "defending_indirect_wide",
        }.get(selected_routine_key, selected_routine_key)
        if selected_routine_key not in routine_keys:
            selected_routine_key = "attacking_corner_left"
        controls = (
            "<form class='filters set-piece-controls' method='get' action='/set-pieces'>"
            f"<input type='hidden' name='routine' value='{html.escape(selected_routine_key, quote=True)}'>"
            "<label>Delivery curve<select name='delivery'>"
            + _options(DELIVERY_STYLES.items(), report.delivery_style, "")
            + "</select></label><label>Attacking commitment<select name='risk'>"
            + _options(ATTACKING_RISKS.items(), report.attacking_risk, "")
            + "</select></label>"
            + (
                "<label>Match XI<select name='tactic'>"
                + _options(tactic_options, selected_tactic_key, "")
                + "</select></label>" if tactic_options else ""
            )
            + "<button type='submit'>Rebuild plan</button></form>"
        )
        scope_note = (
            "Optimized against the selected tactic's exact XI."
            if report.uses_match_xi else
            "This provisional squad-wide plan is not optimized against a match XI."
        )
        routine_query = {
            "delivery": report.delivery_style,
            "risk": report.attacking_risk,
        }
        if selected_tactic_key:
            routine_query["tactic"] = selected_tactic_key
        coverage = "".join(
            f"<li>{html.escape(note)}</li>" for note in report.coverage_notes
        ) or "<li>All dedicated taker inputs used by this plan are present.</li>"
        data_warning = (
            "" if report.uses_match_xi else
            "<div class='set-piece-data-warning'><b>Incomplete role data</b>"
            "Assignments are provisional. Complete the Data page, then rebuild against a match XI.</div>"
        )
        taker_recommendations = tuple(
            item for item in report.recommendations
            if item.task.key not in {"attacking_aerial_target", "defensive_aerial_target"}
        )
        actionable_takers = sum(
            1 for item in taker_recommendations
            if _set_piece_choice(report, item)[0] is not None
        )
        settings = (
            "<details class='fm-set-piece-settings'><summary>Adjust plan settings</summary>"
            "<p class='muted'>Change the match XI, delivery curve, or attacking commitment, then rebuild the plan.</p>"
            + controls
            + "</details>"
        )
        body = (
            "<section class='fm-set-piece-decision'><span class='eyebrow'>"
            + ("Match plan" if report.uses_match_xi else "Provisional plan")
            + "</span>"
            f"<h2>{html.escape(report.lineup_name)}</h2><p>{html.escape(scope_note)}</p>"
            + "<div class='fm-set-piece-actions'><a class='button-link' href='#match-day-assignments'>"
            "Review assignments</a><a class='button-link secondary' href='#routines'>Open routines</a></div></section>"
            + "<section class='fm-decision-grid fm-set-piece-summary' aria-label='Set-piece plan summary'>"
            "<article class='fm-decision-stat'><span>Plan scope</span><b>"
            + ("Match XI" if report.uses_match_xi else "Squad-wide")
            + "</b><small>"
            + ("tactic-specific selections" if report.uses_match_xi else "provisional selections")
            + "</small></article>"
            "<article class='fm-decision-stat'><span>Final takers</span><b>"
            f"{actionable_takers} / {len(taker_recommendations)}</b><small>roles with a named choice</small></article>"
            "<article class='fm-decision-stat'><span>Routine templates</span><b>"
            f"{len(report.routines)}</b><small>attacking and defensive situations</small></article></section>"
            + ("<section class='fm-workspace-panel fm-set-piece-alerts'>" + data_warning
               + "<details><summary>Plan checks and coverage</summary><ul class='fm-risk-list'>"
               + coverage + "</ul>" + unavailable + "</details></section>")
            + settings
            + "<section class='fm-workspace-panel fm-set-piece-assignments-panel' aria-labelledby='match-day-assignments'><div class='fm-panel-heading'>"
            "<div><h2 id='match-day-assignments'>Match-day assignments</h2>"
            "<p>These are the final choices to copy into FM.</p></div><span class='fm-panel-count'>"
            f"{actionable_takers} named takers</span></div>"
            + _set_piece_assignment_cards(report)
            + "<details class='taker-evidence fm-set-piece-evidence'><summary>Why these takers? View specialist rankings and backups</summary>"
            "<p class='muted'>Routine takers are chosen with the whole routine in mind. The rankings below show the underlying specialists and alternatives.</p>"
            "<div class='table-scroll'><table><thead><tr><th scope='col'>Assignment</th>"
            "<th scope='col'>Final choice</th><th scope='col'>Set-piece attribute score</th>"
            "<th scope='col'>Evidence</th><th scope='col'>Side fit</th><th scope='col'>Alternatives</th>"
            "</tr></thead><tbody>" + "".join(summary_rows) + "</tbody></table></div>"
            + "".join(details) + "</details></section>"
            + "<section class='fm-workspace-panel fm-routine-panel' aria-labelledby='routines'><div class='fm-panel-heading'>"
            "<div><h2 id='routines'>Routines</h2>"
            "<p>Select one situation to see the instructions to copy into FM.</p></div></div>"
            + _set_piece_routine_switcher(
                report, selected_routine_key, routine_query, labels
            )
            + "</section>"
            + "<section class='fm-workspace-panel fm-set-piece-notes'><details class='operating-notes'><summary>Evidence and operating notes</summary>"
            "<ul class='legend'>" + coverage
            + "<li><b>Set-piece attribute score</b> is a transparent 0–100 comparison for this job, not a prediction of goals.</li>"
            "<li>Unknown values stay at the floor of the current ranking and widen its range; they never create false certainty.</li>"
            "<li>Condition and match fitness do not alter technique, but unavailable, injured, and suspended players are excluded.</li>"
            "<li>Copy the named instructions into FM, then adapt marking to the opponent's actual threats.</li></ul>"
            + unavailable + "</details></section>"
        )
        self._send(_layout("Set pieces", path, body))  # type: ignore[attr-defined]

    def _depth_page(self, path: str, query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Depth")  # type: ignore[attr-defined]
        if bundle is None:
            return
        pinned = bundle.policy.pinned_tactics
        show_all = _query_first(query, "scope") == "all"
        depth_report = bundle.squad_depth if show_all else bundle.planning_depth
        scope_note = ""
        if pinned:
            names = ", ".join(
                html.escape(evaluation.tactic.name) for evaluation in bundle.pinned
            )
            scope_note = (
                f"<p>Evaluated across <b>{'all ' + str(len(bundle.squad_depth.tactic_keys)) + ' tactics' if show_all else 'your pinned tactics'}</b>"
                + ("" if show_all else f": {names}")
                + ". "
                + (
                    "<a href='/depth'>Show pinned tactics only</a>"
                    if show_all
                    else "<a href='/depth?scope=all'>Show every tactic</a>"
                )
                + "</p>"
            )
        persistent = depth_report.persistent_weaknesses
        occasional = depth_report.occasional_weaknesses
        flagged = {depth.position for depth in persistent} | {
            depth.position for depth in occasional
        }

        conclusions = []
        if persistent:
            conclusions.append(
                "<li><strong>Persistent</strong> -- weak in every tactic that fields it: "
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

        rows = "".join(
            _row(depth, "persistent", "badge-persistent") for depth in persistent
        )
        rows += "".join(
            _row(depth, "occasional", "badge-occasional") for depth in occasional
        )
        rows += "".join(
            _row(depth, "ok", "badge-ok")
            for position, depth in sorted(depth_report.positions.items())
            if position not in flagged
        )
        body = (
            scope_note
            + "<div class='fm-decision-grid'>"
            f"<section class='fm-decision-stat'><span>Persistent risks</span><b>{len(persistent)}</b><small>Need attention in every tactic</small></section>"
            f"<section class='fm-decision-stat'><span>Occasional risks</span><b>{len(occasional)}</b><small>Shape-specific concerns</small></section>"
            f"<section class='fm-decision-stat'><span>Positions assessed</span><b>{len(depth_report.positions)}</b><small>Across the active planning scope</small></section>"
            "</div>"
            "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
            "<h2>Conclusions</h2><p>Prioritise persistent gaps first; occasional gaps may only matter for a particular shape.</p>"
            "</div></div><ul class='fm-risk-list'>" + "".join(conclusions) + "</ul></section>"
            "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
            "<h2>By position</h2>"
            "<p>Relative to your own squad: a weak link is below the XI median; weak cover is a sharp drop from the starter.</p>"
            "</div></div>"
            "<div class='fm-table-card'><table><tr><th>Position</th><th>Status</th><th>Weak in</th>"
            "<th>Reasons</th></tr>"
            + rows
            + "</table></div></section>"
        )
        self._send(_layout("Depth", path, body))  # type: ignore[attr-defined]

    def _data_page(self, path: str, _query: dict[str, list[str]]) -> None:
        """Show field coverage even when the squad is not yet fully scorable."""
        try:
            game, squad = self.server.read()  # type: ignore[attr-defined]
            validate_recommendation_snapshot(game, squad)
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            self._send(  # type: ignore[attr-defined]
                _error_page("Data", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE
            )
            return
        required = required_role_attributes()
        rows = []
        complete_players = 0
        no_familiarity_readings = 0
        for player in squad.players:
            missing = sorted(required.difference(player.attributes))
            familiarity_count = len(player.position_familiarity)
            if not missing:
                complete_players += 1
            if not familiarity_count:
                no_familiarity_readings += 1
            preferred_foot = (
                html.escape(player.preferred_foot)
                if player.preferred_foot
                else "<span class='muted'>not captured</span>"
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
        other_team_players = [
            player for team in squad.other_teams for player in team.players
        ]
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
            "<section class='fm-data-hero'><span class='eyebrow'>System readiness</span>"
            "<h2>Make the evidence visible</h2>"
            f"<p>Role scoring needs {len(required)} attributes per player. Position familiarity adds precision but is never guessed.</p>"
            "<div class='fm-decision-grid fm-data-summary'>"
            f"<section class='fm-decision-stat'><span>Complete profiles</span><b>{complete_players}</b><small>Ready for every role score</small></section>"
            f"<section class='fm-decision-stat'><span>Needs attributes</span><b>{len(squad.players) - complete_players}</b><small>Cannot be fully role scored</small></section>"
            f"<section class='fm-decision-stat'><span>No familiarity reading</span><b>{no_familiarity_readings}</b><small>Still usable; less position precision</small></section>"
            "</div></section>"
            "<section class='fm-workspace-panel fm-data-panel'><div class='fm-panel-heading'><div>"
            "<h2>Senior squad coverage</h2>"
            f"<p>Required role-scoring attributes: {len(required)}. "
            f"<code>positionFamiliarity</code> is additive and optional — absence means "
            "no reading is available yet, not that a player is unfamiliar everywhere.</p>"
            "</div></div><div class='fm-table-card'><table><tr><th>Player</th><th>Attribute coverage</th>"
            "<th>Missing attributes</th><th>Position familiarity</th><th>Preferred foot</th></tr>"
            + "".join(rows)
            + "</table></div></section>"
            + "<section class='fm-workspace-panel fm-data-other-teams'><h2>Other club squads</h2>"
            + other_coverage + "</section>"
        )
        self._send(_layout("Data", path, body))  # type: ignore[attr-defined]
