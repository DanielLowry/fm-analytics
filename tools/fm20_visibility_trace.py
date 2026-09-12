#!/usr/bin/env python3
"""Resolve research-only FM20 attribute addresses without reading their values.

This tool prepares passive/debugger visibility tracing. It deliberately emits
only transient addresses and identifiers, never raw attribute values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    parse_module_mapping,
    read_i32,
    read_pointer_collection,
    read_u64,
    validate_executable,
)
from tools.fm20_linux_probe_runtime import choose_pid


PLAYER_FROM_PERSON_OFFSET = 0x1C0
PLAYER_ATTRIBUTE_BLOCK_OFFSET = 0x164
# The traced virtual getter indexes attributes from player + 0x16c. The
# framework offsets below are relative to player + 0x164, so its display-path
# attribute identifier is eight less than the framework offset.
DISPLAY_ATTRIBUTE_BASE_DELTA = 0x08

# Supported-build instruction immediately after the caller has loaded the
# three-byte visibility result pointer and immediately before it invokes the
# string formatter. The first two result bytes are the visible bounds or the
# unknown sentinels; research capture must never read the concealed third byte.
VISIBILITY_RESULT_RVA = 0x1D97A3E

# Pinned FMScoutFramework PlayerAttributeOffsets for FM20 20.4.4.
ATTRIBUTE_OFFSETS = {
    "crossing": 0x0F,
    "dribbling": 0x10,
    "finishing": 0x11,
    "heading": 0x12,
    "longShots": 0x13,
    "marking": 0x14,
    "offTheBall": 0x15,
    "passing": 0x16,
    "tackling": 0x18,
    "vision": 0x19,
    "handling": 0x1A,
    "aerialReach": 0x1B,
    "commandOfArea": 0x1C,
    "communication": 0x1D,
    "kicking": 0x1E,
    "throwing": 0x1F,
    "anticipation": 0x20,
    "decisions": 0x21,
    "oneOnOnes": 0x22,
    "positioning": 0x23,
    "reflexes": 0x24,
    "firstTouch": 0x25,
    "technique": 0x26,
    "flair": 0x29,
    "corners": 0x2A,
    "teamwork": 0x2B,
    "workRate": 0x2C,
    "rushingOut": 0x2F,
    "acceleration": 0x31,
    "strength": 0x33,
    "stamina": 0x34,
    "pace": 0x35,
    "jumpingReach": 0x36,
    "balance": 0x39,
    "bravery": 0x3A,
    "aggression": 0x3C,
    "agility": 0x3D,
    "naturalFitness": 0x41,
    "determination": 0x42,
    "composure": 0x43,
    "concentration": 0x44,
}


@dataclass(frozen=True)
class TraceTarget:
    pid: int
    profile: str
    module_base: str
    player_id: str
    player_address: str
    attribute: str
    display_attribute_id: str
    visibility_result_breakpoint: str
    raw_attribute_address: str
    value_read: bool = False


def raw_attribute_address(player_address: int, attribute: str) -> int:
    try:
        attribute_offset = ATTRIBUTE_OFFSETS[attribute]
    except KeyError as exc:
        raise ProbeError(f"unsupported trace attribute {attribute!r}") from exc
    return player_address + PLAYER_ATTRIBUTE_BLOCK_OFFSET + attribute_offset


def display_attribute_id(attribute: str) -> int:
    try:
        attribute_offset = ATTRIBUTE_OFFSETS[attribute]
    except KeyError as exc:
        raise ProbeError(f"unsupported trace attribute {attribute!r}") from exc
    return attribute_offset - DISPLAY_ATTRIBUTE_BASE_DELTA


def resolve_trace_target(
    pid: int,
    player_id: int | None,
    attribute: str,
    *,
    proc_root: Path = Path("/proc"),
) -> TraceTarget:
    process_dir = proc_root / str(pid)
    try:
        with (process_dir / "maps").open(encoding="utf-8") as maps_file:
            module_base, executable = parse_module_mapping(maps_file)
    except OSError as exc:
        raise ProbeError(f"cannot read process {pid} mappings: {exc}") from exc
    validate_executable(executable)
    try:
        memory_fd = os.open(process_dir / "mem", os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ProbeError(f"cannot open process {pid} memory read-only: {exc}") from exc
    try:
        resolved_player_id = (
            player_id
            if player_id is not None
            else read_i32(
                memory_fd,
                module_base + FM20_4_4_STEAM.active_object_offset,
            )
        )
        people = read_pointer_collection(
            memory_fd,
            module_base,
            FM20_4_4_STEAM.main_address_offset,
            FM20_4_4_STEAM.person_collection_offset,
            FM20_4_4_STEAM.collection_indirection_offset,
        )
        expected_type = module_base + FM20_4_4_STEAM.player_type_offset
        person_address = None
        for address in people:
            if not address:
                continue
            try:
                is_target = (
                    read_u64(memory_fd, address) == expected_type
                    and read_i32(memory_fd, address + 0xC) == resolved_player_id
                )
            except ProbeError:
                # Collections can contain an object that disappears while FM
                # is running. One stale pointer must not abort the full scan.
                continue
            if is_target:
                person_address = address
                break
        if person_address is None:
            source = "active object" if player_id is None else "requested ID"
            raise ProbeError(
                f"{source} {resolved_player_id} is not a loaded player"
            )
        player_address = person_address - PLAYER_FROM_PERSON_OFFSET
        target_address = raw_attribute_address(player_address, attribute)
    finally:
        os.close(memory_fd)
    return TraceTarget(
        pid=pid,
        profile=FM20_4_4_STEAM.name,
        module_base=f"0x{module_base:x}",
        player_id=str(resolved_player_id),
        player_address=f"0x{player_address:x}",
        attribute=attribute,
        display_attribute_id=f"0x{display_attribute_id(attribute):02x}",
        visibility_result_breakpoint=f"0x{module_base + VISIBILITY_RESULT_RVA:x}",
        raw_attribute_address=f"0x{target_address:x}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve a raw FM20 attribute address for visibility tracing"
    )
    parser.add_argument("--pid", type=int, help="FM20 host PID; auto-detected")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--player-id", type=int)
    identity.add_argument(
        "--active-player",
        action="store_true",
        help="resolve the player currently selected in FM",
    )
    parser.add_argument(
        "--attribute",
        choices=tuple(sorted(ATTRIBUTE_OFFSETS)),
        default="passing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = resolve_trace_target(
            choose_pid(args.pid),
            args.player_id if not args.active_player else None,
            args.attribute,
        )
    except ProbeError as exc:
        print(f"error: {exc}")
        return 1
    print(json.dumps(asdict(target), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
