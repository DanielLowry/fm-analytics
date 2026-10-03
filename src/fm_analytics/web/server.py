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
import json
import os
import sqlite3
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Sequence

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    OpponentProfile,
    TacticRankingExecutor,
    rank_for_position,
    ScoutingAlerts,
    build_scouting_alerts,
)
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.candidate_pool import DEFAULT_OUT_OF_DATE_MONTHS, compose_candidate_pool
from fm_analytics.domain import SourceHealth
from fm_analytics.knowledge_ingest import DEFAULT_DATABASE as DEFAULT_KNOWLEDGE_DATABASE
from fm_analytics.knowledge_ingest import default_save_key, record_capture_file
from fm_analytics.match_ingest import DEFAULT_DATABASE as DEFAULT_MATCH_DATABASE
from fm_analytics.match_ingest import DEFAULT_CAPTURE as DEFAULT_MATCH_CAPTURE
from fm_analytics.match_ingest import capture_and_record, record_capture_file as record_match_capture
from fm_analytics.persistence.match_history import MatchHistoryStore
from fm_analytics.persistence import (
    PlayerKnowledgeStore,
    RecordResult,
    SnapshotStore,
    SnapshotStoreError,
    Verdict,
    VerdictRecord,
)
from fm_analytics.reporting import (
    RecommendationBundle,
    RecommendationPolicy,
    TacticMatchdayReport,
    build_recommendation_bundle,
    build_tactic_matchday_report,
    has_complete_role_attributes,
    parse_pinned_tactics,
    validate_recommendation_snapshot,
    weakest_slots,
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


from fm_analytics.web.rendering import ScoutingPoolNotBuilt, _scouting_refresh_command


from fm_analytics.web.handlers import SquadWebHandler
from fm_analytics.web.match_state import MatchHistoryState
from fm_analytics.web.league_state import DEFAULT_CAPTURE as DEFAULT_LEAGUE_CAPTURE
from fm_analytics.web.league_state import LeagueState, league_capture_command, league_json_provider
from fm_analytics.persistence.league_history import LeagueHistoryStore


@dataclass(frozen=True)
class ScoutingRefreshJob:
    status: str = "idle"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    message: str = ""
    error: str = ""
    allow_rebuild: bool = False
    needs_player_search: bool = False



class SquadWebServer(LeagueState, MatchHistoryState, ThreadingHTTPServer):
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
    _MAX_BUNDLE_PROFILES = 8

    def __init__(
        self,
        address: tuple[str, int],
        provider: GameSquadProvider,
        *,
        scouting_provider=None,
        scouting_refresh: Callable[..., str] | None = None,
        scouting_capture_path: Path | None = None,
        cache_ttl_seconds: float = 8.0,
        health_interval_seconds: float = 30.0,
        ranking_executor: TacticRankingExecutor | None = None,
        pinned_tactics: tuple[str, ...] = (),
        knowledge_recorder: Callable[[], RecordResult] | None = None,
        # Where the manager's own Target/Watch/Reject verdicts live. The store
        # may be configured without a save key (nothing can name a save yet),
        # which quietly means verdicts are off rather than half available.
        knowledge_store: PlayerKnowledgeStore | None = None,
        knowledge_save_key: str | None = None,
        out_of_date_months: int = DEFAULT_OUT_OF_DATE_MONTHS,
        match_store: MatchHistoryStore | None = None,
        match_capture: Callable[[], str] | None = None,
        league_provider=None,
        league_store: LeagueHistoryStore | None = None,
        league_capture: Callable[[], str] | None = None,
    ):
        self.setup_league(league_provider, league_store, league_capture)
        self.setup_match_history(match_store, match_capture)
        # Appends each fresh scouting capture to the player-knowledge database
        # (see ``record_knowledge``). None disables recording.
        self.knowledge_recorder = knowledge_recorder
        self.knowledge_store = knowledge_store
        self.knowledge_save_key = knowledge_save_key
        # (message, succeeded) from the latest recording, shown on the
        # Scouting page so a failure to keep history is never silent.
        self.knowledge_note: tuple[str, bool] | None = None
        self.out_of_date_months = out_of_date_months
        # The feed merged with the save's knowledge history (see ``scouting``):
        # (feed tuple, knowledge generation, pool). Rebuilt only when the feed
        # file or the recorded history changes, because reading a whole save's
        # history costs seconds and the rank cache needs stable objects.
        self._pool: tuple[object, int, tuple] | None = None
        self._pool_lock = threading.Lock()
        self._knowledge_generation = 0
        # Fixed for the life of the server, so the bundle cache is still keyed
        # on the opponent alone. If pins ever become editable from a page they
        # must join that key, or one page would serve another's analysis.
        self.pinned_tactics = pinned_tactics
        self.provider = provider
        self.scouting_provider = scouting_provider or empty_scouting_provider()
        self.scouting_refresh = scouting_refresh
        self.scouting_capture_path = scouting_capture_path
        self._scouting_refresh_lock = threading.Lock()
        self._scouting_refresh_job = ScoutingRefreshJob()
        self._scouting_refresh_thread: threading.Thread | None = None
        # Scores of scouting candidates per (player, position, options); see
        # ``rank_for_position``. Lets sorting and filtering re-rank a
        # thousand-player pool without scoring it again.
        self.scouting_rank_cache: dict = {}
        self.cache_ttl_seconds = cache_ttl_seconds
        self.health_interval_seconds = health_interval_seconds
        self.ranking_executor = ranking_executor
        self._lock = threading.Lock()
        self._read_at = 0.0
        self._read_result: tuple[object, object] | None = None
        self._read_error: Exception | None = None
        # A recommendation is immutable for the captured squad, but opponent
        # controls can ask for several different analyses of that same
        # snapshot. Keep a small LRU so moving a slider back and forth is
        # cheap without allowing arbitrary query strings to grow memory.
        self._bundle_results: OrderedDict[OpponentProfile, RecommendationBundle] = (
            OrderedDict()
        )
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
        """The scouting pool every page reads: the feed plus the save's history.

        List, live results and player report all come through here, so they
        always agree on who is in the pool and what is known about him.
        """
        # Completed captures are swapped atomically, so readers never need to
        # wait for the slow capture subprocess.
        current = self.scouting_provider()
        generation = self._knowledge_generation
        return self._with_knowledge(current, generation)

    def _with_knowledge(self, current, generation: int):
        """Merge the save's best-known profiles into ``current``, once per change.

        Never raises: a history that cannot be read leaves the page on the
        current feed alone, which is what it showed before the history existed.
        """
        store, key = self.knowledge_store, self.knowledge_save_key
        as_of = next((item.captured_game_date for item in current if item.captured_game_date), None)
        if store is None or key is None or as_of is None:
            return current
        with self._pool_lock:
            if self._pool is not None and self._pool[0] is current and self._pool[1] == generation:
                return self._pool[2]
            try:
                pool = compose_candidate_pool(
                    current, store.best_known_profiles(key, as_of),
                    save_key=key, as_of=as_of, out_of_date_months=self.out_of_date_months,
                )
            except Exception as exc:  # noqa: BLE001 - see the docstring
                print(f"Player-knowledge history could not be read: {exc}", file=sys.stderr)
                return current
            self._pool = (current, generation, pool)
            return pool

    def warm_scouting_rankings(self) -> None:
        """Score the whole pool once, off the request path.

        Scoring every player against every role is the slow part of the default
        Scouting view (seconds for a full Player Search pool); ``scouting_rank_cache``
        makes every later sort and filter of it instant, so pay for it before
        the manager asks. Best effort: a missing or unreadable capture just
        means the first page load pays instead.
        """
        try:
            rank_for_position(self.scouting(), MVP_CATALOGUE, cache=self.scouting_rank_cache)
        except (OSError, ValueError, KeyError):
            pass

    def refresh_scouting(self, *, allow_rebuild: bool = False) -> str:
        """Run a refresh synchronously (kept for startup and direct callers)."""
        if self.scouting_refresh is None:
            raise ValueError("Scouting refresh is not configured for this server.")
        result = self.scouting_refresh(allow_rebuild=allow_rebuild)
        if self.scouting_capture_path is not None:
            # A refresh can be the first capture, or belong to a different
            # playthrough. Never merge one save's notebook into another's feed.
            self.knowledge_save_key = _capture_save_key(self.scouting_capture_path)
        self.record_knowledge()
        threading.Thread(target=self.warm_scouting_rankings, daemon=True, name="scouting-warm").start()
        return result

    def request_scouting_refresh(self, *, allow_rebuild: bool = False) -> bool:
        """Start one background refresh, returning immediately."""
        if self.scouting_refresh is None:
            raise ValueError("Scouting refresh is not configured for this server.")
        with self._scouting_refresh_lock:
            if self._scouting_refresh_job.status == "running":
                return False
            self._scouting_refresh_job = ScoutingRefreshJob(
                status="running", started_at=datetime.now(timezone.utc),
                allow_rebuild=allow_rebuild,
            )
            worker = threading.Thread(
                target=self._background_scouting_refresh,
                kwargs={"allow_rebuild": allow_rebuild},
                daemon=True,
                name="scouting-refresh",
            )
            self._scouting_refresh_thread = worker
            worker.start()
        return True

    def _background_scouting_refresh(self, *, allow_rebuild: bool) -> None:
        try:
            message = self.refresh_scouting(allow_rebuild=allow_rebuild)
        except Exception as exc:  # noqa: BLE001 - failure is retained as job state
            with self._scouting_refresh_lock:
                started = self._scouting_refresh_job.started_at
                self._scouting_refresh_job = ScoutingRefreshJob(
                    status="failed", started_at=started,
                    ended_at=datetime.now(timezone.utc), error=str(exc),
                    allow_rebuild=allow_rebuild,
                    needs_player_search=isinstance(exc, ScoutingPoolNotBuilt),
                )
            return
        with self._scouting_refresh_lock:
            started = self._scouting_refresh_job.started_at
            self._scouting_refresh_job = ScoutingRefreshJob(
                status="succeeded", started_at=started,
                ended_at=datetime.now(timezone.utc), message=message,
                allow_rebuild=allow_rebuild,
            )

    @property
    def scouting_refresh_job(self) -> ScoutingRefreshJob:
        with self._scouting_refresh_lock:
            return self._scouting_refresh_job

    @property
    def scouting_capture_age(self) -> str | None:
        path = self.scouting_capture_path
        if path is None:
            return None
        try:
            seconds = max(0, int(time.time() - path.stat().st_mtime))
        except OSError:
            return None
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        return f"{seconds // 3600}h"

    def record_knowledge(self) -> None:
        """Append the current scouting capture to the player-knowledge database.

        Never raises: a refresh that succeeded must not be reported as failed
        because history could not be kept. The failure is instead recorded in
        ``knowledge_note`` and printed, because unrecorded observations cannot
        be recovered once FM stops showing them.
        """
        if self.knowledge_recorder is None:
            return
        try:
            note = (self.knowledge_recorder().summary(), True)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            note = (f"Player knowledge was NOT recorded: {exc}", False)
            print(note[0], file=sys.stderr)
        self.knowledge_note = note
        # The scouting pool reads this history, so the next page rebuilds it.
        self._knowledge_generation += 1

    @property
    def verdicts_enabled(self) -> bool:
        """Whether this session can write verdicts: a database and a save to key them by."""
        return self.knowledge_store is not None and self.knowledge_save_key is not None

    def current_verdicts(self) -> dict[str, VerdictRecord]:
        """The current verdicts of the save being watched, keyed by player id.

        Never raises: a verdict problem must not take the Scouting page down.
        Failing open shows a player the manager rejected -- which he can see
        and sort out -- where failing closed hides the whole list.
        """
        store, key = self.knowledge_store, self.knowledge_save_key
        if store is None or key is None:
            return {}
        try:
            return store.current_verdicts(key)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            print(f"Verdicts could not be read: {exc}", file=sys.stderr)
            return {}

    def scouting_alerts(self, candidates=None) -> ScoutingAlerts:
        """Prepare current-save alerts; unavailable prerequisites mean no alerts."""
        store, key = self.knowledge_store, self.knowledge_save_key
        if store is None or key is None:
            return ScoutingAlerts()
        pool = tuple(candidates if candidates is not None else self.scouting())
        as_of = next((item.captured_game_date for item in pool if item.captured_game_date), None)
        if as_of is None:
            return ScoutingAlerts()
        try:
            previous = store.previous_profiles(key, as_of)
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            previous = {}
        try:
            weak_slots = weakest_slots(self.bundle())
        except (OSError, RuntimeError, ValueError, KeyError):
            weak_slots = ()
        try:
            return build_scouting_alerts(
                pool, previous, self.current_verdicts(), weak_slots,
            )
        except (OSError, ValueError, KeyError, sqlite3.Error):
            return ScoutingAlerts()

    def set_verdict(
        self, player_id: str, verdict: Verdict | str, *, note: str, decided_on: str
    ) -> None:
        """Record the manager's own decision. Local database only; never FM."""
        store, key = self.knowledge_store, self.knowledge_save_key
        if store is None or key is None:
            raise ValueError("Verdicts need a player-knowledge database and a save.")
        store.set_verdict(key, player_id, verdict, note=note, decided_on=decided_on)

    def clear_verdict(self, player_id: str, *, decided_on: str) -> None:
        """Forget the current decision, keeping the ones already made."""
        store, key = self.knowledge_store, self.knowledge_save_key
        if store is None or key is None:
            raise ValueError("Verdicts need a player-knowledge database and a save.")
        store.clear_verdict(key, player_id, decided_on=decided_on)

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

    def bundle(
        self, opponent: OpponentProfile = OpponentProfile.neutral()
    ) -> RecommendationBundle:
        with self._lock:
            cached = self._bundle_results.get(opponent)
            if cached is not None:
                self._bundle_results.move_to_end(opponent)
                return cached
        game, squad = self.read()
        try:
            validate_recommendation_snapshot(game, squad)
            if not has_complete_role_attributes(squad):
                raise ValueError(
                    "This source has not supplied every role-scoring attribute yet; "
                    "see the Data page for exactly what is missing."
                )
            built = build_recommendation_bundle(
                game,
                squad,
                policy=RecommendationPolicy(
                    opponent=opponent, pinned_tactics=self.pinned_tactics
                ),
                ranking_executor=self.ranking_executor,
                form=self.recent_form(game, squad),
            )
        except (BridgeSourceError, OSError, ValueError, KeyError):
            raise
        with self._lock:
            self._bundle_results[opponent] = built
            self._bundle_results.move_to_end(opponent)
            while len(self._bundle_results) > self._MAX_BUNDLE_PROFILES:
                _evicted_profile, evicted_bundle = self._bundle_results.popitem(last=False)
                evicted_id = id(evicted_bundle)
                self._tactic_report_cache = {
                    key: report
                    for key, report in self._tactic_report_cache.items()
                    if key[0] != evicted_id
                }
            if self._snapshot_at is None:
                self._snapshot_at = datetime.now(timezone.utc)
        return built

    def forget_recommendations(self) -> None:
        """Drop every computed recommendation, so the next page rebuilds it from the
        same squad: new matches, notes or role codes change recent form."""
        with self._lock:
            self._bundle_results.clear()
            self._tactic_report_cache.clear()

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
                game,
                squad,
                policy=RecommendationPolicy(
                    opponent=OpponentProfile.neutral(),
                    pinned_tactics=self.pinned_tactics,
                ),
                ranking_executor=self.ranking_executor,
                form=self.recent_form(game, squad),
            )
        except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
            with self._lock:
                self._refreshing, self._refresh_error = False, exc
            return
        with self._lock:
            self._read_result, self._read_error, self._read_at = (game, squad), None, time.monotonic()
            self._bundle_results = OrderedDict(((OpponentProfile.neutral(), built),))
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
        status = health.status
        state = "unavailable" if status == "unavailable" else "ready"
        return (
            "<aside class='fm-status'>"
            + f"<span class='fm-status-dot' data-state='{html.escape(state)}' aria-hidden='true'></span>"
            + "<div class='fm-status-copy'><b>FM "
            + html.escape(status)
            + "</b><span>Snapshot: "
            + html.escape(game_date)
            + "</span></div>"
            + "<details><summary>Data controls</summary><div class='fm-status-actions'>"
            + f"<span class='fm-metric-note'>Health checked: {html.escape(checked)}</span>"
            + f"<span class='fm-metric-note'>Loaded: {html.escape(snapshot)}</span>"
            + (f"<span class='warn'>{html.escape(detail)}</span>" if detail else "")
            + "<form method='post' action='/health/refresh'><button type='submit'"
            + (" disabled" if health_checking else "")
            + ">Check connection</button></form>"
            + "<form method='post' action='/refresh'><button type='submit'"
            + (" disabled" if refreshing else "")
            + ">Refresh squad data</button></form>"
            + "</div></details></aside>"
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
        self,
        tactic_key: str,
        *,
        bench_size: int | None = None,
        opponent: OpponentProfile = OpponentProfile.neutral(),
    ) -> TacticMatchdayReport:
        """Return a cached drill-down without bloating the overview bundle."""
        bundle = self.bundle(opponent)
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
    parser.add_argument("--league-json", type=Path,
                        help="dated manager-visible league capture for team comparison; with --direct-live it "
                             "defaults to data/league-capture.json, which the League page's read button writes")
    parser.add_argument("--league-db", type=Path, default=Path("data/league-history.sqlite3"),
                        help="append-only league and roster capture history")
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
        "--my-tactics",
        metavar="KEY[,KEY...]",
        help=(
            "comma-separated tactic keys you actually play, primary first "
            "(e.g. vertical_442,wing_play_442). Depth, set pieces and the "
            "tactics page then default to these instead of the top-ranked tactic."
        ),
    )
    parser.add_argument(
        "--knowledge-db",
        type=Path,
        default=DEFAULT_KNOWLEDGE_DATABASE,
        help=(
            "player-knowledge database that scouting captures are recorded into "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--out-of-date-months",
        type=int,
        default=DEFAULT_OUT_OF_DATE_MONTHS,
        help=(
            "game months after which a remembered attribute or fact is labelled "
            "out of date on the Scouting pages (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--no-record-knowledge",
        action="store_true",
        help="do not record scouting captures into the player-knowledge database",
    )
    parser.add_argument(
        "--match-db",
        type=Path,
        default=DEFAULT_MATCH_DATABASE,
        help="match-history database the Matches page reads and records into (default: %(default)s)",
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
        # Fail at startup, in plain text, rather than the first page load
        # hitting an unreadable capture mid-request.
        try:
            SnapshotStore(args.snapshot_db).initialize()
        except SnapshotStoreError as exc:
            raise SystemExit(str(exc)) from exc
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


def _capture_save_key(path: Path) -> str | None:
    """Which save the current capture belongs to; None when it cannot say.

    Verdicts are stored per save so two playthroughs never share one. A
    missing or malformed capture means no verdicts this session rather than
    a server that refuses to start.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            return None
        return default_save_key(document)
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ranking_workers < 1:
        raise SystemExit("--ranking-workers must be at least 1")
    if args.out_of_date_months < 0:
        raise SystemExit("--out-of-date-months cannot be negative")
    try:
        pinned_tactics = parse_pinned_tactics(args.my_tactics)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
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
        # These immutable tactic views are shared by every future snapshot.
        # Preparing them here keeps the first user-visible ranking comparable
        # with later warm refreshes; workers receive the completed catalogue.
        for tactic_key in MVP_CATALOGUE.tactics:
            MVP_CATALOGUE.for_tactic(tactic_key)
        ranking_executor.warm()
    except (OSError, RuntimeError) as exc:
        # The server remains usable on constrained systems: ranking falls
        # back to the existing sequential implementation rather than failing
        # to start its read-only UI.
        print(f"Could not start tactic-ranking workers; using sequential ranking: {exc}")
        ranking_executor.shutdown(wait=False)
        ranking_executor = None
    # The store is always configured: recording captures can be switched off,
    # but the manager's verdicts are his own and need somewhere to live.
    knowledge_store = PlayerKnowledgeStore(args.knowledge_db)
    knowledge_recorder = None
    if not args.no_record_knowledge:

        def knowledge_recorder() -> RecordResult:
            return record_capture_file(knowledge_store, refresh_path)

    match_store = MatchHistoryStore(args.match_db)
    league_path = args.league_json or (DEFAULT_LEAGUE_CAPTURE if args.direct_live else None)
    server = SquadWebServer(
        (args.host, args.port), provider,
        scouting_provider=scouting_json_provider(refresh_path, allow_missing=True),
        scouting_refresh=_scouting_refresh_command(refresh_path),
        scouting_capture_path=refresh_path,
        cache_ttl_seconds=args.cache_ttl_seconds,
        ranking_executor=ranking_executor,
        pinned_tactics=pinned_tactics,
        knowledge_recorder=knowledge_recorder,
        knowledge_store=knowledge_store,
        knowledge_save_key=_capture_save_key(refresh_path),
        out_of_date_months=args.out_of_date_months,
        match_store=match_store,
        match_capture=lambda: capture_and_record(match_store),
        league_provider=league_json_provider(league_path, allow_missing=args.direct_live) if league_path else None,
        league_store=LeagueHistoryStore(args.league_db) if league_path else None,
        # Reading FM needs FM: only a live server offers the League page's read button.
        league_capture=league_capture_command(league_path) if args.direct_live else None,
    )
    if knowledge_recorder is not None and refresh_path.exists():
        # Catches captures made by running the tool directly since last time.
        server.record_knowledge()
        if server.knowledge_note is not None:
            print(server.knowledge_note[0])
    if DEFAULT_MATCH_CAPTURE.exists():
        # Catches a capture made with `fm-matches capture` or the tool directly.
        try:
            print(f"Match history: {record_match_capture(match_store, DEFAULT_MATCH_CAPTURE).summary()}")
        except Exception as exc:  # noqa: BLE001 - the Matches page still works without it
            print(f"Match history: the last capture was not recorded: {exc}", file=sys.stderr)
    print(f"FM Analytics web view listening on http://{args.host}:{args.port}")
    threading.Thread(target=server.warm_scouting_rankings, daemon=True, name="scouting-warm").start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _default_fixture_path() -> str:
    return str(
        Path(__file__).resolve().parents[1] / "fixtures" / "sample-game.json"
    )


def _default_scouting_path():
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
