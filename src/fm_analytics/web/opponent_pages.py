"""The Opponent page: the report on our next opponent, or on any club in the league.

Read-only: it renders `reporting.build_opponent_report` over the match
history, the other league clubs' matches recorded with it, FM's fixture list
and the latest league read. Reading FM happens on the Matches page.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from http import HTTPStatus

from fm_analytics.analytics.opponent_report import DEFAULT_WINDOW, WINDOWS
from fm_analytics.reporting import build_opponent_export, build_opponent_report, opponent_choices
from fm_analytics.web.attribute_export import profile_copy_control
from fm_analytics.web.opponent_render import opponent_body, opponent_empty
from fm_analytics.web.rendering import _error_page, _layout, _query_first, _query_number

TITLE = "Opponent report"


class OpponentPagesMixin:
    def _opponent_league(self):
        """The latest league read, for their players' visible attributes; None when there is none or it cannot be read."""
        provider = getattr(self.server, "league_provider", None)  # type: ignore[attr-defined]
        if provider is None:
            return None
        try:
            return provider()
        except (OSError, ValueError, KeyError) as exc:
            print(f"Opponent report without attributes: {exc}", file=sys.stderr)
            return None

    def _opponent_page(self, path: str, query: dict[str, list[str]]) -> None:
        server = self.server  # type: ignore[attr-defined]
        try:
            window = _query_number(query, "window", integer=True) or DEFAULT_WINDOW
            if window not in WINDOWS:
                raise ValueError(f"window must be one of {', '.join(map(str, WINDOWS))}")
        except ValueError as exc:
            self._send(_error_page(TITLE, str(exc), path), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        try:
            history = server.match_history()
            fixtures = server.match_fixtures() if history is not None else None
            club_matches = server.club_matches() if history is not None else ()
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self._send(_error_page(TITLE, f"The match history could not be read: {exc}", path),  # type: ignore[attr-defined]
                       HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if history is None:
            body = opponent_empty((), window, (
                "No matches are recorded yet. With FM running and your save loaded, use <strong>Read matches "
                "from FM</strong> on the <a href='/matches'>Matches page</a>: it reads your results, every league "
                "club's archived matches and FM's fixture list. There is nothing to do in FM."
            ))
            self._send(_layout(TITLE, path, body))  # type: ignore[attr-defined]
            return
        choices = opponent_choices(history, fixtures)
        club_id = _query_first(query, "club")
        try:
            report = build_opponent_report(
                history, club_matches, club_id=club_id, fixtures=fixtures, window=window,
                league=self._opponent_league(),
            )
        except ValueError as exc:
            self._send(_error_page(TITLE, str(exc), path), HTTPStatus.NOT_FOUND)  # type: ignore[attr-defined]
            return
        if report is None:
            reason = (
                "FM's fixture list has not been read yet: <strong>Read matches from FM</strong> on the "
                "<a href='/matches'>Matches page</a> reads it." if fixtures is None
                else "FM's fixture list has no match of ours still to play."
            )
            self._send(_layout(TITLE, path, opponent_empty(choices, window, reason + " Or pick a club.")))  # type: ignore[attr-defined]
            return
        notice = ""
        if not club_matches:
            notice = (
                "<p class='fm-workspace-panel fm-opp-notice'>Only our own matches against them are recorded. <strong>Read matches from "
                "FM</strong> on the <a href='/matches'>Matches page</a> to add every league club's matches.</p>"
            )
        copy = profile_copy_control(
            json.dumps(build_opponent_export(report), indent=2, ensure_ascii=False),
            label="Copy report to clipboard", success="Opponent report copied as JSON!",
        )
        body = notice + opponent_body(report, choices, window=window, our_club_id=history.club.id, copy_control=copy)
        self._send(_layout(TITLE, path, body, wide=True))  # type: ignore[attr-defined]
