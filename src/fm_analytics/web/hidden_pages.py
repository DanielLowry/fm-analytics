"""The League page's hidden view, /league/hidden: is it the squad, or is it us? HIDDEN DATA.

Renders `hidden_reporting.build_hidden_strength_report`, worked out in the
background by `HiddenState`, over the latest hidden-attribute read, the match
history and the other league clubs' recorded matches.
"""
from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.hidden_reporting import build_hidden_strength_export, hidden_seasons
from fm_analytics.web.attribute_export import profile_copy_control
from fm_analytics.web.hidden_render import (
    PATH,
    empty_page,
    formations_section,
    hero,
    line_ups_section,
    method_section,
    our_matches_section,
    results_section,
    tactics_section,
)
from fm_analytics.web.rendering import _error_page, _layout, _query_first

TITLE = "League · hidden attributes"


class HiddenPagesMixin:
    def _post_hidden_capture(self) -> None:
        """Read hidden attributes from FM (read-only), then go back to the page."""
        self.server.capture_hidden_from_fm()  # type: ignore[attr-defined]
        self._redirect(PATH)  # type: ignore[attr-defined]

    def _hidden_page(self, path: str, query: dict[str, list[str]]) -> None:
        server = self.server  # type: ignore[attr-defined]
        tactic = _query_first(query, "tactic") or ""
        season_text = _query_first(query, "season") or ""
        if tactic and tactic not in MVP_CATALOGUE.tactics:
            self._send(_error_page(TITLE, "Unknown tactic", PATH), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        if season_text and not season_text.isdigit():
            self._send(_error_page(TITLE, "Unknown season", PATH), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        try:
            capture, history, club_matches = server.hidden_inputs()
        except (OSError, RuntimeError, ValueError, KeyError, sqlite3.Error) as exc:
            self._send(_error_page(TITLE, f"The hidden-attribute read or the match history could not be read: {exc}",  # type: ignore[attr-defined]
                                   PATH), HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if capture is None:
            self._send(_layout(TITLE, PATH, empty_page(  # type: ignore[attr-defined]
                "Read hidden attributes from FM to score every league club's squad and every XI in this season's "
                "matches from what its players are really like.", server)))
            return
        if history is None:
            self._send(_layout(TITLE, PATH, empty_page(  # type: ignore[attr-defined]
                "No matches are recorded yet. Use <strong>Read matches from FM</strong> on the "
                "<a href='/matches'>Matches page</a> first: it reads your results and every league club's matches.",
                server)))
            return
        if capture.club.id != history.club.id:
            self._send(_layout(TITLE, PATH, empty_page(  # type: ignore[attr-defined]
                f"The hidden-attribute read is of {capture.club.name}, but the match history is "
                f"{history.club.name}'s. Read hidden attributes from FM again.", server)), HTTPStatus.CONFLICT)
            return
        seasons = hidden_seasons(history)
        season = int(season_text) if season_text else None
        if season is not None and season not in seasons:
            self._send(_error_page(TITLE, f"No competitive match of ours is recorded in season {season}", PATH),  # type: ignore[attr-defined]
                       HTTPStatus.NOT_FOUND)
            return
        view = server.hidden_view(season, tactic or None, retry=_query_first(query, "retry") == "1")
        if view.status == "loading":
            self._send(_layout(TITLE, PATH, empty_page(  # type: ignore[attr-defined]
                "<span data-league-pending role='status'>Working out every XI in the league from hidden attributes. "
                "This takes a few seconds, and the page updates by itself.</span>", server)), HTTPStatus.ACCEPTED)
            return
        if view.status == "error":
            retry = f"{PATH}?" + "&".join(f"{key}={value}" for key, value in
                                          (("season", season_text), ("tactic", tactic), ("retry", "1")) if value)
            self._send(_layout(TITLE, PATH, empty_page(  # type: ignore[attr-defined]
                f"Working the tables out failed: {view.error} <a href='{retry}'>Try again</a>.", server)),
                HTTPStatus.SERVICE_UNAVAILABLE)
            return
        report = view.report
        if report is None:
            self._send(_layout(TITLE, PATH, empty_page(  # type: ignore[attr-defined]
                "No competitive match of ours is recorded yet.", server)))
            return
        copy = profile_copy_control(json.dumps(build_hidden_strength_export(report), indent=1, ensure_ascii=False),
                                    label="Copy everything as JSON", success="Every table and XI copied as JSON!")
        notice = ""
        if not club_matches:
            notice = ("<p class='fm-workspace-panel'>Only our own matches are recorded, so expected points and the "
                      "other clubs' formations are missing. <strong>Read matches from FM</strong> on the "
                      "<a href='/matches'>Matches page</a> adds every league club's matches.</p>")
        body = (hero(report, server, seasons=seasons, catalogue=MVP_CATALOGUE, tactic=tactic, copy_control=copy)
                + notice + our_matches_section(report) + tactics_section(report) + formations_section(report)
                + results_section(report) + line_ups_section(report) + method_section(report))
        self._send(_layout(TITLE, PATH, body, wide=True))  # type: ignore[attr-defined]
