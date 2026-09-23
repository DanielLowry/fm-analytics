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
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
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
    TacticRankingExecutor,
    WeaknessKind,
    WeaknessReport,
    assess_scouting_candidates,
    available_fact_values,
    filter_scouting_candidates,
)
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.domain import SourceHealth, Squad
from fm_analytics.reporting import (
    RecommendationBundle,
    TacticMatchdayReport,
    build_recommendation_bundle,
    build_tactic_matchday_report,
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


from fm_analytics.web.rendering import (
    _MAX_SCOUTING_ROWS,
    _band,
    _error_page,
    _injury_risk_count,
    _input_value,
    _label,
    _layout,
    _options,
    _position_display,
    _query_first,
    _raw_position_notice,
    _scouting_filters,
    _scouting_refresh_command,
    _tactic_notes,
    _tactical_shortfalls,
)


from fm_analytics.web.handlers import SquadWebHandler



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
        scouting_refresh: Callable[..., str] | None = None,
        cache_ttl_seconds: float = 8.0,
        health_interval_seconds: float = 30.0,
        ranking_executor: TacticRankingExecutor | None = None,
    ):
        self.provider = provider
        self.scouting_provider = scouting_provider or empty_scouting_provider()
        self.scouting_refresh = scouting_refresh
        self._scouting_refresh_lock = threading.Lock()
        self.cache_ttl_seconds = cache_ttl_seconds
        self.health_interval_seconds = health_interval_seconds
        self.ranking_executor = ranking_executor
        self._lock = threading.Lock()
        self._read_at = 0.0
        self._read_result: tuple[object, object] | None = None
        self._read_error: Exception | None = None
        self._bundle_at = 0.0
        self._bundle_result: RecommendationBundle | None = None
        self._bundle_error: Exception | None = None
        self._tactic_report_cache: dict[tuple[int, str, int | None], TacticMatchdayReport] = {}
        self._snapshot_at: datetime | None = None
        self._refreshing = False
        self._refresh_error: Exception | None = None
        self._health = SourceHealth("unknown", "not checked")
        self._health_at: datetime | None = None
        self._health_checking = False
        self._health_stop = threading.Event()
        super().__init__(address, SquadWebHandler)
        threading.Thread(target=self._health_loop, daemon=True, name="fm-health").start()

    def scouting(self):
        # A refresh overwrites the capture file. Do not let another request
        # parse the JSON while that write is in progress.
        with self._scouting_refresh_lock:
            return self.scouting_provider()

    def refresh_scouting(self, *, allow_rebuild: bool = False) -> str:
        if self.scouting_refresh is None:
            raise ValueError("Scouting refresh is not configured for this server.")
        if not self._scouting_refresh_lock.acquire(blocking=False):
            raise ValueError("A scouting refresh is already running.")
        try:
            return self.scouting_refresh(allow_rebuild=allow_rebuild)
        finally:
            self._scouting_refresh_lock.release()

    def read(self):
        with self._lock:
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
            built = build_recommendation_bundle(
                game, squad, ranking_executor=self.ranking_executor
            )
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            with self._lock:
                self._bundle_result, self._bundle_error, self._bundle_at = None, exc, time.monotonic()
            raise
        with self._lock:
            self._bundle_result, self._bundle_error, self._bundle_at = built, None, time.monotonic()
            self._snapshot_at = datetime.now(timezone.utc)
            self._tactic_report_cache.clear()
        return built

    def request_refresh(self) -> bool:
        """Start a full snapshot refresh without blocking an HTTP request."""
        with self._lock:
            if self._refreshing:
                return False
            self._refreshing, self._refresh_error = True, None
        threading.Thread(target=self._refresh_snapshot, daemon=True, name="fm-refresh").start()
        return True

    def _refresh_snapshot(self) -> None:
        try:
            game, squad = self.provider()
            validate_recommendation_snapshot(game, squad)
            if not has_complete_role_attributes(squad):
                raise ValueError("This source has not supplied every role-scoring attribute yet.")
            built = build_recommendation_bundle(
                game, squad, ranking_executor=self.ranking_executor
            )
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            with self._lock:
                self._refreshing, self._refresh_error = False, exc
            return
        with self._lock:
            self._read_result, self._read_error, self._read_at = (game, squad), None, time.monotonic()
            self._bundle_result, self._bundle_error, self._bundle_at = built, None, time.monotonic()
            self._snapshot_at = datetime.now(timezone.utc)
            self._tactic_report_cache.clear()
            self._refreshing = False

    def _health_loop(self) -> None:
        while not self._health_stop.is_set():
            self.check_health()
            self._health_stop.wait(self.health_interval_seconds)

    def check_health(self) -> None:
        with self._lock:
            if self._health_checking:
                return
            self._health_checking = True
        try:
            health_method = getattr(self.provider, "health", None)
            health = health_method() if health_method is not None else SourceHealth("ready", "snapshot")
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            health = SourceHealth("unavailable", "provider", str(exc))
        with self._lock:
            self._health, self._health_at, self._health_checking = health, datetime.now(timezone.utc), False

    def request_health_check(self) -> bool:
        with self._lock:
            if self._health_checking:
                return False
            self._health_checking = True
        threading.Thread(target=self._forced_health_check, daemon=True, name="fm-health-manual").start()
        return True

    def _forced_health_check(self) -> None:
        try:
            health_method = getattr(self.provider, "health", None)
            health = health_method(force=True) if health_method is not None else SourceHealth("ready", "snapshot")
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            health = SourceHealth("unavailable", "provider", str(exc))
        with self._lock:
            self._health, self._health_at, self._health_checking = health, datetime.now(timezone.utc), False

    def status_html(self) -> str:
        with self._lock:
            health = self._health
            checked = self._health_at.isoformat(timespec="seconds") if self._health_at else "not yet"
            snapshot = self._snapshot_at.isoformat(timespec="seconds") if self._snapshot_at else "not yet"
            game_date = self._read_result[0].game_date.isoformat() if self._read_result else "not yet"
            refreshing = self._refreshing
            health_checking = self._health_checking
            error = str(self._refresh_error) if self._refresh_error else ""
        detail = "refreshing…" if refreshing else ("refresh failed: " + error if error else "")
        return (
            "<aside class='fm-status'><b>FM: " + html.escape(health.status) + "</b>"
            + f"<br>Health checked: {html.escape(checked)}"
            + f"<br>Recommendation snapshot: {html.escape(game_date)} ({html.escape(snapshot)})"
            + (f"<br><span class='warn'>{html.escape(detail)}</span>" if detail else "")
            + "<form method='post' action='/health/refresh'><button type='submit'"
            + (" disabled" if health_checking else "")
            + ">Check connection</button></form>"
            + "<form method='post' action='/refresh'><button type='submit'"
            + (" disabled" if refreshing else "")
            + ">Refresh squad data</button></form></aside>"
        )

    def shutdown(self) -> None:
        self._health_stop.set()
        super().shutdown()

    def server_close(self) -> None:
        self._health_stop.set()
        if self.ranking_executor is not None:
            self.ranking_executor.shutdown()
        super().server_close()

    def tactic_report(
        self, tactic_key: str, *, bench_size: int | None = None
    ) -> TacticMatchdayReport:
        """Return a cached drill-down without bloating the overview bundle."""
        bundle = self.bundle()
        cache_key = (id(bundle), tactic_key, bench_size)
        with self._lock:
            cached = self._tactic_report_cache.get(cache_key)
        if cached is not None:
            return cached
        built = build_tactic_matchday_report(
            bundle,
            tactic_key,
            bench_size=bench_size,
        )
        with self._lock:
            self._tactic_report_cache[cache_key] = built
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
    parser.add_argument(
        "--ranking-workers",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help=(
            "bounded worker processes for tactic ranking; use 1 for the "
            "existing sequential calculation (default: %(default)s)"
        ),
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
    if args.ranking_workers < 1:
        raise SystemExit("--ranking-workers must be at least 1")
    provider = _build_provider(args)
    default_scouting_path = _default_scouting_path()
    scouting_path = args.scouting_json or default_scouting_path
    refresh_path = (
        Path(scouting_path)
        if scouting_path is not None
        else Path(__file__).resolve().parents[3] / "data" / "scouting-capture.json"
    )
    ranking_executor = TacticRankingExecutor(workers=args.ranking_workers)
    try:
        ranking_executor.warm()
    except (OSError, RuntimeError) as exc:
        # The server remains usable on constrained systems: ranking falls
        # back to the existing sequential implementation rather than failing
        # to start its read-only UI.
        print(f"Could not start tactic-ranking workers; using sequential ranking: {exc}")
        ranking_executor.shutdown(wait=False)
        ranking_executor = None
    server = SquadWebServer(
        (args.host, args.port), provider,
        scouting_provider=(scouting_json_provider(scouting_path) if scouting_path else None),
        scouting_refresh=_scouting_refresh_command(refresh_path),
        cache_ttl_seconds=args.cache_ttl_seconds,
        ranking_executor=ranking_executor,
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
