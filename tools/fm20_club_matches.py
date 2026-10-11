"""The match capture's reading of other clubs' matches and of our fixtures still to play.

For the opponent report (`fm_analytics.analytics.opponent_report`): which
results are the other league clubs' competitive matches, each side's formation
and everyone's name and FM ID in an archived match between two AI sides, and
our scheduled fixtures from FM's fixture list. Read-only, like the rest of
`fm20_match_probe.py`, which calls these.
"""

from __future__ import annotations

from typing import Any

from tools import fm20_match_archive as archive
from tools import fm20_match_layout as layout
from tools.fm20_linux_probe import ProbeError
from tools.fm20_match_tactics import candidate_prefixes, formation_name


def scheduled_fixtures(memory, team: int, played: set[tuple]) -> dict[tuple, dict[str, Any]]:
    """The team's fixtures FM has scheduled and not yet played, once each, keyed by date and teams.

    FM keeps a scheduled fixture (`layout.FIXTURE`) after it is played, so
    one that already has a played result is left out.
    """
    fixtures: dict[tuple, dict[str, Any]] = {}
    for address in memory.instances(layout.FIXTURE):
        try:
            record = layout.decode_fixture(memory.read(address, layout.FIXTURE_SIZE))
        except (OSError, ProbeError):
            continue
        if team not in (record["home_team"], record["away_team"]) or record["date"] is None:
            continue
        key = (record["date"], record["home_team"], record["away_team"])
        if key not in played:
            fixtures.setdefault(key, record)
    return fixtures


MAX_LEAGUE_TEAMS = 48


def is_league(results, fixture_name: int, team: int) -> bool:
    """Whether a competition's results make a league table worth keeping.

    Friendlies span thousands of clubs and a cup round gives each team one
    match; neither has a table. A league has a bounded set of teams and the
    managed team plays in it more than once.
    """
    teams: set[int] = set()
    ours = 0
    for result in results:
        if result["fixture_name"] != fixture_name:
            continue
        teams.update((result["home_team"], result["away_team"]))
        ours += team in (result["home_team"], result["away_team"])
        if len(teams) > MAX_LEAGUE_TEAMS:
            return False
    return ours >= 2


def league_clubs_results(
    results: dict[tuple, dict[str, Any]], competitions: dict[int, dict[str, str]], team: int
) -> dict[tuple, dict[str, Any]]:
    """Every competitive result of the other first teams in our leagues, in any competition.

    A league's first teams are the teams in its results; a friendly has no
    season, so it is left out.
    """
    league_teams = {
        side
        for fixture_name in competitions if is_league(results.values(), fixture_name, team)
        for result in results.values() if result["fixture_name"] == fixture_name
        for side in (result["home_team"], result["away_team"])
    } - {team}
    return {
        key: result for key, result in results.items()
        if result["season"] and team not in (result["home_team"], result["away_team"])
        and (result["home_team"] in league_teams or result["away_team"] in league_teams)
    }


def side_formations(chunk: bytes, detail: dict[str, Any]) -> dict[str, str]:
    """Each side's formation as FM names it, for a match between two sides FM's AI manages."""
    prefixes = candidate_prefixes(chunk)
    found = {}
    for side in ("home", "away"):
        positions = [
            layout.position_code(player["start_position"], player["start_centre_side"])
            for player in detail["players"]
            if player["side"] == side and player.get("started") and player.get("start_position")
        ]
        name = formation_name(prefixes, positions)
        if name:
            found[side] = name
    return found


def club_detail(chunk: bytes, detail: dict[str, Any]) -> dict[str, Any]:
    """Another club's match from its archive chunk: everyone named from the chunk, with FM's unique ID."""
    names, ids = archive.person_names(chunk), archive.person_ids(chunk)
    for player in detail["players"]:
        player["name"] = names.get(player["short_id"])
        player["player_id"] = str(ids[player["short_id"]]) if player["short_id"] in ids else None
    detail["formations"] = side_formations(chunk, detail)
    return detail
