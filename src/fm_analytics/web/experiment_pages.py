"""The Experiments pages and their buttons: storing, grouping, labelling and comparing matches.

Mixed into `SquadWebHandler`. Every figure comes from `reporting`; nothing is
stored except by a button press here or on a match page.
"""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from urllib.parse import unquote

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.domain.experiments import MatchLabel
from fm_analytics.experiment_ingest import ALL_STORED, experiment_document
from fm_analytics.reporting import build_experiment_report, build_stored_match_report
from fm_analytics.web.attribute_export import profile_copy_control
from fm_analytics.web.experiment_render import experiments_body, group_body, group_url
from fm_analytics.web.match_detail_render import match_body
from fm_analytics.web.rendering import _error_page, _layout

_ERRORS = (ValueError, OSError, RuntimeError, sqlite3.Error)


def _label(form: dict[str, list[str]]) -> MatchLabel:
    tactic = form.get("tactic", [""])[0] or None
    if tactic is not None and tactic not in MVP_CATALOGUE.tactics:
        raise ValueError(f"{tactic!r} is not a tactic in the catalogue.")
    tags = {}
    for line in form.get("tags", [""])[0].splitlines():
        if line.strip():
            key, separator, value = line.partition("=")
            if not separator or not key.strip():
                raise ValueError(f"A tag is key=value, not {line.strip()!r}.")
            tags[key.strip()] = value.strip()
    return MatchLabel(form.get("label", [""])[0], tactic, form.get("note", [""])[0], tags)


class ExperimentPagesMixin:
    def _history_or_none(self):
        try:
            return self.server.match_history()  # type: ignore[attr-defined]
        except _ERRORS:
            return None

    def _experiments_page(self, path: str, _query) -> None:
        server = self.server  # type: ignore[attr-defined]
        try:
            body = experiments_body(server.stored_matches(), server.experiment_groups(), MVP_CATALOGUE,
                                    note=server.experiment_note, reads_fm=server.experiments_read_fm)
        except _ERRORS as exc:
            self._send(_error_page("Experiments", f"The experiments could not be read: {exc}", path),  # type: ignore[attr-defined]
                       HTTPStatus.SERVICE_UNAVAILABLE)
            return
        server.experiment_note = None
        self._send(_layout("Experiments", "/experiments", body, wide=True))  # type: ignore[attr-defined]

    def _experiment_group_page(self, path: str, _query) -> None:
        server = self.server  # type: ignore[attr-defined]
        if path == "/experiments/all":
            name, note, stored = ALL_STORED, "", server.stored_matches()
        else:
            group = next((group for group in server.experiment_groups()
                          if group.name == unquote(path[len("/experiments/group/"):])), None)
            if group is None:
                self._send(_error_page("Experiment", "No such group.", "/experiments"), HTTPStatus.NOT_FOUND)  # type: ignore[attr-defined]
                return
            name, note, stored = group.name, group.note, group.matches
        report = build_experiment_report(name, stored, self._history_or_none(), note=note)
        copy = profile_copy_control(
            json.dumps(experiment_document(report), indent=2, ensure_ascii=False),
            label="Copy experiment to clipboard", success="Experiment copied as JSON!",
        )
        body = group_body(report, MVP_CATALOGUE, copy_control=copy, note=server.experiment_note)
        server.experiment_note = None
        self._send(_layout(name, "/experiments", body, wide=True))  # type: ignore[attr-defined]

    def _stored_match_page(self, path: str, _query) -> None:
        server = self.server  # type: ignore[attr-defined]
        try:
            match_id = int(path[len("/experiments/match/"):])
        except ValueError:
            match_id = -1
        stored = next((item for item in server.stored_matches() if item.id == match_id), None)
        report = build_stored_match_report(stored, self._history_or_none()) if stored else None
        if report is None:
            self._send(_error_page("Stored match", "No such stored match.", "/experiments"), HTTPStatus.NOT_FOUND)  # type: ignore[attr-defined]
            return
        match = stored.match
        title = f"#{stored.id} {match.home.name} {match.home_goals}–{match.away_goals} {match.away.name}"
        body = (
            "<p><a href='/experiments'>← Experiments</a></p>"
            f"<p class='intro'>Stored match #{stored.id}, labelled <strong>{stored.label.variant}</strong>"
            + (f", in {', '.join(stored.groups)}" if stored.groups else "")
            + ". This is the match as stored, which for a replay is not the one in your season.</p>"
            + match_body(report, MVP_CATALOGUE, (), None, notes=False)
        )
        self._send(_layout(title, "/experiments", body, wide=True))  # type: ignore[attr-defined]

    # -- buttons -------------------------------------------------------------

    def _form_groups(self, form: dict[str, list[str]]) -> list[str]:
        """The groups ticked on a form, creating the new one it names."""
        groups = [name for name in form.get("group", []) if name.strip()]
        new = form.get("new_group", [""])[0].strip()
        if new:
            if not any(group.name == new for group in self.server.experiment_groups()):  # type: ignore[attr-defined]
                self.server.create_experiment_group(new)  # type: ignore[attr-defined]
            groups.append(new)
        return groups

    def _post_experiment_store(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        try:
            label, groups = _label(form), self._form_groups(form)
        except _ERRORS as exc:
            self.server.experiment_note = (str(exc), False)  # type: ignore[attr-defined]
        else:
            self.server.store_played_match(label, groups)  # type: ignore[attr-defined]
        self._redirect("/experiments")  # type: ignore[attr-defined]

    def _post_experiment_store_history(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        try:
            match_id = self.server.store_history_match(  # type: ignore[attr-defined]
                form.get("match", [""])[0], _label(form), self._form_groups(form)
            )
        except _ERRORS as exc:
            self._send(_error_page("Store for experiments", str(exc), "/experiments"), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        self._redirect(f"/experiments/match/{match_id}")  # type: ignore[attr-defined]

    def _post_experiment_group(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        name = form.get("name", [""])[0]
        try:
            self.server.create_experiment_group(name, form.get("note", [""])[0])  # type: ignore[attr-defined]
        except _ERRORS as exc:
            self._send(_error_page("Experiment group", str(exc), "/experiments"), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        self._redirect(group_url(name.strip()))  # type: ignore[attr-defined]

    def _post_experiment_membership(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        try:
            ids = [int(value) for value in form.get("id", [])]
            if not ids:
                raise ValueError("Tick at least one stored match first.")
            self.server.set_experiment_membership(  # type: ignore[attr-defined]
                form.get("group", [""])[0], ids, member=form.get("member", ["1"])[0] == "1"
            )
        except _ERRORS as exc:
            self._send(_error_page("Experiment group", str(exc), "/experiments"), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        self._redirect("/experiments")  # type: ignore[attr-defined]

    def _post_experiment_relabel(self) -> None:
        form = self._read_form()  # type: ignore[attr-defined]
        back = form.get("back", [""])[0]
        location = "/experiments/all" if back in ("", "All stored matches") else group_url(back)
        try:
            self.server.relabel_stored_match(  # type: ignore[attr-defined]
                int(form.get("id", [""])[0]), _label(form), withdrawn=form.get("withdraw", ["0"])[0] == "1"
            )
        except _ERRORS as exc:
            self._send(_error_page("Stored match", str(exc), location), HTTPStatus.BAD_REQUEST)  # type: ignore[attr-defined]
            return
        self._redirect(location)  # type: ignore[attr-defined]
