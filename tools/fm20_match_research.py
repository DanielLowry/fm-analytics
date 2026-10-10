#!/usr/bin/env python3
"""The research views of ``fm20_match_probe.py``: how its match layouts were found.

Run through the probe (``python3 tools/fm20_match_probe.py matches`` and the
other commands it lists); nothing here is part of the capture. Read-only, as
the probe is.
"""

from __future__ import annotations

import argparse
import bisect
import json
import mmap
import struct
from datetime import datetime
from pathlib import Path
from typing import Sequence

from tools import fm20_linux_probe as probe
from tools import fm20_match_layout as layout
from tools.fm20_field_workbench import PeImage, find_rtti_vtables
from tools.fm20_match_probe import (
    Clubs, Memory, competition, first_team_address, managed_squad, match_detail, played_results, player_names,
)


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
