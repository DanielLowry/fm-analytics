from __future__ import annotations

import json
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import urlopen

from fm_analytics.contract import versioned_path
from fm_analytics.domain import GameState, SourceHealth, Squad


class BridgeError(RuntimeError):
    """The FM bridge could not be reached or returned invalid data."""


class BridgeContractError(BridgeError):
    """The FM bridge response does not satisfy the selected contract."""


Decoded = TypeVar("Decoded")


class BridgeClient:
    def __init__(self, base_url: str = "http://localhost:5072", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def get_game(self) -> GameState:
        return self._decode("game", GameState.from_dict)

    def get_health(self) -> SourceHealth:
        return self._decode(
            "health",
            SourceHealth.from_dict,
            accept_error=True,
        )

    def get_squad(self) -> Squad:
        return self._decode("squad", Squad.from_dict)

    def _decode(
        self,
        resource: str,
        decoder: Callable[[dict[str, Any]], Decoded],
        *,
        accept_error: bool = False,
    ) -> Decoded:
        payload = self._get(resource, accept_error=accept_error)
        try:
            return decoder(payload)
        except KeyError as exc:
            field = exc.args[0] if exc.args else "unknown"
            raise BridgeContractError(
                f"invalid v1 {resource} response: missing required field {field!r}"
            ) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise BridgeContractError(
                f"invalid v1 {resource} response: {exc}"
            ) from exc

    def _get(self, path: str, *, accept_error: bool = False) -> dict[str, Any]:
        url = urljoin(self.base_url, versioned_path(path))
        try:
            with urlopen(url, timeout=self.timeout) as response:  # noqa: S310
                payload = json.load(response)
        except HTTPError as exc:
            if accept_error:
                payload = self._read_error_payload(exc)
                if payload is not None:
                    return payload
            detail = self._http_error_detail(exc)
            raise BridgeError(f"could not read {url}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BridgeError(f"could not read {url}: {exc}") from exc

        if not isinstance(payload, dict):
            raise BridgeError(f"expected an object from {url}")
        return payload

    @staticmethod
    def _http_error_detail(error: HTTPError) -> str:
        payload = BridgeClient._read_error_payload(error)
        if payload is None:
            return f"HTTP {error.code} {error.reason}"
        status = payload.get("status", f"HTTP {error.code}")
        message = payload.get("error") or payload.get("detail")
        return f"{status}: {message}" if message else str(status)

    @staticmethod
    def _read_error_payload(error: HTTPError) -> dict[str, Any] | None:
        try:
            payload = json.load(error)
        except (json.JSONDecodeError, UnicodeError):
            return None
        return payload if isinstance(payload, dict) else None
