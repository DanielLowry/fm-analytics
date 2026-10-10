"""Match review: how our matches played out, by opposition strength, tactic and role.

Everything is counted from what FM showed on its match screens, captured by
`tools/fm20_match_probe.py` and kept in the match history. The review
describes; it does not judge. Every group carries its match count, groups
under `MIN_GROUP_MATCHES` are flagged as too small to read, and nothing here
says one tactic is better than another. A season is about 50 matches spread
across several groups, so most cells are small.

Results exist for every match. Shots, possession and the other panel stats
exist only for matches whose full stats were captured, so their averages are
over those matches alone, and each group says how many that is.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.appearance_context import appearance_roles
from fm_analytics.analytics.match_players import PlayerSeason, summarise_players
from fm_analytics.analytics.match_roles import RoleCodes, RoleSummary, summarise_roles
from fm_analytics.analytics.match_timeline import MatchTimeline, build_timeline
from fm_analytics.analytics.penalty_record import ConcededPenalty, PenaltyKey, conceded_penalties
from fm_analytics.analytics.match_strength import (
    BANDS,
    GROUPING_LABELS,
    GROUPINGS,
    Band,
    Strength,
    StrengthCalculator,
)
from fm_analytics.domain.matches import MATCH_MINUTES, Competition, LeagueResult, MatchRecord, TeamRef
from fm_analytics.domain.mentality import MentalityPlan

MIN_GROUP_MATCHES = 5
COMPETITION_SCOPES = ("league", "competitive", "all")
COMPETITION_SCOPE_LABELS = {
    "league": "League only",
    "competitive": "League and cups",
    "all": "Everything, friendlies included",
}
# (key, label, is a percentage) for the per-side averages.
METRICS: tuple[tuple[str, str, bool], ...] = (
    ("shots", "Shots", False),
    ("shots_on_target", "On target", False),
    ("off_target", "Off target", False),
    ("clear_cut_chances", "Clear-cut chances", False),
    ("possession", "Possession", True),
    ("corners", "Corners", False),
    ("fouls", "Fouls", False),
    ("pass_completion", "Passes completed", True),
    ("tackles_won", "Tackles won", True),
    ("headers_won", "Headers won", True),
)
PERIODS: tuple[tuple[str, int, int], ...] = (
    ("1-15", 0, 15), ("16-30", 16, 30), ("31-45", 31, 45),
    ("46-60", 46, 60), ("61-75", 61, 75), ("76-90", 76, 90), ("90+", 91, 200),
)
NO_TACTIC = "none"


@dataclass(frozen=True)
class ReviewFilters:
    grouping: str = "table"
    competitions: str = "competitive"
    venue: str | None = None  # "home" | "away"
    tactic: str | None = None  # a tactic key, or NO_TACTIC for "not known"
    season: int | None = None  # the year it starts (2019 for 2019/20); see `match_seasons`

    def __post_init__(self) -> None:
        if self.grouping not in GROUPINGS:
            raise ValueError(f"grouping must be one of {', '.join(GROUPINGS)}")
        if self.competitions not in COMPETITION_SCOPES:
            raise ValueError(f"competitions must be one of {', '.join(COMPETITION_SCOPES)}")
        if self.venue not in (None, "home", "away"):
            raise ValueError("venue must be home or away")
        if self.season is not None and not isinstance(self.season, int):
            raise ValueError("season must be the year it starts, e.g. 2019 for 2019/20")


def season_label(season: int) -> str:
    """A season as FM names it, from the year it starts: 2019 is 2019/20."""
    return f"{season}/{(season + 1) % 100:02d}"


def match_seasons(matches: Iterable[MatchRecord]) -> dict[str, int | None]:
    """The season each match belongs to, by match key.

    FM files every competitive match under a season. A friendly has none, so
    it takes the season of the next match FM did file: a pre-season friendly
    belongs to the season it leads into. A friendly after the last filed match
    takes that match's season, so pre-season friendlies read before the new
    season's first competitive match count in the old season until it is read.
    None only when no match has a season.
    """
    ordered = sorted(matches, key=lambda match: match.date)
    latest = next((match.season for match in reversed(ordered) if match.season is not None), None)
    seasons: dict[str, int | None] = {}
    following = latest
    for match in reversed(ordered):
        if match.season is not None:
            following = match.season
        seasons[match.key] = following
    return seasons


def _percent(part: int, whole: int) -> float | None:
    return 100 * part / whole if whole else None


def side_metrics(match: MatchRecord, side: str) -> dict[str, float | None] | None:
    """One side's panel stats for a match with full stats, else None."""
    detail = match.detail
    if detail is None:
        return None
    team = detail.team(side)
    players = detail.players_for(side)
    # FM's panel counts a blocked shot as neither on nor off target.
    off_target = (
        team["shots"] - team["shots_on_target"]
        - sum(player.stat("shots_blocked") for player in players)
        if players and "shots" in team and "shots_on_target" in team else None
    )
    return {
        # A missing panel value is unknown, not a zero.  The diagnostic gate
        # relies on that distinction and older partial captures remain honest.
        "shots": team.get("shots"),
        "shots_on_target": team.get("shots_on_target"),
        "off_target": off_target,
        "clear_cut_chances": team.get("clear_cut_chances"),
        "possession": detail.possession_percent(side),
        "corners": team.get("corners"),
        "fouls": team.get("fouls"),
        "pass_completion": _percent(team.get("passes_completed", 0), team.get("passes_attempted", 0)),
        "tackles_won": _percent(team.get("tackles_won", 0), team.get("tackles_attempted", 0)),
        "headers_won": _percent(team.get("headers_won", 0), team.get("headers_attempted", 0)),
    }


@dataclass(frozen=True)
class MatchSummary:
    match: MatchRecord
    side: str
    opponent: TeamRef
    goals_for: int
    goals_against: int
    strength: Strength
    band: Band
    tactic_key: str | None
    tactic_inferred: bool
    ours: Mapping[str, float | None] | None
    theirs: Mapping[str, float | None] | None
    note: str = ""
    mentality: MentalityPlan | None = None  # as you recorded it; FM keeps none we can read

    @property
    def result(self) -> str:
        return "W" if self.goals_for > self.goals_against else "D" if self.goals_for == self.goals_against else "L"

    @property
    def venue(self) -> str:
        return "Home" if self.side == "home" else "Away"


@dataclass(frozen=True)
class GroupSummary:
    key: str
    label: str
    matches: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    detailed: int = 0
    averages_for: Mapping[str, float | None] = field(default_factory=dict)
    averages_against: Mapping[str, float | None] = field(default_factory=dict)

    @property
    def points(self) -> int:
        return 3 * self.wins + self.draws

    @property
    def points_per_game(self) -> float | None:
        return self.points / self.matches if self.matches else None

    @property
    def enough(self) -> bool:
        return self.matches >= MIN_GROUP_MATCHES


def summarise_group(key: str, label: str, summaries: Sequence[MatchSummary]) -> GroupSummary:
    detailed = [summary for summary in summaries if summary.ours is not None]

    def averages(which: str) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for metric, _label, _percentage in METRICS:
            values = [getattr(summary, which)[metric] for summary in detailed]
            values = [value for value in values if value is not None]
            result[metric] = sum(values) / len(values) if values else None
        return result

    results = Counter(summary.result for summary in summaries)
    return GroupSummary(
        key=key,
        label=label,
        matches=len(summaries),
        wins=results["W"],
        draws=results["D"],
        losses=results["L"],
        goals_for=sum(summary.goals_for for summary in summaries),
        goals_against=sum(summary.goals_against for summary in summaries),
        detailed=len(detailed),
        averages_for=averages("ours"),
        averages_against=averages("theirs"),
    )


@dataclass(frozen=True)
class GoalBreakdown:
    """When goals came and which roles scored and made them (full-stats matches)."""

    periods: tuple[str, ...]
    scored: tuple[int, ...]
    conceded: tuple[int, ...]
    scorers: tuple[tuple[str, int], ...]
    assisters: tuple[tuple[str, int], ...]
    conceded_to: tuple[tuple[str, int], ...]
    goals_for_covered: int
    goals_for_total: int
    goals_against_covered: int
    goals_against_total: int
    # Goal minutes come from each result's goals and sendings-off, which every
    # match captured since 30 September 2026 has, else from the timeline of a
    # match FM still held in memory; the period chart counts only matches whose
    # every goal is timed.
    timed_matches: int = 0
    timed_goals_for: int = 0
    timed_goals_against: int = 0
    # From the same incidents: penalties and own goals for and against, and
    # players sent off on each side.
    penalties_for: int = 0
    penalties_against: int = 0
    own_goals_for: int = 0
    own_goals_against: int = 0
    sent_off_ours: int = 0
    sent_off_theirs: int = 0


@dataclass(frozen=True)
class UnconfirmedRoleCode:
    code: int
    appearances: int
    examples: tuple[str, ...]


@dataclass(frozen=True)
class TacticRow:
    tactic_key: str | None
    label: str
    overall: GroupSummary
    by_band: Mapping[str, GroupSummary]


@dataclass(frozen=True)
class MatchReview:
    club: TeamRef
    filters: ReviewFilters
    grouping_label: str
    bands: tuple[Band, ...]
    matches: tuple[MatchSummary, ...]
    groups: tuple[GroupSummary, ...]
    venues: tuple[GroupSummary, ...]
    tactics: tuple[TacticRow, ...]
    goals: GoalBreakdown
    roles: tuple[RoleSummary, ...]
    players: tuple[PlayerSeason, ...]
    unconfirmed_roles: tuple[UnconfirmedRoleCode, ...]
    leagues: tuple[Competition, ...]
    excluded: int
    # (match key, side, short ID) -> the role each player played; see `appearance_roles`.
    appearance_roles: Mapping[tuple[str, str, int], str] = field(default_factory=dict)
    # Every season in the history, newest first, whatever the filters select.
    seasons: tuple[int, ...] = ()

    @property
    def overall(self) -> GroupSummary:
        return summarise_group("all", "All matches", self.matches)


def _in_scope(match: MatchRecord, scope: str, league_ids: set[str]) -> bool:
    if scope == "league":
        return match.competition.id in league_ids
    if scope == "competitive":
        return not match.competition.is_friendly
    return True


def summarise_matches(
    matches: Iterable[MatchRecord],
    leagues: Sequence[tuple[Competition, Sequence[LeagueResult]]],
    club: TeamRef,
    *,
    notes: Mapping[str, object],
    codes: RoleCodes,
    grouping: str,
    mentalities: Mapping[str, MentalityPlan] = {},
) -> tuple[MatchSummary, ...]:
    calculator = StrengthCalculator(leagues, club.id)
    summaries = []
    for match in matches:
        side = match.side_of(club.id)
        other = "away" if side == "home" else "home"
        note = notes.get(match.key)
        tactic_key = getattr(note, "tactic_key", None)
        inferred = False
        if tactic_key is None and match.detail is not None:
            tactic_key = codes.infer_tactic(
                player for player in match.detail.players_for(side) if player.started
            )
            inferred = tactic_key is not None
        strength = calculator.strength(match, match.team(other).id, getattr(note, "opponent_rating", None))
        summaries.append(
            MatchSummary(
                match=match,
                side=side,
                opponent=match.team(other),
                goals_for=match.goals(side),
                goals_against=match.goals(other),
                strength=strength,
                band=strength.band(grouping),
                tactic_key=tactic_key,
                tactic_inferred=inferred,
                ours=side_metrics(match, side),
                theirs=side_metrics(match, other),
                note=getattr(note, "note", "") or "",
                mentality=mentalities.get(match.key),
            )
        )
    return tuple(summaries)


def _period(minute: int, added_time: int = 0) -> str:
    """A goal's period; first-half added time stays in 31-45, second-half added time is 90+."""
    if minute >= MATCH_MINUTES and added_time:
        minute += added_time
    return next(label for label, low, high in PERIODS if low <= minute <= high)


def _goal_breakdown(
    summaries: Sequence[MatchSummary], codes: RoleCodes, roles: Mapping[tuple[str, str, int], str]
) -> GoalBreakdown:
    scored, conceded = Counter(), Counter()
    scorers, assisters, conceded_to = Counter(), Counter(), Counter()
    incidents = Counter()
    covered_for = covered_against = 0
    timed = timed_for = timed_against = 0
    for summary in summaries:
        match, detail = summary.match, summary.match.detail
        goals = [incident for incident in match.incidents if incident.is_goal]
        events = [event for event in detail.events if event.kind == "goal"] if detail else []
        if len(goals) == summary.goals_for + summary.goals_against:
            timed_by = [(goal.side, _period(goal.minute, goal.added_time)) for goal in goals]
        elif detail and (events or (detail.events and not summary.goals_for and not summary.goals_against)):
            timed_by = [(event.side, _period(event.minute)) for event in events]
        else:
            timed_by = None
        if timed_by is not None:
            timed += 1
            timed_for += summary.goals_for
            timed_against += summary.goals_against
            for side, period in timed_by:
                (scored if side == summary.side else conceded)[period] += 1
        for incident in match.incidents:
            ours = incident.side == summary.side
            if incident.kind in ("penalty", "own_goal"):
                incidents[f"{incident.kind}_{'for' if ours else 'against'}"] += 1
            elif incident.kind == "sent_off":
                incidents["sent_off_ours" if ours else "sent_off_theirs"] += 1
        if detail is None:
            continue
        covered_for += summary.goals_for
        covered_against += summary.goals_against
        for player in detail.players:
            role = roles.get((match.key, player.side, player.short_id)) or codes.label(player.role_code, player.position)
            if player.side == summary.side:
                if player.stat("goals"):
                    scorers[role] += player.stat("goals")
                if player.stat("assists"):
                    assisters[role] += player.stat("assists")
            elif player.stat("goals"):
                conceded_to[role] += player.stat("goals")
    labels = tuple(label for label, _low, _high in PERIODS)
    return GoalBreakdown(
        periods=labels,
        scored=tuple(scored[label] for label in labels),
        conceded=tuple(conceded[label] for label in labels),
        scorers=tuple(scorers.most_common()),
        assisters=tuple(assisters.most_common()),
        conceded_to=tuple(conceded_to.most_common()),
        goals_for_covered=covered_for,
        goals_for_total=sum(summary.goals_for for summary in summaries),
        goals_against_covered=covered_against,
        goals_against_total=sum(summary.goals_against for summary in summaries),
        timed_matches=timed,
        timed_goals_for=timed_for,
        timed_goals_against=timed_against,
        penalties_for=incidents["penalty_for"],
        penalties_against=incidents["penalty_against"],
        own_goals_for=incidents["own_goal_for"],
        own_goals_against=incidents["own_goal_against"],
        sent_off_ours=incidents["sent_off_ours"],
        sent_off_theirs=incidents["sent_off_theirs"],
    )


def _unconfirmed(summaries: Sequence[MatchSummary], codes: RoleCodes) -> tuple[UnconfirmedRoleCode, ...]:
    seen: dict[int, list[str]] = {}
    for summary in summaries:
        if summary.match.detail is None:
            continue
        for player in summary.match.detail.players_for(summary.side):
            if player.played and player.role_code and codes.role_key(player.role_code) is None:
                seen.setdefault(player.role_code, []).append(
                    f"{player.label}, {summary.match.date:%d %b} v {summary.opponent.name}"
                )
    return tuple(
        UnconfirmedRoleCode(code, len(examples), tuple(examples[:3]))
        for code, examples in sorted(seen.items(), key=lambda item: -len(item[1]))
    )


@dataclass(frozen=True)
class MatchReport:
    """One match as the match page shows it: its summary and its role names."""

    summary: MatchSummary
    role_labels: Mapping[tuple[str, int], str]  # (side, short ID) -> the role he played
    timeline: MatchTimeline | None = None  # None without match detail
    # Penalties scored against us, with the manager's record of who gave each away.
    penalties: tuple[ConcededPenalty, ...] = ()


def report_match(
    match_key: str,
    matches: Sequence[MatchRecord],
    leagues: Sequence[tuple[Competition, Sequence[LeagueResult]]],
    club: TeamRef,
    *,
    catalogue: FootballCatalogue,
    notes: Mapping[str, object] = {},
    confirmed_role_codes: Mapping[int, str] = {},
    usual_roles: Mapping[tuple[str, str], str] = {},
    penalty_fouls: Mapping[PenaltyKey, int] = {},
    mentalities: Mapping[str, MentalityPlan] = {},
) -> MatchReport | None:
    codes = RoleCodes.build(catalogue, confirmed_role_codes)
    match = next((match for match in matches if match.key == match_key), None)
    if match is None:
        return None
    (summary,) = summarise_matches([match], leagues, club, notes=notes, codes=codes, grouping="table",
                                   mentalities=mentalities)
    roles = appearance_roles([match], club.id, notes=notes, codes=codes, usual_roles=usual_roles)
    penalties = conceded_penalties(match, club.id, penalty_fouls)
    return MatchReport(
        summary,
        {(side, short_id): role for (_key, side, short_id), role in roles.items()},
        build_timeline(match, summary.side, mentality=summary.mentality, given_away={
            (penalty.minute, penalty.added_time): penalty.given_away_by for penalty in penalties if penalty.given_away_by
        }),
        penalties,
    )


def review_matches(
    matches: Sequence[MatchRecord],
    leagues: Sequence[tuple[Competition, Sequence[LeagueResult]]],
    club: TeamRef,
    *,
    catalogue: FootballCatalogue,
    notes: Mapping[str, object] = {},
    confirmed_role_codes: Mapping[int, str] = {},
    filters: ReviewFilters = ReviewFilters(),
    usual_roles: Mapping[tuple[str, str], str] = {},
    mentalities: Mapping[str, MentalityPlan] = {},
) -> MatchReview:
    codes = RoleCodes.build(catalogue, confirmed_role_codes)
    # The role each player had in each match, with the duty his slot settles.
    roles = appearance_roles(matches, club.id, notes=notes, codes=codes, usual_roles=usual_roles)
    league_ids = {competition.id for competition, _results in leagues}
    seasons = match_seasons(matches)
    everything = summarise_matches(
        matches, leagues, club, notes=notes, codes=codes, grouping=filters.grouping, mentalities=mentalities
    )
    selected = tuple(
        summary for summary in everything
        if _in_scope(summary.match, filters.competitions, league_ids)
        and (filters.season is None or seasons[summary.match.key] == filters.season)
        and (filters.venue is None or summary.side == filters.venue)
        and (
            filters.tactic is None
            or (filters.tactic == NO_TACTIC and summary.tactic_key is None)
            or summary.tactic_key == filters.tactic
        )
    )
    bands = BANDS[filters.grouping]
    groups = tuple(
        summarise_group(band.key, band.label, [s for s in selected if s.band.key == band.key])
        for band in bands
    )
    venues = tuple(
        summarise_group(side, label, [s for s in selected if s.side == side])
        for side, label in (("home", "Home"), ("away", "Away"))
    )
    tactic_keys = sorted({s.tactic_key for s in selected}, key=lambda key: (key is None, key or ""))
    tactics = tuple(
        TacticRow(
            tactic_key=key,
            label=catalogue.tactics[key].name if key in catalogue.tactics else (key or "Tactic not known"),
            overall=summarise_group(key or NO_TACTIC, "All", [s for s in selected if s.tactic_key == key]),
            by_band={
                band.key: summarise_group(
                    band.key, band.label, [s for s in selected if s.tactic_key == key and s.band.key == band.key]
                )
                for band in bands
            },
        )
        for key in tactic_keys
    )
    appearances = [
        (
            player, summary.match.key, int(summary.ours["shots"] or 0) if summary.ours else 0,
            roles.get((summary.match.key, player.side, player.short_id)) or codes.label(player.role_code, player.position),
        )
        for summary in selected
        if summary.match.detail is not None
        for player in summary.match.detail.players_for(summary.side)
    ]
    return MatchReview(
        club=club,
        filters=filters,
        grouping_label=GROUPING_LABELS[filters.grouping],
        bands=bands,
        matches=selected,
        groups=groups,
        venues=venues,
        tactics=tactics,
        goals=_goal_breakdown(selected, codes, roles),
        roles=summarise_roles(appearances, codes),
        players=summarise_players(
            (
                (
                    player, summary.match.date, summary.opponent.name,
                    roles.get((summary.match.key, player.side, player.short_id))
                    or codes.label(player.role_code, player.position),
                )
                for summary in selected
                if summary.match.detail is not None
                for player in summary.match.detail.players_for(summary.side)
            ),
        ),
        unconfirmed_roles=_unconfirmed(selected, codes),
        leagues=tuple(competition for competition, _results in leagues),
        excluded=len(everything) - len(selected),
        appearance_roles=roles,
        seasons=tuple(sorted({season for season in seasons.values() if season is not None}, reverse=True)),
    )
