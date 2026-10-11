"""The web server's side of the League page's hidden view: reading FM, and working the view out once.

HIDDEN DATA: this serves `hidden_reporting.build_hidden_strength_report` and nothing
else. The capture it reads (`data/hidden-capture.json`) holds the real values
FM keeps for every player, so no other page or computation is given it.

Working the view out takes several seconds (every XI fielded in a league
season), so it runs in one background thread, as the League comparison does,
and is kept until the read, the match history or the choices change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from fm_analytics.analytics.hidden_strength import HiddenStrength
from fm_analytics.domain.hidden import HiddenCapture
from fm_analytics.hidden_reporting import build_hidden_strength_report

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_TOOL = PROJECT_ROOT / "tools" / "fm20_hidden_capture.py"
CAPTURE_TIMEOUT_SECONDS = 120
DEFAULT_CAPTURE = PROJECT_ROOT / "data" / "hidden-capture.json"


def hidden_json_provider(path: str | Path):
    """The latest hidden-attribute read, parsed once per file revision; None before the first."""
    path = Path(path)
    loaded: list[tuple[bytes, HiddenCapture]] = []

    def provide() -> HiddenCapture | None:
        if not path.exists():
            return None
        payload = path.read_bytes()
        if not loaded or loaded[0][0] != payload:
            loaded[:] = [(payload, HiddenCapture.from_document(json.loads(payload)))]
        return loaded[0][1]

    return provide


def hidden_capture_command(output: str | Path, match_db: str | Path):
    """Read every league player's hidden attributes into `output`, in its own process, read-only."""
    output, match_db = Path(output), Path(match_db)

    def capture() -> str:
        command = ["uv", "run", "--extra", "research", "python", str(CAPTURE_TOOL),
                   "--output", str(output), "--match-db", str(match_db)]
        try:
            result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True,
                                    timeout=CAPTURE_TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Reading hidden attributes from FM timed out.") from exc
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "unknown failure").strip()[-2_000:])
        summary = json.loads(result.stdout)
        return (f"Read {summary['players']} players at {summary['clubs']} clubs from FM "
                f"at game date {summary['gameDate']}.")

    return capture


def add_hidden_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hidden-json", type=Path,
                        help="hidden-attribute read for the League page's hidden view; with --direct-live it "
                             "defaults to data/hidden-capture.json, which that page's read button writes")


def hidden_options(args: argparse.Namespace) -> dict:
    """`SquadWebServer`'s hidden-view arguments: the read to show, and reading FM only when live."""
    live = bool(args.direct_live) and not args.read_only
    path = args.hidden_json or (DEFAULT_CAPTURE if live else None)
    return {"hidden_provider": hidden_json_provider(path) if path else None,
            "hidden_capture": hidden_capture_command(path, args.match_db) if live else None}


@dataclass(frozen=True)
class HiddenView:
    report: HiddenStrength | None = None
    status: str = "ready"  # "ready", "loading" or "error"
    error: str = ""


class HiddenState:
    """Mixed into `SquadWebServer`; `setup_hidden` must run in its constructor."""

    def setup_hidden(self, provider=None, capture=None) -> None:
        self.hidden_provider = provider
        self.hidden_capture = capture
        # (message, succeeded) from the latest read, shown on the page.
        self.hidden_capture_note: tuple[str, bool] | None = None
        self._hidden_capture_lock = threading.Lock()
        self._hidden_lock = threading.Lock()
        self._hidden_reports: OrderedDict[str, HiddenStrength | None] = OrderedDict()
        self._hidden_errors: dict[str, str] = {}
        self._hidden_pending: tuple[str, tuple] | None = None
        self._hidden_thread: threading.Thread | None = None

    def capture_hidden_from_fm(self) -> None:
        """Read hidden attributes from FM. Never raises: the outcome is the note."""
        if self.hidden_capture is None:
            self.hidden_capture_note = ("Reading hidden attributes from FM is not configured.", False)
            return
        if not self._hidden_capture_lock.acquire(blocking=False):
            self.hidden_capture_note = ("Hidden attributes are already being read.", False)
            return
        try:
            self.hidden_capture_note = (self.hidden_capture(), True)
        except Exception as exc:  # noqa: BLE001 - reported on the page, never a crash
            self.hidden_capture_note = (f"Hidden attributes could not be read from FM: {exc}", False)
            print(f"Hidden attributes were not read: {exc}", file=sys.stderr)
        finally:
            self._hidden_capture_lock.release()

    def hidden_inputs(self):
        """(capture, history, club matches): None for whichever is not there yet."""
        capture = self.hidden_provider() if self.hidden_provider is not None else None
        history = self.match_history()
        club_matches = self.club_matches() if history is not None else ()
        return capture, history, club_matches

    def hidden_view(self, season: int | None, tactic: str | None, *, retry: bool = False) -> HiddenView:
        """The view for these choices if worked out, else start working it out (one at a time)."""
        capture, history, club_matches = self.hidden_inputs()
        if capture is None or history is None:
            return HiddenView()
        key = _key(capture, history, club_matches, season, tactic)
        with self._hidden_lock:
            if key in self._hidden_reports:
                self._hidden_reports.move_to_end(key)
                return HiddenView(self._hidden_reports[key])
            if retry:
                self._hidden_errors.pop(key, None)
            if key in self._hidden_errors:
                return HiddenView(None, "error", self._hidden_errors[key])
            self._hidden_pending = (key, (capture, history, club_matches, season, tactic))
            if self._hidden_thread is None:
                self._hidden_thread = threading.Thread(target=self._hidden_worker, daemon=True, name="hidden-strength")
                self._hidden_thread.start()
        return HiddenView(None, "loading")

    def _hidden_worker(self) -> None:
        while True:
            with self._hidden_lock:
                if self._hidden_pending is None:
                    self._hidden_thread = None
                    return
                key, (capture, history, club_matches, season, tactic) = self._hidden_pending
                self._hidden_pending = None
            try:
                report = build_hidden_strength_report(capture, history, club_matches, season=season, extra_tactic=tactic)
            except Exception as exc:  # noqa: BLE001 - shown on the page with a retry
                with self._hidden_lock:
                    self._hidden_errors[key] = str(exc)
                print(f"Hidden view failed: {exc}", file=sys.stderr)
                continue
            with self._hidden_lock:
                self._hidden_reports[key] = report
                while len(self._hidden_reports) > 4:
                    self._hidden_reports.popitem(last=False)


def _key(capture: HiddenCapture, history, club_matches, season, tactic) -> str:
    """Everything the view depends on: the read, every match and note of ours, theirs, and the choices."""
    digest = hashlib.sha256()
    digest.update(capture.content_hash().encode())
    for match in history.matches:
        note = history.notes.get(match.key)
        digest.update(f"{match.key}|{match.home_goals}|{match.away_goals}|{match.detail is not None}|"
                      f"{getattr(note, 'tactic_key', '')}\n".encode())
    digest.update(json.dumps(sorted(history.role_codes.items()) if hasattr(history.role_codes, "items")
                             else str(history.role_codes), default=str).encode())
    digest.update(f"{len(club_matches)}|{club_matches[-1].key if club_matches else ''}|{season}|{tactic}".encode())
    return digest.hexdigest()
