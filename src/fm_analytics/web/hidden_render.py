"""The League page's hidden view (/league/hidden): HTML for `hidden_reporting.build_hidden_strength_report`. HIDDEN DATA.

Formatting only: every figure comes from `analytics.hidden_strength`. Each
table is marked for both copy buttons (tab-separated and Markdown).
"""
from __future__ import annotations

import html
from urllib.parse import urlencode

from fm_analytics.analytics.hidden_strength import MATCHUPS, UNIT_NAMES, UNITS, HiddenStrength, OurMatch, XiStrength
from fm_analytics.web.rendering import _options

_e = html.escape
PATH = "/league/hidden"

BANNER = (
    "<aside class='fm-hidden-banner' role='note'><b>This page uses hidden attributes.</b> "
    "Every figure here comes from the real values FM keeps for each player: every attribute and position "
    "rating, including the ones FM does not show you because you have not scouted him. A manager cannot "
    "see this in the game. It is here to measure your squad, and nothing on this page feeds the "
    "recommendations or any other page.</aside>"
)


def _score(value: float | None, places: int = 1) -> str:
    return "—" if value is None else f"{value:.{places}f}"


def _signed(value: float | None, places: int = 1) -> str:
    if value is None:
        return "—"
    text = f"{value:+.{places}f}"
    # A plain minus, so a copied table pastes into a spreadsheet as numbers.
    return text[1:] if float(text) == 0 else text


def _delta(value: float | None, places: int = 1) -> str:
    """A signed difference, tinted by direction (the sign is always printed too)."""
    if value is None:
        return "<td>—</td>"
    tone = "up" if value >= 0.05 else "down" if value <= -0.05 else "level"
    return f"<td class='fm-hidden-delta' data-tone='{tone}' data-sort='{value:.3f}'>{_signed(value, places)}</td>"


def _xi_cell(xi: XiStrength) -> str:
    if xi.score is None:
        why = "; ".join(xi.missing) or "not scored"
        return f"<td title='{_e('Not scored: ' + why, quote=True)}'>—</td>"
    notes = []
    if not xi.exact_shape:
        notes.append("scored in the nearest shape our tactics have")
    if xi.out_of_position:
        notes.append("not enough players for every position: some play out of position")
    title = f"Scored in {xi.tactic_name}" + ("; " + "; ".join(notes) if notes else "")
    # The * is drawn by CSS, so a copied table keeps a plain number.
    flag = " class='fm-hidden-flag'" if notes else ""
    return f"<td{flag} title='{_e(title, quote=True)}' data-sort='{xi.score:.3f}'>{xi.score:.1f}</td>"


def _table(head: list[str], rows: list[str], *, foot: str = "", label: str) -> str:
    return ("<div class='fm-table-scroll'><table data-copy-markdown aria-label='" + _e(label, quote=True) + "'><thead><tr>"
            + "".join(f"<th>{_e(cell)}</th>" for cell in head) + "</tr></thead><tbody>" + "".join(rows)
            + "</tbody>" + (f"<tfoot>{foot}</tfoot>" if foot else "") + "</table></div>")


def _href(**params) -> str:
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    return _e(PATH + ("?" + query if query else ""), quote=True)


# --- Hero ------------------------------------------------------------------------------------------------


def _verdict(report: HiddenStrength) -> str:
    verdict, model = report.verdict, report.model
    if verdict is None:
        reason = ("Not enough league matches have both line-ups scored to say how strength turns into results yet."
                  if model is None else "None of our league matches this season has both line-ups scored yet.")
        return f"<p class='fm-hidden-answer'>{_e(reason)}</p>"
    reading = {
        "better": "Your results are <b>better than your players explain</b>, by more than the usual run of luck.",
        "worse": ("Your results are <b>worse than your players explain</b>, by more than the usual run of luck: "
                  "something other than the squad is costing points."),
        "in line": ("Your results are <b>in line with your squad</b>: the difference is within the usual run of luck "
                    f"for {verdict.played} matches (about ±{verdict.spread:.1f} points)."),
    }[verdict.reading]
    recent = ""
    if verdict.recent_played:
        recent = (f" In the last {verdict.recent_played}: <b>{verdict.recent_points}</b> points against "
                  f"<b>{verdict.recent_expected:.1f}</b> expected (usual run of luck ±{verdict.recent_spread:.1f}).")
    tactic = report.tactic_names.get(verdict.best_tactic, "")
    units = ""
    if verdict.fielded_unit_ranks:
        units = ("<p class='fm-hidden-units-line'>By unit, the XIs you have fielded rank "
                 + _unit_ranks(verdict.fielded_unit_ranks, verdict.clubs) + "."
                 + (f" Your best XI in {_e(tactic)}: " + _unit_ranks(verdict.best_unit_ranks, verdict.clubs) + "."
                    if verdict.best_unit_ranks and tactic else "")
                 + " <a href='#units'>See section 5</a></p>")
    tiles = [
        ("Points", f"{verdict.points}", f"from {verdict.played} league matches · {_rank(verdict.points_rank, verdict.clubs)}"),
        ("Expected from the XIs", f"{verdict.expected_points:.1f}", f"{_signed(verdict.points_gap)} against what you have"),
        ("XIs you fielded", _rank(verdict.fielded_rank, verdict.clubs), "by average XI score this season"),
        ("Best XI", _rank(verdict.best_rank, verdict.clubs), f"in {tactic}" if tactic else "in your most-used tactic"),
    ]
    return ("<p class='fm-hidden-answer'>" + reading + recent + "</p>" + units
            + "<div class='fm-decision-grid fm-hidden-tiles'>"
            + "".join(f"<section class='fm-decision-stat'><span>{_e(label)}</span><b>{_e(value)}</b><small>{_e(note)}</small></section>"
                      for label, value, note in tiles) + "</div>")


def _unit_ranks(ranks, clubs: int) -> str:
    return ", ".join(f"{UNIT_NAMES[key].lower()} <b>{_ordinal(ranks[key])}</b>" for key, _name, _p in UNITS
                     if key in ranks) + f" of {clubs}"


def _ordinal(rank: int) -> str:
    return f"{rank}" + ("th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th"))


def _rank(rank: int | None, of: int) -> str:
    return "—" if rank is None else f"{_ordinal(rank)} of {of}"


def read_panel(server, *, first: bool = False) -> str:
    """The "Read hidden attributes from FM" button, when this server can read FM."""
    if getattr(server, "hidden_capture", None) is None:
        return ("<p class='muted'>Start the web view with <code>--direct-live</code> to read hidden attributes from "
                "FM, or pass a read with <code>--hidden-json</code>.</p>") if first else ""
    note = ""
    if server.hidden_capture_note:
        message, ok = server.hidden_capture_note
        note = f"<p class='{'muted' if ok else 'error'}'>{_e(message)}</p>"
    label = "Read hidden attributes from FM" if first else "Read again from FM"
    return ("<div class='refresh-panel'><form class='refresh' method='post' action='/league/hidden/capture'>"
            f"<button type='submit'>{label}</button></form>" + note
            + "<details><summary>What gets read</summary><p class='muted'>Read-only: nothing is written to FM, "
            "no FM code runs, and there is nothing to do in FM. Every club in your league and its first-team squad, "
            "plus everyone who started a match your match history holds, with the real value of every attribute and "
            "position rating FM keeps for them. It takes a couple of seconds; the tables are then worked out in "
            "the background.</p></details></div>")


def _controls(report: HiddenStrength, seasons, catalogue, tactic: str) -> str:
    season_options = _options(((str(season), f"{season}/{(season + 1) % 100:02d}") for season in seasons),
                              str(report.season), "")
    played = {key for key, _count in report.our_tactics}
    choices = [("", "Only the tactics we played")] + [
        (key, value.name) for key, value in catalogue.tactics.items() if key not in played
    ]
    return ("<form method='get' class='filters fm-hidden-controls'>"
            f"<label>Season<select name='season'>{season_options}</select></label>"
            f"<label>Also compare in<select name='tactic'>{_options(choices, tactic, '')}</select></label>"
            "<button type='submit'>Show</button></form>")


def hero(report: HiddenStrength, server, *, seasons, catalogue, tactic: str, copy_control: str) -> str:
    capture = report.capture
    model = report.model
    fit = ("" if model is None else
           f" Across those matches each point of XI-score advantage was worth about "
           f"<b>{model.goals_per_point():.2f}</b> goals a match.")
    return ("<section class='fm-decision-hero fm-hidden-hero'><span class='eyebrow'>League · hidden attributes</span>"
            "<h2>Is it the squad, or is it us?</h2>" + BANNER
            + f"<p class='fm-metric-note'>{_e(capture.competition.name)} · {report.season}/{(report.season + 1) % 100:02d} · "
            f"attributes read at game date {capture.game_date.isoformat()} · {report.league_scored} of "
            f"{report.league_matches} league matches with both line-ups scored</p>"
            + ("" if not any(row.match.date > capture.game_date for row in report.our_matches) else
               "<p class='warn'>Some matches were played after this read. Reading hidden attributes from FM again "
               "scores every XI with today's attributes.</p>")
            + ("" if report.league_scored == report.league_matches else
               f"<p class='warn'>{report.league_matches - report.league_scored} league match(es) have a starter this "
               "read does not include, so they are left out. If they were recorded after the read, reading hidden "
               "attributes from FM again adds those players.</p>")
            + "<p>Every XI below is scored by the same team model as the League page, from true attributes, with "
            "every player fully fit, so the numbers compare players and nothing else. The expected points come "
            f"from how results followed the gap between the two XIs across the whole league.{fit}</p>"
            + _verdict(report)
            + "<div class='fm-hidden-hero-foot'>" + _controls(report, seasons, catalogue, tactic) + copy_control
            + "</div>" + read_panel(server) + "</section>")


# --- Tables ----------------------------------------------------------------------------------------------


def _anchor(row: OurMatch) -> str:
    return f"xi-{row.match.date.isoformat()}-{row.opponent.id}"


def _match_row(row: OurMatch) -> str:
    match = row.match
    result = "W" if row.points == 3 else "D" if row.points == 1 else "L"
    expected = row.expected_points
    return (f"<tr><td class='fm-nowrap' data-sort='{match.date.isoformat()}'>{match.date.isoformat()}</td><td>{_e(match.competition.label)}</td>"
            f"<td><a href='#{_anchor(row)}' title='Both XIs'>{_e(row.opponent.name)}</a></td><td>{'H' if row.side == 'home' else 'A'}</td>"
            f"<td class='fm-nowrap'><span class='fm-hidden-result' data-result='{result}'>{result}</span> {row.goals_for}–{row.goals_against}</td>"
            f"<td>{row.points}</td><td>{_score(expected, 2)}</td>"
            + _delta(None if expected is None else row.points - expected, 2)
            + _xi_cell(row.ours) + _xi_cell(row.theirs) + _delta(row.gap)
            + f"<td>{_e(row.our_formation)}</td><td>{_e(row.their_formation)}</td></tr>")


def our_matches_section(report: HiddenStrength) -> str:
    rows = [_match_row(row) for row in report.our_matches]
    totals = report.our_totals
    foot = ""
    if totals:
        foot = (f"<tr><th scope='row' colspan='5'>League, {totals.matches} matches</th><td>{totals.points}</td>"
                f"<td>{totals.expected_points:.1f}</td>" + _delta(totals.points - totals.expected_points)
                + f"<td>{totals.our_xi:.1f}</td><td>{totals.their_xi:.1f}</td>" + _delta(totals.gap)
                + "<td></td><td></td></tr>")
    head = ["Date", "Competition", "Opponent", "Venue", "Result", "Pts", "Expected pts", "Pts − expected",
            "Our XI", "Their XI", "Gap", "Our formation", "Their formation"]
    return ("<section class='fm-workspace-panel' id='our-matches'><h2>1 · The XIs in our matches</h2>"
            "<p class='muted'>Both starting XIs exactly as they started each competitive match this season, every "
            "player in the position he started. Expected points are what the gap between the two XIs predicts, "
            "home or away. <b>*</b> marks an XI whose shape our tactics do not have, scored in the nearest one; hover "
            "a score to see the tactic it was scored in, and click an opponent for both XIs player by player. A dash means a starter is no longer in FM's database "
            "(FM removes players it made up for lower-league cup ties).</p>"
            + _table(head, rows, foot=foot, label="The XIs in our matches") + "</section>")


def tactics_section(report: HiddenStrength) -> str:
    keys = report.compared_tactics
    if not keys:
        return ("<section class='fm-workspace-panel' id='our-tactics'><h2>2 · Best XI in our tactics</h2>"
                "<p class='muted'>No match of ours this season has a known tactic. Pick one under <b>Also compare "
                "in</b> above.</p></section>")
    used = dict(report.our_tactics)
    main = keys[0]
    ours = next((row for row in report.by_tactic if row.ours), None)
    mine = ours.xis[main].score if ours else None
    ordered = sorted(report.by_tactic, key=lambda row: (row.xis[main].score is None, -(row.xis[main].score or 0),
                                                        row.club.name))
    rows = []
    for rank, row in enumerate(ordered, 1):
        score = row.xis[main].score
        rows.append(f"<tr{' class=our-club' if row.ours else ''}><td>{rank if score is not None else '—'}</td>"
                    f"<td>{_e(row.club.name)}{' · you' if row.ours else ''}</td>"
                    + "".join(_xi_cell(row.xis[key]) for key in keys)
                    + _delta(None if score is None or mine is None or row.ours else mine - score)
                    + f"<td>{row.squad_size}</td></tr>")
    head = ["Rank", "Club"] + [
        f"{report.tactic_names[key]} ({used[key]} of our matches)" if key in used else f"{report.tactic_names[key]} (picked)"
        for key in keys] + [f"You vs them in {report.tactic_names[main]}", "Squad"]
    return ("<section class='fm-workspace-panel' id='our-tactics'><h2>2 · Best XI in our tactics</h2>"
            "<p class='muted'>Every club's best XI from its whole first-team squad, in each tactic we played this "
            f"season, ranked by the one we played most ({_e(report.tactic_names[main])}). <b>You vs them</b> is your "
            "score minus theirs, so a club with a stronger XI shows a minus. Every player may play where "
            "FM rates him able to; <b>*</b> marks a squad with nobody for some slot, picked with players out of "
            "position at their real rating there.</p>"
            + _table(head, rows, label="Best XI in our tactics") + "</section>")


def formations_section(report: HiddenStrength) -> str:
    ours = next((row for row in report.by_formation if row.ours), None)
    mine = ours.best.score if ours and ours.best else None
    ordered = sorted(report.by_formation, key=lambda row: (row.best is None or row.best.score is None,
                                                           -(row.best.score or 0) if row.best else 0, row.club.name))
    rows = []
    for rank, row in enumerate(ordered, 1):
        score = row.best.score if row.best else None
        used = ", ".join(f"{use.name} ×{use.matches}" + ("" if use.exact else "*") for use in row.formations) or "—"
        rows.append(f"<tr{' class=our-club' if row.ours else ''}><td>{rank if score is not None else '—'}</td>"
                    f"<td>{_e(row.club.name)}{' · you' if row.ours else ''}</td><td>{_e(used)}</td>"
                    + (_xi_cell(row.best) if row.best else "<td>—</td>")
                    + f"<td>{_e(row.best.tactic_name or '—') if row.best else '—'}</td>"
                    + f"<td>{_e(row.best_formation or '—')}</td>"
                    + _delta(None if score is None or mine is None or row.ours else mine - score) + "</tr>")
    head = ["Rank", "Club", "Formations played (league matches)", "Best XI", "Scored in", "From their formation",
            "You vs them"]
    return ("<section class='fm-workspace-panel' id='their-formations'><h2>3 · Best XI in the formations they've played</h2>"
            "<p class='muted'>The same best XI, but only in the formations each club has started a league match in this "
            "season (ours: in our tactics' shapes). Each formation is scored in every tactic of ours with that shape, "
            "and the club's best is shown. <b>*</b> after a formation means our tactics have no exact match for it, so "
            "the nearest shape stood in.</p>"
            + _table(head, rows, label="Best XI in the formations they've played") + "</section>")


def results_section(report: HiddenStrength) -> str:
    model = report.model
    if model is None:
        return ("<section class='fm-workspace-panel' id='results'><h2>4 · Results against strength</h2>"
                f"<p class='muted'>Only {report.league_scored} league matches have both line-ups scored: too few to say "
                "how strength turns into results. Read matches from FM on the <a href='/matches'>Matches page</a> to "
                "add every league club's matches.</p></section>")
    rows = []
    for position, row in enumerate(report.clubs, 1):
        rows.append(f"<tr{' class=our-club' if row.ours else ''}><td>{position}</td>"
                    f"<td>{_e(row.club.name)}{' · you' if row.ours else ''}</td><td>{row.played}</td>"
                    f"<td>{row.points}</td><td>{row.expected_points:.1f}</td>" + _delta(row.points_gap)
                    + f"<td>{row.goals_for}–{row.goals_against}</td><td>{row.expected_for:.1f}–{row.expected_against:.1f}</td>"
                    + _delta(row.goals_for - row.goals_against - (row.expected_for - row.expected_against))
                    + f"<td>{row.average_xi:.1f}</td><td>{row.average_opponent_xi:.1f}</td></tr>")
    head = ["Rank", "Club", "P", "Pts", "Expected pts", "Pts − expected", "Goals", "Expected goals",
            "GD − expected", "Average XI fielded", "Average opposition XI"]
    return ("<section class='fm-workspace-panel' id='results'><h2>4 · Results against strength, every club</h2>"
            f"<p class='muted'>Each club's league season so far against what its XIs predicted, match by match, from "
            f"the line-ups both sides started with. Fitted on {model.matches} league matches: a 1-point XI-score "
            f"advantage was worth {model.goals_per_point():.2f} goals a match (± {model.slope_error / model.slope * model.goals_per_point():.2f}), "
            "and at equal strength the home side scored "
            f"{model.outcome(0, 0).home_goals:.2f} to {model.outcome(0, 0).away_goals:.2f}. Ranked by points from the "
            "matches recorded, so it can differ from FM's table where a match is missing; matches with a line-up we "
            "cannot score are left out of every column.</p>"
            + _table(head, rows, label="Results against strength") + "</section>")


_UNIT_INTRO = (
    "<p class='muted'>Each XI split by where each player was placed: <b>goalkeeper</b>; <b>defence</b> (centre-backs, "
    "full-backs, wing-backs); <b>midfield</b> (defensive midfielders and the midfield line, wide midfielders included); "
    "<b>attack</b> (attacking midfielders, wingers and strikers). A unit's score combines its players' own scores the "
    "way the XI's does, before the tactic's balance factor. Which line a wide player is in depends on the formation, "
    "so a 4-4-2's attack is its two strikers and a 4-3-3's is its front three.</p>"
)


def _unit_cells(units, ranks) -> str:
    cells = []
    for key, _name, _positions in UNITS:
        value = units.get(key)
        if value is None:
            cells.append("<td>—</td>")
        else:
            rank = ranks.get(key)
            # The rank is drawn by CSS from data-rank, so a copied table keeps a plain number.
            ranked = f" class='fm-hidden-ranked' data-rank='{_ordinal(rank)}'" if rank else ""
            cells.append(f"<td{ranked} data-sort='{value:.3f}'>{value:.1f}</td>")
    return "".join(cells)


def units_section(report: HiddenStrength) -> str:
    unit_head = [name for _key, name, _positions in UNITS]
    parts = ["<section class='fm-workspace-panel' id='units'><h2>5 · Defence, midfield and attack</h2>" + _UNIT_INTRO]
    if report.clubs:
        ordered = sorted(report.clubs, key=lambda row: (-row.average_xi, row.club.name))
        rows = [f"<tr{' class=our-club' if row.ours else ''}><td>{rank}</td><td>{_e(row.club.name)}{' · you' if row.ours else ''}</td>"
                + _unit_cells(row.average_units, report.fielded_unit_ranks.get(row.club.id, {}))
                + f"<td data-sort='{row.average_xi:.3f}'>{row.average_xi:.1f}</td></tr>"
                for rank, row in enumerate(ordered, 1)]
        parts.append("<h3>The XIs each club has fielded</h3><p class='muted'>Averaged over its league matches with both "
                     "line-ups scored; the small figure is the club's rank in that unit (left out of the "
                     "copies, so they paste as numbers).</p>"
                     + _table(["Rank", "Club", *unit_head, "Whole XI"], rows, label="The XIs each club has fielded, by unit"))
    if report.compared_tactics:
        main = report.compared_tactics[0]
        ordered = sorted(report.by_tactic, key=lambda row: (row.xis[main].score is None, -(row.xis[main].score or 0),
                                                            row.club.name))
        rows = [f"<tr{' class=our-club' if row.ours else ''}><td>{rank if row.xis[main].score is not None else '—'}</td>"
                f"<td>{_e(row.club.name)}{' · you' if row.ours else ''}</td>"
                + _unit_cells(row.xis[main].units, report.best_unit_ranks.get(row.club.id, {})) + _xi_cell(row.xis[main]) + "</tr>"
                for rank, row in enumerate(ordered, 1)]
        parts.append(f"<h3>Each club's best XI in {_e(report.tactic_names[main])}</h3>"
                     "<p class='muted'>The best XIs of section 2, unit by unit, in the tactic we played most.</p>"
                     + _table(["Rank", "Club", *unit_head, "Whole XI"], rows, label="Best XI by unit"))
    rows = []
    for row in report.our_matches:
        result = "W" if row.points == 3 else "D" if row.points == 1 else "L"
        rows.append(f"<tr><td class='fm-nowrap' data-sort='{row.match.date.isoformat()}'>{row.match.date.isoformat()}</td>"
                    f"<td><a href='#{_anchor(row)}'>{_e(row.opponent.name)}</a></td><td>{'H' if row.side == 'home' else 'A'}</td>"
                    f"<td class='fm-nowrap'><span class='fm-hidden-result' data-result='{result}'>{result}</span> "
                    f"{row.goals_for}–{row.goals_against}</td>"
                    + "".join(_delta(row.unit_gap(key)) for key, _name, _positions in UNITS)
                    + "".join(_delta(row.matchups[key]) for key, _mine, _theirs in MATCHUPS) + "</tr>")
    totals = report.our_totals
    foot = "" if totals is None else (
        f"<tr><th scope='row' colspan='4'>League average, {totals.matches} matches</th>"
        + "".join(_delta(totals.unit_gaps.get(key)) for key, _name, _positions in UNITS)
        + "".join(_delta(totals.matchups.get(key)) for key, _mine, _theirs in MATCHUPS) + "</tr>")
    parts.append("<h3>Our matches, unit against unit</h3><p class='muted'>Each figure is ours minus theirs, so a minus "
                 "means theirs was stronger. The last two set our back line against their forwards and our forwards "
                 "against their back line; both are how well players suit their jobs on the same 0–100 scale, so read "
                 "them as a rough guide.</p>"
                 + _table(["Date", "Opponent", "Venue", "Result", *unit_head, "Our defence vs their attack",
                           "Our attack vs their defence"], rows, foot=foot, label="Our matches, unit against unit"))
    return "".join(parts) + "</section>"


def _xi_list(xi: XiStrength, heading: str) -> str:
    if xi.score is None:
        why = "; ".join(xi.missing) or "not scored"
        return f"<div><h4>{_e(heading)}</h4><p class='muted'>Not scored: {_e(why)}</p></div>"
    return (f"<div><h4>{_e(heading)} · {xi.score:.1f}</h4><p class='fm-metric-note'>Scored in {_e(xi.tactic_name or '')}"
            + ("" if xi.exact_shape else ", the nearest shape our tactics have") + "</p><ol class='fm-hidden-xi'>"
            + "".join(f"<li><span>{_e(player.position)}</span><b>{_e(player.name)}</b><small>{_e(player.role_name)}</small>"
                      f"<em>{player.score:.1f}</em></li>" for player in xi.players) + "</ol></div>")


def line_ups_section(report: HiddenStrength) -> str:
    items = []
    for row in reversed(report.our_matches):
        match = row.match
        items.append(f"<details class='fm-disclosure' id='{_anchor(row)}'><summary>{match.date.isoformat()} · {_e(row.opponent.name)} "
                     f"({'H' if row.side == 'home' else 'A'}) {row.goals_for}–{row.goals_against}</summary>"
                     "<div class='fm-hidden-pair'>" + _xi_list(row.ours, "Our XI") + _xi_list(row.theirs, "Their XI")
                     + "</div></details>")
    return ("<section class='fm-workspace-panel' id='line-ups'><h2>Both XIs, match by match</h2>"
            "<p class='muted'>Each starter's own score in the XI, the role he was scored in, and where he started. "
            "Latest first.</p>" + "".join(items) + "</section>")


def method_section(report: HiddenStrength) -> str:
    notes = "".join(f"<li>{_e(note)}</li>" for note in report.capture.notes)
    return ("<section class='fm-workspace-panel' id='method'><details class='fm-disclosure'><summary>How this is worked "
            "out, and what it leaves out</summary><ul class='fm-hidden-method'>"
            "<li><b>The score.</b> The team model's XI score (0–100), exactly as the League page and the Tactics page "
            "compute it: role fit, tactic emphasis and tapers, position familiarity, and the tactic's balance. Here it "
            "uses each player's true attributes and FM's real position ratings, everyone fully fit, and no recent "
            "form, so it measures the players and nothing else.</li>"
            "<li><b>An XI as it started.</b> Each player stays where he started. The XI is scored in whichever of our "
            "tactics with that shape suits those eleven best, so a club is not marked down for roles we would not "
            "pick. Where our tactics have no such shape, the nearest stands in, and only the players it moves change "
            "position.</li>"
            "<li><b>Attributes are today's.</b> Every XI, however old the match, uses its players' attributes at the "
            f"read date ({report.capture.game_date.isoformat()}). FM keeps no record of past values.</li>"
            "<li><b>Expected points.</b> Each side's goals are a Poisson count whose rate rises with its XI-score "
            "advantage, fitted on every league match this season with both line-ups scored; the odds of a win, draw "
            "and defeat follow from the two rates. The usual run of luck is the spread of points those odds give.</li>"
            "<li><b>Not included.</b> Tactics, instructions, mentality, substitutes, injuries during a match, morale "
            "and FM's hidden personality attributes (consistency, big matches and so on). Whatever they are worth "
            "shows up as the gap between points and expected points.</li>"
            + notes + "</ul></details></section>")


def empty_page(message: str, server) -> str:
    return ("<section class='fm-decision-hero fm-hidden-hero'><span class='eyebrow'>League · hidden attributes</span>"
            "<h2>Is it the squad, or is it us?</h2>" + BANNER + f"<p>{message}</p>" + read_panel(server, first=True)
            + "</section>")
