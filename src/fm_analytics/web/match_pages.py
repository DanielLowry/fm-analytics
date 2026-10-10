"""The Matches pages: the review, one match, and the three local POSTs.

The only things these write are the local match-history database (a capture
of what FM shows, the manager's notes on a match, and a confirmed role code).
Nothing is ever written to FM: reading matches runs the read-only
`tools/fm20_match_probe.py`.
"""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from urllib.parse import quote, unquote

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.match_analysis import ReviewFilters
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.match_ingest import export_path
from fm_analytics.reporting import (
    build_match_diagnosis,
    build_match_diagnostics,
    build_match_export,
    build_match_intervention_evaluation,
    build_match_report,
    build_match_breakdowns,
    build_match_review,
    build_matches_export,
    build_penalty_record,
    build_season_export,
)
from fm_analytics.season_export import DETAIL_LEVELS
from fm_analytics.web.match_render import (
    capture_panel,
    export_links,
    match_url,
    matches_copy_control,
    review_body,
    tactic_history_panel,
    tactic_record_panel,
)
from fm_analytics.web.attribute_export import profile_copy_control
from fm_analytics.web.match_breakdowns_render import breakdown_panels
from fm_analytics.web.experiment_render import keep_match_form
from fm_analytics.web.match_detail_render import match_body
from fm_analytics.web.mentality_render import plan_from_form
from fm_analytics.web.rendering import _error_page, _layout, _query_first, _query_number


def _review_filters(query: dict[str, list[str]]) -> ReviewFilters:
    """The Matches page's filters from its query; raises ValueError for a bad one."""
    return ReviewFilters(
        grouping=_query_first(query, "group") or "table",
        competitions=_query_first(query, "competitions") or "competitive",
        venue=_query_first(query, "venue") or None,
        tactic=_query_first(query, "tactic") or None,
        season=_query_number(query, "season", integer=True),
    )


class MatchPagesMixin:
    def _match_record_block(self, tactic_keys, quality: int) -> str:
        """The Tactics page's match-record box, or nothing when there is no history.

        Never raises: the Tactics page must not fail because the history could not be read.
        """
        try:
            history = self.server.match_history()  # type: ignore[attr-defined]
            if history is None or not history.matches:
                return ""
            review = build_match_review(history, filters=ReviewFilters(grouping="rating"))
        except Exception:  # noqa: BLE001 - see the docstring
            return ""
        return tactic_record_panel(review, MVP_CATALOGUE, tactic_keys, quality)

    def _tactic_history_block(self, tactic_key: str) -> str:
        """A tactic page's record of the matches played with it, or nothing when there is no history.

        Never raises, for the same reason as `_match_record_block`.
        """
        try:
            history = self.server.match_history()  # type: ignore[attr-defined]
            if history is None or not history.matches:
                return ""
            review = build_match_review(history, filters=ReviewFilters(tactic=tactic_key))
        except Exception:  # noqa: BLE001 - see the docstring
            return ""
        return tactic_history_panel(review, MVP_CATALOGUE, tactic_key)

    def _match_capture_panel(self) -> str:
        server = self.server  # type: ignore[attr-defined]
        note = server.match_capture_note
        return capture_panel(server.match_status(), *(note if note else (None, True)))

    def _matches_page(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            filters = _review_filters(query)
        except ValueError as exc:
            self._send(_error_page("Matches", str(exc), path), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        try:
            history = self.server.match_history()  # type: ignore[attr-defined]
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self._send(_error_page("Matches", f"The match history could not be read: {exc}", path),  # type: ignore[attr-defined]
                       HTTPStatus.SERVICE_UNAVAILABLE)
            return
        panel = self._match_capture_panel()
        if history is None:
            body = panel + (
                "<p class='intro'>No matches recorded yet. With FM running and your save loaded, use "
                "<strong>Read matches from FM</strong>: it reads every result this season and each "
                "match's full stats. There is nothing to do in FM.</p>"
            )
            self._send(_layout("Matches", "/matches", body))  # type: ignore[attr-defined]
            return
        review = build_match_review(history, filters=filters)
        penalties = build_penalty_record(history, review)
        breakdowns = build_match_breakdowns(history, review)
        diagnostic_review = build_match_review(
            history, filters=ReviewFilters(grouping="table", competitions="competitive")
        )
        body = review_body(
            review,
            build_match_diagnostics(diagnostic_review),
            build_match_intervention_evaluation(history, diagnostic_review),
            history.interventions,
            MVP_CATALOGUE,
            pinned=self.server.pinned_tactics,  # type: ignore[attr-defined]
            capture=panel + export_links(),
            copy_control=matches_copy_control(review),
            penalties=penalties,
            extra_panels=breakdown_panels(review, breakdowns),
        )
        self._send(_layout("Matches", "/matches", body, wide=True))  # type: ignore[attr-defined]

    def _matches_export_api(self, _path: str, query: dict[str, list[str]]) -> None:
        """The matches the Matches page selects, as JSON: `reporting.build_matches_export`.

        Takes the page's own filters; the page's "Copy all match data" button fetches it.
        """
        try:
            filters = _review_filters(query)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        try:
            history = self.server.match_history()  # type: ignore[attr-defined]
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self._send_json({"error": f"The match history could not be read: {exc}"},  # type: ignore[attr-defined]
                            HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if history is None:
            self._send_json({"error": "No matches are recorded yet."}, HTTPStatus.NOT_FOUND)  # type: ignore[attr-defined]
            return
        self._send_json(build_matches_export(history, filters=filters))  # type: ignore[attr-defined]

    def _export_api(self, _path: str, query: dict[str, list[str]]) -> None:
        """The season as JSON: `reporting.build_season_export`, as `fm-matches export` writes it.

        `detail` is basic, standard (default) or verbose. With `squad=live` (the
        default) the squad sections come from the same cached recommendation the
        Tactics page shows, and fail closed if it cannot be built; `squad=none`
        leaves them out.
        """
        server = self.server  # type: ignore[attr-defined]
        detail = _query_first(query, "detail") or "standard"
        squad = _query_first(query, "squad") or "live"
        if detail not in DETAIL_LEVELS or squad not in ("live", "none"):
            self._send_json(  # type: ignore[attr-defined]
                {"error": f"detail must be one of {', '.join(DETAIL_LEVELS)}; squad must be live or none"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        try:
            history = server.match_history()
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self._send_json({"error": f"The match history could not be read: {exc}"},  # type: ignore[attr-defined]
                            HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if history is None:
            self._send_json({"error": "No matches are recorded yet."}, HTTPStatus.NOT_FOUND)  # type: ignore[attr-defined]
            return
        bundle = None
        if squad == "live" and detail != "basic":
            try:
                bundle = server.bundle()
            except (BridgeSourceError, OSError, ValueError, KeyError) as exc:
                self._send_json(  # type: ignore[attr-defined]
                    {"error": f"The squad could not be read: {exc}. Add squad=none to export without it."},
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
        document = build_season_export(
            history, detail=detail, bundle=bundle,
            squad_note="left out (squad=none)",
        )
        filename = export_path(history.club.name, document["meta"]["game_date"], detail).name
        self._send_json(document, filename=filename)  # type: ignore[attr-defined]

    def _match_page(self, path: str, _query: dict[str, list[str]]) -> None:
        key = unquote(path[len("/matches/"):])
        try:
            history = self.server.match_history()  # type: ignore[attr-defined]
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self._send(_error_page("Match", str(exc), "/matches"), HTTPStatus.SERVICE_UNAVAILABLE)  # type: ignore[attr-defined]
            return
        report = build_match_report(history, key) if history is not None else None
        if report is None:
            self._send(_error_page("Match", f"No match {key} is recorded.", "/matches"), HTTPStatus.NOT_FOUND)  # type: ignore[attr-defined]
            return
        summary = report.summary
        title = f"{summary.match.home.name} {summary.match.home_goals}–{summary.match.away_goals} {summary.match.away.name}"
        document = build_match_export(history, report)
        copy = profile_copy_control(
            json.dumps(document, indent=2, ensure_ascii=False),
            label="Copy match to clipboard", success="Match copied as JSON!",
        )
        body = "<p><a href='/matches'>← All matches</a></p>" + match_body(
            report, MVP_CATALOGUE, self.server.pinned_tactics,  # type: ignore[attr-defined]
            history.notes.get(summary.match.key), copy_control=copy,
            diagnosis=build_match_diagnosis(history, report),
        )
        if self.server.experiment_store is not None:  # type: ignore[attr-defined]
            body += keep_match_form(summary.match.key, MVP_CATALOGUE, self.server.experiment_groups(),  # type: ignore[attr-defined]
                                    mentality=summary.mentality)
        self._send(_layout(title, "/matches", body, wide=True))  # type: ignore[attr-defined]

    def _post_match_capture(self) -> None:
        """Read matches from FM (read-only) and record them, then go back."""
        self.server.capture_matches()  # type: ignore[attr-defined]
        self._redirect("/matches")

    def _post_match_note(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        key = form.get("match", [""])[0]
        tactic = form.get("tactic", [""])[0] or None
        rating_text = form.get("rating", [""])[0]
        try:
            if tactic is not None and tactic not in MVP_CATALOGUE.tactics:
                raise ValueError(f"{tactic!r} is not a tactic in the catalogue.")
            rating = int(rating_text) if rating_text else None
            self.server.add_match_note(  # type: ignore[attr-defined]
                key, tactic_key=tactic, opponent_rating=rating, note=form.get("note", [""])[0]
            )
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._send(_error_page("Match notes", str(exc), match_url(key) if key else "/matches"),  # type: ignore[attr-defined]
                       HTTPStatus.BAD_REQUEST)
            return
        self._redirect(match_url(key))

    def _post_penalty_foul(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        key = form.get("match", [""])[0]
        player = form.get("player", [""])[0]
        try:
            self.server.record_penalty_foul(  # type: ignore[attr-defined]
                key, int(form.get("minute", [""])[0]), int(form.get("added", ["0"])[0] or 0),
                int(player) if player else None,
            )
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._send(_error_page("Penalty", str(exc), match_url(key) if key else "/matches"),  # type: ignore[attr-defined]
                       HTTPStatus.BAD_REQUEST)
            return
        self._redirect(match_url(key))

    def _post_match_mentality(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        key = form.get("match", [""])[0]
        try:
            plan = None if form.get("clear", [""])[0] == "1" else plan_from_form(form)
            self.server.record_match_mentality(key, plan)  # type: ignore[attr-defined]
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._send(_error_page("Mentality", str(exc), match_url(key) if key else "/matches"),  # type: ignore[attr-defined]
                       HTTPStatus.BAD_REQUEST)
            return
        self._redirect(match_url(key))

    def _post_role_code(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        role = form.get("role", [""])[0]
        try:
            code = int(form.get("code", [""])[0])
            if role not in MVP_CATALOGUE.roles:
                raise ValueError(f"{role!r} is not a role in the catalogue.")
            self.server.confirm_role_code(code, role)  # type: ignore[attr-defined]
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._send(_error_page("Role code", str(exc), "/matches"), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        self._redirect("/matches")

    def _post_intervention_start(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        finding_key = form.get("finding", [""])[0]
        try:
            self.server.start_match_intervention(  # type: ignore[attr-defined]
                finding_key, form.get("note", [""])[0]
            )
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._send(  # type: ignore[attr-defined]
                _error_page("Controlled intervention", str(exc), "/matches"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/matches")

    def _post_intervention_finish(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        try:
            intervention_id = int(form.get("intervention", [""])[0])
            self.server.finish_match_intervention(  # type: ignore[attr-defined]
                intervention_id,
                outcome=form.get("outcome", [""])[0],
                note=form.get("note", [""])[0],
            )
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._send(  # type: ignore[attr-defined]
                _error_page("Controlled intervention", str(exc), "/matches"),
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._redirect("/matches")

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)  # type: ignore[attr-defined]
        self.send_header("Location", quote(location, safe="/:?=&%"))  # type: ignore[attr-defined]
        self.end_headers()  # type: ignore[attr-defined]
