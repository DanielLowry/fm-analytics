"""Bounded POST actions and form parsing for the web view."""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from fm_analytics.web.rendering import _error_page


class WebActionsMixin:
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health/refresh":
            started = self.server.request_health_check()  # type: ignore[attr-defined]
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/?health=" + ("started" if started else "running"))
            self.end_headers()
            return
        if parsed.path == "/refresh":
            started = self.server.request_refresh()  # type: ignore[attr-defined]
            back_to_league = self._read_form().get("return_to", [""])[0] == "/league"
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/league" if back_to_league else "/?refresh=" + ("started" if started else "running"))
            self.end_headers()
            return
        if self.server.read_only:  # type: ignore[attr-defined]
            self._send(
                _error_page("Read-only comparison", "Recording and editing are disabled in read-only comparison mode.", "/tactics"),
                HTTPStatus.FORBIDDEN,
            )
            return
        if parsed.path == "/scouting/verdict":
            self._post_scouting_verdict()
            return
        match_posts = {
            "/matches/capture": self._post_match_capture,
            "/matches/note": self._post_match_note,
            "/matches/penalty": self._post_penalty_foul,
            "/matches/role-code": self._post_role_code,
            "/matches/intervention/start": self._post_intervention_start,
            "/matches/intervention/finish": self._post_intervention_finish,
        }
        if parsed.path in match_posts:
            match_posts[parsed.path]()
            return
        if parsed.path == "/league/capture":
            self._post_league_capture()  # type: ignore[attr-defined]
            return
        if parsed.path != "/scouting/refresh":
            self._send(
                _error_page("Not found", "No such action.", parsed.path),
                HTTPStatus.NOT_FOUND,
            )
            return
        form = self._read_form()
        allow_rebuild = form.get("allow_rebuild", [""])[0] == "1"
        return_view = form.get("return_view", [""])[0]
        if return_view not in {"all", "scouted"}:
            return_view = ""
        try:
            started = self.server.request_scouting_refresh(allow_rebuild=allow_rebuild)  # type: ignore[attr-defined]
        except (OSError, RuntimeError, ValueError) as exc:
            self._send(
                _error_page("Scouting refresh", str(exc), "/scouting"),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        refresh_kind = "started" if started else "running"
        self.send_header(
            "Location",
            "/scouting?"
            + (f"view={return_view}&" if return_view else "")
            + "refreshed=" + refresh_kind,
        )
        self.end_headers()

    def _read_form(self) -> dict[str, list[str]]:
        """Parse a bounded form body; an unreadable body is simply no consent."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if not 0 < length <= 4096:
            return {}
        return parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
