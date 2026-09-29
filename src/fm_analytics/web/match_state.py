"""The web server's side of the match history: which save, reading and writing it.

Kept apart from `server.py`'s squad caching. Reading the history is cheap (a
season is tens of matches), so nothing here is cached.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

from fm_analytics.persistence.match_history import MatchHistory, MatchHistoryStore


class MatchHistoryState:
    """Mixed into `SquadWebServer`; `setup_match_history` must run in its constructor."""

    def setup_match_history(
        self,
        store: MatchHistoryStore | None,
        capture: Callable[[], str] | None,
        save_key: str | None = None,
    ) -> None:
        self.match_store = store
        # Reads FM (read-only) and records the capture; see `match_ingest.capture_and_record`.
        self.match_capture = capture
        # None means "the save most recently recorded", which is right for one playthrough.
        self.match_save_key = save_key
        # (message, succeeded) from the latest read, shown on the Matches page.
        self.match_capture_note: tuple[str, bool] | None = None
        self._match_capture_lock = threading.Lock()

    def _match_key(self) -> str | None:
        if self.match_store is None:
            return None
        return self.match_save_key or self.match_store.latest_save_key()

    def match_history(self) -> MatchHistory | None:
        key = self._match_key()
        return self.match_store.load_history(key) if key else None

    def match_status(self) -> str:
        """One line for the Matches page: what is recorded so far."""
        if self.match_store is None:
            return "Match history is switched off."
        key = self._match_key()
        summary = next((save for save in self.match_store.saves() if save.key == key), None)
        if summary is None:
            return "No matches recorded yet."
        return (
            f"{summary.matches} matches recorded, {summary.detailed_matches} with full stats; "
            f"last read at game date {summary.last_game_date}."
        )

    def capture_matches(self) -> None:
        """Read FM and record what it shows. Never raises: the outcome is the note."""
        if self.match_capture is None:
            self.match_capture_note = ("Reading matches from FM is not configured.", False)
            return
        if not self._match_capture_lock.acquire(blocking=False):
            self.match_capture_note = ("Matches are already being read.", False)
            return
        try:
            self.match_capture_note = (self.match_capture(), True)
        except Exception as exc:  # noqa: BLE001 - reported on the page, never a crash
            self.match_capture_note = (str(exc), False)
            print(f"Matches were not read: {exc}", file=sys.stderr)
        finally:
            self._match_capture_lock.release()

    def add_match_note(
        self, match_key: str, *, tactic_key: str | None, opponent_rating: int | None, note: str
    ) -> None:
        """The manager's own notes on a match. Local database only; never FM."""
        key = self._match_key()
        if key is None:
            raise ValueError("No matches are recorded yet.")
        self.match_store.add_note(
            key, match_key, tactic_key=tactic_key, opponent_rating=opponent_rating, note=note
        )

    def confirm_role_code(self, code: int, role_key: str) -> None:
        if self.match_store is None:
            raise ValueError("Match history is switched off.")
        self.match_store.confirm_role_code(code, role_key)
