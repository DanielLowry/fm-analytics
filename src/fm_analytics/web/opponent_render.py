"""The Opponent page: one club's report, from `reporting.build_opponent_report`.

Presentation only: every figure is the report's. The pitch places the
likely XI by the position each player most often started in, as FM's tactics
screen does (attacking upwards, their left on the left).
"""

from __future__ import annotations

import html
from typing import Sequence

from fm_analytics.analytics.match_timeline import CORNER_GUESS
from fm_analytics.analytics.opponent_goals import FAR_SIDE_GUESS, PATTERN_ODDS, GoalProfile, ProfileRow
from fm_analytics.analytics.opponent_players import LIKELY_STARTS, MIN_RATE_MINUTES, RECENT, PlayerLine
from fm_analytics.analytics.opponent_report import WINDOWS, OpponentReport
from fm_analytics.analytics.chance_value import one_in
from fm_analytics.web.match_render import chip, match_url


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _day(value) -> str:
    return f"{value.day} {value:%b %Y}" if value else "–"


def _long_day(value) -> str:
    return f"{value:%A} {value.day} {value:%B %Y}"


def _ordinal(number: int) -> str:
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _surname(name: str) -> str:
    return name.split(" ")[-1] if " " in name else name


def _rate(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}"


# -- the picker and the hero ------------------------------------------------


def opponent_picker(choices, current: str | None, window: int) -> str:
    """Pick a club (next opponent first) and how many of their matches to read."""
    def label(choice) -> str:
        if choice.fixture is None:
            return choice.club.name
        return f"{choice.club.name} · {choice.fixture.date.day} {choice.fixture.date:%b}"

    options = "".join(
        f"<option value='{_e(choice.club.id)}'{' selected' if choice.club.id == current else ''}>{_e(label(choice))}</option>"
        for choice in choices
    )
    windows = "".join(
        f"<option value='{size}'{' selected' if size == window else ''}>Last {size}</option>" for size in WINDOWS
    )
    return (
        "<form class='filters fm-opp-picker' method='get' action='/opponent'>"
        f"<label>Club<select name='club'>{options}</select></label>"
        f"<label>Their matches<select name='window'>{windows}</select></label>"
        "<button type='submit'>Show</button></form>"
    )


def _hero(report: OpponentReport, choices, window: int, our_club_id: str, copy_control: str) -> str:
    fixture = report.fixture
    if fixture is not None:
        venue = "we play at home" if fixture.home.id == our_club_id else "we play away"
        eyebrow = f"Opponent report · {fixture.competition.label}"
        fixture_line = (
            f"<p class='fm-opp-fixture'><b>{_e(_long_day(fixture.date))}</b> · {_e(fixture.home.name)} v "
            f"{_e(fixture.away.name)} · {venue}</p>"
        )
    else:
        eyebrow = "Opponent report"
        fixture_line = "<p class='fm-opp-fixture'>No fixture against them is scheduled in FM's fixture list.</p>"
    standing = ""
    if report.league_position is not None:
        table = report.league_position
        standing = (f"<span>{_ordinal(table.position)} of {table.teams} in {_e(report.league_name)}, "
                    f"{table.points} points from {table.played}</span>")
    form = ""
    if report.form:
        chips = "".join(
            f"<span class='fm-opp-form-item' title='{_e(f'{entry.date:%d %b} {entry.venue} {entry.opponent} {entry.goals_for}-{entry.goals_against}')}'>"
            + chip(entry.outcome) + "</span>"
            for entry in reversed(report.form)
        )
        form = f"<span class='fm-opp-form'>Form <span class='form-strip'>{chips}</span></span>"
    evidence = report.evidence
    if evidence.matches:
        evidence_text = (
            f"From their last <strong>{evidence.matches}</strong> competitive matches with full stats, "
            f"{_e(_day(evidence.first))} to {_e(_day(evidence.last))}"
            + (f" ({evidence.against_us} against us)" if evidence.against_us else "")
            + ", read from FM's match reports"
            + (", before this fixture" if fixture is not None else "")
            + "."
            + (f" {evidence.league_results_missing} of their league results in that time "
               f"{'is' if evidence.league_results_missing == 1 else 'are'} not in FM's archive, so not counted."
               if evidence.league_results_missing else "")
        )
    else:
        evidence_text = "No match of theirs with full stats is recorded before then."
    return (
        "<section class='fm-match-review-hero fm-opp-hero'>"
        "<div class='fm-opp-hero-top'><div>"
        f"<span class='eyebrow'>{_e(eyebrow)}</span><h2>{_e(report.club.name)}</h2>"
        + fixture_line
        + f"<p class='fm-opp-standing'>{standing}{form}</p>"
        + "</div>" + opponent_picker(choices, report.club.id, window) + "</div>"
        + f"<div class='fm-opp-hero-foot'><p>{evidence_text}</p>{copy_control}</div>"
        + "</section>"
    )


def _tiles(report: OpponentReport) -> str:
    evidence = report.evidence
    usual = report.formations.usual
    matches = evidence.matches or 1
    top_scorer = report.finishers[0] if report.finishers and report.finishers[0].goals else None
    supplier = report.suppliers[0] if report.suppliers and report.suppliers[0].assists else None
    possession = next((figure for figure in report.style if figure.key == "possession"), None)

    def tile(label: str, value: str, note: str) -> str:
        return f"<article class='fm-decision-stat'><span>{_e(label)}</span><b>{value}</b><small>{note}</small></article>"

    return (
        "<section class='fm-decision-grid fm-match-summary fm-opp-tiles' aria-label='Opponent summary'>"
        + tile("Usual shape", _e(usual.name) if usual else "Not known",
               f"{usual.matches} of {report.formations.known} matches FM names it for" if usual else "FM names none")
        + tile("Goals a match", f"{report.goals_for / matches:.1f} <i>for</i> · {report.goals_against / matches:.1f} <i>against</i>",
               f"{report.goals_for} scored, {report.goals_against} conceded in {evidence.matches}")
        + tile("Top scorer", _e(top_scorer.name) if top_scorer else "Nobody stands out",
               f"{top_scorer.goals} goals, {top_scorer.headed_goals} headed · {_e(top_scorer.position or '?')}" if top_scorer else "")
        + tile("Main supplier", _e(supplier.name) if supplier else "Nobody stands out",
               f"{supplier.assists} assists, {supplier.assists_from_crosses} from crosses · {_e(supplier.position or '?')}" if supplier else "")
        + (tile("Possession", f"{possession.value:.0f}%",
                f"{_ordinal(possession.rank)} of {possession.teams} in the league" if possession.rank else "")
           if possession else "")
        + "</section>"
    )


# -- panels -----------------------------------------------------------------


def _panel(title: str, description: str, content: str, *, panel_id: str, panel_class: str = "", actions: str = "") -> str:
    return (
        f"<section class='fm-workspace-panel fm-match-panel fm-opp-panel {panel_class}' id='{panel_id}'>"
        f"<div class='fm-panel-heading'><div><h2>{title}</h2><p>{description}</p></div>{actions}</div>"
        + content + "</section>"
    )


def _watch(report: OpponentReport) -> str:
    if not report.watch:
        return "<p class='muted'>Nothing stands out from what FM shows of their matches.</p>"
    return "<ul class='fm-opp-watch'>" + "".join(f"<li>{_e(item)}</li>" for item in report.watch) + "</ul>"


def _instructions(report: OpponentReport) -> str:
    if not report.instructions:
        return ("<p class='muted'>None: no player of theirs who is likely to play stands out on what FM shows. "
                "FM's defaults are a fair choice.</p>")
    cards = []
    for item in report.instructions:
        settings = "".join(
            f"<span class='fm-opp-setting'><small>{_e(column)}</small>{_e(value)}</span>"
            for column, value in item.settings
        )
        reasons = "".join(f"<li>{_e(reason)}</li>" for reason in item.reasons)
        cards.append(
            "<article class='fm-opp-instruction'>"
            f"<header><span class='fm-opp-position'>{_e(item.position or '?')}</span><h3>{_e(item.player)}</h3></header>"
            f"<div class='fm-opp-settings'>{settings}</div><ul>{reasons}</ul></article>"
        )
    return (
        "<div class='fm-opp-instructions'>" + "".join(cards) + "</div>"
        "<details class='fm-chances-method fm-opp-method'><summary>How these are chosen</summary>"
        f"<p>Only players who started at least {LIKELY_STARTS} of their last {RECENT} matches, and never the "
        "goalkeeper. Their goal threat (2+ non-penalty goals and a fifth of the team's, or the top scorer with 3) "
        "is marked tight, and shown onto his weaker foot when his goals are struck with his foot. A player who "
        "shoots 3 or more times a match is marked tight. Their supplier is closed down: always in the middle, "
        "where a playmaker given time picks the pass; more out wide, shown onto his weaker foot. A supplier whose "
        "assists were mostly crosses that may have been his own corners is left alone. Their best dribbler "
        "(3+ a match) is eased off and shown onto his weaker foot. Where FM shows a composure or first touch of "
        "8 or less for certain, he is closed down always (a striker is not: it pulls a centre-back out) and "
        "tackled hard. Nobody FM shows as two-footed is shown onto a foot. These are football rules of thumb "
        "applied to what FM shows, not fitted to results.</p></details>"
    )


_ROWS = {"GK": 92, "SW": 85, "DR": 76, "DC": 78, "DL": 76, "WBR": 61, "WBL": 61, "DM": 60,
         "MR": 44, "MC": 45, "ML": 44, "AMR": 26, "AMC": 28, "AML": 26, "ST": 11}
_LEFT_X, _RIGHT_X = 13, 87


def _pitch(players: Sequence[PlayerLine]) -> str:
    """The likely XI on a pitch, attacking upwards."""
    placed: list[tuple[float, float, PlayerLine]] = []
    rows: dict[int, list[PlayerLine]] = {}
    for line in players:
        position = line.position or "MC"
        y = _ROWS.get(position, 47)
        if position in ("DL", "WBL", "ML", "AML"):
            placed.append((_LEFT_X, y, line))
        elif position in ("DR", "WBR", "MR", "AMR"):
            placed.append((_RIGHT_X, y, line))
        else:
            rows.setdefault(y, []).append(line)
    order = {"left": 0, "centre": 1, "right": 2}
    for y, row in rows.items():
        row.sort(key=lambda line: order.get(line.side, 1))
        count = len(row)
        span = min(24 * (count - 1), 58)
        for index, line in enumerate(row):
            x = 50 if count == 1 else 50 - span / 2 + span * index / (count - 1)
            placed.append((x, y, line))
    dots = "".join(
        f"<div class='fm-opp-player' style='left:{x:.1f}%;top:{y:.1f}%' tabindex='0' "
        f"title='{_e(f'{line.name} · {line.position} · started {line.recent_starts} of the last {RECENT}, {line.starts} in all · {line.goals} goals, {line.assists} assists')}'>"
        f"<span class='fm-opp-dot'>{_e(line.position or '?')}</span>"
        f"<span class='fm-opp-name'>{_e(_surname(line.name))}</span>"
        f"<span class='fm-opp-starts'>{line.recent_starts}/{RECENT}</span></div>"
        for x, y, line in placed
    )
    return (
        "<div class='fm-opp-pitch' role='img' aria-label='Their likely starting eleven on a pitch'>"
        "<div class='fm-opp-pitch-lines'><i class='half'></i><i class='circle'></i><i class='box top'></i>"
        "<i class='box bottom'></i></div>" + dots + "</div>"
    )


def _shape(report: OpponentReport) -> str:
    formations = report.formations
    known = formations.known or 1
    uses = "".join(
        "<li class='fm-opp-bar-row'>"
        f"<span class='fm-opp-bar-label'>{_e(use.name)}</span>"
        f"<span class='fm-opp-track' title='{_e(f'{use.matches} of {formations.known} matches')}'>"
        f"<span class='fm-opp-bar' style='width:{100 * use.matches / known:.0f}%'></span></span>"
        f"<span class='fm-opp-bar-value'><b>{use.matches}</b> <small>{use.home} home · {use.away} away</small></span></li>"
        for use in formations.uses
    ) or "<li class='muted'>FM names no shape for their matches.</li>"
    recent = "".join(f"<span class='fm-opp-recent'>{_e(name or 'not named')}</span>" for name in formations.recent)
    against = (f"<p class='muted'>Against us last time: <b>{_e(formations.against_us)}</b>.</p>"
               if formations.against_us else "")
    xi = _pitch(report.likely_xi) if report.likely_xi else "<p class='muted'>No recent line-up is recorded.</p>"
    return (
        "<div class='fm-opp-shape'>"
        f"<div><h3>Likely starting XI</h3><p class='muted'>The eleven who started most of their last {RECENT} "
        "matches, at the position each most often started in. Each shows his starts of the last five.</p>"
        f"{xi}</div>"
        "<div><h3>Formations</h3><p class='muted'>The shape FM names for each match: a side FM's AI manages "
        "saves its tactic under its formation's name.</p>"
        f"<ul class='fm-opp-bars'>{uses}</ul>"
        f"<p class='fm-opp-recent-row'><span class='muted'>Last five, latest first</span>{recent}</p>{against}</div>"
        "</div>"
    )


def _player_table(lines: Sequence[PlayerLine], *, kind: str) -> str:
    if not lines:
        return "<p class='muted'>Nobody yet.</p>"
    if kind == "finishers":
        head = ("<tr><th>Player</th><th>Pos</th><th>Goals</th><th>Pens</th><th>Headers</th><th>From crosses</th>"
                "<th>Shots</th><th>On target</th><th>Clear-cut</th><th>Shots /90</th><th>Mins</th></tr>")
        rows = "".join(
            f"<tr><td>{_e(line.name)}</td><td>{_e(line.position or '?')}</td><td><b>{line.goals}</b></td>"
            f"<td>{line.penalties}</td><td>{line.headed_goals}</td><td>{line.goals_from_crosses}</td>"
            f"<td>{line.shots}</td><td>{line.shots_on_target}</td><td>{line.clear_cut_chances}</td>"
            f"<td data-sort='{line.per90(line.shots) or 0}'>{_rate(line.per90(line.shots))}</td><td>{line.minutes:,}</td></tr>"
            for line in lines
        )
    else:
        head = ("<tr><th>Player</th><th>Pos</th><th>Assists</th><th>From crosses</th><th>Chances created</th>"
                "<th>Key passes</th><th>Dribbles</th><th>Created /90</th><th>Mins</th></tr>")
        rows = "".join(
            f"<tr><td>{_e(line.name)}</td><td>{_e(line.position or '?')}</td><td><b>{line.assists}</b></td>"
            f"<td>{line.assists_from_crosses}"
            + (f" <small class='muted' title='{_e(CORNER_GUESS)}'>({line.assists_possibly_corners} corner?)</small>"
               if line.assists_possibly_corners else "")
            + f"</td><td>{line.chances_created}</td><td>{line.key_passes}</td><td>{line.dribbles}</td>"
            f"<td data-sort='{line.per90(line.chances_created) or 0}'>{_rate(line.per90(line.chances_created))}</td>"
            f"<td>{line.minutes:,}</td></tr>"
            for line in lines
        )
    return f"<div class='table-scroll'><table data-fm-plain><thead>{head}</thead><tbody>{rows}</tbody></table></div>"


def _threats(report: OpponentReport) -> str:
    partnerships = ""
    if report.partnerships:
        partnerships = (
            "<h3>Partnerships</h3><ul class='fm-opp-pairs'>" + "".join(
                f"<li><b>{_e(pair.supplier)}</b> <span aria-hidden='true'>→</span><span class='fm-opp-sr'>to</span> "
                f"<b>{_e(pair.scorer)}</b> <span class='muted'>{pair.goals} goals"
                + (f", {pair.from_crosses} from crosses" if pair.from_crosses else "") + "</span></li>"
                for pair in report.partnerships
            ) + "</ul>"
        )
    return (
        "<div class='fm-opp-threats'>"
        f"<div><h3>Who finishes</h3>{_player_table(report.finishers, kind='finishers')}</div>"
        f"<div><h3>Who supplies</h3>{_player_table(report.suppliers, kind='suppliers')}{partnerships}</div>"
        "</div>"
        f"<p class='muted fm-opp-footnote'>Goals and assists come from each match's timeline; per-90 figures need "
        f"{MIN_RATE_MINUTES} minutes. A cross from a player who took corners in that match may have been a corner: "
        "that is a guess.</p>"
    )


def _profile_rows(rows: Sequence[ProfileRow], *, hide_empty: bool = True) -> str:
    items = []
    for row in rows:
        if hide_empty and not row.goals and not row.pattern:
            continue
        league = row.league_share
        tick = (f"<span class='fm-opp-league' style='left:{100 * league:.0f}%'></span>" if league is not None else "")
        badge = ""
        if row.pattern and not row.guess:
            words = "More than the league" if row.pattern == "more" else "Fewer than the league"
            badge = (f"<span class='fm-opp-pattern {row.pattern}' title='{_e(f'Luck alone does that {one_in(row.luck)}')}'>"
                     f"{words}</span>")
        title = f"{row.goals} goals, {row.share:.0%}" + (f"; the league {league:.0%}" if league is not None else "")
        items.append(
            f"<li class='fm-opp-bar-row{' guess' if row.guess else ''}'>"
            f"<span class='fm-opp-bar-label'>{_e(row.label)}{badge}</span>"
            f"<span class='fm-opp-track' title='{_e(title)}'><span class='fm-opp-bar' style='width:{100 * row.share:.0f}%'></span>{tick}</span>"
            f"<span class='fm-opp-bar-value'><b>{row.goals}</b> <small>{row.share:.0%}"
            + (f" · league {league:.0%}" if league is not None else "") + "</small></span></li>"
        )
    return "<ul class='fm-opp-bars'>" + "".join(items) + "</ul>" if items else "<p class='muted'>None.</p>"


def _profile(profile: GoalProfile, title: str, verb: str) -> str:
    if not profile.goals:
        return f"<article class='fm-opp-profile'><h3>{title}</h3><p class='muted'>No goals {verb}.</p></article>"
    note = ""
    if profile.described < profile.goals:
        note = (f"<p class='muted'>{profile.goals - profile.described} of {profile.goals} have no description in FM's "
                "record (no timeline was kept), so they are left out of how.</p>")
    far = ""
    if profile.flank_crosses:
        far = (f"<p class='muted fm-opp-far' title='{_e(FAR_SIDE_GUESS)}'>Met at the far side (a guess): "
               f"<b>{profile.far_side}</b> of {profile.flank_crosses} crosses from a flank.</p>")
    return (
        f"<article class='fm-opp-profile'><h3>{title} <small>{profile.goals} goals</small></h3>{note}"
        f"<h4>How</h4>{_profile_rows(profile.how)}"
        f"<h4>Where from</h4>{_profile_rows(profile.area)}"
        f"<h4>Crosses by flank</h4>{_profile_rows(profile.cross_flanks)}{far}"
        f"<h4>Who scored them</h4>{_profile_rows(profile.lines)}"
        f"<h4>When</h4>{_profile_rows(profile.periods, hide_empty=False)}"
        "</article>"
    )


def _goals(report: OpponentReport) -> str:
    return (
        "<div class='fm-opp-profiles'>"
        + _profile(report.scored, "How they score", "scored")
        + _profile(report.conceded, "How they concede", "conceded")
        + "</div>"
        "<p class='muted fm-opp-footnote'>Each bar is their share; the grey tick is the share of every goal in "
        "the league's matches over the same weeks. “More (or fewer) than the league” means luck alone leaves a "
        f"gap that large less often than 1 time in {round(1 / PATTERN_ODDS)}; hover it for how often. Crosses are "
        "by the crosser's position, from their side's point of view: a cross they conceded from the attacker's "
        "right came down their left. Corners are left out of the flanks. " + _e(CORNER_GUESS) + "</p>"
    )


def _style(report: OpponentReport) -> str:
    if not report.style:
        return "<p class='muted'>No match with full stats.</p>"
    rows = []
    for figure in report.style:
        unit = figure.unit
        rank = ""
        if figure.rank:
            tone = " high" if figure.rank <= 3 else " low" if figure.rank > figure.teams - 3 else ""
            rank = f"<span class='fm-opp-rank{tone}'>{_ordinal(figure.rank)} of {figure.teams}</span>"
        league = "–" if figure.league is None else f"{figure.league:g}{unit}"
        rows.append(
            f"<tr><th scope='row'>{_e(figure.label)}</th><td><b>{figure.value:g}{unit}</b></td>"
            f"<td>{figure.against:g}{unit}</td><td>{league}</td><td data-sort='{figure.rank or 0}'>{rank}</td></tr>"
        )
    return (
        "<div class='table-scroll fm-opp-style'><table data-fm-plain><thead><tr><th>Per match</th><th>Them</th>"
        "<th>Their opponents</th><th>League average</th><th>Their rank (1 = most)</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _meetings(report: OpponentReport) -> str:
    if not report.meetings:
        return "<p class='muted'>We have not played them in the matches recorded.</p>"
    rows = "".join(
        f"<tr><td><a href='{_e(match_url(meeting.match_key))}'>{_e(_day(meeting.date))}</a></td>"
        f"<td>{_e(meeting.competition)}</td><td>{'Home' if meeting.venue == 'H' else 'Away'}</td>"
        f"<td>{chip(meeting.outcome)} {meeting.our_goals}–{meeting.their_goals}</td>"
        f"<td>{_e(meeting.their_formation or '–')}</td><td>{_e(', '.join(meeting.their_scorers) or '–')}</td></tr>"
        for meeting in report.meetings
    )
    return (
        "<div class='table-scroll'><table data-fm-plain><thead><tr><th>Date</th><th>Competition</th><th>Venue</th>"
        "<th>Result (us first)</th><th>Their shape</th><th>Their scorers</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _everyone(report: OpponentReport) -> str:
    rows = "".join(
        f"<tr><td>{_e(line.name)}</td><td>{_e(line.position or '?')}</td><td>{line.appearances}</td><td>{line.starts}</td>"
        f"<td>{line.recent_starts}</td><td>{line.minutes:,}</td><td>{line.goals}</td><td>{line.assists}</td>"
        f"<td>{line.shots}</td><td>{line.chances_created}</td><td>{line.dribbles}</td>"
        f"<td>{line.headers_won}/{line.headers_attempted}</td><td>{line.yellow_cards}</td>"
        f"<td data-sort='{line.average_rating or 0}'>{'–' if line.average_rating is None else f'{line.average_rating:.2f}'}</td>"
        f"<td data-sort='{line.last_played.toordinal() if line.last_played else 0}'>{_e(_day(line.last_played))}</td></tr>"
        for line in report.players
    )
    return (
        "<div class='table-scroll'><table class='sortable'><thead><tr><th>Player</th><th>Pos</th><th>Apps</th>"
        f"<th>Starts</th><th>Of last {RECENT}</th><th>Mins</th><th>Goals</th><th>Assists</th><th>Shots</th>"
        "<th>Chances created</th><th>Dribbles</th><th>Headers won</th><th>Booked</th><th>Avg rating</th>"
        f"<th>Last played</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def opponent_body(report: OpponentReport, choices, *, window: int, our_club_id: str, copy_control: str = "") -> str:
    """The whole Opponent page for one club."""
    hero = _hero(report, choices, window, our_club_id, copy_control)
    if not report.evidence.matches:
        return hero + (
            "<section class='fm-workspace-panel'><p>FM's archive has no match of theirs with full stats before "
            "then. <strong>Read matches from FM</strong> on the Matches page reads every league club's archived "
            "matches as well as ours.</p></section>"
        )
    roster = (f" Attributes are the ones FM showed at the league read of {_e(_day(report.roster_date))}."
              if report.roster_date else " Without a league read, no attribute of theirs is used.")
    return (
        "<nav class='fm-section-nav' aria-label='Opponent report sections'>"
        "<a href='#opp-watch'>Key points</a><a href='#opp-instructions'>Instructions</a><a href='#opp-shape'>Shape</a>"
        "<a href='#opp-threats'>Threats</a><a href='#opp-goals'>How goals come</a><a href='#opp-style'>Style</a>"
        "<a href='#opp-meetings'>Against us</a></nav>"
        + hero
        + _tiles(report)
        + _panel("What to take from it", "The few things that stand out, each with its count.",
                 _watch(report), panel_id="opp-watch", panel_class="fm-opp-watch-panel")
        + _panel("Suggested opposition instructions",
                 "For FM's Opposition Instructions, player by player, with the evidence for each." + roster,
                 _instructions(report), panel_id="opp-instructions")
        + _panel("Their shape", "How they line up, from their recent team sheets.", _shape(report), panel_id="opp-shape")
        + _panel("Who finishes, who supplies", "Their players over the same matches.", _threats(report),
                 panel_id="opp-threats")
        + _panel("How their goals come", "Scored and conceded, from FM's description of each goal.",
                 _goals(report), panel_id="opp-goals")
        + _panel("Style", "FM's match stats per match, against their opponents' and every league team's.",
                 _style(report), panel_id="opp-style")
        + _panel("Against us", "Every recorded meeting; open one for its full match page.", _meetings(report),
                 panel_id="opp-meetings")
        + "<details class='fm-workspace-panel fm-disclosure' id='opp-players'><summary>Every player they used</summary>"
        + _everyone(report) + "</details>"
    )


def opponent_empty(choices, window: int, message: str) -> str:
    """The page without a report: why, and the picker."""
    picker = opponent_picker(choices, None, window) if choices else ""
    return (
        "<section class='fm-match-review-hero fm-opp-hero'><span class='eyebrow'>Opponent report</span>"
        f"<h2>Who are we playing?</h2><p>{message}</p>{picker}</section>"
    )
