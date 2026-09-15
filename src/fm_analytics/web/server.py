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
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Sequence
from urllib.parse import urlparse

from fm_analytics.analytics import WeaknessKind, WeaknessReport
from fm_analytics.bridge.errors import BridgeSourceError
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
    snapshot_provider,
)


_NAV: tuple[tuple[str, str], ...] = (
    ("/", "Dashboard"),
    ("/squad", "Squad"),
    ("/roles", "Roles"),
    ("/tactics", "Tactics"),
    ("/depth", "Depth"),
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
  code { background: #eef1f4; padding: 0.05rem 0.3rem; border-radius: 0.25rem; }
  details { margin: 0.4rem 0; border: 1px solid #e5e5e5; border-radius: 0.3rem; padding: 0.3rem 0.6rem; }
  details summary { cursor: pointer; font-weight: 600; }
  details table { margin-top: 0.5rem; }
</style>
"""


def _layout(title: str, active_path: str, body: str) -> str:
    nav = "".join(
        f'<a href="{path}"{" class=\"active\"" if path == active_path else ""}>'
        f"{html.escape(label)}</a>"
        for path, label in _NAV
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)} · FM Analytics</title>{_STYLE}</head>"
        f"<body><nav>{nav}</nav><main><h1>{html.escape(title)}</h1>{body}</main>"
        "</body></html>"
    )


def _error_page(title: str, message: str, active_path: str = "/") -> str:
    return _layout(title, active_path, f"<p class='error'>{html.escape(message)}</p>")


def _band(value) -> str:
    return f"{value.lower:.1f} / {value.central:.1f} / {value.upper:.1f}"


def _injury_risk_count(report: WeaknessReport) -> int:
    return sum(1 for weakness in report.weaknesses if weakness.kind in _INJURY_RISK_KINDS)


class SquadWebHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        routes = {
            "/": self._dashboard,
            "/squad": self._squad_page,
            "/roles": self._roles_page,
            "/tactics": self._tactics_page,
            "/depth": self._depth_page,
            "/data": self._data_page,
        }
        handler = routes.get(path)
        if handler is None:
            self._send(
                _error_page("Not found", f"No page exists at '{path}'."),
                HTTPStatus.NOT_FOUND,
            )
            return
        handler(path)

    def _dashboard(self, path: str) -> None:
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

    def _squad_page(self, path: str) -> None:
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
        )
        self._send(_layout("Squad", path, body))

    def _roles_page(self, path: str) -> None:
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
            "<p class='muted'>Lower / central / upper score band; 'uncertain' means another "
            "candidate's upper bound still beats the leader's lower bound.</p>"
            "<table><tr><th>Role</th><th>Best player</th><th>Score</th>"
            "<th>Eligible candidates</th><th>Decision</th></tr>"
            + "".join(rows)
            + "</table>"
            + uncovered
        )
        self._send(_layout("Roles", path, body))

    def _tactics_page(self, path: str) -> None:
        bundle = self._bundle_or_error(path, "Tactics")
        if bundle is None:
            return
        rows = []
        details = []
        for evaluation in bundle.recommendation.evaluations:
            tactic_key = evaluation.tactic.key
            status = (
                "legal XI"
                if evaluation.has_legal_xi
                else "missing " + ", ".join(slot.key for slot in evaluation.unfilled_slots)
            )
            risk = _injury_risk_count(bundle.squad_depth.per_tactic[tactic_key])
            risk_class = "badge-persistent" if risk else "badge-ok"
            rows.append(
                "<tr>"
                f"<td>{html.escape(evaluation.tactic.name)}</td>"
                f"<td>{html.escape(evaluation.tactic.formation)}</td>"
                f"<td>{_band(evaluation.score)}</td>"
                f"<td>{status}</td>"
                f"<td><span class='badge {risk_class}'>{risk} slot(s)</span></td>"
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
                "<p class='muted'>Tactics worth training towards: potential fit once position "
                "familiarity stops being the limiting factor.</p>"
                "<table><tr><th>Tactic</th><th>Effective</th><th>Potential</th><th>Gap</th></tr>"
                + targets_rows
                + "</table>"
            )
            if bundle.training_targets
            else "<h2>Training targets</h2><p class='muted'>None clear a material margin.</p>"
        )
        body = (
            "<h2>Tactic comparison</h2>"
            "<p class='muted'>"
            "<strong>Fit</strong> blends two numbers -- 65% the XI's average role fit plus "
            "35% its weakest starting slot -- so a tactic that strands one player in a poor "
            "fit scores lower even if the rest are strong. Each score shows three numbers, "
            "<strong>low / best estimate / high</strong>: how much is actually known about "
            "the relevant attributes: a tight band means we're confident, a wide one means "
            "more scouting could move the answer. <strong>Injury risk</strong> counts "
            "starting slots with no adequate, unshared backup in that tactic -- higher means "
            "more exposure if a starter becomes unavailable."
            "</p>"
            "<table><tr><th>Tactic</th><th>Formation</th><th>Fit</th><th>Status</th>"
            "<th>Injury risk</th></tr>"
            + "".join(rows)
            + "</table>"
            + targets_body
            + "<h2>Roles per tactic</h2>"
            "<p class='muted'>Expand a tactic to see its actual role assignment and whether "
            "the squad can currently fill it.</p>"
            + "".join(details)
        )
        self._send(_layout("Tactics", path, body))

    def _depth_page(self, path: str) -> None:
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
            "<p class='muted'>Across every tactic evaluated in Tactics, not the selected "
            "one alone. 'Weak in' counts how many of the tactics fielding that position "
            "flagged a problem there.</p>"
            "<table><tr><th>Position</th><th>Status</th><th>Weak in (of tactics using it)</th>"
            "<th>Reasons</th></tr>"
            + rows
            + "</table>"
        )
        self._send(_layout("Depth", path, body))

    def _data_page(self, path: str) -> None:
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
        body = (
            f"<p>Required role-scoring attributes: {len(required)}. "
            f"<code>positionFamiliarity</code> is additive and optional -- absence means "
            "no reading is available yet, not that a player is unfamiliar everywhere.</p>"
            "<table><tr><th>Player</th><th>Attribute coverage</th>"
            "<th>Missing attributes</th><th>Position familiarity</th></tr>"
            + "".join(rows)
            + "</table>"
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
        cache_ttl_seconds: float = 8.0,
    ):
        self.provider = provider
        self.cache_ttl_seconds = cache_ttl_seconds
        self._lock = threading.Lock()
        self._read_at = 0.0
        self._read_result: tuple[object, object] | None = None
        self._read_error: Exception | None = None
        self._bundle_at = 0.0
        self._bundle_result: RecommendationBundle | None = None
        self._bundle_error: Exception | None = None
        super().__init__(address, SquadWebHandler)

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
    server = SquadWebServer(
        (args.host, args.port), provider, cache_ttl_seconds=args.cache_ttl_seconds
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


if __name__ == "__main__":
    raise SystemExit(main())
