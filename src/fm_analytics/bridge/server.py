from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

from fm_analytics.contract import (
    CONTRACT_PATH_PREFIX,
    CONTRACT_VERSION,
    CONTRACT_VERSION_HEADER,
)

from .errors import BridgeConfigurationError, BridgeSourceError
from .fixture import FixtureDataSource
from .linux_proton import LinuxProtonDataSource
from .protocol import FmDataSource


def source_from_environment(environ: dict[str, str] | None = None) -> FmDataSource:
    settings = os.environ if environ is None else environ
    source_name = settings.get("FM_BRIDGE_SOURCE", "fixture")
    if source_name == "fixture":
        return FixtureDataSource(settings.get("FM_BRIDGE_FIXTURE"))
    if source_name == "linux-proton":
        return LinuxProtonDataSource(
            probe_path=settings.get("FM_BRIDGE_PROBE"),
            python_executable=settings.get("FM_BRIDGE_PYTHON"),
            timeout_seconds=settings.get("FM_BRIDGE_PROBE_TIMEOUT_SECONDS"),
        )
    raise BridgeConfigurationError(
        f"Unsupported FM_BRIDGE_SOURCE '{source_name}'. Use 'fixture' or 'linux-proton'."
    )


class BridgeHandler(BaseHTTPRequestHandler):
    """HTTP contract for the Python FM bridge."""

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        resource_path = self._resource_path(path)
        if resource_path is None:
            return
        source: FmDataSource = self.server.source  # type: ignore[attr-defined]
        if resource_path == "/health":
            self._health(source)
        elif resource_path == "/game":
            self._resource(source.get_game, lambda value: value.to_dict())
        elif resource_path == "/squad":
            self._resource(source.get_squad, lambda value: value.to_dict())
        else:
            self._send(
                {
                    "status": "not_found",
                    "error": f"No contract resource exists at '{path}'.",
                },
                HTTPStatus.NOT_FOUND,
            )

    def _resource_path(self, path: str) -> str | None:
        version_prefix = f"/{CONTRACT_PATH_PREFIX}"
        if path == version_prefix:
            return "/"
        if path.startswith(f"{version_prefix}/"):
            return path[len(version_prefix):]

        first_segment = path.lstrip("/").partition("/")[0]
        if first_segment.startswith("v") and first_segment[1:].isdigit():
            self._send(
                {
                    "status": "unsupported_contract_version",
                    "error": (
                        f"Contract version '{first_segment[1:]}' is not supported; "
                        f"use version '{CONTRACT_VERSION}'."
                    ),
                },
                HTTPStatus.NOT_FOUND,
            )
            return None

        # Phase 00 clients used unversioned paths. Keep them as v1 aliases while
        # consumers migrate; new clients always use the explicit prefix.
        return path

    def _health(self, source: FmDataSource) -> None:
        try:
            health = source.get_health()
            status = HTTPStatus.OK if health.is_ready else HTTPStatus.SERVICE_UNAVAILABLE
            self._send(health.to_dict(), status)
        except BridgeSourceError as exc:
            self._send(
                {"status": exc.status, "source": source.name, "detail": str(exc)},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def _resource(
        self,
        operation: Callable[[], Any],
        serializer: Callable[[Any], dict[str, Any]],
    ) -> None:
        try:
            self._send(serializer(operation()), HTTPStatus.OK)
        except BridgeSourceError as exc:
            self._send(
                {"status": exc.status, "error": str(exc)},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            self._send(
                {"status": "invalid_payload", "error": str(exc)},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def _send(self, payload: dict[str, Any], status: HTTPStatus) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(CONTRACT_VERSION_HEADER, CONTRACT_VERSION)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        return


class BridgeServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], source: FmDataSource):
        self.source = source
        super().__init__(address, BridgeHandler)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Serve the FM Analytics HTTP bridge")
    parser.add_argument("--host", help="listen host")
    parser.add_argument("--port", type=int, help="listen port")
    args = parser.parse_args(argv)
    try:
        host, port = _listen_address(args.host, args.port)
        server = BridgeServer((host, port), source_from_environment())
    except (BridgeConfigurationError, OSError) as exc:
        parser.error(str(exc))
    print(f"FM bridge listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _listen_address(host: str | None, port: int | None) -> tuple[str, int]:
    configured_url = os.environ.get("FM_BRIDGE_URL")
    if configured_url and (host is None or port is None):
        parsed = urlparse(configured_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise BridgeConfigurationError(
                "FM_BRIDGE_URL must be an absolute HTTP URL"
            )
        host = host or parsed.hostname
        port = port or parsed.port or (443 if parsed.scheme == "https" else 80)
    return (
        host or os.environ.get("FM_BRIDGE_HOST", "127.0.0.1"),
        port or int(os.environ.get("FM_BRIDGE_PORT", "5072")),
    )
