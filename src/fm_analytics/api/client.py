from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import urlopen

from fm_analytics.domain import GameState, Squad


class BridgeError(RuntimeError):
    """The FM bridge could not be reached or returned invalid data."""


class BridgeClient:
    def __init__(self, base_url: str = "http://localhost:5072", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def get_game(self) -> GameState:
        return GameState.from_dict(self._get("game"))

    def get_squad(self) -> Squad:
        return Squad.from_dict(self._get("squad"))

    def _get(self, path: str) -> dict[str, Any]:
        url = urljoin(self.base_url, path)
        try:
            with urlopen(url, timeout=self.timeout) as response:  # noqa: S310
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BridgeError(f"could not read {url}: {exc}") from exc

        if not isinstance(payload, dict):
            raise BridgeError(f"expected an object from {url}")
        return payload

