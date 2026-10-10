"""The web server's side of experiments: the store, and storing only when asked.

Mixed into `SquadWebServer` beside `MatchHistoryState`. Nothing here runs on
its own: a match is stored only when the manager presses a button, and
reading FM for it writes `data/experiment-capture.json`, never the match
history's capture.
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Sequence

from fm_analytics.domain.experiments import MatchLabel, MatchGroup, StoredMatch
from fm_analytics.experiment_ingest import DEFAULT_EXPERIMENTS, store_from_fm, store_from_history
from fm_analytics.persistence.experiments import ExperimentStore


def add_experiment_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--experiments-db",
        type=Path,
        default=DEFAULT_EXPERIMENTS,
        help="the matches you choose to store for experiments (default: %(default)s)",
    )


def experiment_options(args: argparse.Namespace) -> dict:
    """`SquadWebServer`'s experiment arguments: none in read-only mode; reading FM only when live."""
    return {
        "experiment_store": ExperimentStore(args.experiments_db) if not args.read_only else None,
        "experiments_read_fm": bool(args.direct_live) and not args.read_only,
    }


class ExperimentState:
    def setup_experiments(self, store: ExperimentStore | None, *, reads_fm: bool) -> None:
        self.experiment_store = store
        # Whether "store the match you've just played" may read FM (a live server only).
        self.experiments_read_fm = reads_fm and store is not None
        # (message, succeeded) from the latest action, shown on the Experiments page.
        self.experiment_note: tuple[str, bool] | None = None
        self._experiment_lock = threading.Lock()

    def _experiments(self) -> ExperimentStore:
        if self.experiment_store is None:
            raise ValueError("Experiments are switched off (read-only comparison mode).")
        return self.experiment_store

    def stored_matches(self) -> tuple[StoredMatch, ...]:
        return self.experiment_store.matches() if self.experiment_store is not None else ()

    def experiment_groups(self) -> tuple[MatchGroup, ...]:
        return self.experiment_store.groups() if self.experiment_store is not None else ()

    def store_played_match(self, label: MatchLabel, groups: Sequence[str]) -> None:
        """Read FM (read-only) and store the match just played. Never raises: the outcome is the note."""
        if not self.experiments_read_fm:
            self.experiment_note = ("Reading FM is only available when fm-web runs with --direct-live.", False)
            return
        if not self._experiment_lock.acquire(blocking=False):
            self.experiment_note = ("A match is already being read.", False)
            return
        try:
            stored, match = store_from_fm(self._experiments(), label, groups=groups)
            self.experiment_note = (
                f"{'Stored' if stored.added else 'Already stored'} as #{stored.match_id}: {match.date:%d %b %Y} "
                f"{match.home.name} {match.home_goals}–{match.away_goals} {match.away.name}.", True,
            )
        except Exception as exc:  # noqa: BLE001 - reported on the page, never a crash
            self.experiment_note = (str(exc), False)
            print(f"The match was not stored: {exc}", file=sys.stderr)
        finally:
            self._experiment_lock.release()

    def store_history_match(self, match_key: str, label: MatchLabel, groups: Sequence[str]) -> int:
        history = self.match_history()  # type: ignore[attr-defined]
        if history is None:
            raise ValueError("No matches are recorded yet.")
        stored = store_from_history(self._experiments(), history, match_key, label, groups=groups)
        self.experiment_note = (
            f"{'Stored' if stored.added else 'Already stored'} as #{stored.match_id}.", True
        )
        return stored.match_id

    def create_experiment_group(self, name: str, note: str = "") -> None:
        self._experiments().create_group(name, note)

    def set_experiment_membership(self, group: str, match_ids: Sequence[int], *, member: bool) -> None:
        self._experiments().set_membership(group, match_ids, member=member)

    def relabel_stored_match(self, match_id: int, label: MatchLabel, *, withdrawn: bool) -> None:
        self._experiments().relabel(match_id, label, withdrawn=withdrawn)

    def delete_stored_matches(self, match_ids: Sequence[int]) -> None:
        self._experiments().delete(match_ids)
        numbers = ", ".join(f"#{match_id}" for match_id in match_ids)
        self.experiment_note = (f"Deleted {numbers} for good.", True)

    def edit_experiment_group(self, name: str, new_name: str, note: str) -> None:
        self._experiments().edit_group(name, new_name, note)

    def delete_experiment_group(self, name: str) -> None:
        self._experiments().delete_group(name)
        self.experiment_note = (f"Deleted the group {name!r}; its matches are still stored.", True)
