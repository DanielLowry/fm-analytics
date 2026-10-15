"""Serve only catalogued, checksum-verified original FM tactic files."""

from hashlib import sha256
from http import HTTPStatus
from importlib import resources
from urllib.parse import unquote

from fm_analytics.analytics.catalogue import MVP_CATALOGUE


def send_tactic_download(handler, path: str, _query) -> None:
    key = unquote(path.removeprefix("/tactics/").removesuffix("/download"))
    tactic = MVP_CATALOGUE.tactics.get(key)
    if tactic is None or tactic.source is None:
        handler.send_error(HTTPStatus.NOT_FOUND, "No original tactic file for this entry")
        return
    source = tactic.source
    try:
        content = resources.files("fm_analytics.analytics").joinpath(
            "data", "tactic_files", source.filename,
        ).read_bytes()
    except FileNotFoundError:
        handler.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Original tactic file is unavailable")
        return
    if sha256(content).hexdigest() != source.sha256:
        handler.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Original tactic checksum mismatch")
        return
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Disposition", f'attachment; filename="{source.filename}"')
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    try:
        handler.wfile.write(content)
    except (BrokenPipeError, ConnectionResetError):
        pass
