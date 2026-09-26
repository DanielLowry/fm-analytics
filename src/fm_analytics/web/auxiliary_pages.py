"""Set-piece, squad-depth, and data-coverage web pages."""

from __future__ import annotations

import html
from http import HTTPStatus

from fm_analytics.analytics import ATTACKING_RISKS, DELIVERY_STYLES, recommend_set_pieces
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.reporting import (
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
)
from fm_analytics.web.rendering import _band, _error_page, _layout, _options, _query_first


def _set_piece_summary_cards(report) -> str:
    wanted = (
        ("corners", "left", "Left corner"),
        ("corners", "right", "Right corner"),
        ("direct_free_kicks", "left", "Left direct FK"),
        ("direct_free_kicks", "right", "Right direct FK"),
        ("penalties", None, "Penalty"),
    )
    cards = []
    for task_key, side, label in wanted:
        routine_assignment = None
        if task_key == "corners":
            routine = next(
                item for item in report.routines
                if item.key == f"attacking_corner_{side}"
            )
            routine_assignment = next(
                (item for item in routine.assignments if item.role.unit == "Delivery"),
                None,
            )
        recommendation = next(
            item for item in report.recommendations
            if item.task.key == task_key and item.side == side
        )
        candidate = recommendation.suggested
        if candidate is None:
            routine_assignment = None
        player_name = (
            routine_assignment.player.name if routine_assignment else
            candidate.player.name if candidate else None
        )
        evidence_label = (
            "Whole-routine choice" if routine_assignment else
            candidate.evidence_label if candidate else "More evidence needed"
        )
        cards.append(
            "<div><span>" + html.escape(label) + "</span><b>"
            + (html.escape(player_name) if player_name else "No rated taker")
            + "</b><small>"
            + html.escape(evidence_label)
            + "</small></div>"
        )
    return "<div class='set-piece-summary'>" + "".join(cards) + "</div>"


def _set_piece_routine(routine, labels: dict[str, str], *, open_by_default: bool = False) -> str:
    rows = []
    for assignment in routine.assignments:
        contributions = sorted(
            assignment.score.contributions,
            key=lambda item: (-item.weight, item.attribute),
        )[:3]
        evidence = " · ".join(
            f"{labels.get(item.attribute, item.attribute)} {item.observation.display()}"
            for item in contributions
        )
        side_fit = (
            f"<br><small>{html.escape(assignment.side_fit_label)}</small>"
            if assignment.role.taker_task_key else ""
        )
        rows.append(
            "<tr>"
            f"<td><span class='set-piece-unit'>{html.escape(assignment.role.unit)}</span></td>"
            f"<td><b>{html.escape(assignment.role.instruction)}</b><br>"
            f"<small>{html.escape(assignment.role.zone)}</small></td>"
            f"<td><b>{html.escape(assignment.player.name)}</b>{side_fit}</td>"
            f"<td>{_band(assignment.score.score)}</td>"
            f"<td>{html.escape(evidence)}</td>"
            f"<td>{html.escape(assignment.role.explanation)}</td>"
            "</tr>"
        )
    unfilled = (
        "<div class='advisory-banner'><b>Partial routine</b>Not enough eligible players to fill: "
        + ", ".join(html.escape(role.instruction) for role in routine.unfilled_roles)
        + ".</div>" if routine.unfilled_roles else ""
    )
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in routine.notes)
    open_attribute = " open" if open_by_default else ""
    shape_summary = (
        f"{routine.players_in_box} in box · {routine.players_held_back} held back"
        if routine.phase == "attacking" else
        f"{routine.players_in_box} box defenders · {routine.players_held_back} outlet"
    )
    return (
        f"<details class='set-piece-routine'{open_attribute}><summary>"
        f"<span>{html.escape(routine.name)}</span>"
        f"<small>{shape_summary} · "
        f"{round(routine.evidence_coverage * 100):.0f}% evidence</small></summary>"
        f"<p>{html.escape(routine.objective)}</p>"
        "<table><tr><th>Unit</th><th>FM instruction / zone</th><th>Player</th>"
        "<th>Job fit</th><th>Strongest inputs</th><th>Purpose</th></tr>"
        + "".join(rows) + "</table>" + unfilled
        + "<ul class='legend'>" + notes + "</ul></details>"
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
                    if tactic_key else bundle.recommendation.selected
                )
                selected_tactic_key = evaluation.tactic.key
                selected_ids = tuple(item.player_id for item in evaluation.assignments)
                lineup_positions = {
                    item.player_id: item.slot.position for item in evaluation.assignments
                }
                lineup_name = f"{evaluation.tactic.name} match XI"
                tactic_options = tuple(
                    (item.tactic.key, item.tactic.name)
                    for item in bundle.recommendation.evaluations if item.has_legal_xi
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
            if suggested is None:
                suggested_name = (
                    "No evidence-based suggestion"
                    if recommendation.candidates
                    else "No available player"
                )
                score, backups = "—", "—"
                side_fit = "—"
            else:
                suggested_name = html.escape(suggested.player.name)
                score = _band(suggested.score.score)
                side_fit = html.escape(suggested.side_fit_label)
                backups = ", ".join(
                    html.escape(candidate.player.name)
                    for candidate in recommendation.candidates[1:3]
                ) or "—"
            note = (
                " <span class='warn'>Proxy — "
                + html.escape(task.proxy_for_unread_attribute)
                + " is not captured.</span>"
                if suggested is not None and suggested.evidence_mode == "proxy" else ""
            )
            summary_rows.append(
                "<tr>"
                f"<td>{html.escape(recommendation.name)}{note}</td><td><b>{suggested_name}</b></td>"
                f"<td>{score}</td><td>{html.escape(suggested.evidence_label) if suggested else '—'}</td>"
                f"<td>{side_fit}</td><td>{backups}</td></tr>"
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
                f"<td>{html.escape(candidate.player.name)}</td>"
                f"<td>{_band(candidate.score.score)}</td>"
                f"<td>{html.escape(candidate.evidence_label)}</td>"
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
                + "<table><tr><th>Player</th><th>Attribute score</th><th>Evidence</th><th>Side fit</th><th>Inputs (in weight order)</th></tr>"
                + candidate_rows
                + "</table></details>"
            )

        unavailable = (
            "<p class='muted'><b>Not proposed for this match:</b> "
            + ", ".join(html.escape(player.name) for player in report.unavailable_players)
            + ".</p>"
            if report.unavailable_players else ""
        )
        controls = (
            "<form class='filters set-piece-controls' method='get' action='/set-pieces'>"
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
            "Squad-wide template because role data is incomplete; rebuild against a match XI when the Data page is complete."
        )
        corners = "".join(
            _set_piece_routine(routine, labels, open_by_default=routine.side == "left")
            for routine in report.routines if routine.key.startswith("attacking_corner")
        )
        free_kicks = "".join(
            _set_piece_routine(routine, labels)
            for routine in report.routines if routine.key.startswith("attacking_wide_free_kick")
        )
        defending = "".join(
            _set_piece_routine(routine, labels, open_by_default=True)
            for routine in report.routines if routine.phase == "defending"
        )
        coverage = "".join(
            f"<li>{html.escape(note)}</li>" for note in report.coverage_notes
        ) or "<li>All dedicated taker inputs used by this plan are present.</li>"
        body = (
            "<div class='set-piece-hero'><span class='eyebrow'>Match plan</span>"
            f"<h2>{html.escape(report.lineup_name)}</h2><p>{html.escape(scope_note)}</p></div>"
            + controls
            + _set_piece_summary_cards(report)
            + "<nav class='section-jump'><a href='#takers'>Takers</a>"
            "<a href='#corners'>Attacking corners</a><a href='#free-kicks'>Wide free kicks</a>"
            "<a href='#defending'>Defending</a></nav>"
            "<h2 id='takers'>Taker depth chart</h2>"
            "<p class='muted'>Standalone delivery specialists and two backups for each side. For corners and crossed free kicks, the routine board is the final choice because it also considers the taker's best alternative job. Direct free kicks and penalties use the top specialist here.</p>"
            "<table><tr><th>Assignment</th><th>Top specialist</th><th>Set-piece attribute score</th>"
            "<th>Evidence</th><th>Side fit</th><th>Backups</th></tr>"
            + "".join(summary_rows)
            + "</table>"
            + "<h2 id='corners'>Attacking corners</h2>"
            "<p>Every player receives one job: delivery, separated box zones, second ball, support, or rest defence.</p>"
            + corners
            + "<h2 id='free-kicks'>Attacking wide free kicks</h2>"
            "<p>Use these for crossed deliveries. Direct shooting free kicks use the taker order above.</p>"
            + free_kicks
            + "<h2 id='defending'>Defensive routines</h2>"
            + defending
            + "<h2>Why these takers</h2>"
            + "".join(details)
            + "<h2>Evidence and operating notes</h2><ul class='legend'>"
            + coverage
            + "<li><b>Set-piece attribute score</b> is a transparent 0–100 comparison for this job, not a prediction of goals.</li>"
            "<li>Unknown values stay at the floor of the current ranking and widen its range; they never create false certainty.</li>"
            "<li>Condition and match fitness do not alter technique, but unavailable, injured, and suspended players are excluded.</li>"
            "<li>Copy the named instructions into FM, then adapt marking to the opponent's actual threats.</li></ul>"
            + unavailable
        )
        self._send(_layout("Set pieces", path, body))  # type: ignore[attr-defined]

    def _depth_page(self, path: str, _query: dict[str, list[str]]) -> None:
        bundle = self._bundle_or_error(path, "Depth")  # type: ignore[attr-defined]
        if bundle is None:
            return
        persistent = bundle.squad_depth.persistent_weaknesses
        occasional = bundle.squad_depth.occasional_weaknesses
        flagged = {depth.position for depth in persistent} | {
            depth.position for depth in occasional
        }

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

        rows = "".join(
            _row(depth, "persistent", "badge-persistent") for depth in persistent
        )
        rows += "".join(
            _row(depth, "occasional", "badge-occasional") for depth in occasional
        )
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
        for player in squad.players:
            missing = sorted(required.difference(player.attributes))
            familiarity_count = len(player.position_familiarity)
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
            f"<p>Required role-scoring attributes: {len(required)}. "
            f"<code>positionFamiliarity</code> is additive and optional -- absence means "
            "no reading is available yet, not that a player is unfamiliar everywhere.</p>"
            "<table><tr><th>Player</th><th>Attribute coverage</th>"
            "<th>Missing attributes</th><th>Position familiarity</th><th>Preferred foot</th></tr>"
            + "".join(rows)
            + "</table>"
            + other_coverage
        )
        self._send(_layout("Data", path, body))  # type: ignore[attr-defined]
