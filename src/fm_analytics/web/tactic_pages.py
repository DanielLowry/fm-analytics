"""Tactics overview, tactic drill-down, and tactic-check web pages."""

from __future__ import annotations

import html
from http import HTTPStatus
from urllib.parse import quote, unquote

from fm_analytics.web.ui import position_key, cell_details
from fm_analytics.analytics import MVP_CATALOGUE, OpponentProfile
from fm_analytics.reporting import RecommendationBundle
from fm_analytics.web.bench_render import bench_priority_section
from fm_analytics.web.opponent_controls import (
    opponent_controls as _opponent_controls,
    opponent_from_query as _opponent_from_query,
    opponent_query as _opponent_query,
    opponent_summary_items as _opponent_summary_items,
)
from fm_analytics.web.in_possession_render import in_possession_section
from fm_analytics.web.in_transition_render import in_transition_section
from fm_analytics.web.out_of_possession_render import out_of_possession_section
from fm_analytics.web.rendering import (
    _band,
    _error_page,
    _injury_risk_count,
    _layout,
    _slot_reasoning,
    _tactic_notes,
    _tactical_shortfalls,
)
from fm_analytics.web.scouting_render import squad_player_link
from fm_analytics.web.tactic_checks_page import tactic_checks_body


class TacticPagesMixin:
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
        active_axes = _opponent_summary_items(opponent)
        pinned_keys = bundle.policy.pinned_tactics
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
            if tactic_key in pinned_keys:
                recommendation += (
                    " <span class='badge badge-ok'>Primary</span>"
                    if tactic_key == pinned_keys[0]
                    else " <span class='badge badge-ok'>Pinned</span>"
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
                    cell_details("When to use", evaluation.tactic.when_to_use)
                    if evaluation.tactic.when_to_use else ""
                )
                + "</td>"
                f"<td>{html.escape(evaluation.tactic.formation)}</td>"
                f"<td><b>{_band(evaluation.score)}</b></td>"
                f"<td>{'Full XI' if evaluation.has_legal_xi else 'Incomplete XI'}</td>"
                f"<td>{cell_details('Review issue', issue) if issue not in ('—', 'None') else html.escape(issue)}</td>"
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
        pinned_block = ""
        if pinned_keys:
            ranks = {
                evaluation.tactic.key: rank
                for rank, evaluation in enumerate(bundle.recommendation.evaluations, start=1)
            }
            pinned_rows = "".join(
                "<tr>"
                f"<td>{html.escape(evaluation.tactic.name)}"
                + (" <span class='muted'>(primary)</span>" if index == 0 else "")
                + "</td>"
                f"<td>{ranks[evaluation.tactic.key]} of {len(ranks)}</td>"
                f"<td><b>{_band(evaluation.score)}</b></td>"
                f"<td>{evaluation.score.central - selected.score.central:+.1f}</td>"
                f"<td><a class='tactic-link' href='/tactics/{quote(evaluation.tactic.key, safe='')}"
                f"{link_query_suffix}'>View tactic →</a></td></tr>"
                for index, evaluation in enumerate(bundle.pinned)
            )
            pinned_block = (
                "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
                "<h2>Your tactics</h2><p>Your pinned order drives the planning view; the first tactic is your primary.</p>"
                "</div><span class='fm-panel-count'>" + str(len(pinned_keys)) + " pinned</span></div>"
                "<div class='fm-table-card'><table><tr><th>Tactic</th><th>Rank</th><th>Play-now score</th>"
                "<th>vs top-ranked</th><th></th></tr>"
                + pinned_rows
                + "</table></div></section>"
            )
        body = (
            "<details class='fm-disclosure fm-tactic-opponent'><summary>Opponent profile · "
            + html.escape(" · ".join(active_axes) or "Neutral") + "</summary>"
            + _opponent_controls(opponent) + "</details>"
            + profile_summary
            + "<section class='fm-decision-hero'>"
            f"<span class='eyebrow'>Recommended {'for this opponent' if active_axes else 'for today'}</span>"
            f"<h2>{html.escape(selected.tactic.name)}</h2>"
            f"<p>{html.escape(selected.tactic.formation)} · Play-now tactic score "
            f"<b>{_band(selected.score)}</b></p>"
            f"<p><a class='button-link' href='/tactics/{quote(selected.tactic.key, safe='')}{link_query_suffix}'>"
            "Open recommended tactic →</a></p></section>"
            + pinned_block
            + self._match_record_block(pinned_keys, opponent.quality)  # type: ignore[attr-defined]
            + "<section class='fm-workspace-panel'><div class='fm-panel-heading'><div>"
            "<h2>Compare tactics</h2>"
            "<p>A quick squad-fit comparison. Open a tactic to inspect its "
            f"XI, why each player was selected, and a {bundle.policy.bench_size}-player "
            "matchday bench.</p></div>"
            f"<span class='fm-panel-count'>{len(rows)} options</span></div>"
            "<div class='fm-table-card'><table><tr><th>Rank</th><th>Tactic</th><th>Shape</th>"
            "<th>Play-now score</th><th>Line-up</th><th>Key issue</th>"
            + opponent_headers
            + "<th></th></tr>"
            + "".join(rows)
            + "</table></div>"
            "<details><summary>How tactics are ranked</summary>"
            "<p class='muted'>The play-now score is the balanced player score multiplied "
            "by the selected roles’ tactic-balance factor. Player fit includes position "
            "familiarity, condition and match fitness. The balance factor is 1.0 only when "
            "the roles meet every structural and instruction requirement. Opponent fit is "
            "reported separately: it does not silently discount the tactic score.</p></details></section>"
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
        for assignment in sorted(evaluation.assignments, key=lambda item: (position_key(item.slot.position), position_key(item.slot.key))):
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
                "<tr class='fm-xi-row'>"
                f"<td>{html.escape(assignment.slot.key)}</td>"
                f"<td>{html.escape(assignment.slot.position)}</td>"
                f"<td>{html.escape(assignment.intrinsic_role_score.role_name)}</td>"
                f"<td>{squad_player_link(player)}</td>"
                f"<td>{player.condition_percent if player.condition_percent is not None else '?'}% / "
                f"{player.match_fitness_percent if player.match_fitness_percent is not None else '?'}%</td>"
                f"<td><b>{_band(assignment.selection_score)}</b></td>"
                "</tr>"
                "<tr class='explanation-row fm-xi-explanation'><td colspan='6'>"
                "<details class='fm-slot-rationale fm-disclosure'><summary>Slot responsibilities</summary>"
                + _slot_reasoning(
                    assignment.slot,
                    assignment.intrinsic_role_score.role_key,
                    assignment.intrinsic_role_score.role_name,
                )
                + "</details>"
                + f"<details class='fm-selection-details'><summary>Why {html.escape(assignment.player_name)}?</summary>"
                f"{selection_path}{warnings}"
                "<p class='muted'>Alternatives use this exact role; the other ten slots are "
                "re-optimised for each comparison.</p>"
                "<div class='fm-alternative-table'><table><tr><th>Alternative</th><th>Role fit</th><th>In-position</th>"
                "<th>Condition / sharpness</th><th>Today</th><th>Why not selected</th></tr>"
                + alternatives
                + "</table></div></details></td></tr>"
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
        for slot in sorted(evaluation.tactic.slots, key=lambda item: (position_key(item.position), position_key(item.key))):
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
        active_axes = _opponent_summary_items(opponent)
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
        risk_count = _injury_risk_count(bundle.squad_depth.per_tactic[tactic_key])
        risk_items = []
        if evaluation.unfilled_slots:
            risk_items.append(
                "<li><b>Line-up:</b> cannot fill "
                + html.escape(", ".join(slot.key for slot in evaluation.unfilled_slots))
                + ".</li>"
            )
        if risk_count:
            risk_items.append(
                f"<li><b>Cover:</b> {risk_count} starting slot"
                f"{'s' if risk_count != 1 else ''} lack reliable replacement cover.</li>"
            )
        if structural_problems:
            risk_items.append(
                "<li><b>Tactic balance:</b> selected roles miss "
                + html.escape(_tactical_shortfalls(structural_problems))
                + ".</li>"
            )
        risk_summary = (
            "<ul class='fm-risk-list'>" + "".join(risk_items) + "</ul>"
            if risk_items
            else "<p class='fm-risk-clear'>No immediate line-up, cover, or tactic-balance issue is flagged.</p>"
        )
        selected_count = len(evaluation.assignments)
        total_slots = len(evaluation.tactic.slots)
        line_up_note = (
            "all slots selected"
            if selected_count == total_slots
            else "slots selected today"
        )
        balance_note = (
            "all structural checks met"
            if not structural_problems
            else "structural check needs review"
        )
        recommendation_label = (
            "Recommended today"
            if bundle.recommendation.selected.tactic.key == tactic_key
            else "Tactic review"
        )
        opponent_profile = (
            f"<details class='fm-tactic-opponent'{' open' if active_axes else ''}>"
            "<summary>Adjust opponent profile</summary>"
            "<p class='muted'>Use a scout report to tune the match-up; the URL keeps these assumptions.</p>"
            + _opponent_controls(opponent, action=path)
            + "</details>"
        )
        history_panel = self._tactic_history_block(tactic_key)  # type: ignore[attr-defined]
        body = (
            f"<p class='fm-tactic-back'><a href='{html.escape(tactics_href, quote=True)}'>← All tactics</a></p>"
            + "<section class='fm-tactic-decision'>"
            "<div class='fm-tactic-decision-heading'>"
            f"<span class='eyebrow'>{recommendation_label} · {html.escape(evaluation.tactic.formation)}</span>"
            f"<h2>{html.escape(evaluation.tactic.name)}</h2>"
            f"<p class='tactic-headline'>{html.escape(issue)}</p></div>"
            + score_summary
            + opponent_context
            + "<div class='fm-tactic-actions'>"
            "<a class='button-link' href='#starting-xi'>Review starting XI</a>"
            "<a class='button-link secondary' href='#matchday-risks'>Check matchday risks</a>"
            + ("<a class='button-link secondary' href='#tactic-history'>How it has played</a>" if history_panel else "")
            + "</div></section>"
            + "<section class='fm-decision-grid fm-tactic-summary' aria-label='Matchday summary'>"
            "<article class='fm-decision-stat'><span>Starting XI</span>"
            f"<b>{selected_count} / {total_slots}</b><small>{line_up_note}</small></article>"
            "<article class='fm-decision-stat'><span>Bench plan</span>"
            f"<b>{len(report.bench.entries)} / {bundle.policy.bench_size}</b><small>substitute places prioritised</small></article>"
            "<article class='fm-decision-stat'><span>Tactic balance</span>"
            f"<b>{evaluation.tactic_balance_multiplier * 100:.0f}%</b><small>{balance_note}</small></article>"
            "</section>"
            + "<section class='fm-workspace-panel fm-tactic-risks' id='matchday-risks'>"
            "<div class='fm-panel-heading'><div><h2>Matchday risks</h2>"
            "<p>Check these before committing to the line-up. Evidence and alternatives remain attached to each decision below.</p>"
            "</div><span class='fm-panel-count'>"
            + (f"{len(risk_items)} to review" if risk_items else "clear")
            + "</span></div>"
            + risk_summary
            + structural_warning
            + "</section>"
            + opponent_profile
            + "<section class='fm-workspace-panel fm-starting-xi' id='starting-xi'>"
            "<div class='fm-panel-heading'><div><h2>Starting XI</h2>"
            "<p>Best available XI today. Expand a player to inspect role fit, readiness, and exact-role alternatives.</p>"
            "</div><span class='fm-panel-count'>"
            + f"{selected_count} selected</span></div>"
            "<div class='fm-table-card'><table><tr><th>Slot</th><th>Position</th><th>Role</th><th>Player</th>"
            "<th>Condition / fitness</th><th>Today</th></tr>"
            + "".join(xi_rows)
            + "</table></div></section>"
            + bench_section
            + "<section class='fm-workspace-panel fm-coverage-panel'>"
            "<div class='fm-panel-heading'><div><h2>Substitution coverage</h2>"
            "<p>Options are scored for the exact replacement role, today.</p>"
            "</div><span class='fm-panel-count'>"
            + f"{total_slots} starting slots</span></div>"
            "<details class='fm-coverage-details'><summary>View cover for every position</summary>"
            "<div class='coverage-grid'>" + "".join(coverage_cards) + "</div></details></section>"
            + history_panel
            + "<section class='fm-workspace-panel fm-tactic-evidence'>"
            "<div class='fm-panel-heading'><div><h2>Tactical instructions and evidence</h2>"
            "<p>Use this after the matchday choices are clear: it explains the score, shape, and FM settings.</p>"
            "</div></div>"
            + in_possession_section(evaluation.tactic)
            + in_transition_section(evaluation.tactic)
            + out_of_possession_section(evaluation.tactic)
            + rationale
            + (f"<div class='fm-tactic-training'>{training}</div>" if training else "")
            + score_breakdown
            + "<details class='score-guide'><summary>Score guide</summary>"
            "<div class='score-guide-grid'>"
            "<article><b>Role fit</b><span>How well a player’s visible attributes suit the role.</span></article>"
            "<article><b>Position</b><span>Role fit adjusted for positional familiarity.</span></article>"
            "<article><b>Today</b><span>Position score adjusted for condition and match fitness.</span></article>"
            "</div></details></section>"
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
