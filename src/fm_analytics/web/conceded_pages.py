"""The Conceded page: every goal and clear-cut chance against us in the Matches page's selection, broken down.

Read-only: it renders `reporting.build_conceded_review` over the matches the
Matches page's filters select (`/conceded` takes the same query).
"""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.conceded_export import conceded_json
from fm_analytics.reporting import build_conceded_review, build_match_review
from fm_analytics.web.attribute_export import profile_copy_control
from fm_analytics.web.conceded_render import conceded_body
from fm_analytics.web.match_pages import _review_filters
from fm_analytics.web.rendering import _error_page, _layout

TITLE = "Goals conceded"


class ConcededPagesMixin:
    def _conceded_page(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            filters = _review_filters(query)
        except ValueError as exc:
            self._send(_error_page(TITLE, str(exc), path), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        try:
            history = self.server.match_history()  # type: ignore[attr-defined]
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self._send(_error_page(TITLE, f"The match history could not be read: {exc}", path),  # type: ignore[attr-defined]
                       HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if history is None:
            body = (
                "<section class='fm-match-review-hero'><span class='eyebrow'>Goals and chances conceded</span>"
                "<h2>How we concede</h2><p>No matches are recorded yet. With FM running and your save loaded, use "
                "<strong>Read matches from FM</strong> on the <a href='/matches'>Matches page</a>. There is nothing "
                "to do in FM.</p></section>"
            )
            self._send(_layout(TITLE, path, body))  # type: ignore[attr-defined]
            return
        review = build_match_review(history, filters=filters, catalogue=MVP_CATALOGUE)
        conceded = build_conceded_review(history, (summary.match for summary in review.matches))
        copy = profile_copy_control(
            json.dumps(conceded_json(conceded), indent=2, ensure_ascii=False),
            label="Copy to clipboard", success="Goals and chances conceded copied as JSON!",
        )
        body = conceded_body(review, conceded, MVP_CATALOGUE, self.server.pinned_tactics,  # type: ignore[attr-defined]
                             copy_control=copy)
        self._send(_layout(TITLE, path, body, wide=True))  # type: ignore[attr-defined]
