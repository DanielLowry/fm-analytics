"""The opponent report as JSON: the Opponent page's "Copy report to clipboard" and `fm-matches opponent --json`.

Serialisation only: `analytics.opponent_report` works everything out, and
the page shows the same figures. Shares are fractions (0.25 is a quarter).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fm_analytics.analytics.game_plan_suggestion import PLAN_GUESS
from fm_analytics.analytics.opponent_goals import FAR_SIDE_GUESS, GoalProfile, ProfileRow
from fm_analytics.analytics.opponent_players import PlayerLine
from fm_analytics.analytics.opponent_report import OpponentReport
from fm_analytics.analytics.match_timeline import CORNER_GUESS

FORMAT = "fm-analytics/opponent-report"
FORMAT_VERSION = 1


def _day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _row(row: ProfileRow) -> dict[str, Any]:
    document: dict[str, Any] = {"key": row.key, "label": row.label, "goals": row.goals, "share": round(row.share, 3)}
    if row.league_share is not None:
        document["league_share"] = round(row.league_share, 3)
    if row.luck is not None:
        document["luck_odds"] = round(row.luck, 3)
    if row.pattern:
        document["pattern"] = row.pattern
    if row.guess:
        document["guess"] = True
    return document


def _profile(profile: GoalProfile) -> dict[str, Any]:
    return {
        "goals": profile.goals,
        "with_timeline": profile.described,
        "how": [_row(row) for row in profile.how],
        "where_from": [_row(row) for row in profile.area],
        "by_line": [_row(row) for row in profile.lines],
        "by_period": [_row(row) for row in profile.periods],
        "crosses_by_flank": [_row(row) for row in profile.cross_flanks],
        "crosses_met_at_far_side_guess": {"goals": profile.far_side, "of_crosses_from_a_flank": profile.flank_crosses},
    }


def _player(line: PlayerLine) -> dict[str, Any]:
    document = {
        "name": line.name, "player_id": line.player_id, "position": line.position, "side": line.side,
        "appearances": line.appearances, "starts": line.starts, "starts_of_last_five": line.recent_starts,
        "minutes": line.minutes, "goals": line.goals, "penalties": line.penalties,
        "headed_goals": line.headed_goals, "goals_from_crosses": line.goals_from_crosses,
        "assists": line.assists, "assists_from_crosses": line.assists_from_crosses,
        "assists_possibly_corners_guess": line.assists_possibly_corners,
        "shots": line.shots, "shots_on_target": line.shots_on_target, "clear_cut_chances": line.clear_cut_chances,
        "chances_created": line.chances_created, "key_passes": line.key_passes, "dribbles": line.dribbles,
        "headers_won": line.headers_won, "headers_attempted": line.headers_attempted,
        "yellow_cards": line.yellow_cards, "red_cards": line.red_cards,
        "average_rating": line.average_rating, "last_played": _day(line.last_played),
    }
    if line.foot:
        document["preferred_foot"] = line.foot
    return document


def opponent_document(report: OpponentReport, *, generated_at: datetime | None = None) -> dict[str, Any]:
    """Everything the Opponent page shows for one club, as JSON."""
    evidence = report.evidence
    return {
        "format": FORMAT,
        "formatVersion": FORMAT_VERSION,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "club": {"id": report.club.id, "name": report.club.name},
        "as_of": _day(report.as_of),
        "fixture": None if report.fixture is None else {
            "date": report.fixture.date.isoformat(),
            "home": report.fixture.home.name,
            "away": report.fixture.away.name,
            "competition": report.fixture.competition.label,
        },
        "evidence": {
            "matches": evidence.matches, "first": _day(evidence.first), "last": _day(evidence.last),
            "against_us": evidence.against_us, "window": evidence.window,
            "league_results_not_in_fm_archive": evidence.league_results_missing,
            "goals_without_timeline": evidence.goals_without_timeline,
            "roster_read_on": _day(report.roster_date),
        },
        "league": None if report.league_position is None else {
            "name": report.league_name, "position": report.league_position.position,
            "teams": report.league_position.teams, "played": report.league_position.played,
            "points": report.league_position.points,
        },
        "goals_for": report.goals_for,
        "goals_against": report.goals_against,
        "form": [
            {"date": entry.date.isoformat(), "venue": entry.venue, "opponent": entry.opponent,
             "score": f"{entry.goals_for}-{entry.goals_against}", "outcome": entry.outcome,
             "competition": entry.competition, "formation": entry.formation}
            for entry in report.form
        ],
        "formations": {
            "named_for": report.formations.known,
            "uses": [{"name": use.name, "matches": use.matches, "home": use.home, "away": use.away,
                      "last_used": use.last_used.isoformat()} for use in report.formations.uses],
            "last_five": list(report.formations.recent),
            "last_against_us": report.formations.against_us,
        },
        "likely_xi": [{"name": line.name, "position": line.position, "side": line.side,
                       "starts_of_last_five": line.recent_starts} for line in report.likely_xi],
        "finishers": [_player(line) for line in report.finishers],
        "suppliers": [_player(line) for line in report.suppliers],
        "partnerships": [{"supplier": pair.supplier, "scorer": pair.scorer, "goals": pair.goals,
                          "from_crosses": pair.from_crosses} for pair in report.partnerships],
        "scored": _profile(report.scored),
        "conceded": _profile(report.conceded),
        "style": [
            {"key": figure.key, "label": figure.label, "per_match": figure.value, "opponents_per_match": figure.against,
             "league_per_match": figure.league, "rank": figure.rank, "teams": figure.teams, "unit": figure.unit}
            for figure in report.style
        ],
        "meetings": [
            {"match": meeting.match_key, "date": meeting.date.isoformat(), "venue": meeting.venue,
             "competition": meeting.competition, "score": f"{meeting.our_goals}-{meeting.their_goals}",
             "outcome": meeting.outcome, "their_formation": meeting.their_formation,
             "their_scorers": list(meeting.their_scorers)}
            for meeting in report.meetings
        ],
        "opposition_instructions": [
            {"player": item.player, "player_id": item.player_id, "position": item.position,
             "settings": {column: value for column, value in item.settings}, "why": list(item.reasons)}
            for item in report.instructions
        ],
        "watch": list(report.watch),
        "suggested_game_plan": (
            {"plans": [plan.label for plan in report.plan.plans], "they": report.plan.style,
             "why": list(report.plan.reasons), "guess": PLAN_GUESS}
            if report.plan is not None else None
        ),
        "players": [_player(line) for line in report.players],
        "guesses": {"possibly_from_corners": CORNER_GUESS, "far_side": FAR_SIDE_GUESS},
    }
