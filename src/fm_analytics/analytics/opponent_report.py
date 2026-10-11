"""The opponent report: what a club does, from its own matches, before we play it.

Everything here comes from FM's own match reports, which FM shows for any
match in its archive, other clubs' included, and from the attributes FM shows
for their players. Nothing reads a value FM keeps private: the archive's
highlights list, with its chance-quality figures, is never read
(`tools/fm20_match_archive.py`).

The evidence is the club's most recent competitive matches with full stats
before the report's date (`as_of`), its matches against us included. A report
dated before a match uses nothing played on or after that day, so a report on
an old fixture reads as it would have that morning (docs phase 08's rule that
no post-match information leaks into a pre-match report).

It answers, with counts throughout:

* **their shape:** the formation FM names for each match, and the starters of
  the last five;
* **who finishes** and **who supplies** their goals, from the timeline (each
  goal's scorer, its assist and how it was scored, `goal_descriptions`);
* **how they score and concede:** from crosses (headed or not, and from which
  flank), set pieces, from distance, by period, and by which line scored,
  each against the league's share, with how often luck alone leaves a gap that
  large;
* **their style:** each panel figure per match, against the league's average
  and where they rank;
* **suggested opposition instructions**, from declared rules
  (`opposition_instructions`), each with the evidence behind it.

Its parts: `opponent_players` (who played where, who finishes and supplies),
`opponent_goals` (how goals came) and `opposition_instructions`.

"From a corner" and "at the far side" are guesses and always say so: FM's
goal record marks neither (`match_timeline.CORNER_GUESS`, `FAR_SIDE_GUESS`).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

from fm_analytics.analytics.chance_value import one_in
from fm_analytics.analytics.match_strength import TablePosition, league_seasons, positions
from fm_analytics.analytics.opponent_goals import GoalProfile, ProfileRow, count_goals, goal_profile
from fm_analytics.analytics.opponent_players import (
    RECENT,
    Partnership,
    PlayerLine,
    likely_xi,
    partnerships_in,
    player_lines,
    tally_players,
)
from fm_analytics.analytics.opposition_instructions import OppositionInstruction, suggest_instructions
from fm_analytics.domain.matches import LeagueResult, MatchRecord, ScheduledFixture, TeamRef
from fm_analytics.domain.models import Player

WINDOWS = (10, 20, 40)
DEFAULT_WINDOW = 20


@dataclass(frozen=True)
class Evidence:
    """Which matches the report rests on."""

    matches: int  # competitive matches with full stats, the window
    first: date | None
    last: date | None
    against_us: int
    window: int  # the most matches it would use
    # Their league results in that span FM's archive did not have, so not counted.
    league_results_missing: int = 0
    # Goals in the window whose timeline FM's archive did not keep: counted for
    # the score and their scorer, but not for how they were scored.
    goals_without_timeline: int = 0


@dataclass(frozen=True)
class FormEntry:
    date: date
    venue: str  # "H" or "A"
    opponent: str
    goals_for: int
    goals_against: int
    competition: str
    formation: str | None = None
    match_key: str | None = None  # ours, when it was against us
    against_us: bool = False

    @property
    def outcome(self) -> str:
        return "W" if self.goals_for > self.goals_against else "D" if self.goals_for == self.goals_against else "L"


@dataclass(frozen=True)
class FormationUse:
    name: str
    matches: int
    home: int
    away: int
    last_used: date


@dataclass(frozen=True)
class Formations:
    uses: tuple[FormationUse, ...]  # most used first
    known: int  # matches whose formation FM's archive names
    recent: tuple[str | None, ...]  # the last five, latest first
    against_us: str | None  # what they lined up in the last time they played us

    @property
    def usual(self) -> FormationUse | None:
        return self.uses[0] if self.uses else None


@dataclass(frozen=True)
class StyleFigure:
    key: str
    label: str
    value: float  # theirs, per match
    against: float  # their opponents', per match
    league: float | None  # every league team's, per match
    rank: int | None  # where they stand among the league's teams, 1 the most
    teams: int
    unit: str = ""  # "%" for percentages


@dataclass(frozen=True)
class Meeting:
    match_key: str
    date: date
    venue: str  # ours: "H" or "A"
    competition: str
    our_goals: int
    their_goals: int
    their_formation: str | None
    their_scorers: tuple[str, ...]

    @property
    def outcome(self) -> str:
        return "W" if self.our_goals > self.their_goals else "D" if self.our_goals == self.their_goals else "L"


@dataclass(frozen=True)
class OpponentReport:
    club: TeamRef
    as_of: date | None
    fixture: ScheduledFixture | None  # the match it is for, when known
    evidence: Evidence
    league_position: TablePosition | None
    league_name: str | None
    form: tuple[FormEntry, ...]  # latest first
    formations: Formations
    likely_xi: tuple[PlayerLine, ...]  # in FM's position order
    players: tuple[PlayerLine, ...]  # everyone who played, most minutes first
    finishers: tuple[PlayerLine, ...]
    suppliers: tuple[PlayerLine, ...]
    partnerships: tuple[Partnership, ...]
    scored: GoalProfile
    conceded: GoalProfile
    style: tuple[StyleFigure, ...]
    meetings: tuple[Meeting, ...]  # against us, latest first
    instructions: tuple[OppositionInstruction, ...]
    watch: tuple[str, ...]  # the few things to take from it, in words
    roster_date: date | None = None  # the league read their squad and attributes come from
    goals_for: int = 0
    goals_against: int = 0


def _competitive(match: MatchRecord) -> bool:
    return not match.competition.is_friendly


def _other(side: str) -> str:
    return "away" if side == "home" else "home"


def matches_of(club_id: str, matches: Iterable[MatchRecord], as_of: date | None) -> list[MatchRecord]:
    """The club's competitive matches before `as_of`, latest first, once each."""
    found: dict[str, MatchRecord] = {}
    for match in matches:
        if club_id in (match.home.id, match.away.id) and _competitive(match) and (as_of is None or match.date < as_of):
            found.setdefault(match.key, match)  # the first given wins
    return sorted(found.values(), key=lambda match: (match.date, match.key), reverse=True)


def _formations(matches: Sequence[MatchRecord], club_id: str, against_us: str | None) -> Formations:
    uses: dict[str, list] = {}
    known = 0
    for match in matches:
        side = match.side_of(club_id)
        name = match.detail.formations.get(side)
        if not name:
            continue
        known += 1
        entry = uses.setdefault(name, [0, 0, 0, match.date])
        entry[0] += 1
        entry[1 if side == "home" else 2] += 1
        entry[3] = max(entry[3], match.date)
    return Formations(
        uses=tuple(sorted(
            (FormationUse(name, *values) for name, values in uses.items()),
            key=lambda use: (-use.matches, -use.last_used.toordinal(), use.name),
        )),
        known=known,
        recent=tuple(match.detail.formations.get(match.side_of(club_id)) for match in matches[:RECENT]),
        against_us=against_us,
    )


STYLE = (
    ("possession", "Possession", "%"),
    ("shots", "Shots", ""),
    ("shots_on_target", "Shots on target", ""),
    ("clear_cut_chances", "Clear-cut chances", ""),
    ("corners", "Corners", ""),
    ("pass_completion", "Pass completion", "%"),
    ("passes_attempted", "Passes", ""),
    ("headers_attempted", "Headers contested", ""),
    ("tackles_attempted", "Tackles", ""),
    ("fouls", "Fouls", ""),
    ("yellow_cards", "Bookings", ""),
)


def _figures(match: MatchRecord, side: str) -> dict[str, float]:
    team = match.detail.team(side)
    figures = {key: float(team.get(key, 0)) for key, _label, _unit in STYLE if key in team}
    possession = match.detail.possession_percent(side)
    if possession is not None:
        figures["possession"] = float(possession)
    if team.get("passes_attempted"):
        figures["pass_completion"] = 100 * team.get("passes_completed", 0) / team["passes_attempted"]
    figures["yellow_cards"] = float(sum(1 for event in match.detail.events if event.side == side and event.kind == "yellow_card"))
    return figures


def _averages(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    sums: Counter = Counter()
    counts: Counter = Counter()
    for row in rows:
        for key, value in row.items():
            sums[key] += value
            counts[key] += 1
    return {key: sums[key] / counts[key] for key in sums}


def _style(
    matches: Sequence[MatchRecord], club_id: str, league_pool: Sequence[MatchRecord], league_teams: set[str]
) -> tuple[StyleFigure, ...]:
    theirs = _averages([_figures(match, match.side_of(club_id)) for match in matches])
    against = _averages([_figures(match, _other(match.side_of(club_id))) for match in matches])
    by_team: dict[str, list] = defaultdict(list)
    for match in league_pool:
        for side in ("home", "away"):
            team = match.team(side).id
            if team in league_teams:
                by_team[team].append(_figures(match, side))
    team_averages = {team: _averages(rows) for team, rows in by_team.items() if len(rows) >= 3}
    figures = []
    for key, label, unit in STYLE:
        if key not in theirs:
            continue
        values = sorted((averages[key] for team, averages in team_averages.items() if key in averages and team != club_id),
                        reverse=True)
        league = _averages([rows for team in team_averages for rows in by_team[team]]).get(key) if team_averages else None
        rank = 1 + sum(1 for value in values if value > theirs[key]) if values else None
        figures.append(StyleFigure(
            key, label, round(theirs[key], 1), round(against.get(key, 0.0), 1),
            round(league, 1) if league is not None else None, rank, len(values) + 1 if values else 0, unit,
        ))
    return tuple(figures)


def _finding(row: ProfileRow, total: int, verb: str) -> str:
    text = f"They {verb} {row.goals} of {total} goals {row.words}"
    if row.league_share is not None:
        text += f" ({row.share:.0%}; the league {row.league_share:.0%})"
    luck = f"luck alone does that {one_in(row.luck)}" if row.luck is not None else ""
    return text + (f": {luck}." if luck else ".")


def _watch(report_parts: dict) -> tuple[str, ...]:
    """The few things worth taking from the report, in words, each with its count.

    A way of scoring or conceding is named only when it is a pattern
    (`ProfileRow.pattern`) of at least 3 goals; "fewer than the league" only
    for how goals came, where scoring rarely from crosses, say, is worth
    knowing. Own goals and the corner guess are never findings.
    """
    lines: list[str] = []
    formations: Formations = report_parts["formations"]
    if formations.usual is not None and formations.known:
        usual = formations.usual
        if usual.matches == formations.known:
            text = f"Always {usual.name} in the {formations.known} matches FM names their shape for"
        else:
            text = f"Usually {usual.name}: {usual.matches} of the {formations.known} matches FM names their shape for"
            others = [use for use in formations.uses[1:] if use.matches >= 2]
            if others:
                text += "; also " + ", ".join(f"{use.name} ({use.matches})" for use in others[:2])
        lines.append(text + ".")
    finishers: Sequence[PlayerLine] = report_parts["finishers"]
    goals_for = report_parts["goals_for"]
    if finishers and finishers[0].goals >= 2:
        top = finishers[0]
        extra = f", {top.headed_goals} of them headers" if top.headed_goals else ""
        lines.append(f"{top.name} ({top.position or '?'}) scored {top.goals} of their {goals_for} goals{extra}.")
    suppliers: Sequence[PlayerLine] = report_parts["suppliers"]
    if suppliers and suppliers[0].assists >= 2:
        top = suppliers[0]
        extra = f", {top.assists_from_crosses} from crosses" if top.assists_from_crosses else ""
        if top.assists_possibly_corners:
            extra += f" ({top.assists_possibly_corners} possibly his corners, a guess)"
        lines.append(f"{top.name} ({top.position or '?'}) set up {top.assists} of their goals{extra}.")
    scored: GoalProfile = report_parts["scored"]
    conceded: GoalProfile = report_parts["conceded"]
    for profile, verb in ((scored, "scored"), (conceded, "conceded")):
        if not profile.described:
            continue
        notable = [
            (row, sum(item.goals for item in group))
            for name, group in (("how", profile.how), ("area", profile.area), ("lines", profile.lines),
                                ("periods", profile.periods), ("flanks", profile.cross_flanks))
            for row in group
            if row.pattern and not row.guess and row.key != "own_goal"
            and (row.pattern == "more" and row.goals >= 3 or row.pattern == "fewer" and name == "how")
        ]
        for row, total in sorted(notable, key=lambda item: item[0].luck or 1)[:2]:
            lines.append(_finding(row, total, verb))
    if scored.described:
        set_pieces = sum(scored.row(key).goals for key in ("penalty", "direct_free_kick", "possibly_corner") if scored.row(key))
        if set_pieces >= 3:
            corner = scored.row("possibly_corner")
            lines.append(
                f"{set_pieces} of their goals came from penalties, direct free kicks or possibly corners"
                + (f" ({corner.goals} of them the corner guess)" if corner and corner.goals else "") + "."
            )
    return tuple(lines[:8])


def _league_pool(
    pool: Sequence[MatchRecord], start: date | None, as_of: date | None, teams: set[str]
) -> list[MatchRecord]:
    return [
        match for match in pool
        if match.detail is not None and _competitive(match)
        and (start is None or match.date >= start) and (as_of is None or match.date < as_of)
        and (match.home.id in teams or match.away.id in teams)
    ]


def _league(
    league_results: Sequence[tuple], club_id: str, as_of: date | None
) -> tuple[TablePosition | None, str | None, set[str], list[LeagueResult]]:
    """Their league season as of the report's date: their position, its name, its teams and its results."""
    seasons = [
        season for season in league_seasons(league_results)
        if club_id in season.teams and (as_of is None or season.starts < as_of)
    ]
    if not seasons:
        return None, None, set(), []
    season = max(seasons, key=lambda item: item.starts)
    before = as_of or date.max
    table = positions(season.results, before)
    return table.get(club_id), season.competition.label, set(season.teams), list(season.results)


def _form(matches: Sequence[MatchRecord], club_id: str, league_results: Sequence[LeagueResult],
          as_of: date | None, ours: str | None) -> tuple[FormEntry, ...]:
    entries: dict[tuple, FormEntry] = {}
    for match in matches:
        side = match.side_of(club_id)
        other = _other(side)
        entries[(match.date, match.home.id, match.away.id)] = FormEntry(
            match.date, "H" if side == "home" else "A", match.team(other).name,
            match.goals(side), match.goals(other), match.competition.label,
            match.detail.formations.get(side) if match.detail else None,
            match.key if ours in (match.home.id, match.away.id) else None,
            ours in (match.home.id, match.away.id),
        )
    for result in league_results:
        if club_id not in (result.home.id, result.away.id) or (as_of is not None and result.date >= as_of):
            continue
        key = (result.date, result.home.id, result.away.id)
        if key in entries:
            continue
        home = result.home.id == club_id
        entries[key] = FormEntry(
            result.date, "H" if home else "A", (result.away if home else result.home).name,
            result.home_goals if home else result.away_goals, result.away_goals if home else result.home_goals,
            "League", None, None, ours in (result.home.id, result.away.id),
        )
    return tuple(sorted(entries.values(), key=lambda entry: entry.date, reverse=True))


def build_opponent_report(
    club: TeamRef,
    *,
    our_club_id: str,
    our_matches: Sequence[MatchRecord],
    club_matches: Sequence[MatchRecord],
    league_results: Sequence[tuple] = (),
    as_of: date | None = None,
    fixture: ScheduledFixture | None = None,
    window: int = DEFAULT_WINDOW,
    roster: Sequence[Player] | None = None,
    roster_date: date | None = None,
) -> OpponentReport:
    """The report on `club` from its matches before `as_of`: ours against it and every other one FM archived.

    `roster` is their squad as the latest league read saw it, with the
    attributes FM shows; without it no attribute is used.
    """
    if window not in WINDOWS:
        raise ValueError(f"the window must be one of {', '.join(map(str, WINDOWS))} matches")
    # Our own record of a match against them comes first: it has our names and notes' context.
    everything = list(our_matches) + list(club_matches)
    theirs = matches_of(club.id, everything, as_of)
    detailed = [match for match in theirs if match.detail is not None and match.detail.players][:window]
    position, league_name, league_teams, season_results = _league(league_results, club.id, as_of)
    first = detailed[-1].date if detailed else None
    last = detailed[0].date if detailed else None

    latest_five = {match.key for match in detailed[:RECENT]}
    roster_by_id = {player.id: player for player in roster} if roster is not None else None
    players = player_lines(tally_players(detailed, club.id, latest_five), roster_by_id)

    goals_for = sum(match.goals(match.side_of(club.id)) for match in detailed)
    goals_against = sum(match.goals(_other(match.side_of(club.id))) for match in detailed)
    teams = league_teams or {club.id}
    pool = _league_pool(everything, first, as_of, teams)
    league_sides = [(match, side) for match in pool for side in ("home", "away") if match.team(side).id in teams]
    league_scored, _without = count_goals(league_sides)
    league_conceded, _without = count_goals(
        ((match, _other(side)) for match, side in league_sides), conceded=True
    )
    scored_counts, without_for = count_goals((match, match.side_of(club.id)) for match in detailed)
    conceded_counts, without_against = count_goals(
        ((match, _other(match.side_of(club.id))) for match in detailed), conceded=True
    )

    missing = 0
    if first is not None:
        found = {(match.date, match.home.id, match.away.id) for match in theirs}
        missing = sum(
            1 for result in season_results
            if club.id in (result.home.id, result.away.id) and first <= result.date <= last
            and (result.date, result.home.id, result.away.id) not in found
        ) if season_results else 0

    against_us = next(
        (match for match in theirs if our_club_id in (match.home.id, match.away.id) and match.detail), None
    )
    formations = _formations(
        detailed, club.id, against_us.detail.formations.get(against_us.side_of(club.id)) if against_us else None
    )
    meetings = tuple(
        Meeting(
            match_key=match.key,
            date=match.date,
            venue="H" if match.home.id == our_club_id else "A",
            competition=match.competition.label,
            our_goals=match.goals(match.side_of(our_club_id)),
            their_goals=match.goals(match.side_of(club.id)),
            their_formation=match.detail.formations.get(match.side_of(club.id)) if match.detail else None,
            their_scorers=tuple(
                incident.player or "?" for incident in match.incidents
                if incident.side == match.side_of(club.id) and incident.kind in ("goal", "penalty")
            ),
        )
        for match in matches_of(club.id, our_matches, as_of)
        if our_club_id in (match.home.id, match.away.id)
    )
    finishers = tuple(sorted(
        (line for line in players if line.goals or line.shots >= 5),
        key=lambda line: (-line.goals, -line.shots, line.name),
    )[:6])
    suppliers = tuple(sorted(
        (line for line in players if line.assists or line.chances_created >= 3),
        key=lambda line: (-line.assists, -line.chances_created, -line.key_passes, line.name),
    )[:6])
    partnerships = partnerships_in(detailed, club.id, players)
    scored = goal_profile(scored_counts, league_scored if pool else None)
    conceded = goal_profile(conceded_counts, league_conceded if pool else None)
    parts = {
        "formations": formations, "finishers": finishers, "suppliers": suppliers,
        "scored": scored, "conceded": conceded, "goals_for": goals_for,
    }
    return OpponentReport(
        club=club,
        as_of=as_of,
        fixture=fixture,
        evidence=Evidence(
            matches=len(detailed), first=first, last=last,
            against_us=sum(1 for match in detailed if our_club_id in (match.home.id, match.away.id)),
            window=window, league_results_missing=missing,
            goals_without_timeline=without_for + without_against,
        ),
        league_position=position,
        league_name=league_name,
        form=_form(theirs, club.id, season_results, as_of, our_club_id)[:RECENT + 1],
        formations=formations,
        likely_xi=likely_xi(players),
        players=players,
        finishers=finishers,
        suppliers=suppliers,
        partnerships=partnerships,
        scored=scored,
        conceded=conceded,
        style=_style(detailed, club.id, pool, teams) if detailed else (),
        meetings=meetings,
        instructions=suggest_instructions(players),
        watch=_watch(parts),
        roster_date=roster_date,
        goals_for=goals_for,
        goals_against=goals_against,
    )


def next_fixture(
    fixtures: Sequence[ScheduledFixture], our_club_id: str, played: Iterable[MatchRecord], on_or_after: date
) -> ScheduledFixture | None:
    """Our first fixture on or after `on_or_after` that the history does not already hold as played."""
    done = {match.key for match in played}
    upcoming = [
        fixture for fixture in fixtures
        if fixture.date >= on_or_after and our_club_id in (fixture.home.id, fixture.away.id)
        and f"{fixture.date.isoformat()}:{fixture.home.id}:{fixture.away.id}" not in done
    ]
    return min(upcoming, key=lambda fixture: fixture.date, default=None)


@dataclass(frozen=True)
class OpponentChoice:
    """A club the Opponent page can report on, with our next fixture against it when one is scheduled."""

    club: TeamRef
    fixture: ScheduledFixture | None


def club_choices(
    our_club_id: str,
    league_results: Sequence[tuple],
    played: Iterable[MatchRecord],
    fixtures: tuple[date, tuple[ScheduledFixture, ...]] | None,
    last_read: date | None,
) -> tuple[OpponentChoice, ...]:
    """Every club in our current league season, and any other we have a fixture with: the next opponent first.

    `fixtures` is the game date of the capture that read FM's fixture list,
    and that list; a fixture before that day, or already played, is not next.
    """
    today = fixtures[0] if fixtures is not None else last_read
    clubs: dict[str, TeamRef] = {}
    seasons = [season for season in league_seasons(league_results) if our_club_id in season.teams]
    if seasons:
        latest = max(seasons, key=lambda season: season.starts)
        for result in latest.results:
            for team in (result.home, result.away):
                if team.id != our_club_id:
                    clubs.setdefault(team.id, team)
    upcoming: dict[str, ScheduledFixture] = {}
    done = {match.key for match in played}
    for fixture in sorted(fixtures[1] if fixtures else (), key=lambda item: item.date):
        if today is not None and fixture.date < today:
            continue
        if f"{fixture.date.isoformat()}:{fixture.home.id}:{fixture.away.id}" in done:
            continue
        opponent = fixture.opponent_of(our_club_id)
        clubs.setdefault(opponent.id, opponent)
        upcoming.setdefault(opponent.id, fixture)
    return tuple(sorted(
        (OpponentChoice(club, upcoming.get(club.id)) for club in clubs.values()),
        key=lambda choice: (choice.fixture is None, choice.fixture.date if choice.fixture else None, choice.club.name),
    ))
