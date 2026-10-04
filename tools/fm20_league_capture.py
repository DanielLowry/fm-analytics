#!/usr/bin/env python3
"""Capture the managed club's league from FM for the League pages.

Writes a version 1 league capture (docs/contracts/league-capture.md) for
``fm-web --direct-live --league-json``. Everything is read-only:

- **Which clubs.** Every first team carries FM's link to the league it plays
  in this season (``team + 0x50``, the same competition object as the league's
  fixtures). Every first team with our league's link is a participant, played
  or not, so this works before a ball is kicked. Checked 3 October 2026 on the
  National League South save: exactly 22 of 127,012 teams, identical to the
  22 clubs in its 352 played results. When league results exist, every club in
  them must be among the participants, or membership is marked incomplete.
- **Which players.** Each club's first-team squad vector, the same one our own
  squad is read from, so a rival's roster has the same scope as ours.
- **What FM shows.** Visible attributes from FM's own visibility builder and
  visible positions from FM's own position-knowledge check, both run in the
  sandbox over a read-only copy of FM's memory (``tools.fm20_sandbox_queries``,
  ``tools.fm20_visible_positions``). Hidden ratings never leave this process.
- **Our club.** The same read ``fm-web --direct-live`` uses, so the League page
  can check our row against the squad it already shows.

Rival readiness, injuries and contracts are not read: availability is
``unknown``, which the comparison labels as an assumption. A player whose
attributes the sandbox could not read stays in the roster as uncaptured.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from fm_analytics.bridge.errors import BridgeSourceError
from fm_analytics.bridge.linux_proton import LinuxProtonDataSource
from fm_analytics.domain import AttributeObservation, Club, Player, Squad
from fm_analytics.domain.leagues import LeagueCapture, LeagueRoster
from fm_analytics.domain.matches import Competition
from tools import fm20_linux_probe as probe
from tools import fm20_match_layout as layout
from tools.fm20_cold_query_cache import resolve_player_interfaces
from tools.fm20_linux_probe_runtime import decode_fm_date, snapshot_marker
from tools.fm20_match_probe import Memory, first_team_address, played_results
from tools.fm20_sandbox import FmSandbox, SandboxError
from tools.fm20_sandbox_queries import SandboxSearchContext, read_visible_attributes, resolve_sandbox_context, resolve_scout_persons
from tools.fm20_status import running_pid
from tools.fm20_visible_positions import (
    KNOWLEDGE_BY_THRESHOLD,
    PLAYER_PERSON_OFFSET,
    PositionReadError,
    read_position_ratings,
    read_position_threshold,
    visible_positions,
)

TEAM_CLUB = 0x18
TEAM_KIND = 0x30  # 0 is a club's first team
TEAM_LEAGUE = 0x50  # this season's league competition
COMP_ID = 0x0C
SANDBOX_WORKERS = 8
SANDBOX_PASSES = 3


class LeagueCaptureError(RuntimeError):
    """FM's state could not give a coherent league capture."""


def league_members(memory: Memory, managed_team: int) -> tuple[int, tuple[int, ...]]:
    """Our league's competition object and every first team that plays in it."""
    competition = memory.u64(managed_team + TEAM_LEAGUE)
    if not competition:
        raise LeagueCaptureError("our first team has no league this season")
    layout_ = probe.FM20_4_4_STEAM
    teams = probe.read_pointer_collection(
        memory.fd, memory.module_base, layout_.main_address_offset,
        layout_.team_collection_offset, layout_.collection_indirection_offset,
    )
    members = []
    for team in teams:
        try:
            if team and memory.u64(team + TEAM_LEAGUE) == competition and memory.read(team + TEAM_KIND, 1) == b"\0":
                members.append(team)
        except OSError:
            continue
    if managed_team not in members:
        raise LeagueCaptureError("our first team is not among its own league's participants")
    return competition, tuple(members)


def played_league_teams(results: Mapping[Any, Mapping[str, Any]], memory: Memory, competition: int) -> set[int]:
    """Teams with a played result in this league -- the cross-check, not the source."""
    teams: set[int] = set()
    for row in results.values():
        try:
            if memory.u64(row["fixture_name"] + layout.FIXTURE_NAME_COMP) == competition:
                teams.update((row["home_team"], row["away_team"]))
        except OSError:
            continue
    return teams


def membership_evidence(members: Sequence[int], played: set[int]) -> tuple[bool, str]:
    extra = played - set(members)
    text = (f"FM's own league link on every first team: {len(members)} clubs. "
            f"{len(played)} of them have played league results")
    if extra:
        return False, text + f"; {len(extra)} club(s) in those results are missing from the link, so the list may be incomplete."
    return True, text + ", all among the linked clubs."


def season_label(game_date: date) -> str:
    start = game_date.year if game_date.month >= 7 else game_date.year - 1
    return f"{start}/{(start + 1) % 100:02d}"


def _person(fd: int, interface: int) -> int:
    table = struct.unpack("<Q", os.pread(fd, 8, interface + 8))[0]
    return interface + 8 + struct.unpack("<i", os.pread(fd, 4, table + 4))[0]


def read_identity(fd: int, person: int, as_of: date) -> tuple[str, date | None, int | None]:
    actual = person + 0x28
    name = " ".join(part for part in (probe.read_fm_string(fd, actual + 0x30), probe.read_fm_string(fd, actual + 0x38)) if part)
    if not name:
        raise LeagueCaptureError("player has no readable name")
    try:
        born = decode_fm_date(probe.read_exact(fd, actual + 0x1C, 4), maximum_year=as_of.year)
    except (OSError, probe.ProbeError):
        return name, None, None
    return name, born, probe.calculate_age(born, as_of)


def _sandbox_pass(pid: int, context: SandboxSearchContext, interfaces: Mapping[int, int],
                  scouts: Mapping[int, int], player_ids: list[int], workers: int):
    """Visible attributes and FM's position threshold, each shard in a fresh sandbox."""
    count = max(1, min(workers, len(player_ids)))
    size = -(-len(player_ids) // count)
    shards = [player_ids[start:start + size] for start in range(0, len(player_ids), size)]

    def run(shard):
        found = {}
        with FmSandbox(pid, context.module_base) as box:
            for player_id in shard:
                try:
                    attributes = read_visible_attributes(box, context, interfaces[player_id], scouts.get(player_id, 0))
                    threshold = read_position_threshold(box, context.manager_interface, interfaces[player_id])
                except (SandboxError, PositionReadError):
                    continue
                found[player_id] = (attributes, threshold)
        return found

    combined = {}
    with ThreadPoolExecutor(max_workers=count) as pool:
        for shard_result in pool.map(run, shards):
            combined.update(shard_result)
    return combined


def read_visible(pid: int, context: SandboxSearchContext, interfaces: Mapping[int, int], scouts: Mapping[int, int]):
    """Retry only the players a pass missed, in new sandboxes (see capture_players)."""
    remaining, found = sorted(interfaces), {}
    for attempt in range(SANDBOX_PASSES):
        if not remaining:
            break
        found.update(_sandbox_pass(pid, context, interfaces, scouts, remaining,
                                   SANDBOX_WORKERS if attempt == 0 else 4))
        remaining = [player_id for player_id in remaining if player_id not in found]
    return found


def rival_roster(fd: int, team: int, club: Club, ids: Sequence[int], as_of: date, interfaces: Mapping[int, int],
                 visible: Mapping[int, tuple[dict[str, AttributeObservation], int]]) -> LeagueRoster:
    players, errors, knowledge = [], [], {}
    unreadable = uncaptured = 0
    for player_id in sorted(ids):
        interface = interfaces.get(player_id)
        try:
            if interface is None:
                raise LeagueCaptureError("not found among FM's people")
            person = _person(fd, interface)
            name, born, age = read_identity(fd, person, as_of)
        except (OSError, probe.ProbeError, LeagueCaptureError):
            unreadable += 1
            continue
        attributes, positions = {}, ()
        if player_id in visible:
            attributes, threshold = visible[player_id]
            if person - interface == PLAYER_PERSON_OFFSET:
                try:
                    positions = visible_positions(read_position_ratings(fd, person), threshold)
                except (OSError, probe.ProbeError, PositionReadError):
                    positions = ()
            label = KNOWLEDGE_BY_THRESHOLD[threshold]
            knowledge[label] = knowledge.get(label, 0) + 1
        else:
            uncaptured += 1
        players.append(Player(
            id=str(player_id), name=name, date_of_birth=born, age=age, positions=positions, club_id=club.id,
            condition_percent=None, match_fitness_percent=None, availability="unknown", injured=None,
            suspended=None, contract=None, attributes=attributes,
        ))
    if unreadable:
        errors.append(f"{unreadable} squad member(s) could not be read from FM")
    if uncaptured:
        errors.append(f"{uncaptured} player(s)' visible attributes and positions could not be read this time")
    evidence = ("First-team squad from FM; visible attributes and positions decided by FM's own knowledge "
                "checks (" + ", ".join(f"{count} {label}" for label, count in sorted(knowledge.items())) + ")")
    return LeagueRoster(Squad(club, as_of, tuple(players)), unreadable == 0,
                        all(player.positions for player in players), evidence, tuple(errors))


def capture_league(pid: int, *, save_key: str | None = None) -> LeagueCapture:
    started = time.monotonic()
    before = snapshot_marker(pid)
    game, owned = LinuxProtonDataSource().read_snapshot()
    if game.game_date.isoformat() != before.game_date or game.controlled_club is None:
        raise LeagueCaptureError("FM moved on while our own squad was being read; try again")
    as_of = game.game_date
    with closing(Memory(pid)) as memory:
        managed = first_team_address(memory)
        competition, members = league_members(memory, managed)
        complete, evidence = membership_evidence(members, played_league_teams(played_results(memory), memory, competition))
        comp = Competition(str(struct.unpack("<i", memory.read(competition + COMP_ID, 4))[0]),
                           probe.read_fm_string(memory.fd, competition + layout.COMP_NAME, indirect=False) or "League",
                           probe.read_fm_string(memory.fd, competition + layout.COMP_SHORT_NAME, indirect=False) or "")
        clubs, rosters = {}, {}
        for team in members:
            if team == managed:
                continue
            club = probe.read_club_from_team(memory.fd, team)
            if club is None:
                raise LeagueCaptureError(f"a league team at {team:#x} has no readable club")
            clubs[team] = Club(club.id, club.name)
            rosters[team] = tuple(sorted(int(i) for i in probe.read_first_team_ids(memory.fd, memory.module_base, team)))
        context = resolve_sandbox_context(pid)
        wanted = {player_id for ids in rosters.values() for player_id in ids}
        interfaces = resolve_player_interfaces(pid, memory.fd, memory.module_base, wanted)
        scouts = resolve_scout_persons(memory.fd, memory.module_base, context.knowledge_context, sorted(wanted))
        visible = read_visible(pid, context, interfaces, scouts)
        teams = [LeagueRoster(replace(owned, other_teams=()), True, all(p.positions for p in owned.players),
                              "Our first team, read exactly as the Squad page reads it")]
        teams += [rival_roster(memory.fd, team, clubs[team], rosters[team], as_of, interfaces, visible)
                  for team in sorted(rosters, key=lambda t: clubs[t].name.casefold())]
        moved = [clubs[team].name for team in rosters
                 if tuple(sorted(int(i) for i in probe.read_first_team_ids(memory.fd, memory.module_base, team))) != rosters[team]]
    if snapshot_marker(pid) != before or moved:
        raise LeagueCaptureError("FM changed during the capture" + (f" ({', '.join(moved)})" if moved else "") + "; try again")
    capture = LeagueCapture(save_key or f"club:{game.controlled_club.id}", game, season_label(as_of), comp, complete,
                            evidence + f" Read in {time.monotonic() - started:.1f} s.", "manager-visible", tuple(teams))
    return LeagueCapture.from_document(capture.to_document())  # the same validation the web applies


def write_capture(capture: LeagueCapture, output: Path) -> None:
    """Replace the file whole, so the web never reads half a capture."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    temporary.write_text(json.dumps(capture.to_document(), indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/league-capture.json"))
    parser.add_argument("--save-key", help="save identity; defaults to club:<our club id>, as the other stores do")
    args = parser.parse_args(argv)
    try:
        capture = capture_league(running_pid(), save_key=args.save_key)
    except (OSError, probe.ProbeError, SandboxError, LeagueCaptureError, BridgeSourceError, ValueError) as exc:
        print(f"League capture failed: {exc}", file=sys.stderr)
        return 1
    write_capture(capture, args.output)
    print(json.dumps({
        "output": str(args.output), "gameDate": capture.game.game_date.isoformat(),
        "competition": capture.competition.name, "clubs": len(capture.teams),
        "membershipComplete": capture.membership_complete,
        "players": sum(len(team.squad.players) for team in capture.teams),
        "rostersComplete": sum(team.roster_complete for team in capture.teams),
        "positionsComplete": sum(team.positions_complete for team in capture.teams),
        "errors": {team.squad.club.name: list(team.errors) for team in capture.teams if team.errors},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
