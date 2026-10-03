"""Coherent capture loading and bounded league report caching."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from fm_analytics.analytics.league_comparison import LeagueReport
from fm_analytics.domain.leagues import LeagueCapture
from fm_analytics.reporting import RecommendationPolicy, build_league_comparison


class LeagueOutOfDate(ValueError):
    """The league was read on an earlier game date than the squad now shown."""

    def __init__(self, captured, current):
        super().__init__(f"The league was read at game date {captured.isoformat()}, but FM is now at "
                         f"{current.isoformat()}. Read it again to compare today's squads.")


@dataclass(frozen=True)
class LeagueView:
    report: LeagueReport | None = None
    status: str = "ready"
    error: str = ""


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_TOOL = PROJECT_ROOT / "tools" / "fm20_league_capture.py"
CAPTURE_TIMEOUT_SECONDS = 180
DEFAULT_CAPTURE = PROJECT_ROOT / "data" / "league-capture.json"


def league_json_provider(path: str | Path, *, allow_missing: bool = False):
    path = Path(path)
    loaded = []

    def provide():
        # Read and parse one complete file revision; never combine club rows
        # from successive captures. A malformed replacement remains an error.
        if allow_missing and not path.exists():
            return None  # nothing read from FM yet: the page offers to read it
        payload = path.read_bytes()
        if not loaded or loaded[0][0] != payload:
            captured = LeagueCapture.from_document(json.loads(payload))
            loaded[:] = [(payload, captured)]
            return captured
        return loaded[0][1]

    return provide


def league_capture_command(output: str | Path):
    """Read the league from FM into `output` in its own process, read-only.

    As with the Matches and Scouting buttons, a problem reading FM cannot take
    the web server down with it. The tool replaces the file whole.
    """
    output = Path(output)

    def capture() -> str:
        command = ["uv", "run", "--extra", "research", "python", str(CAPTURE_TOOL), "--output", str(output)]
        try:
            result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True,
                                    timeout=CAPTURE_TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Reading the league from FM timed out.") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown failure").strip()
            raise RuntimeError(detail[-2_000:])
        summary = json.loads(result.stdout)
        return (f"Read {summary['clubs']} clubs and {summary['players']} players from FM "
                f"at game date {summary['gameDate']}.")

    return capture


class LeagueState:
    def setup_league(self, provider=None, store=None, capture=None):
        self.league_provider = provider
        self.league_store = store
        # Reads FM (read-only) into the provider's file; see `league_capture_command`.
        self.league_capture = capture
        # (message, succeeded) from the latest read, shown on the League page.
        self.league_capture_note: tuple[str, bool] | None = None
        self._league_capture_lock = threading.Lock()
        self._league_lock = threading.Lock()
        self._league_compute_lock = threading.Lock()
        self._league_reports = OrderedDict()
        self._league_errors = OrderedDict()
        self._league_pending = None
        self._league_active = None
        self._league_thread = None

    def capture_league_from_fm(self) -> None:
        """Read the league from FM. Never raises: the outcome is the note."""
        if self.league_capture is None:
            self.league_capture_note = ("Reading the league from FM is not configured.", False)
            return
        if not self._league_capture_lock.acquire(blocking=False):
            self.league_capture_note = ("The league is already being read.", False)
            return
        try:
            self.league_capture_note = (self.league_capture(), True)
        except Exception as exc:  # noqa: BLE001 - reported on the page, never a crash
            self.league_capture_note = (f"The league could not be read from FM: {exc}", False)
            print(f"League was not read: {exc}", file=sys.stderr)
        finally:
            self._league_capture_lock.release()

    def _league_capture(self):
        if self.league_provider is None:
            return None
        capture = self.league_provider()
        if capture is None:
            return None
        game, _squad = self.read()
        if capture.game.game_date != game.game_date and self.league_capture is not None:
            raise LeagueOutOfDate(capture.game.game_date, game.game_date)
        if (capture.game.game_date != game.game_date or
            capture.game.human_manager.id != game.human_manager.id or
            (capture.game.controlled_club.id if capture.game.controlled_club else None) !=
            (game.controlled_club.id if game.controlled_club else None)):
            raise ValueError("League and squad captures belong to different dates, managers, or clubs")
        owned = next((roster.squad for roster in capture.teams if game.controlled_club and
                      roster.squad.club.id == game.controlled_club.id), None)
        if owned is not None and owned.players != _squad.players:
            raise ValueError("League and squad captures contain different observations for your first team")
        return capture

    def league_report(self, tactic_key: str | None = None):
        """Blocking reporting entry point for scripts and benchmarks."""
        capture = self._league_capture()
        if capture is None:
            return None
        key = (capture.content_hash(), tactic_key)
        return self._build_league_report(capture, key)

    def _build_league_report(self, capture, key):
        with self._league_lock:
            if key in self._league_reports:
                self._league_reports.move_to_end(key)
                return self._league_reports[key]
        with self._league_compute_lock:
            with self._league_lock:
                if key in self._league_reports:
                    return self._league_reports[key]
            if self.league_store is not None:
                self.league_store.record(capture)
            report = build_league_comparison(capture, policy=RecommendationPolicy(),
                                            tactic_keys=(key[1],) if key[1] else None)
            with self._league_lock:
                self._league_reports[key] = report
                while len(self._league_reports) > 2:
                    self._league_reports.popitem(last=False)
            return report

    def league_view(self, tactic_key=None, *, retry=False):
        """Queue a coherent revision without blocking an HTTP request.

        There is one computing job and at most one pending request. Repeated
        polling joins that work; rapid changes replace the pending request.
        An old report is usable only within this save and tactic scope.
        """
        capture = self._league_capture()
        if capture is None:
            return LeagueView()
        key = (capture.content_hash(), tactic_key)
        with self._league_lock:
            if key in self._league_reports:
                self._league_reports.move_to_end(key)
                return LeagueView(self._league_reports[key])
            previous = next((report for old_key, report in reversed(self._league_reports.items())
                             if old_key[1] == tactic_key and report.capture.save_key == capture.save_key
                             and report.capture.game.human_manager.id == capture.game.human_manager.id
                             and report.capture.game.controlled_club == capture.game.controlled_club
                             and report.capture.game.game_date <= capture.game.game_date), None)
            if retry:
                self._league_errors.pop(key, None)
            if key in self._league_errors:
                return LeagueView(previous, "error", self._league_errors[key])
            if key != self._league_active:
                self._league_pending = (capture, key)
            if self._league_thread is None:
                self._league_thread = threading.Thread(target=self._league_worker, daemon=True,
                                                      name="league-comparison")
                self._league_thread.start()
            return LeagueView(previous, "loading")

    def _league_worker(self):
        while True:
            with self._league_lock:
                pending = self._league_pending
                if pending is None:
                    self._league_active = self._league_thread = None
                    return
                self._league_pending = None
                capture, key = pending
                self._league_active = key
            try:
                self._build_league_report(capture, key)
            except Exception as exc:
                # Publish the failure coherently rather than leaving a polling
                # page permanently loading. A retry is explicit.
                with self._league_lock:
                    self._league_errors[key] = str(exc)
                    while len(self._league_errors) > 2:
                        self._league_errors.popitem(last=False)
