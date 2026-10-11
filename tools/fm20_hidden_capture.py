#!/usr/bin/env python3
"""Read every league club's players' hidden attributes from FM, for the League page's hidden view.

HIDDEN DATA. This reads what FM keeps for a player whether or not it shows the
manager: the true value of every attribute on his profile, and his true rating
at every position. It writes ``data/hidden-capture.json`` (``domain/hidden.py``),
which only the League page's "Hidden attributes" view reads
(docs/hidden-attributes.md). The recommendation, the visible League comparison
and Scouting never see it.

Read-only plain memory reads: no FM code runs, in the game or in a sandbox.

- **Clubs and squads.** The same league link and first-team squads as the
  League page's read (``fm20_league_capture``), loans inside the league
  resolved the same way, so both pages compare the same squads. Our own squad
  is read like the others' here, from our first team's list.
- **Starters.** Every player in a starting line-up the match history holds for
  this save, ours and the other league clubs', wherever he plays now. A line-up
  names players by the short ID FM's match records use; a player's person part
  carries that short ID at +0x08 and his unique ID at +0x0C
  (``fm20_match_probe.player_names``), so one pass over FM's person list finds
  everyone.
- **Values.** The block at player + 0x164: the fifteen position ratings, then
  each attribute at the offsets FMScoutFramework pins for 20.4.4
  (``fm20_visibility_trace.ATTRIBUTE_OFFSETS``), converted to FM's 1-20 scale
  exactly as our own squad's read converts them.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Iterable

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from fm_analytics.domain.hidden import HiddenCapture, POSITION_CODES
from fm_analytics.persistence.match_history import MatchHistoryStore
from tools import fm20_linux_probe as probe
from tools.fm20_league_capture import (
    COMP_ID,
    LeagueCaptureError,
    contracted_club,
    league_members,
    read_identity,
    read_squad,
    season_label,
    shared_players,
)
from tools import fm20_match_layout as layout
from tools.fm20_linux_probe_runtime import snapshot_marker
from tools.fm20_match_probe import Memory, first_team_address
from tools.fm20_owned_visible_source import normalize_attribute_byte
from tools.fm20_status import running_pid
from tools.fm20_visibility_trace import ATTRIBUTE_OFFSETS, PLAYER_ATTRIBUTE_BLOCK_OFFSET

BLOCK_SIZE = max(ATTRIBUTE_OFFSETS.values()) + 1
PERSON_SHORT_ID = 0x08
PERSON_UNIQUE_ID = 0x0C


def decode_block(block: bytes) -> tuple[dict[str, int], dict[str, int]]:
    """(attributes on FM's 1-20 scale, the fifteen position ratings) from a player's block."""
    if len(block) < BLOCK_SIZE:
        raise probe.ProbeError(f"a player's attribute block needs {BLOCK_SIZE} bytes, got {len(block)}")
    ratings = dict(zip(POSITION_CODES, block[:len(POSITION_CODES)]))
    if not all(1 <= rating <= 20 for rating in ratings.values()):
        raise probe.ProbeError("a player's position ratings are not FM's 1-20 ratings")
    attributes = {name: normalize_attribute_byte(struct.unpack_from("<b", block, offset)[0])
                  for name, offset in ATTRIBUTE_OFFSETS.items()}
    return attributes, ratings


def player_index(memory: Memory) -> dict[int, tuple[int, int, int]]:
    """Every player in FM's person list: short ID -> (player record, person part, unique ID).

    Ordinary players and players who also hold a staff role alike
    (``fm20_linux_probe.SHOWN_PLAYER_LAYOUTS``); the player record sits
    before the person part by the layout's own distance.
    """
    profile = probe.FM20_4_4_STEAM
    people = probe.read_pointer_collection(memory.fd, memory.module_base, profile.main_address_offset,
                                           profile.person_collection_offset, profile.collection_indirection_offset)
    record_offset = {memory.module_base + type_rva: person_offset - 8
                     for person_offset, type_rva in probe.SHOWN_PLAYER_LAYOUTS}
    index: dict[int, tuple[int, int, int]] = {}
    for person in people:
        if not person:
            continue
        try:
            table, short_id, unique_id = struct.unpack("<QII", os.pread(memory.fd, 16, person))
        except (OSError, struct.error):
            continue
        offset = record_offset.get(table)
        if offset is not None and short_id:
            index[short_id] = (person - offset, person, unique_id)
    return index


def stored_starters(store: MatchHistoryStore, save_key: str) -> tuple[set[str], set[int]]:
    """(unique IDs, short IDs) of everyone in a starting line-up the history holds for the save."""
    history = store.load_history(save_key)
    matches = (history.matches if history else ()) + store.load_club_matches(save_key)
    unique_ids: set[str] = set()
    short_ids: set[int] = set()
    for match in matches:
        for player in match.detail.players if match.detail else ():
            if player.started:
                short_ids.add(player.short_id)
                if player.player_id:
                    unique_ids.add(player.player_id)
    return unique_ids, short_ids


def read_player(fd: int, record: int, person: int, unique_id: int, short_id: int, as_of: date) -> dict:
    name, _born, age = read_identity(fd, person, as_of)
    attributes, ratings = decode_block(probe.read_exact(fd, record + PLAYER_ATTRIBUTE_BLOCK_OFFSET, BLOCK_SIZE))
    return {"id": str(unique_id), "shortId": short_id, "name": name, "age": age,
            "attributes": attributes, "positionRatings": ratings}


def _club(memory: Memory, team: int) -> probe.ClubResult:
    club = probe.read_club_from_team(memory.fd, team)
    if club is None:
        raise LeagueCaptureError(f"a league team at {team:#x} has no readable club")
    return club


def capture_hidden(pid: int, store: MatchHistoryStore, *, save_key: str | None = None) -> HiddenCapture:
    started = time.monotonic()
    before = snapshot_marker(pid)
    as_of = date.fromisoformat(before.game_date)
    key = save_key or f"club:{before.club_id}"
    with closing(Memory(pid)) as memory:
        managed = first_team_address(memory)
        competition, members = league_members(memory, managed)
        clubs = {team: _club(memory, team) for team in members}
        squads = {team: read_squad(memory, team)[0] for team in members}
        ours = clubs[managed].id
        listings = {clubs[team].id: [str(player_id) for player_id in squad] for team, squad in squads.items()}
        interfaces = {player_id: interface for squad in squads.values() for player_id, interface in squad.items()}
        left_out = shared_players(listings, lambda player_id: contracted_club(memory.fd, interfaces[int(player_id)]),
                                  ours, {club.id: club.name for club in clubs.values()})
        index = player_index(memory)
        by_unique = {unique_id: short_id for short_id, (_record, _person, unique_id) in index.items()}
        unique_ids, short_ids = stored_starters(store, key)
        wanted = {by_unique[int(player_id)] for team_squad in listings.values() for player_id in team_squad
                  if int(player_id) in by_unique}
        wanted |= {by_unique[int(player_id)] for player_id in unique_ids if int(player_id) in by_unique}
        wanted |= short_ids & index.keys()
        players, unreadable = {}, 0
        for short_id in sorted(wanted):
            record, person, unique_id = index[short_id]
            try:
                players[str(unique_id)] = read_player(memory.fd, record, person, unique_id, short_id, as_of)
            except (OSError, probe.ProbeError, LeagueCaptureError, struct.error):
                unreadable += 1
        teams = []
        for team in sorted(members, key=lambda t: (t != managed, clubs[t].name.casefold())):
            club = clubs[team]
            kept = [player_id for player_id in listings[club.id]
                    if player_id not in left_out.get(club.id, {}) and player_id in players]
            missing = len(listings[club.id]) - len(left_out.get(club.id, {})) - len(kept)
            evidence = (f"First-team squad from FM, {len(kept)} players"
                        + (f"; {len(left_out[club.id])} on loan at another league club counted there"
                           if club.id in left_out else "")
                        + (f"; {missing} could not be read" if missing else ""))
            teams.append({"club": {"id": club.id, "name": club.name}, "playerIds": kept, "evidence": evidence})
        comp = {"id": str(struct.unpack("<i", memory.read(competition + COMP_ID, 4))[0]),
                "name": probe.read_fm_string(memory.fd, competition + layout.COMP_NAME, indirect=False) or "League",
                "shortName": probe.read_fm_string(memory.fd, competition + layout.COMP_SHORT_NAME, indirect=False) or ""}
        moved = [clubs[team].name for team in members if read_squad(memory, team)[0] != squads[team]]
    if snapshot_marker(pid) != before or moved:
        raise LeagueCaptureError("FM changed during the read" + (f" ({', '.join(moved)})" if moved else "") + "; try again")
    unfound = len(short_ids - index.keys())
    notes = [f"Read in {time.monotonic() - started:.1f} s: {len(players)} players, every league squad and "
             f"{len(short_ids) - unfound} of the {len(short_ids)} starters in stored line-ups."]
    if unfound:
        # Seen 11 October 2026: last season's retirements, and players FM made up for
        # lower-league cup opponents and removed afterwards. Every league starter was found.
        notes.append(f"{unfound} starter(s) in stored line-ups are no longer players in FM's database (retired, "
                     "or made up by FM for a lower-league cup opponent), so line-ups with them are not scored.")
    if unreadable:
        notes.append(f"{unreadable} player(s) could not be read this time.")
    document = {"format": "fm-analytics/hidden-attributes", "formatVersion": 1, "saveKey": key,
                "gameDate": as_of.isoformat(), "season": season_label(as_of),
                "club": {"id": ours, "name": clubs[managed].name}, "competition": comp,
                "teams": teams, "players": sorted(players.values(), key=lambda row: int(row["id"])), "notes": notes}
    return HiddenCapture.from_document(document)  # the same checks the web applies


def write_capture(capture: HiddenCapture, output: Path) -> None:
    """Replace the file whole, so the web never reads half a capture."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    temporary.write_text(json.dumps(capture.to_document(), indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, output)


def summary(capture: HiddenCapture, output: Path) -> dict:
    return {"output": str(output), "gameDate": capture.game_date.isoformat(),
            "competition": capture.competition.name, "clubs": len(capture.teams),
            "players": len(capture.players), "notes": list(capture.notes)}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/hidden-capture.json"))
    parser.add_argument("--match-db", type=Path, default=Path("data/match-history.sqlite3"),
                        help="the match history whose stored line-ups to read players for")
    parser.add_argument("--save-key", help="save identity; defaults to club:<our club id>, as the other stores do")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        capture = capture_hidden(running_pid(), MatchHistoryStore(args.match_db), save_key=args.save_key)
    except (OSError, probe.ProbeError, LeagueCaptureError, ValueError) as exc:
        print(f"Hidden attributes were not read: {exc}", file=sys.stderr)
        return 1
    write_capture(capture, args.output)
    print(json.dumps(summary(capture, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
