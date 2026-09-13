#!/usr/bin/env python3
"""Query every manager-visible attribute for one player, by name or ID.

This formalizes the cold-call research proven throughout `03.2-fm-representation-research.md`
into one reusable entry point: resolve a player's stable ID, then sweep every
supported attribute through FM's own visibility builder via a fresh,
non-chained native call per attribute (see `fm20_cold_visibility_ptrace.py`
for the call mechanics and safety guarantees).

Deliberately NOT wired into `FmDataSource`/the HTTP bridge/the recruitment
analytics yet. Name/ID resolution here scans every loaded player in process
memory -- exactly like the research validation earlier in this project -- and
that is explicitly not a discoverability check. Phase 03's own guardrail
applies unchanged: "Never treat enumeration of the internal player database as
player-search visibility." This tool answers "what does the manager see for
THIS specific, already-identified player" -- a manual research/lookup tool,
not a source for "which players exist to consider," which remains gated
behind the unbuilt discoverability work.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fm_analytics.bridge.visibility_result import decode_visible_bound_bytes
from tools.fm20_cold_visibility_ptrace import cold_query
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    parse_module_mapping,
    read_fm_string,
    read_i32,
    read_pointer_collection,
    read_u64,
    validate_executable,
)
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_visibility_trace import DISPLAY_ATTRIBUTE_IDS

ATTRIBUTE_CATEGORY = {
    "aerialReach": "goalkeeping", "commandOfArea": "goalkeeping",
    "communication": "goalkeeping", "handling": "goalkeeping",
    "kicking": "goalkeeping", "reflexes": "goalkeeping",
    "rushingOut": "goalkeeping", "throwing": "goalkeeping",
    "oneOnOnes": "goalkeeping",
    "crossing": "technical", "dribbling": "technical", "finishing": "technical",
    "heading": "technical", "longShots": "technical", "marking": "technical",
    "passing": "technical", "tackling": "technical", "technique": "technical",
    "firstTouch": "technical", "corners": "technical",
    "aggression": "mental", "anticipation": "mental", "bravery": "mental",
    "vision": "mental", "decisions": "mental", "determination": "mental",
    "flair": "mental", "offTheBall": "mental", "positioning": "mental",
    "teamwork": "mental", "workRate": "mental", "composure": "mental",
    "concentration": "mental",
    "acceleration": "physical", "agility": "physical", "balance": "physical",
    "pace": "physical", "stamina": "physical", "strength": "physical",
    "jumpingReach": "physical", "naturalFitness": "physical",
}


@dataclass(frozen=True)
class ResolvedPlayer:
    id: str
    name: str


def find_player_by_name(pid: int, name: str, *, proc_root: Path = Path("/proc")) -> ResolvedPlayer:
    """Resolve a player's stable ID by an exact, case-insensitive name match.

    Reads only identity fields (type tag, ID, first/last name) -- never an
    attribute value. Fails closed on zero or multiple matches rather than
    guessing.
    """

    process = proc_root / str(pid)
    with (process / "maps").open(encoding="utf-8") as mappings:
        module_base, executable = parse_module_mapping(mappings)
    validate_executable(executable)
    wanted = name.casefold().strip()
    fd = os.open(process / "mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        people = read_pointer_collection(
            fd,
            module_base,
            FM20_4_4_STEAM.main_address_offset,
            FM20_4_4_STEAM.person_collection_offset,
            FM20_4_4_STEAM.collection_indirection_offset,
        )
        expected_type = module_base + FM20_4_4_STEAM.player_type_offset
        matches: list[ResolvedPlayer] = []
        for address in people:
            if not address:
                continue
            try:
                if read_u64(fd, address) != expected_type:
                    continue
                actual_person = address + 0x28
                first = read_fm_string(fd, actual_person + 0x30)
                last = read_fm_string(fd, actual_person + 0x38)
                full_name = f"{first} {last}".strip()
                if full_name.casefold() == wanted:
                    matches.append(
                        ResolvedPlayer(id=str(read_i32(fd, address + 0xC)), name=full_name)
                    )
            except (OSError, ProbeError):
                continue
    finally:
        os.close(fd)
    if len(matches) != 1:
        raise ProbeError(
            f"player name {name!r} matched {len(matches)} loaded players; "
            "use --player-id for an unambiguous lookup"
        )
    return matches[0]


def query_visible_attributes(
    pid: int,
    player_id: int,
    *,
    attributes: Sequence[str] = (),
) -> dict[str, dict[str, object]]:
    """Sweep every requested attribute through a fresh, non-chained cold call each."""

    selected = tuple(attributes) or tuple(sorted(DISPLAY_ATTRIBUTE_IDS))
    results: dict[str, dict[str, object]] = {}
    for attribute in selected:
        lower, upper = cold_query(pid, player_id, attribute)
        observation = decode_visible_bound_bytes(lower, upper)
        results[attribute] = {
            "category": ATTRIBUTE_CATEGORY.get(attribute, "unknown"),
            "visibility": observation.visibility.value,
            "value": observation.value,
            "minimum": observation.minimum,
            "maximum": observation.maximum,
        }
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--player-id", type=int)
    identity.add_argument("--player-name")
    parser.add_argument(
        "--attribute", action="append", choices=tuple(sorted(DISPLAY_ATTRIBUTE_IDS)),
        help="attribute to query; repeatable; defaults to every supported attribute",
    )
    parser.add_argument("--acknowledge-native-call", action="store_true", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pid = choose_pid(args.pid)
        if args.player_name is not None:
            resolved = find_player_by_name(pid, args.player_name)
            player_id, player_name = int(resolved.id), resolved.name
        else:
            player_id, player_name = args.player_id, None
        attributes = query_visible_attributes(
            pid, player_id, attributes=tuple(args.attribute or ())
        )
    except (OSError, ProbeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "playerId": str(player_id),
        "playerName": player_name,
        "researchOnly": True,
        "discoverabilityVerified": False,
        "attributes": attributes,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
