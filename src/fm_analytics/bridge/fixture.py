from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from fm_analytics.domain import GameState, SourceHealth, Squad


class FixtureDataSource:
    """Read the deterministic combined game/squad fixture."""

    name = "fixture"

    def __init__(self, fixture_path: str | Path | None = None):
        self.fixture_path = Path(fixture_path) if fixture_path else None

    def get_health(self) -> SourceHealth:
        return SourceHealth(status="ready", source=self.name)

    def get_game(self) -> GameState:
        return self._read_fixture()[0]

    def get_squad(self) -> Squad:
        return self._read_fixture()[1]

    def _read_fixture(self) -> tuple[GameState, Squad]:
        if self.fixture_path is None:
            raw_text = (
                files("fm_analytics.fixtures") / "sample-game.json"
            ).read_text(encoding="utf-8")
        else:
            raw_text = self.fixture_path.read_text(encoding="utf-8")
        payload: Any = json.loads(raw_text)
        if not isinstance(payload, dict):
            raise ValueError("fixture must contain a JSON object")
        return GameState.from_dict(payload["game"]), Squad.from_dict(payload["squad"])
