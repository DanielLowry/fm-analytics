"""The web server's side of the match history: which save, reading and writing it.

Kept apart from `server.py`'s squad caching. Reading the history is cheap (a
season is tens of matches), so nothing here is cached.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.match_analysis import ReviewFilters
from fm_analytics.analytics.match_interventions import evaluate_intervention, propose_intervention
from fm_analytics.analytics.player_form import FormLookup
from fm_analytics.persistence.match_history import MatchHistory, MatchHistoryError, MatchHistoryStore
from fm_analytics.reporting import build_match_diagnostics, build_match_review, squad_form


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

    def recent_form(self, game, squad) -> FormLookup | None:
        """Recent form for the recommendation, from this save's match history.

        None when there is no usable history. A history that cannot be read
        leaves form out rather than stopping the recommendation.
        """
        if self.match_store is None:
            return None
        try:
            return squad_form(self.match_history(), game, squad)
        except MatchHistoryError as exc:
            print(f"Recent form left out: {exc}", file=sys.stderr)
            return None

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
            self.forget_recommendations()
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
        self.forget_recommendations()  # a match's tactic decides which job its ratings count for

    def record_penalty_foul(self, match_key: str, minute: int, added_time: int, player_short_id: int | None) -> None:
        """The manager's record of who gave a penalty away. Local database only; never FM."""
        key = self._match_key()
        if key is None:
            raise ValueError("No matches are recorded yet.")
        self.match_store.record_penalty_foul(key, match_key, minute, added_time, player_short_id)

    def confirm_role_code(self, code: int, role_key: str) -> None:
        if self.match_store is None:
            raise ValueError("Match history is switched off.")
        self.match_store.confirm_role_code(code, role_key)
        self.forget_recommendations()

    def start_match_intervention(self, finding_key: str, note: str = "") -> None:
        """Freeze a current season-wide diagnostic and its baseline."""
        history = self.match_history()
        if history is None or self.match_store is None:
            raise ValueError("No matches are recorded yet.")
        review = build_match_review(
            history,
            filters=ReviewFilters(grouping="table", competitions="competitive"),
            catalogue=MVP_CATALOGUE,
        )
        diagnostics = build_match_diagnostics(review)
        proposal = propose_intervention(review, diagnostics, finding_key, manager_note=note)
        self.match_store.start_intervention(history.save_key, proposal)

    def finish_match_intervention(
        self,
        intervention_id: int,
        *,
        outcome: str,
        note: str = "",
    ) -> None:
        key = self._match_key()
        if key is None or self.match_store is None:
            raise ValueError("No matches are recorded yet.")
        if outcome != "stopped":
            history = self.match_history()
            review = build_match_review(
                history,
                filters=ReviewFilters(grouping="table", competitions="competitive"),
                catalogue=MVP_CATALOGUE,
            )
            active = next(
                (item for item in history.interventions if item.active and item.id == intervention_id),
                None,
            )
            if active is None:
                raise ValueError("that active intervention is not recorded for this save")
            if not evaluate_intervention(review, active).review_due:
                raise ValueError("collect all five eligible exposures before recording the result")
        self.match_store.finish_intervention(
            key, intervention_id, outcome=outcome, note=note
        )
