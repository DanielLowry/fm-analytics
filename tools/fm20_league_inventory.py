#!/usr/bin/env python3
"""Read-only league roster identity reconnaissance; never a production capture.

Played results locate candidate league team objects. They cannot prove current
participant completeness or manager-visible roster/position semantics. Record
IDs only; do not use the owned-player reader for external attributes, readiness,
or raw position ratings. Run through the fm20_research recipe controller.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import fm20_linux_probe as probe
from tools.fm20_linux_probe_runtime import snapshot_marker
from tools.fm20_match_probe import Clubs, Memory, _is_league, competition, first_team_address, played_results


def read_roster_ids(memory: Memory, team: int) -> tuple[str, ...]:
    """The narrow identity-only reader, not the owned-squad field reader."""
    return tuple(sorted(probe.read_first_team_ids(memory.fd, memory.module_base, team)))


def inventory(memory: Memory) -> dict[str, Any]:
    managed_team = first_team_address(memory)
    results = tuple(played_results(memory).values())
    candidates = sorted({row["fixture_name"] for row in results
                         if managed_team in (row["home_team"], row["away_team"])})
    clubs = Clubs(memory)
    leagues = []
    rosters: dict[int, tuple[str, ...]] = {}
    errors = []
    for fixture_name in candidates:
        if not _is_league(results, fixture_name, managed_team):
            continue
        rows = [row for row in results if row["fixture_name"] == fixture_name]
        teams = sorted({row[side] for row in rows for side in ("home_team", "away_team")})
        observations = []
        for team in teams:
            club = clubs(team)
            if club is None:
                errors.append({"teamAddress": hex(team), "error": "club identity unavailable"})
                continue
            try:
                ids = read_roster_ids(memory, team)
            except (OSError, probe.ProbeError) as exc:
                errors.append({"club": club, "error": str(exc)})
                observations.append({"club": club, "playerIds": None, "rosterVerified": False})
                continue
            rosters[team] = ids
            observations.append({"club": club, "playerIds": list(ids), "rosterVerified": False})
        leagues.append({
            "competition": competition(memory, fixture_name),
            "membershipComplete": False,
            "discoveryBasis": "played-results-league-heuristic",
            "resultCount": len(rows),
            "firstResultDate": min(row["date"] for row in rows).isoformat(),
            "lastResultDate": max(row["date"] for row in rows).isoformat(),
            "teams": observations,
        })
    # A same-date transfer or squad move is not covered by the owned marker.
    stable = all(read_roster_ids(memory, team) == ids for team, ids in rosters.items())
    return {
        "researchOnly": True,
        "membershipComplete": False,
        "rosterVisibilityVerified": False,
        "positionsVisibilityVerified": False,
        "stable": stable,
        "candidateLeagueCount": len(leagues),
        "rostersRead": len(rosters),
        "leagues": leagues,
        "errors": errors,
    }


def capture_inventory(pid: int) -> dict[str, Any]:
    before = snapshot_marker(pid)
    with closing(Memory(pid)) as memory:
        report = inventory(memory)
    after = snapshot_marker(pid)
    report["stable"] = report["stable"] and before == after
    report.update({
        "status": "complete" if report["stable"] else "changed_during_read",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "gameDate": before.game_date,
        "managerId": before.manager_id,
        "managedClubId": before.club_id,
        "limitations": [
            "Played results do not establish complete current league membership.",
            "Roster identities require FM UI validation before production use.",
            "No external attributes, readiness, or position ratings were read.",
        ],
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error("report already exists; research evidence is immutable")
    try:
        report = capture_inventory(args.pid)
    except (OSError, probe.ProbeError) as exc:
        report = {"researchOnly": True, "status": "error", "error": str(exc)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in
                      ("status", "gameDate", "candidateLeagueCount", "rostersRead", "stable")}))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
