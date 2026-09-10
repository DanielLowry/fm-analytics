from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

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
        source: FmDataSource = self.server.source  # type: ignore[attr-defined]
        if path == "/health":
            self._health(source)
        elif path == "/game":
            self._resource(source.get_game, lambda value: value.to_dict())
        elif path == "/squad":
            self._resource(source.get_squad, lambda value: value.to_dict())
        else:
            self._send({"error": "not found"}, HTTPStatus.NOT_FOUND)

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
