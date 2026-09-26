"""Set-piece, squad-depth, and data-coverage web pages."""

from __future__ import annotations

import html
from http import HTTPStatus

from fm_analytics.analytics import recommend_set_pieces
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.reporting import required_role_attributes, validate_recommendation_snapshot
from fm_analytics.web.rendering import _band, _error_page, _layout, _query_first


class AuxiliaryPagesMixin:
    """Pages that support, but do not define, the core squad/tactic views."""

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
            self._send(  # type: ignore[attr-defined]
                _error_page("Set pieces", str(exc), path), HTTPStatus.SERVICE_UNAVAILABLE
            )
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
