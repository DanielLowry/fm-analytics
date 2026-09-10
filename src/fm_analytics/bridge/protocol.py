from __future__ import annotations

from typing import Protocol

from fm_analytics.domain import GameState, SourceHealth, Squad


class FmDataSource(Protocol):
    """The small source seam used by the HTTP bridge."""

    name: str

    def get_health(self) -> SourceHealth:
        ...

    def get_game(self) -> GameState:
        ...

    def get_squad(self) -> Squad:
        ...
