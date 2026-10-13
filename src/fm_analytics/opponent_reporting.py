"""The opponent report's entry points: `reporting.build_opponent_report`, its JSON copy and the club picker.

Kept out of `reporting.py`, which re-exports them, so that module stays a
readable size; they are still the one computation behind the Opponent page and
`fm-matches opponent` (docs/opponent-report.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Sequence

from fm_analytics.analytics.opponent_report import (
    DEFAULT_WINDOW,
    OpponentChoice,
    OpponentReport,
    build_opponent_report as _build_opponent_report,
    club_choices,
    next_fixture,
)
from fm_analytics.domain.leagues import LeagueCapture
from fm_analytics.domain.matches import MatchRecord, ScheduledFixture
from fm_analytics.opponent_export import opponent_document

if TYPE_CHECKING:
    from fm_analytics.persistence.match_history import MatchHistory


def opponent_choices(
    history: MatchHistory,
    fixtures: tuple[Any, tuple[ScheduledFixture, ...]] | None = None,
) -> tuple[OpponentChoice, ...]:
    """Every club in our current league, and any other we have a fixture with: the next opponent first.

    `fixtures` is `MatchHistoryStore.load_fixtures`: the game date of the
    capture that read FM's fixture list, and that list.
    """
    return club_choices(history.club.id, history.league_results, history.matches, fixtures, history.last_game_date)


def build_opponent_report(
    history: MatchHistory,
    club_matches: Sequence[MatchRecord],
    *,
    club_id: str | None = None,
    fixtures: tuple[Any, tuple[ScheduledFixture, ...]] | None = None,
    window: int = DEFAULT_WINDOW,
    league: LeagueCapture | None = None,
    before: Any = None,
) -> OpponentReport | None:
    """The one opponent report, behind the Opponent page and `fm-matches opponent`.

    Without `club_id` it is on our next opponent, from FM's fixture list
    (`fixtures`, as `MatchHistoryStore.load_fixtures` gives it), and None when
    no fixture is known. It uses only matches played before that fixture, or
    before `before` when given; with neither, every match recorded.
    `club_matches` is `MatchHistoryStore.load_club_matches`. `league` is the
    latest league read: their players' visible attributes come from it.
    """
    ours = history.club.id
    choices = opponent_choices(history, fixtures)
    if club_id is None:
        today = fixtures[0] if fixtures is not None else history.last_game_date
        fixture = next_fixture(fixtures[1], ours, history.matches, today) if fixtures and today else None
        if fixture is None:
            return None
        club = fixture.opponent_of(ours)
    else:
        choice = next((item for item in choices if item.club.id == club_id), None)
        club = choice.club if choice else next(
            (match.team(side) for match in (*history.matches, *club_matches)
             for side in ("home", "away") if match.team(side).id == club_id),
            None,
        )
        if club is None:
            raise ValueError(f"no match of club {club_id} is recorded")
        fixture = choice.fixture if choice else None
    as_of = before if before is not None else (fixture.date if fixture else None)
    if before is not None and fixture is not None and fixture.date != before:
        fixture = None  # a report as of another day is not this fixture's
    roster = next((team.squad for team in league.teams if team.squad.club and team.squad.club.id == club.id), None) \
        if league is not None else None
    return _build_opponent_report(
        club,
        our_club_id=ours,
        our_matches=history.matches,
        club_matches=club_matches,
        league_results=history.league_results,
        as_of=as_of,
        fixture=fixture,
        window=window,
        roster=roster.players if roster is not None else None,
        roster_date=league.game.game_date if roster is not None else None,
    )


def build_opponent_export(report: OpponentReport, *, generated_at: datetime | None = None) -> dict[str, Any]:
    """The opponent report as JSON: the Opponent page's copy button and `fm-matches opponent --json`."""
    return opponent_document(report, generated_at=generated_at)
