"""Small, readable match captures for the match-history tests.

A four-team league (us, Alpha, Bravo, Charlie) with results chosen so the
table on any date is easy to work out by hand.
"""

from __future__ import annotations

import copy
from typing import Any

US = {"id": "100", "name": "Hungerford Town"}
ALPHA = {"id": "201", "name": "Alpha"}
BRAVO = {"id": "202", "name": "Bravo"}
CHARLIE = {"id": "203", "name": "Charlie"}
CUP_SIDE = {"id": "300", "name": "Cup Rovers"}
LEAGUE = {"id": "148", "name": "Test League South", "shortName": "Test South"}
CUP = {"id": "9", "name": "Test Cup", "shortName": "Cup"}
FRIENDLY = {"id": "1", "name": "Friendly", "shortName": "Friendly"}

# Vertical 4-4-2's role codes in line-up order (GK, back four, midfield four, forwards).
VERTICAL_442_CODES = (0x1, 0x4, 0x2, 0x2, 0x4, 0x80, 0x10000, 0x20, 0x80, 0x80000000, 0x800)


def team_stats(**overrides: int) -> dict[str, int]:
    stats = {
        "possession_time": 5000, "goals": 0, "shots": 10, "shots_on_target": 4,
        "clear_cut_chances": 1, "corners": 3, "fouls": 10, "passes_attempted": 400,
        "passes_completed": 300, "tackles_attempted": 20, "tackles_won": 15,
        "headers_attempted": 50, "headers_won": 25,
    }
    stats.update(overrides)
    return stats


def player(
    side: str, order: int, code: int, *, name: str | None = None,
    came_on: int | None = None, went_off: int | None = None, **stats: int,
) -> dict[str, Any]:
    return {
        "side": side, "order": order, "started": order < 11, "shortId": 1000 + order + (0 if side == "home" else 500),
        "playerId": None, "name": name, "shirt": order + 1, "roleCode": code, "played": True,
        "rating": 6.8, "stats": stats, "cameOn": came_on, "wentOff": went_off,
    }


def lineup(side: str, codes=VERTICAL_442_CODES, **per_order: dict[str, int]) -> list[dict[str, Any]]:
    """Eleven starters with the given role codes; `o9={"shots": 3}` gives the 10th player stats."""
    return [
        player(side, order, code, name=f"{side.title()} {order + 1}", **per_order.get(f"o{order}", {}))
        for order, code in enumerate(codes)
    ]


def match(
    day: str,
    home: dict,
    away: dict,
    home_goals: int,
    away_goals: int,
    *,
    competition: dict = LEAGUE,
    detail: dict | None = None,
) -> dict[str, Any]:
    return {
        "date": day, "competition": competition, "home": home, "away": away,
        "homeGoals": home_goals, "awayGoals": away_goals, "attendance": 500, "detail": detail,
    }


def detail(
    home: dict[str, int] | None = None,
    away: dict[str, int] | None = None,
    players: list[dict] | None = None,
    events: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "home": home or team_stats(), "away": away or team_stats(),
        "players": players or [], "events": events or [],
    }


def result(day: str, home: dict, away: dict, home_goals: int, away_goals: int) -> dict[str, Any]:
    return {"date": day, "home": home, "away": away, "homeGoals": home_goals, "awayGoals": away_goals}


# By the morning of 2019-09-01, all played 3: Alpha 7 pts, Bravo 4, Charlie 2 (goal
# difference -1), us 2 (-2). Before 2019-08-17 nobody has played 3 games (early season).
LEAGUE_RESULTS = [
    result("2019-08-03", ALPHA, BRAVO, 2, 0),
    result("2019-08-03", US, CHARLIE, 1, 1),
    result("2019-08-10", ALPHA, CHARLIE, 1, 0),
    result("2019-08-10", BRAVO, US, 2, 0),
    result("2019-08-17", ALPHA, US, 0, 0),
    result("2019-08-17", BRAVO, CHARLIE, 1, 1),
    result("2019-09-01", US, ALPHA, 2, 1),
    result("2019-09-01", CHARLIE, BRAVO, 0, 3),
]


def capture_document(matches: list[dict], *, game_date: str = "2019-09-05", league_results=None) -> dict[str, Any]:
    return {
        "format": "fm-analytics/match-capture",
        "formatVersion": 1,
        "capturedAt": "2026-09-29T10:00:00+00:00",
        "gameDate": game_date,
        "source": {"tool": "tests", "managedClub": US},
        "matches": copy.deepcopy(matches),
        "competitionResults": [
            {"competition": LEAGUE, "results": copy.deepcopy(LEAGUE_RESULTS if league_results is None else league_results)}
        ],
    }


def season() -> list[dict[str, Any]]:
    """Our four league matches plus a cup tie and a friendly; the last league match has full stats."""
    return [
        match("2019-07-20", US, CUP_SIDE, 5, 0, competition=FRIENDLY),
        match("2019-08-03", US, CHARLIE, 1, 1),
        match("2019-08-10", BRAVO, US, 2, 0),
        match("2019-08-17", ALPHA, US, 0, 0),
        match("2019-08-24", CUP_SIDE, US, 0, 1, competition=CUP),
        match(
            "2019-09-01", US, ALPHA, 2, 1,
            detail=detail(
                home=team_stats(goals=2, shots=12, shots_on_target=6, clear_cut_chances=3, possession_time=4000),
                away=team_stats(goals=1, shots=6, shots_on_target=2, clear_cut_chances=1, possession_time=6000),
                players=lineup("home", o9={"shots": 3, "goals": 1}, o10={"shots": 5, "goals": 1, "clear_cut_chances": 2},
                               o5={"assists": 2, "shots": 1})
                + lineup("away", o10={"shots": 4, "goals": 1}),
                events=[
                    {"minute": 12, "side": "home", "kind": "goal", "code": 1},
                    {"minute": 50, "side": "away", "kind": "goal", "code": 1},
                    {"minute": 93, "side": "home", "kind": "goal", "code": 1},
                    {"minute": 30, "side": "home", "kind": "clear_cut_chance", "code": 47},
                ],
            ),
        ),
    ]
