"""Squad data sources for the web view, composable the same way the CLI's are.

A provider is just `() -> (GameState, Squad)`. The web server never knows or
cares which of these produced its data -- that is the seam the whole app is
built around: a manual source and an automated one are interchangeable inputs
to the same rendering code, and a source can be swapped, or layered with an
HTML overlay, without touching `server.py` at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Sequence

from fm_analytics.analytics import overlay_squad_export
from fm_analytics.api import BridgeClient
from fm_analytics.bridge import LinuxProtonDataSource
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.analytics.scouting import ScoutingCandidate
from fm_analytics.domain import GameState, SourceHealth, Squad
from fm_analytics.imports import merge_fm_squad_html_exports, parse_fm_squad_html_export
from fm_analytics.persistence import SnapshotStore

GameSquadProvider = Callable[[], tuple[GameState, Squad]]
ScoutingProvider = Callable[[], tuple[ScoutingCandidate, ...]]


def empty_scouting_provider() -> ScoutingProvider:
    """Use until a manager-visible discoverability capture has been supplied."""
    return lambda: ()


def scouting_json_provider(path: str | Path) -> ScoutingProvider:
    """Read a manager-visible scouting capture without coupling web UI to tools.

    The JSON document is either a list of candidate objects or an object with
    a ``players`` list. It is deliberately a separate feed from the owned
    squad provider: external-player discovery has its own evidence boundary.
    """
    resolved = Path(path)

    def provide() -> tuple[ScoutingCandidate, ...]:
        with resolved.open(encoding="utf-8") as scouting_file:
            raw = json.load(scouting_file)
        rows = raw.get("players") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise ValueError("scouting JSON must be a player list or an object with players")
        captured = raw.get("gameDate") if isinstance(raw, dict) else None
        candidates = tuple(
            ScoutingCandidate.from_dict({**row, "capturedGameDate": captured} if captured else row)
            for row in rows
        )
        ids = [candidate.id for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("scouting JSON contains duplicate player IDs")
        return candidates

    return provide


def fixture_provider(path: str | Path) -> GameSquadProvider:
    """Read a fixed game/squad snapshot from a JSON file, for development or demos."""
    resolved = Path(path)

    def provide() -> tuple[GameState, Squad]:
        with resolved.open(encoding="utf-8") as fixture_file:
            payload = json.load(fixture_file)
        return GameState.from_dict(payload["game"]), Squad.from_dict(payload["squad"])

    return provide


def snapshot_provider(
    db_path: str | Path, *, capture_id: int | None = None
) -> GameSquadProvider:
    """Read a previously captured, immutable observation back out of SQLite."""
    store = SnapshotStore(db_path)

    def provide() -> tuple[GameState, Squad]:
        resolved_id = capture_id if capture_id is not None else store.latest_capture_id()
        if resolved_id is None:
            raise BridgeSourceError("unavailable", f"No captures exist in '{db_path}'.")
        return store.load(resolved_id)

    return provide


class LiveGameSquadProvider:
    """A callable provider that also exposes an independent health check."""

    def __init__(self, source) -> None:
        self.source = source

    def __call__(self) -> tuple[GameState, Squad]:
        if isinstance(self.source, LinuxProtonDataSource):
            return self.source.read_snapshot()
        health = self.source.get_health()
        if not health.is_ready:
            raise BridgeSourceError(health.status, health.detail or health.status)
        return self.source.get_game(), self.source.get_squad()

    def health(self, *, force: bool = False) -> SourceHealth:
        try:
            return self.source.get_health(force=force)
        except TypeError:  # HTTP bridge and older sources have no force option.
            return self.source.get_health()


def live_provider(*, base_url: str | None = None, direct: bool = False) -> LiveGameSquadProvider:
    """Read the current squad straight from the running game or its bridge."""
    source = LinuxProtonDataSource() if direct else BridgeClient(base_url or "http://localhost:5072")

    return LiveGameSquadProvider(source)


def html_overlay_provider(
    base: GameSquadProvider,
    html_paths: Sequence[str | Path],
    *,
    expected_players: int | None = None,
) -> GameSquadProvider:
    """Layer a manual FM20 Squad HTML export onto another provider's squad.

    This is the same overlay the CLI's `--fm-html` flag applies, expressed as
    a composable wrapper instead of a flag: wrap `live_provider(...)` today
    while automated position/attribute reads are still incomplete, and drop
    the wrapper later without changing anything else once they are not.
    """
    paths = tuple(Path(path) for path in html_paths)

    def provide() -> tuple[GameState, Squad]:
        game, squad = base()
        export = merge_fm_squad_html_exports(
            tuple(
                parse_fm_squad_html_export(path.read_text(encoding="utf-8", errors="replace"))
                for path in paths
            )
        )
        if expected_players is not None:
            from fm_analytics.imports import verify_export_completeness

            verify_export_completeness(export, expected_players=expected_players)
        merged = overlay_squad_export(squad, export)
        return game, merged.squad

    return provide
