"""A read-only squad decision-support view over `reporting.build_recommendation_bundle`.

Every page here computes through the same shared reporting path the CLI
uses (see `fm_analytics.reporting`), so a number shown on a page and a
number printed by `fm-analytics --recommend` are the same number computed
the same way. This module owns HTML rendering only; it holds no analytics
logic of its own; and it consumes a `GameSquadProvider`
(`fm_analytics.web.providers`) rather than any particular data source, so a
fixture, a snapshot, a live bridge, or an HTML-overlaid live bridge are all
equally valid inputs.
"""

from __future__ import annotations

import argparse
import html
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import parse_qs, urlparse

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    ScoutRecommendation,
    ScoutingFilters,
    TacticDefinition,
    WeaknessKind,
    WeaknessReport,
    assess_scouting_candidates,
    available_fact_values,
    filter_scouting_candidates,
)
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.domain import Squad
from fm_analytics.reporting import (
    RecommendationBundle,
    build_recommendation_bundle,
    has_complete_role_attributes,
    required_role_attributes,
    validate_recommendation_snapshot,
)
from fm_analytics.web.providers import (
    GameSquadProvider,
    fixture_provider,
    html_overlay_provider,
    live_provider,
    empty_scouting_provider,
    snapshot_provider,
    scouting_json_provider,
)


_NAV: tuple[tuple[str, str], ...] = (
    ("/", "Dashboard"),
    ("/squad", "Squad"),
    ("/roles", "Roles"),
    ("/tactics", "Tactics"),
    ("/depth", "Depth"),
    ("/scouting", "Scouting"),
    ("/data", "Data"),
)

# Slot weaknesses that answer "if this starter is unavailable, are we
# covered": no backup at all, a backup that itself falls below the
# threshold, or a backup that is only first cover because it is shared
# across several simultaneous slots. Used to build the Tactics page's
# injury-risk column; see WeaknessKind for what each one means precisely.
_INJURY_RISK_KINDS = frozenset(
    {WeaknessKind.NO_BACKUP, WeaknessKind.WEAK_BACKUP, WeaknessKind.SHARED_COVER}
)
_MAX_SCOUTING_ROWS = 100

_TACTICAL_DIMENSION_LABELS = {
    "aerialOutlet": "aerial outlet",
    "attack duties": "attacking duties",
    "ballProgression": "ball progression",
    "boxPresence": "presence in the box",
    "creativity": "creativity",
    "creators": "creative roles",
    "defensiveCover": "defensive cover",
    "penetration": "penetration",
    "pressing": "pressing",
    "restDefence": "defensive security after losing the ball",
    "runners": "forward runners",
    "width": "width",
}

_STYLE = """
<style>
  body { font-family: system-ui, sans-serif; margin: 0; color: #1a1a1a; background: #fafafa; }
  nav { background: #1a2b3c; padding: 0.75rem 1.5rem; }
  nav a { color: #cdd8e3; text-decoration: none; margin-right: 1.25rem; font-size: 0.95rem; }
  nav a.active, nav a:hover { color: #ffffff; font-weight: 600; }
  main { padding: 1.5rem 2rem; max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.25rem; }
  table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid #e5e5e5; }
  th { background: #f0f2f5; }
  .muted { color: #666; }
  .warn { color: #9a4a00; }
  .error { color: #a30000; font-weight: 600; }
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.8rem; }
  .badge-persistent { background: #fde2e2; color: #8a1f1f; }
  .badge-occasional { background: #fff2d6; color: #8a5a00; }
  .badge-ok { background: #e3f3e1; color: #1e6b1e; }
  .tag { display: inline-block; padding: 0.1rem 0.5rem; margin: 0 0.25rem 0.25rem 0; border-radius: 0.75rem; font-size: 0.75rem; background: #eef1f4; color: #445; }
  code { background: #eef1f4; padding: 0.05rem 0.3rem; border-radius: 0.25rem; }
  details { margin: 0.4rem 0; border: 1px solid #e5e5e5; border-radius: 0.3rem; padding: 0.3rem 0.6rem; }
  details summary { cursor: pointer; font-weight: 600; }
  details table { margin-top: 0.5rem; }
  ul.legend { color: #555; font-size: 0.85rem; margin: 0.25rem 0 0.75rem; padding-left: 1.2rem; }
  form.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.65rem; padding: 1rem; background: #f0f2f5; border-radius: 0.4rem; }
  form.filters label { display: grid; gap: 0.2rem; font-size: 0.78rem; color: #455; }
  form.filters input, form.filters select { min-width: 0; padding: 0.35rem; border: 1px solid #bbc3cc; border-radius: 0.25rem; background: white; }
  form.filters .check { display: flex; align-items: end; gap: 0.35rem; color: #1a1a1a; }
  form.filters button { align-self: end; padding: 0.45rem 0.65rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  form.refresh { margin: 0.75rem 0; display: flex; align-items: center; gap: 0.65rem; }
  form.refresh button { padding: 0.45rem 0.65rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  .badge-scout { background: #fff2d6; color: #805400; }
  .badge-proven { background: #e3f3e1; color: #1e6b1e; }
  .badge-unlikely { background: #eee; color: #555; }
  .attribute-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.35rem; }
  .attribute-grid div { border: 1px solid #e5e5e5; padding: 0.35rem; border-radius: 0.25rem; }
  .attribute-grid b { display: block; font-size: 0.75rem; color: #667; }
</style>
"""


def _nav_link(path: str, label: str, active_path: str) -> str:
    active_class = ' class="active"' if path == active_path else ""
    return f'<a href="{path}"{active_class}>{html.escape(label)}</a>'


def _tactical_shortfalls(shortfalls: Sequence[str]) -> str:
    """Turn compact model diagnostics into short manager-facing phrases."""
    labels: list[str] = []
    for shortfall in shortfalls:
        dimension, _separator, _amounts = shortfall.rpartition(" ")
        labels.append(_TACTICAL_DIMENSION_LABELS.get(dimension, dimension))
    displayed = labels[:2]
    remainder = len(labels) - len(displayed)
    suffix = f" +{remainder} more" if remainder else ""
    return ", ".join(displayed) + suffix


def _tactic_notes(tactic: TacticDefinition) -> str:
    """Render the catalogue author's own explanation of a tactic, if given.

    These fields (style/description/whyGood/keyRequirements/tags) are
    manager-facing commentary carried alongside the tactic in the catalogue
    data, not scoring input -- a tactic with none of them still renders
    correctly, since older catalogue entries may not define any.
    """
    if not any(
        (tactic.style, tactic.description, tactic.why_good, tactic.key_requirements, tactic.tags)
    ):
        return ""
    parts = []
    if tactic.style:
        parts.append(f"<p><b>{html.escape(tactic.style)}</b></p>")
    if tactic.description:
        parts.append(f"<p>{html.escape(tactic.description)}</p>")
    if tactic.why_good:
        parts.append(f"<p class='muted'><b>Why it works:</b> {html.escape(tactic.why_good)}</p>")
    if tactic.key_requirements:
        parts.append(
            "<p class='muted'><b>Needs:</b> "
            + ", ".join(html.escape(item) for item in tactic.key_requirements)
            + "</p>"
        )
    if tactic.tags:
        parts.append(
            "<p>"
            + " ".join(f"<span class='tag'>{html.escape(tag)}</span>" for tag in tactic.tags)
            + "</p>"
        )
    return "".join(parts)


def _raw_position_notice(candidates: Sequence[object]) -> str:
    raw_count = sum(bool(getattr(candidate, "raw_positions", ())) for candidate in candidates)
    if raw_count == 0:
        return (
            "<p class='warn'><b>Raw external positions enabled, but unavailable.</b> "
            "This capture has no raw position labels yet. Recapture the scouting feed "
            "and reload this page.</p>"
        )
    return (
        "<p class='warn'><b>Raw external positions enabled.</b> These labels are "
        "derived from non-owned players' raw position data under the accepted short-"
        "term visibility gap. They can reveal secondary positions FM does not "
        f"currently show the manager ({raw_count} captured).</p>"
    )


def _position_display(candidate, *, include_raw_external_positions: bool) -> str:
    positions = candidate.positions_for(
        include_raw_external_positions=include_raw_external_positions
    )
    return html.escape(", ".join(positions) or "Not yet captured")


def _layout(title: str, active_path: str, body: str) -> str:
    nav = "".join(_nav_link(path, label, active_path) for path, label in _NAV)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)} · FM Analytics</title>{_STYLE}</head>"
        f"<body><nav>{nav}</nav><main><h1>{html.escape(title)}</h1>{body}</main>"
        "</body></html>"
    )


def _error_page(title: str, message: str, active_path: str = "/") -> str:
    return _layout(title, active_path, f"<p class='error'>{html.escape(message)}</p>")


def _band(value) -> str:
    """One number when attributes are fully known; low–expected–high otherwise."""
    if value.lower == value.upper:
        return f"{value.central:.1f}"
    return f"{value.central:.1f} ({value.lower:.1f}–{value.upper:.1f})"


def _injury_risk_count(report: WeaknessReport) -> int:
    return sum(1 for weakness in report.weaknesses if weakness.kind in _INJURY_RISK_KINDS)


def _query_first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    return values[0].strip() if values and values[0].strip() else None


def _query_number(query: dict[str, list[str]], name: str, *, integer: bool = False):
    raw = _query_first(query, name)
    if raw is None:
        return None
    try:
        value = int(raw) if integer else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _scouting_filters(query: dict[str, list[str]]) -> ScoutingFilters:
    visibility = _query_first(query, "visibility") or "any"
    if visibility not in {"any", "known", "partial", "unknown"}:
        raise ValueError("visibility filter is invalid")
    facts = {
        key.removeprefix("fact."): value[0]
        for key, value in query.items()
        if key.startswith("fact.") and value and value[0]
    }
    return ScoutingFilters(
        position=_query_first(query, "position"), role_key=_query_first(query, "role"),
        minimum_age=_query_number(query, "minAge", integer=True),
        maximum_age=_query_number(query, "maxAge", integer=True),
        club_contains=_query_first(query, "club"), nationality=_query_first(query, "nationality"),
        footedness=_query_first(query, "footedness"),
        transfer_status=_query_first(query, "transferStatus"), availability=_query_first(query, "availability"),
        visibility=visibility, minimum_floor=_query_number(query, "minFloor"),
        minimum_ceiling=_query_number(query, "minCeiling"),
        include_unlikely=_query_first(query, "includeUnlikely") == "1",
        include_raw_external_positions=_query_first(query, "includeRawPositions") == "1",
        facts=facts,
    )


def _options(items, selected: str | None, blank: str) -> str:
    output = f"<option value=''>{html.escape(blank)}</option>" if blank else ""
    for value, label in items:
        selected_text = " selected" if value == selected else ""
        output += f"<option value='{html.escape(value, quote=True)}'{selected_text}>{html.escape(label)}</option>"
    return output


def _input_value(value: object) -> str:
    return "" if value is None else html.escape(str(value), quote=True)


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").capitalize()


def _scouting_refresh_command(path: Path) -> Callable[[], str]:
    """Build the bounded local command used by the Scouting-page refresh button."""
    project_root = Path(__file__).resolve().parents[3]
    capture_tool = project_root / "tools" / "fm20_scouting_feed.py"
    target = path.resolve()

    def refresh() -> str:
        command = [
            "uv",
            "run",
            "--extra",
            "research",
            "python",
            str(capture_tool),
            "--output",
            str(target),
        ]
        if target.exists():
            command.extend(("--base-feed", str(target), "--replace"))
        try:
            result = subprocess.run(
                command,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Scouting refresh timed out after three minutes.") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown capture failure").strip()
            raise RuntimeError(f"Scouting refresh failed: {detail[-2_000:]}")
        return (result.stdout or "Scouting data refreshed.").strip()

    return refresh


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
            "<ul class='legend'><li><b>Uncertain</b>: a rival could still overtake "
            "once scouted</li></ul>"
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


class SquadWebServer(ThreadingHTTPServer):
    """Serves `SquadWebHandler`, with a short-TTL cache in front of the source.

    Both the provider call and the full recommendation computation can cost
    real seconds -- a direct-live provider re-spawns the probe and
    owned-attribute subprocesses on every call, and the dual effective/
    potential tactic search over a large catalogue is measurably slow (see
    Phase 05's benchmark). Caching means clicking between pages, or
    reloading the same one, does not re-pay either cost every time. This is
    the mitigation flagged as the right first move before touching the
    search algorithm itself; it is not a fix for the search cost, only a way
    to stop paying it more often than necessary.
    """

    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        provider: GameSquadProvider,
        *,
        scouting_provider=None,
        scouting_refresh: Callable[[], str] | None = None,
        cache_ttl_seconds: float = 8.0,
    ):
        self.provider = provider
        self.scouting_provider = scouting_provider or empty_scouting_provider()
        self.scouting_refresh = scouting_refresh
        self._scouting_refresh_lock = threading.Lock()
        self.cache_ttl_seconds = cache_ttl_seconds
        self._lock = threading.Lock()
        self._read_at = 0.0
        self._read_result: tuple[object, object] | None = None
        self._read_error: Exception | None = None
        self._bundle_at = 0.0
        self._bundle_result: RecommendationBundle | None = None
        self._bundle_error: Exception | None = None
        super().__init__(address, SquadWebHandler)

    def scouting(self):
        # A refresh overwrites the capture file. Do not let another request
        # parse the JSON while that write is in progress.
        with self._scouting_refresh_lock:
            return self.scouting_provider()

    def refresh_scouting(self) -> str:
        if self.scouting_refresh is None:
            raise ValueError("Scouting refresh is not configured for this server.")
        if not self._scouting_refresh_lock.acquire(blocking=False):
            raise ValueError("A scouting refresh is already running.")
        try:
            return self.scouting_refresh()
        finally:
            self._scouting_refresh_lock.release()

    def read(self):
        with self._lock:
            now = time.monotonic()
            if now - self._read_at < self.cache_ttl_seconds:
                if self._read_error is not None:
                    raise self._read_error
                if self._read_result is not None:
                    return self._read_result
        try:
            result = self.provider()
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            with self._lock:
                self._read_result, self._read_error, self._read_at = None, exc, time.monotonic()
            raise
        with self._lock:
            self._read_result, self._read_error, self._read_at = result, None, time.monotonic()
        return result

    def bundle(self) -> RecommendationBundle:
        with self._lock:
            now = time.monotonic()
            if now - self._bundle_at < self.cache_ttl_seconds:
                if self._bundle_error is not None:
                    raise self._bundle_error
                if self._bundle_result is not None:
                    return self._bundle_result
        game, squad = self.read()
        try:
            validate_recommendation_snapshot(game, squad)
            if not has_complete_role_attributes(squad):
                raise ValueError(
                    "This source has not supplied every role-scoring attribute yet; "
                    "see the Data page for exactly what is missing."
                )
            built = build_recommendation_bundle(game, squad)
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            with self._lock:
                self._bundle_result, self._bundle_error, self._bundle_at = None, exc, time.monotonic()
            raise
        with self._lock:
            self._bundle_result, self._bundle_error, self._bundle_at = built, None, time.monotonic()
        return built


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the read-only squad decision-support view")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--cache-ttl-seconds",
        type=float,
        default=8.0,
        help="how long to reuse a computed recommendation before recomputing it (default: %(default)s)",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--fixture",
        help="serve a fixed game/squad fixture (default when no other source is given)",
    )
    source.add_argument(
        "--snapshot-db",
        help="serve the latest (or --capture-id) capture from a --snapshot-db SQLite file",
    )
    source.add_argument(
        "--base-url",
        help="serve the current squad from the FM HTTP bridge at this URL",
    )
    source.add_argument(
        "--direct-live",
        action="store_true",
        help="serve the current squad directly from FM20, without the HTTP bridge",
    )
    parser.add_argument(
        "--capture-id",
        type=int,
        help="a specific capture id to serve from --snapshot-db (default: the latest)",
    )
    parser.add_argument(
        "--fm-html",
        nargs="+",
        help="overlay a manual FM20 Squad HTML export onto the chosen source, like the CLI's --fm-html",
    )
    parser.add_argument(
        "--fm-html-player-count",
        type=int,
        help="required unique-player count shown by FM for --fm-html completeness",
    )
    parser.add_argument(
        "--scouting-json",
        help="manager-visible discoverability/scouting capture JSON for the Scouting page",
    )
    return parser


def _build_provider(args: argparse.Namespace) -> GameSquadProvider:
    if args.capture_id is not None and not args.snapshot_db:
        raise SystemExit("--capture-id requires --snapshot-db")
    if args.snapshot_db:
        provider = snapshot_provider(args.snapshot_db, capture_id=args.capture_id)
    elif args.base_url:
        provider = live_provider(base_url=args.base_url)
    elif args.direct_live:
        provider = live_provider(direct=True)
    else:
        provider = fixture_provider(args.fixture or _default_fixture_path())
    if args.fm_html:
        provider = html_overlay_provider(
            provider, args.fm_html, expected_players=args.fm_html_player_count
        )
    return provider


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider = _build_provider(args)
    default_scouting_path = _default_scouting_path()
    scouting_path = args.scouting_json or default_scouting_path
    refresh_path = (
        Path(scouting_path)
        if scouting_path is not None
        else Path(__file__).resolve().parents[3] / "data" / "scouting-capture.json"
    )
    server = SquadWebServer(
        (args.host, args.port), provider,
        scouting_provider=(scouting_json_provider(scouting_path) if scouting_path else None),
        scouting_refresh=_scouting_refresh_command(refresh_path),
        cache_ttl_seconds=args.cache_ttl_seconds,
    )
    print(f"FM Analytics web view listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _default_fixture_path() -> str:
    from pathlib import Path

    return str(
        Path(__file__).resolve().parents[1] / "fixtures" / "sample-game.json"
    )


def _default_scouting_path():
    from pathlib import Path

    data_dir = Path(__file__).resolve().parents[3] / "data"
    for filename in (
        "scouting-capture-enriched.json",
        "scouting-capture-hydrated.json",
        "scouting-capture.json",
    ):
        candidate = data_dir / filename
        if candidate.exists():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
