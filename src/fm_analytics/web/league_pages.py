"""League overview, team XI/roster drilldowns, and captured player evidence."""
from __future__ import annotations

import html
import sqlite3
from http import HTTPStatus
from urllib.parse import quote, unquote, urlencode

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.analytics.league_comparison import order_teams, rank_team_players, team_information_gaps
from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.web.league_state import LeagueOutOfDate
from fm_analytics.web.rendering import _error_page, _layout, _options as _base_options, _query_first

escape = html.escape


def _options(items, selected):
    return _base_options(items, selected, "")


def _href(path: str, tactic: str = "") -> str:
    return escape(path + ("?" + urlencode({"tactic": tactic}) if tactic else ""), quote=True)


def _team_path(team) -> str:
    return "/league/teams/" + quote(team.roster.squad.club.id, safe="")


def _player_link(team, player_id, name, tactic="") -> str:
    path = _team_path(team) + "/players/" + quote(player_id, safe="")
    return f"<a href='{_href(path, tactic)}'>{escape(name)}</a>"


def _range(score) -> str:
    return f"{score.lower:.1f}–{score.upper:.1f}" if score else "—"


def _range_bar(score) -> str:
    if score is None:
        return ""
    return (f"<svg class='fm-league-range' viewBox='0 0 100 8' role='img' aria-label='Score {_range(score)}; conservative {score.central:.1f}'>"
            "<rect width='100' height='8' rx='2' fill='var(--fm-border)'/>"
            f"<rect x='{score.lower:.4f}' width='{score.upper-score.lower:.4f}' height='8' fill='var(--color-brand-300)'/>"
            f"<circle cx='{score.central:.4f}' cy='4' r='2' fill='var(--color-brand-600)'/></svg>")


def _controls(tactic, sort, *, player=False, position="", role=""):
    choices = (("", "Best system for each club"),) + tuple((key, value.name) for key, value in MVP_CATALOGUE.tactics.items())
    fields = f"<label>Comparison tactic<select name='tactic'>{_options(choices, tactic)}</select></label>"
    fields += f"<label>Sort<select name='sort'>{_options(((key, label) for key, label in [('central','Conservative score'),('lower','Floor'),('upper','Ceiling'),('uncertainty','Uncertainty'),('name','Name')]), sort)}</select></label>"
    if player:
        positions = sorted({position for role in MVP_CATALOGUE.roles.values() for position in role.eligible_positions})
        fields += f"<label>Position<select name='position'>{_options([('', 'All positions'), *[(p,p) for p in positions]], position)}</select></label>"
        fields += f"<label>Role<select name='role'>{_options([('', 'Best eligible role'), *[(key,value.name) for key,value in MVP_CATALOGUE.roles.items()]], role)}</select></label>"
    return f"<form method='get' class='filters'>{fields}<button type='submit'>Compare</button></form>"


def _context(report):
    capture = report.capture
    example = "<p class='warn'>Example league data</p>" if capture.source_kind == "fixture" else ""
    partial = " · league membership incomplete" if not capture.membership_complete else ""
    return (example + f"<p class='fm-metric-note'>{escape(capture.competition.name)} · {escape(capture.season)} · "
            f"{capture.game.game_date.isoformat()} · {report.comparable_count}/{len(report.teams)} clubs scored{partial}</p>"
            "<p class='intro'>Ranges reflect attribute knowledge under the stated selection assumptions. "
            "Unknown attributes use 1 conservatively and span 1–20. Overlapping ranges leave the order unresolved.</p>"
            "<p class='fm-metric-note'>Recent form is left out for every club, yours included, because it is only "
            "known for your players. Your score here can therefore differ from the Tactics page, which adds it.</p>")


def _status(team):
    return {"ready": "Scored", "roster_incomplete": "Roster incomplete", "positions_incomplete": "Position evidence needed",
            "no_legal_xi": "Cannot verify XI"}[team.comparison.status]


def _knowledge(team):
    known, ranged, unknown, missing = team.knowledge_counts
    return f"{known} exact · {ranged} ranged · {unknown} unknown · {missing} uncaptured"


def _xi(team, scenario, tactic):
    evaluation = getattr(team.comparison, scenario).selected
    bands = [{"ST"}, {"AML", "AMC", "AMR"}, {"ML", "MC", "MR"}, {"DM"},
             {"WBL", "WBR"}, {"DL", "DC", "DR", "SW"}, {"GK"}]
    lines = []
    for positions in bands:
        cells = []
        for assignment in evaluation.assignments:
            if assignment.slot.position not in positions:
                continue
            cells.append("<article>" + _player_link(team, assignment.player_id, assignment.player_name, tactic)
                         + f"<small>{escape(assignment.slot.position)} · {escape(assignment.intrinsic_role_score.role_name)}</small>"
                         + f"<span>{_range(assignment.selection_score)}</span></article>")
        if cells:
            lines.append("<div>" + "".join(cells) + "</div>")
    missing = ", ".join(slot.position for slot in evaluation.unfilled_slots)
    return (f"<h3>{escape(evaluation.tactic.name)}</h3><p>Selected lineup range: {_range(evaluation.score)}"
            + (f" · unfilled: {escape(missing)}" if missing else "") + "</p>"
            + "<div class='fm-league-pitch'>" + "".join(lines) + "</div>")


def _read_panel(server) -> str:
    """The "Read the league from FM" button, when this server can read FM."""
    if getattr(server, "league_capture", None) is None:
        return ""
    note = ""
    if server.league_capture_note:
        message, ok = server.league_capture_note
        note = f"<p class='{'muted' if ok else 'error'}'>{escape(message)}</p>"
    return ("<div class='refresh-panel'><form class='refresh' method='post' action='/league/capture'>"
            "<button type='submit'>Read the league from FM</button></form>" + note
            + "<details><summary>What gets read</summary><p class='muted'>Reading is read-only: nothing is written "
            "to FM and there is nothing to do in FM. Every club in your league and its first-team squad come "
            "from the game's memory. For other clubs' players you get only what FM shows you: their visible "
            "attributes, and the positions FM shows on their profile, which depend on how well you know them. "
            "It takes a few seconds; the comparison is then worked out in the background.</p></details></div>")


class LeaguePagesMixin:
    def _post_league_capture(self) -> None:
        """Read the league from FM (read-only), then go back to the League page."""
        self.server.capture_league_from_fm()
        self._redirect("/league")

    def _league_report_or_error(self, query):
        self._league_notice = ""
        tactic = _query_first(query, "tactic") or ""
        if tactic and tactic not in MVP_CATALOGUE.tactics:
            self._send(_error_page("League", "Unknown comparison tactic", "/league"), HTTPStatus.BAD_REQUEST)
            return False
        try:
            view = self.server.league_view(tactic or None, retry=_query_first(query, "retry") == "1")
            if _query_first(query, "retry") == "1":
                clean = urlencode([(key, value) for key, values in query.items() if key != "retry" for value in values])
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", self.path.split("?", 1)[0] + ("?" + clean if clean else ""))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            if view.status == "loading":
                retained = " Showing the previous completed capture below." if view.report else ""
                self._league_notice = ("<section class='fm-workspace-panel' data-league-pending role='status'>"
                                       "<h2>Updating league comparison</h2><p>The best XIs are being evaluated."
                                       + retained + " This page will update automatically.</p></section>")
                if view.report is None:
                    self._send(_layout("League", "/league", self._league_notice), HTTPStatus.ACCEPTED)
                    return False
            elif view.status == "error":
                retry_query = urlencode([(key, value) for key, values in query.items() for value in values] + [("retry", "1")])
                retry_path = self.path.split("?", 1)[0] + "?" + retry_query
                self._league_notice = ("<section class='fm-error-state' role='alert'><h2>Comparison update failed</h2>"
                                       + f"<p>{escape(view.error)}</p><p><a href='{escape(retry_path, quote=True)}'>Retry comparison</a></p>"
                                       + ("<p>Showing the previous completed capture below.</p>" if view.report else "") + "</section>")
                if view.report is None:
                    self._send(_layout("League", "/league", self._league_notice), HTTPStatus.SERVICE_UNAVAILABLE)
                    return False
            return view.report
        except LeagueOutOfDate as exc:
            self._send(_layout("League", "/league", "<section class='fm-decision-hero'><h2>League out of date</h2>"
                               f"<p>{escape(str(exc))}</p>" + _read_panel(self.server) + "</section>"),
                       HTTPStatus.CONFLICT)
        except (ValueError, TypeError, KeyError) as exc:
            self._send(_error_page("League", str(exc), "/league"), HTTPStatus.BAD_REQUEST)
        except (OSError, RuntimeError, sqlite3.Error, BridgeSourceError) as exc:
            self._send(_error_page("League", str(exc), "/league"), HTTPStatus.SERVICE_UNAVAILABLE)
        return False

    def _league_page(self, path, query):
        report = self._league_report_or_error(query)
        if report is False:
            return
        if report is None:
            reading = getattr(self.server, "league_capture", None) is not None
            self._send(_layout("League", "/league", "<section class='fm-decision-hero'><h2>League data needed</h2>"
                       + ("<p>Read the league from FM to compare every club's best XI with yours.</p>" if reading else
                          "<p>Team comparisons will appear once a current league capture is available.</p>")
                       + "<p>Player knowledge remains available in <a href='/scouting'>Scouting</a>.</p>"
                       + _read_panel(self.server) + "</section>"))
            return
        tactic, sort = _query_first(query, "tactic") or "", _query_first(query, "sort") or "central"
        try:
            teams = order_teams(report.teams, sort)
        except ValueError as exc:
            self._send(_error_page("League", str(exc), path), HTTPStatus.BAD_REQUEST)
            return
        rows = []
        for team in teams:
            club, score = team.roster.squad.club, team.score
            position = "—" if team.rank_lower is None else str(team.rank_lower) if team.rank_lower == team.rank_upper else f"{team.rank_lower}–{team.rank_upper}"
            own = report.capture.game.controlled_club and club.id == report.capture.game.controlled_club.id
            rows.append(f"<tr{' class=our-club' if own else ''}><td>{position}</td><td><a href='{_href(_team_path(team), tactic)}'>{escape(club.name)}</a>"
                        + (" · your club" if own else "") + f"</td><td>{_range(score)}{_range_bar(score)}</td>"
                        + f"<td>{f'{score.central:.1f}' if score else '—'}</td><td>{escape(team.comparison.central.selected.tactic.name) if score else escape(_status(team))}</td>"
                        + f"<td>{_knowledge(team)}</td><td>{escape(team.relative_to_us)}</td></tr>")
        body = ("<section class='fm-decision-hero'><h2>Compare your league</h2>" + _context(report)
                + _read_panel(self.server) + "</section>"
                + "<section class='fm-workspace-panel'>" + _controls(tactic, sort)
                + f"<p>Possible strength positions among {report.comparable_count} scored clubs. Ordered by {escape(sort)}; positions describe the model under its selection assumptions.</p>"
                + "<div class='fm-table-scroll'><table><thead><tr><th>Position</th><th>Club</th><th>Best XI range</th><th>Conservative</th><th>Central system / status</th><th>Role inputs</th><th>Compared with us</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></div></section>")
        self._send(_layout("League", "/league", self._league_notice + body, wide=True))

    def _league_team_page(self, path, query):
        report = self._league_report_or_error(query)
        if report is False:
            return
        pieces = [unquote(piece) for piece in path[len("/league/teams/"):].split("/")]
        team = next((t for t in report.teams if t.roster.squad.club.id == pieces[0]), None) if report else None
        if team is None or len(pieces) not in {1, 3} or len(pieces) == 3 and pieces[1] != "players":
            self._send(_error_page("League", "Team or player not found", "/league"), HTTPStatus.NOT_FOUND)
            return
        tactic = _query_first(query, "tactic") or ""
        if len(pieces) == 3:
            self._league_player_page(team, pieces[2], report, tactic)
            return
        position, role, sort = (_query_first(query, key) or default for key, default in
                                (("position", ""), ("role", ""), ("sort", "central")))
        try:
            players = rank_team_players(team, MVP_CATALOGUE, position=position, role_key=role, sort=sort)
        except ValueError as exc:
            self._send(_error_page("League", str(exc), "/league"), HTTPStatus.BAD_REQUEST)
            return
        rows = "".join(f"<tr><td>{_player_link(team,row.player.id,row.player.name,tactic)}</td><td>{escape(', '.join(row.player.positions) or 'Position needed')}</td>"
                       f"<td>{escape(row.best_role.role_name) if row.best_role else '—'}</td><td>{_range(row.score)}</td><td>{f'{row.score.central:.1f}' if row.score else '—'}</td>"
                       f"<td>{escape(row.player.availability)}</td></tr>" for row in players)
        gaps = "".join("<li>" + _player_link(team, assignment.player_id, assignment.player_name, tactic)
                       + f": {escape(gap.attribute)} · {'Scout more' if gap.supplied else 'Capture needed'} "
                       + f"({gap.uncertainty_span:.1f} uncertain role-fit points)</li>"
                       for assignment, gap in team_information_gaps(team))
        warnings = "".join(f"<li>{escape(item)}</li>" for item in (*team.assumptions, *team.roster.errors))
        body = (f"<p><a href='{_href('/league', tactic)}'>← League comparison</a></p>"
                f"<section class='fm-decision-hero'><h2>{escape(team.roster.squad.club.name)}</h2>" + _context(report)
                + f"<p>Best XI range: <b>{_range(team.score)}</b> · {escape(_status(team))}</p>"
                + (f"<ul>{warnings}</ul>" if warnings else "") + "</section>"
                + "<section class='fm-workspace-panel'><h2>Conservative best XI</h2>" + _xi(team, "central", tactic)
                + "<details class='fm-disclosure'><summary>Floor XI</summary>" + _xi(team, "lower", tactic) + "</details>"
                + "<details class='fm-disclosure'><summary>Ceiling XI</summary>" + _xi(team, "upper", tactic) + "</details></section>"
                + f"<section class='fm-workspace-panel'><h2>What to learn next</h2><ul>{gaps}</ul></section>"
                + "<section class='fm-workspace-panel'><h2>Rank the squad</h2><p>Best role fit uses base-role weights. XI slot scores additionally apply tactic and selection adjustments.</p>"
                + _controls(tactic, sort, player=True, position=position, role=role)
                + "<div class='fm-table-scroll'><table><thead><tr><th>Player</th><th>Position</th><th>Best role fit</th><th>Range</th><th>Conservative</th><th>Availability</th></tr></thead><tbody>"
                + rows + "</tbody></table></div></section>")
        self._send(_layout(team.roster.squad.club.name, "/league", self._league_notice + body, wide=True))

    def _league_player_page(self, team, player_id, report, tactic):
        player = next((p for p in team.roster.squad.players if p.id == player_id), None)
        if player is None:
            self._send(_error_page("League", "Player not found", "/league"), HTTPStatus.NOT_FOUND)
            return
        inputs = sorted({a.name for role in MVP_CATALOGUE.roles.values() for a in role.attributes} | set(player.attributes))
        attributes = "".join(f"<tr><td>{escape(name)}</td><td>{escape(player.attributes[name].display()) if name in player.attributes else 'Uncaptured'}</td></tr>" for name in inputs)
        fits = team.roles.player_profiles[player.id].fits
        roles = "".join(f"<tr><td>{escape(fit.role_name)}</td><td>{_range(fit.role_score.score)}</td><td>{fit.role_score.score.central:.1f}</td></tr>" for fit in fits)
        body = (f"<p><a href='{_href(_team_path(team), tactic)}'>← {escape(team.roster.squad.club.name)}</a></p>"
                f"<section class='fm-decision-hero'><h2>{escape(player.name)}</h2><p>{escape(', '.join(player.positions) or 'Position needed')} · {escape(player.availability)}</p>" + _context(report) + "</section>"
                + "<section class='fm-workspace-panel'><h2>Visible attributes</h2><p>Unknown (?) was captured; Uncaptured has no current observation. Historical values are not substituted.</p>"
                + "<div class='fm-table-scroll'><table><thead><tr><th>Attribute</th><th>Current observation</th></tr></thead><tbody>" + attributes + "</tbody></table></div></section>"
                + "<section class='fm-workspace-panel'><h2>Eligible role rankings</h2><div class='fm-table-scroll'><table><thead><tr><th>Role</th><th>Range</th><th>Conservative</th></tr></thead><tbody>"
                + roles + "</tbody></table></div></section>")
        self._send(_layout(player.name, "/league", self._league_notice + body, wide=True))
