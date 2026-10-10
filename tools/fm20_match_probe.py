#!/usr/bin/env python3
"""Read-only reader for FM20 match data: results, team stats and player stats.

``capture`` writes the manager's match history as the JSON document that
``fm-matches`` records (``fm_analytics.match_ingest``), the way
``fm20_scouting_feed.py`` feeds the Scouting page. The other commands are the
research views used to find the layouts in ``fm20_match_layout.py``; see
``docs/match-analysis-plan.md``.

It never attaches to FM, never runs FM's code and never writes: every read
goes through ``/proc/<pid>/mem`` opened read-only, after checking the process
runs the pinned FM20 build. FM keeps running while it reads, so a capture is
checked against FM's own match screens rather than trusted blindly.

    python3 tools/fm20_match_probe.py capture --output data/match-capture.json
    python3 tools/fm20_match_probe.py matches            # every match-stats object
    python3 tools/fm20_match_probe.py results            # the first team's results
    python3 tools/fm20_match_probe.py squad              # first team with match-record IDs
    python3 tools/fm20_match_probe.py players ADDRESS    # one match's player records
    python3 tools/fm20_match_probe.py scan CLASS...      # live instances of classes
    python3 tools/fm20_match_probe.py describe ADDRESS   # an object's class and text
    python3 tools/fm20_match_probe.py find-u32 VALUE...  # where 4-byte values occur
    python3 tools/fm20_match_probe.py dump ADDRESS [SIZE]
"""

from __future__ import annotations

import argparse
import json
import mmap
import os
import re
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools import fm20_linux_probe as probe
import tools.fm20_linux_probe_runtime  # noqa: F401  (installs decode_fm_date)
from tools import fm20_match_archive as archive
from tools import fm20_match_layout as layout
from tools.fm20_match_tactics import candidate_prefixes, formation_name, team_tactic
from tools.fm20_field_workbench import PeImage, find_rtti_vtables
from tools.fm20_status import running_pid

CHUNK = 64 << 20
CAPTURE_FORMAT = "fm-analytics/match-capture"
CAPTURE_FORMAT_VERSION = 1


class Memory:
    """FM's address space, read-only."""

    def __init__(self, pid: int):
        process = Path("/proc") / str(pid)
        with (process / "maps").open(encoding="utf-8") as maps:
            self.module_base, executable = probe.parse_module_mapping(maps)
        probe.validate_executable(executable)
        self.pid = pid
        self.executable = Path(executable)
        self.fd = os.open(process / "mem", os.O_RDONLY | os.O_CLOEXEC)

    def close(self) -> None:
        os.close(self.fd)

    def read(self, address: int, size: int) -> bytes:
        if not 0 < address < 1 << 47:
            raise probe.ProbeError(f"not a user-space address: {address:#x}")
        return probe.read_exact(self.fd, address, size)

    def u64(self, address: int) -> int:
        return struct.unpack("<Q", self.read(address, 8))[0]

    def writable_regions(self) -> Iterator[tuple[int, int]]:
        with open(f"/proc/{self.pid}/maps", encoding="utf-8") as maps:
            for line in maps:
                parts = line.split()
                start, end = (int(value, 16) for value in parts[0].split("-"))
                path = parts[5] if len(parts) > 5 else ""
                if "r" in parts[1] and "w" in parts[1] and not path.startswith("/"):
                    yield start, end

    def scan(self, patterns: dict[bytes, str], *, align: int, limit: int = 2000) -> dict[str, list[int]]:
        pattern = re.compile(b"|".join(re.escape(needle) for needle in patterns))
        hits: dict[str, list[int]] = {name: [] for name in patterns.values()}
        for start, end in self.writable_regions():
            for position in range(start, end, CHUNK):
                try:
                    data = os.pread(self.fd, min(CHUNK, end - position), position)
                except OSError:
                    continue
                for match in pattern.finditer(data):
                    address = position + match.start()
                    name = patterns[match.group()]
                    if address % align == 0 and len(hits[name]) < limit:
                        hits[name].append(address)
        return hits

    def instances(self, rva: int) -> list[int]:
        needle = struct.pack("<Q", self.module_base + rva)
        return self.scan({needle: "x"}, align=8, limit=1_000_000)["x"]

    def pointers(self, vector_at: bytes, offset: int, *, limit: int = 256) -> list[int]:
        begin, end = layout.vector_bounds(vector_at, offset)
        count = min(max(end - begin, 0) // 8, limit)
        return list(struct.unpack(f"<{count}Q", self.read(begin, count * 8))) if count else []


# -- the capture ------------------------------------------------------------


class Clubs:
    """Team object -> club reference, read once per team."""

    def __init__(self, memory: Memory):
        self.memory = memory
        self._cache: dict[int, dict[str, str] | None] = {}

    def __call__(self, team: int) -> dict[str, str] | None:
        if team not in self._cache:
            try:
                club = probe.read_club_from_team(self.memory.fd, team)
            except (OSError, probe.ProbeError):
                club = None
            self._cache[team] = {"id": club.id, "name": club.name} if club else None
        return self._cache[team]


def competition(memory: Memory, fixture_name: int) -> dict[str, str]:
    try:
        fixture_id = struct.unpack("<I", memory.read(fixture_name + layout.FIXTURE_NAME_ID, 4))[0]
        comp = memory.u64(fixture_name + layout.FIXTURE_NAME_COMP)
        name = probe.read_fm_string(memory.fd, comp + layout.COMP_NAME, indirect=False)
        short = probe.read_fm_string(memory.fd, comp + layout.COMP_SHORT_NAME, indirect=False)
    except (OSError, probe.ProbeError):
        return {"id": f"fixture-name:{fixture_name:#x}", "name": "Unknown competition", "shortName": ""}
    return {"id": str(fixture_id), "name": name or "Unknown competition", "shortName": short or ""}


def played_results(memory: Memory) -> dict[tuple, dict[str, Any]]:
    """Every played result FM holds, once each, keyed by date and teams."""
    results: dict[tuple, dict[str, Any]] = {}
    for address in memory.instances(layout.FIXTURE_RESULT):
        try:
            record = layout.decode_fixture_result(memory.read(address, layout.FIXTURE_RESULT_SIZE))
        except (OSError, probe.ProbeError):
            continue
        if not record["played"] or record["date"] is None:
            continue
        key = (record["date"], record["home_team"], record["away_team"])
        results.setdefault(key, {**record, "address": address})
    return results


MAX_INCIDENTS = 40


def read_incidents(memory: Memory, result: dict[str, Any]) -> list[dict[str, Any]] | None:
    """A result's goals and sendings-off (empty when there were none), or None when unreadable."""
    if not result["incidents_vector"]:
        return []
    try:
        begin, end = layout.vector_bounds(memory.read(result["incidents_vector"], 0x10), 0)
        if end < begin or end - begin > layout.INCIDENT_SIZE * MAX_INCIDENTS:
            return None
        return layout.decode_incidents(memory.read(begin, end - begin)) if end > begin else []
    except (OSError, probe.ProbeError, struct.error):
        return None


def managed_squad(memory: Memory) -> list[dict]:
    """The managed first team, with the short ID match records use.

    A match player record names its player by a short ID stored at person
    +0x08, beside the unique ID the squad reader already uses (+0x0C).
    """
    start = memory.u64(first_team_address(memory) + 0x38)
    end = memory.u64(first_team_address(memory) + 0x40)
    players = []
    for index in range((end - start) // 8):
        try:
            # Player-coaches too: see probe.SHOWN_PLAYER_LAYOUTS.
            person = probe.squad_entry_person(memory.fd, memory.module_base, memory.u64(start + index * 8))
            if person is None:
                continue
            short_id, unique_id = struct.unpack("<Ii", memory.read(person + 0x8, 8))
            actual = person + 0x28
            name = " ".join(
                part for part in (
                    probe.read_fm_string(memory.fd, actual + 0x30),
                    probe.read_fm_string(memory.fd, actual + 0x38),
                ) if part
            )
        except (OSError, probe.ProbeError):
            continue
        players.append({"short_id": short_id, "id": str(unique_id), "name": name})
    return players


def player_names(memory: Memory, short_ids: set[int]) -> dict[int, str]:
    """Names for match-record short IDs, found by one scan of FM's player objects.

    A player's person part starts with its class table and carries the short
    ID straight after it (+0x08), so the pair is a unique 12-byte pattern.
    The names are the same fields the squad reader uses.
    """
    if not short_ids:
        return {}
    # Ordinary players and players with a staff role (player-coaches) alike.
    markers = [struct.pack("<Q", memory.module_base + type_rva) for _, type_rva in probe.SHOWN_PLAYER_LAYOUTS]
    patterns = {marker + struct.pack("<I", short_id): str(short_id) for marker in markers for short_id in short_ids}
    names: dict[int, str] = {}
    for short_id, addresses in memory.scan(patterns, align=8, limit=4).items():
        for person in addresses:
            try:
                name = " ".join(
                    part for part in (
                        probe.read_fm_string(memory.fd, person + 0x58),
                        probe.read_fm_string(memory.fd, person + 0x60),
                    ) if part
                )
            except (OSError, probe.ProbeError):
                continue
            if name:
                names[int(short_id)] = name
                break
    return names


def temporary_folder(pid: int) -> Path | None:
    """FM's Temporary folder, where it keeps its match archive, from the files it has open."""
    fds = Path("/proc") / str(pid) / "fd"
    try:
        for link in fds.iterdir():
            try:
                target = Path(os.readlink(link))
            except OSError:
                continue
            if target.parent.name == "Temporary" and target.name.startswith("pks_"):
                return target.parent
    except OSError:
        pass
    return None


def default_temporary_folder(executable: Path) -> Path | None:
    """Where Proton keeps FM20's Temporary folder, for when FM has no archive file open."""
    library = executable.parents[2]  # .../steamapps
    folder = (library / "compatdata" / "1100600" / "pfx" / "drive_c" / "users" / "steamuser" / "AppData"
              / "Local" / "Sports Interactive" / "Football Manager 2020" / "Temporary")
    return folder if folder.is_dir() else None


def first_team_address(memory: Memory) -> int:
    contexts = probe.read_human_manager_contexts(memory.fd, memory.module_base)
    active = next((context for context in contexts if context.manager.active), None)
    if active is None or active.team_address is None:
        raise probe.ProbeError("FM20 has no active employed human manager")
    return active.team_address


def match_detail(memory: Memory, stats_address: int, squad: dict[int, dict]) -> dict[str, Any] | None:
    """A match's stats panel, players and timeline, or None for a blank copy."""
    header = memory.read(stats_address, layout.MATCH_STATS_SIZE)
    blocks = {
        side: memory.read(layout.pointer(header, offset), layout.TEAM_BLOCK_SIZE)
        for side, offset in (("home", layout.STATS_HOME_BLOCK), ("away", layout.STATS_AWAY_BLOCK))
    }
    teams = {side: layout.decode_team_block(block) for side, block in blocks.items()}
    if all(layout.team_block_is_empty(stats) for stats in teams.values()):
        return None
    players = []
    for side, block in blocks.items():
        order = 0
        for record_address in memory.pointers(block, layout.TEAM_PLAYERS, limit=64):
            player = layout.decode_player_record(memory.read(record_address, layout.PLAYER_RECORD_SIZE))
            if player is None:
                continue
            known = squad.get(player["short_id"]) if side == player["side"] else None
            players.append({
                **player,
                "side": side,
                "order": order,
                "started": order < layout.STARTERS,
                "player_id": known["id"] if known else None,
                "name": known["name"] if known else None,
            })
            order += 1
    events = [
        layout.decode_event(memory.read(event_address, layout.EVENT_SIZE))
        for event_address in memory.pointers(header, layout.STATS_EVENTS)
    ]
    return {"home": teams["home"], "away": teams["away"], "players": players, "events": events}


def saved_tactics(chunk: bytes, detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each side's saved tactic, where one places all its starters as FM's player records do."""
    prefixes = candidate_prefixes(chunk)
    found = {}
    for side in ("home", "away"):
        starters = [
            (layout.position_code(player["start_position"], player["start_centre_side"]), player["role_code"])
            for player in detail["players"]
            if player["side"] == side and player.get("started") and player.get("start_position")
        ]
        tactic = team_tactic(prefixes, starters)
        if tactic is not None:
            found[side] = {
                "name": tactic.name,
                "slots": [
                    {
                        "position": layout.position_name(slot.position & 0xFFFF),
                        "centreSide": layout.CENTRE_SIDES.get((slot.position >> 16) & 0xFF),
                        "roleCode": slot.role,
                        "dutyCode": slot.duty,
                    }
                    for slot in tactic.slots
                ],
            }
    return found


def opposition_formation(chunk: bytes, detail: dict[str, Any], our_side: str) -> dict[str, str]:
    """The opposition's formation as FM names it, keyed by its side, where its starters fix one."""
    their_side = "away" if our_side == "home" else "home"
    positions = [
        layout.position_code(player["start_position"], player["start_centre_side"])
        for player in detail["players"]
        if player["side"] == their_side and player.get("started") and player.get("start_position")
    ]
    ours = detail.get("saved_tactics", {}).get(our_side)
    name = formation_name(
        candidate_prefixes(chunk), positions, excluding=frozenset({ours["name"]}) if ours else frozenset()
    )
    return {their_side: name} if name else {}


def _team_json(club: dict[str, str] | None, team: int) -> dict[str, str]:
    return club or {"id": f"team:{team:#x}", "name": "Unknown team"}


def build_capture(memory: Memory) -> dict[str, Any]:
    clubs = Clubs(memory)
    team = first_team_address(memory)
    managed = clubs(team)
    if managed is None:
        raise probe.ProbeError("the managed club could not be read")
    game_date = probe.decode_fm_date(
        memory.read(memory.module_base + probe.FM20_4_4_STEAM.current_date_offset, 4),
        minimum_year=2018,
    )
    results = played_results(memory)
    ours = {key: result for key, result in results.items() if team in (result["home_team"], result["away_team"])}
    competitions = {result["fixture_name"]: competition(memory, result["fixture_name"]) for result in ours.values()}

    squad = {player["short_id"]: player for player in managed_squad(memory)}
    details: dict[tuple, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for address in memory.instances(layout.GAME_MATCH_STATS):
        try:
            header = memory.read(address, layout.MATCH_STATS_SIZE)
            result = layout.decode_fixture_result(
                memory.read(layout.pointer(header, layout.STATS_RESULT), layout.FIXTURE_RESULT_SIZE)
            )
            key = (result["date"], result["home_team"], result["away_team"])
            if key not in ours or key in details:
                continue
            detail = match_detail(memory, address, squad)
        except (OSError, probe.ProbeError, struct.error):
            continue
        if detail is None:
            continue
        problems = layout.detail_problems(detail, ours[key]["home_goals"], ours[key]["away_goals"])
        if problems:
            rejected.append({"date": key[0].isoformat(), "problems": problems})
        else:
            details[key] = detail
    if rejected and not details:
        raise probe.ProbeError(
            "FM's match stats did not add up for any match, so FM's memory layout may have "
            "changed; nothing was saved. " + "; ".join(rejected[0]["problems"])
        )

    # Every other match's full stats, and every match's saved tactics, from the
    # archive FM keeps on disk (the latest match is there too).
    folder = temporary_folder(memory.pid) or default_temporary_folder(memory.executable)
    fixtures = []
    for key in ours:
        home, away = clubs(ours[key]["home_team"]), clubs(ours[key]["away_team"])
        if home and away and home["id"].isdigit() and away["id"].isdigit() and home["id"] != away["id"]:
            fixtures.append(
                (key, key[0], int(home["id"]), int(away["id"]), ours[key]["home_goals"], ours[key]["away_goals"])
            )
    if folder is not None and fixtures:
        found = archive.find_chunks(folder, fixtures)
        # A match still in memory whose fixture has more than one chunk (it was
        # replayed) is found by its own players' stats instead.
        for key, _date, home_id, away_id, home_goals, away_goals in fixtures:
            if key in details and key not in found:
                chunk_detail = archive.chunk_for_players(
                    folder, home_id, away_id, home_goals, away_goals, details[key]["players"]
                )
                if chunk_detail is not None:
                    found[key] = chunk_detail
        for key, (chunk, detail) in found.items():
            our_side = "home" if ours[key]["home_team"] == team else "away"
            if key not in details:
                for player in detail["players"]:
                    known = squad.get(player["short_id"]) if player["side"] == our_side else None
                    player["player_id"] = known["id"] if known else None
                    player["name"] = known["name"] if known else None
                details[key] = detail
            else:
                # Only the archive has the shots, and its timeline names each
                # event's player and added time, so it is used for the match
                # still in memory too.
                details[key]["events"] = detail["events"] or details[key]["events"]
                details[key]["shots"] = detail["shots"]
            details[key]["saved_tactics"] = saved_tactics(chunk, details[key])
            details[key]["formations"] = opposition_formation(chunk, details[key], our_side)

    # Every result's goals and sendings-off, kept only when the goals add up to the score.
    incidents: dict[tuple, list[dict[str, Any]]] = {}
    for key, result in ours.items():
        found = read_incidents(memory, result)
        problems = (
            ["could not be read"] if found is None
            else layout.incident_problems(found, result["home_goals"], result["away_goals"])
        )
        if problems:
            rejected.append({"date": key[0].isoformat(), "problems": [f"goals and red cards: {p}" for p in problems]})
        else:
            incidents[key] = found

    # A timeline must also show every sending-off the result records; one that
    # does not is incomplete, and is left out rather than shown short.
    for key, detail in details.items():
        sent_off = sum(1 for event in detail["events"] if event["kind"] == "sent_off")
        recorded = sum(1 for item in incidents.get(key, ()) if item["kind"] == "sent_off")
        if detail["events"] and key in incidents and sent_off != recorded and any(
            "playerShortId" in event for event in detail["events"]
        ):
            detail["events"] = []

    # Opposition players, and our own who have since left, are named by one scan.
    known = {short_id: player["name"] for short_id, player in squad.items()}
    known.update({
        player["short_id"]: player["name"]
        for detail in details.values() for player in detail["players"] if player["name"]
    })
    unnamed = {player["short_id"] for detail in details.values() for player in detail["players"] if not player["name"]}
    unnamed |= {item["playerShortId"] for found in incidents.values() for item in found} - set(known)
    names = player_names(memory, unnamed)
    for detail in details.values():
        for player in detail["players"]:
            if not player["name"]:
                player["name"] = names.get(player["short_id"])
    for found in incidents.values():
        for item in found:
            item["player"] = known.get(item["playerShortId"]) or names.get(item["playerShortId"])

    def match_json(key, result) -> dict[str, Any]:
        document = {
            "date": result["date"].isoformat(),
            "competition": competitions[result["fixture_name"]],
            "home": _team_json(clubs(result["home_team"]), result["home_team"]),
            "away": _team_json(clubs(result["away_team"]), result["away_team"]),
            "homeGoals": result["home_goals"],
            "awayGoals": result["away_goals"],
            "attendance": result["attendance"],
            "detail": _detail_json(details.get(key)),
        }
        if result["season"]:
            document["season"] = result["season"]
        if result["score_at_90"]:
            document["scoreAt90"] = list(result["score_at_90"])
        if result["penalties"]:
            document["penalties"] = list(result["penalties"])
        if key in incidents:
            document["incidents"] = incidents[key]
        return document

    league_results = []
    for fixture_name, comp in competitions.items():
        if not _is_league(results.values(), fixture_name, team):
            continue
        rows = [
            {
                "date": result["date"].isoformat(),
                "home": _team_json(clubs(result["home_team"]), result["home_team"]),
                "away": _team_json(clubs(result["away_team"]), result["away_team"]),
                "homeGoals": result["home_goals"],
                "awayGoals": result["away_goals"],
                "season": result["season"],
            }
            for result in results.values()
            if result["fixture_name"] == fixture_name
        ]
        league_results.append({"competition": comp, "results": sorted(rows, key=lambda row: row["date"])})

    return {
        "format": CAPTURE_FORMAT,
        "formatVersion": CAPTURE_FORMAT_VERSION,
        "capturedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gameDate": game_date.isoformat(),
        "source": {"tool": "tools/fm20_match_probe.py", "managedClub": managed},
        "matches": [match_json(key, result) for key, result in sorted(ours.items(), key=lambda item: item[0][0])],
        "competitionResults": league_results,
        "rejectedDetails": rejected,
    }


MAX_LEAGUE_TEAMS = 48


def _is_league(results, fixture_name: int, team: int) -> bool:
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


def _detail_json(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    return {
        "home": detail["home"],
        "away": detail["away"],
        "players": [
            {
                "side": player["side"],
                "order": player["order"],
                "started": player["started"],
                "shortId": player["short_id"],
                "playerId": player["player_id"],
                "name": player["name"],
                "shirt": player["shirt"],
                "roleCode": player["role_code"],
                "position": player["position"],
                "startPosition": player["start_position"],
                "startCentreSide": player["start_centre_side"],
                "played": player["played"],
                "rating": player["rating"],
                "cameOn": player["came_on"],
                "distanceM": player["distance_m"],
                "wentOff": player["went_off"],
                "stats": player["stats"],
            }
            for player in detail["players"]
        ],
        "events": detail["events"],
        **({"shots": detail["shots"]} if detail.get("shots") else {}),
        **({"savedTactics": detail["saved_tactics"]} if detail.get("saved_tactics") else {}),
        **({"formations": detail["formations"]} if detail.get("formations") else {}),
    }


def write_capture(document: dict[str, Any], output: Path) -> None:
    """Replace `output` atomically, so a reader never sees half a file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=output.name, suffix=".tmp", dir=output.parent)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=1)
    os.replace(temporary, output)


# -- research views ---------------------------------------------------------


def class_vtables(executable: Path, names: Sequence[str]) -> dict[str, list[int]]:
    with executable.open("rb") as handle:
        data = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        image = PeImage.parse(data)
        return {
            name: [
                int(table["rva"], 16)
                for result in find_rtti_vtables(data, image, name)
                for locator in result["completeObjectLocators"]
                for table in locator["vtables"]
            ]
            for name in names
        }


def class_name_at(memory: Memory, image, address: int) -> str | None:
    """The RTTI class of the object at `address`, if it has a vtable in FM."""
    try:
        vtable = memory.u64(address)
    except (OSError, probe.ProbeError):
        return None
    info = image.class_at_vtable(vtable - memory.module_base)
    return info.name if info else None


def hexdump(data: bytes) -> str:
    return "\n".join(
        f"+{offset:04x}: " + " ".join(f"{byte:02x}" for byte in data[offset:offset + 16])
        for offset in range(0, len(data), 16)
    )


def research(memory: Memory, args: argparse.Namespace) -> None:
    clubs = Clubs(memory)
    if args.command == "matches":
        for address in memory.instances(layout.GAME_MATCH_STATS):
            header = memory.read(address, layout.MATCH_STATS_SIZE)
            result = layout.decode_fixture_result(
                memory.read(layout.pointer(header, layout.STATS_RESULT), layout.FIXTURE_RESULT_SIZE)
            )
            detail = match_detail(memory, address, {})
            print(json.dumps({
                "address": hex(address),
                "date": result["date"].isoformat() if result["date"] else None,
                "home": (clubs(result["home_team"]) or {}).get("name"),
                "away": (clubs(result["away_team"]) or {}).get("name"),
                "score": f"{result['home_goals']}-{result['away_goals']}",
                "home_stats": detail and detail["home"],
                "away_stats": detail and detail["away"],
            }))
    elif args.command == "results":
        team = first_team_address(memory)
        for (day, home, away), result in sorted(played_results(memory).items(), key=lambda item: item[0][0]):
            if team in (home, away):
                comp = competition(memory, result["fixture_name"])
                print(f"{day} {comp['shortName'] or comp['name']}: {(clubs(home) or {}).get('name')} "
                      f"{result['home_goals']}-{result['away_goals']} {(clubs(away) or {}).get('name')}")
    elif args.command == "squad":
        for player in managed_squad(memory):
            print(json.dumps(player))
    elif args.command == "players":
        header = memory.read(int(args.address, 0), layout.MATCH_STATS_SIZE)
        for side, offset in (("home", layout.STATS_HOME_BLOCK), ("away", layout.STATS_AWAY_BLOCK)):
            block = memory.read(layout.pointer(header, offset), layout.TEAM_BLOCK_SIZE)
            records = memory.pointers(block, layout.TEAM_PLAYERS, limit=64)
            print(f"== {side}: {len(records)} records")
            for record in records:
                print(f"-- {record:#x}\n{hexdump(memory.read(record, layout.PLAYER_RECORD_SIZE))}")
    elif args.command == "scan":
        for name, tables in class_vtables(memory.executable, args.classes).items():
            for rva in tables:
                found = memory.instances(rva)
                print(f"{name} vtable {rva:#x}: {len(found)} instances {[hex(a) for a in found[:8]]}")
    elif args.command == "describe":
        from tools.fm20_pe_symbols import open_image

        address = int(args.address, 0)
        with open_image(memory.executable) as image:
            print(f"{address:#x} = {class_name_at(memory, image, address)}")
            for offset in range(0, 0x100, 8):
                for indirect in (False, True):
                    try:
                        text = probe.read_fm_string(memory.fd, address + offset, indirect=indirect)
                    except (OSError, OverflowError, probe.ProbeError):
                        continue
                    if text and text.isprintable():
                        print(f"  +{offset:#04x} {'indirect' if indirect else 'direct'}: {text!r}")
                try:
                    target = memory.u64(address + offset)
                except (OSError, probe.ProbeError):
                    continue
                name = class_name_at(memory, image, target) if target > 0x10000 else None
                if name:
                    print(f"  +{offset:#04x} -> {target:#x} = {name}")
    elif args.command == "find-u32":
        patterns = {struct.pack("<I", value): str(value) for value in args.values}
        for value, found in memory.scan(patterns, align=4).items():
            print(f"{value}: {len(found)} hits {[hex(a) for a in found[:16]]}")
    elif args.command == "dated":
        target = datetime.fromisoformat(args.date).date()
        for name, tables in class_vtables(memory.executable, [args.class_name]).items():
            for rva in tables:
                for address in memory.instances(rva):
                    try:
                        data = memory.read(address, int(args.size, 0))
                    except (OSError, probe.ProbeError):
                        continue
                    if any(layout.decode_fm_date(data[offset:offset + 4]) == target for offset in range(0, len(data) - 3, 2)):
                        print(f"-- {name} {address:#x}\n{hexdump(data)}")
    elif args.command == "near":
        first, second = args.first, args.second
        width = "<Q" if args.wide else "<I"
        hits = memory.scan({struct.pack(width, first): "a", struct.pack(width, second): "b"},
                           align=struct.calcsize(width), limit=1_000_000)
        seconds = sorted(hits["b"])
        import bisect
        shown = 0
        for a in hits["a"]:
            index = bisect.bisect_left(seconds, a - args.within)
            if index < len(seconds) and abs(seconds[index] - a) <= args.within:
                start = min(a, seconds[index]) - 0x20
                print(f"-- {first} at {a:#x}, {second} at {seconds[index]:#x}\n{hexdump(memory.read(start, args.within + 0x60))}")
                shown += 1
                if shown >= 12:
                    break
    elif args.command == "names":
        for short_id, name in sorted(player_names(memory, set(args.short_ids)).items()):
            print(short_id, name)
    elif args.command == "dump":
        print(hexdump(memory.read(int(args.address, 0), int(args.size, 0))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", type=int, help="FM process (default: the running one)")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="write the match-history capture JSON")
    capture.add_argument("--output", type=Path, required=True)
    for name in ("matches", "results", "squad"):
        commands.add_parser(name)
    commands.add_parser("players").add_argument("address")
    commands.add_parser("describe").add_argument("address")
    commands.add_parser("scan").add_argument("classes", nargs="+", help="e.g. FIXTURE_RESULT@sicomps")
    commands.add_parser("find-u32").add_argument("values", nargs="+", type=int)
    commands.add_parser("names").add_argument("short_ids", nargs="+", type=int)
    near = commands.add_parser("near", help="places where two 4-byte values sit close together")
    near.add_argument("first", type=lambda text: int(text, 0))
    near.add_argument("second", type=lambda text: int(text, 0))
    near.add_argument("--wide", action="store_true", help="8-byte values (pointers) instead of 4")
    near.add_argument("--within", type=int, default=0x40)
    dated = commands.add_parser("dated", help="dump a class's objects that carry a given FM date")
    dated.add_argument("class_name")
    dated.add_argument("date")
    dated.add_argument("size", nargs="?", default="0x80")
    dump = commands.add_parser("dump")
    dump.add_argument("address")
    dump.add_argument("size", nargs="?", default="0x100")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        memory = Memory(args.pid or running_pid())
    except (OSError, probe.ProbeError, RuntimeError) as exc:
        print(f"FM20 cannot be read: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "capture":
            document = build_capture(memory)
            write_capture(document, args.output)
            detailed = sum(1 for match in document["matches"] if match["detail"])
            print(f"Captured {len(document['matches'])} matches ({detailed} with full stats) "
                  f"up to {document['gameDate']}.")
            for item in document["rejectedDetails"]:
                print(f"Part of {item['date']} did not add up and was left out: "
                      + "; ".join(item["problems"]))
        else:
            research(memory, args)
    except probe.ProbeError as exc:
        print(f"FM20 match capture failed: {exc}", file=sys.stderr)
        return 1
    finally:
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
