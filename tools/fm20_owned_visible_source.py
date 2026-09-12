#!/usr/bin/env python3
"""Read cache-independent, manager-visible data for the managed FM20 squad.

This standalone proof deliberately supports only players at the human manager's
club. FM20 exposes all of their attributes exactly, so underlying bytes can be
normalised without guessing another player's visibility. External players are
rejected until the visibility-result builder is safe to query directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    parse_module_mapping,
    read_exact,
    read_i32,
    read_first_team_squad,
    read_club_from_team,
    read_pointer_collection,
    read_u64,
    validate_executable,
)
from tools.fm20_linux_probe_runtime import choose_pid, probe
from tools.fm20_visibility_trace import (
    ATTRIBUTE_OFFSETS,
    DISPLAY_ATTRIBUTE_IDS,
    PLAYER_ATTRIBUTE_BLOCK_OFFSET,
    PLAYER_FROM_PERSON_OFFSET,
)


def normalize_attribute_byte(raw_value: int) -> int:
    """Mirror FM20's signed-byte conversion to its displayed 1--20 scale."""
    if not -128 <= raw_value <= 127:
        raise ProbeError(f"attribute byte is out of range: {raw_value}")
    return max(1, min(20, (raw_value + 2) // 5))


def select_players(
    players: Sequence[Any],
    *,
    player_id: int | None,
    player_name: str | None,
    scope_label: str = "active manager's first-team squad",
) -> tuple[Any, ...]:
    if player_id is not None:
        matches = tuple(player for player in players if player.id == str(player_id))
    elif player_name is not None:
        wanted = player_name.casefold().strip()
        matches = tuple(
            player for player in players if player.name.casefold() == wanted
        )
    else:
        return tuple(players)
    if not matches:
        requested = str(player_id) if player_id is not None else repr(player_name)
        raise ProbeError(f"player {requested} is not in the {scope_label}")
    if len(matches) > 1:
        raise ProbeError(f"player name {player_name!r} is ambiguous; use --player-id")
    return matches


def _process_mapping(pid: int, proc_root: Path) -> tuple[int, str]:
    try:
        with (proc_root / str(pid) / "maps").open(encoding="utf-8") as maps_file:
            return parse_module_mapping(maps_file)
    except OSError as exc:
        raise ProbeError(f"cannot read process {pid} mappings: {exc}") from exc


def _resolve_player_addresses(
    memory_fd: int,
    module_base: int,
    player_ids: set[int],
) -> dict[int, int]:
    people = read_pointer_collection(
        memory_fd,
        module_base,
        FM20_4_4_STEAM.main_address_offset,
        FM20_4_4_STEAM.person_collection_offset,
        FM20_4_4_STEAM.collection_indirection_offset,
    )
    expected_type = module_base + FM20_4_4_STEAM.player_type_offset
    resolved: dict[int, int] = {}
    for person_address in people:
        if not person_address:
            continue
        try:
            if read_u64(memory_fd, person_address) != expected_type:
                continue
            player_id = read_i32(memory_fd, person_address + 0xC)
        except (OSError, ProbeError):
            continue
        if player_id in player_ids:
            resolved[player_id] = person_address - PLAYER_FROM_PERSON_OFFSET
    missing = player_ids.difference(resolved)
    if missing:
        joined = ", ".join(str(item) for item in sorted(missing))
        raise ProbeError(f"managed-squad players disappeared during read: {joined}")
    return resolved


def _read_full_team_index(
    memory_fd: int,
    module_base: int,
) -> tuple[dict[str, object], ...]:
    teams = read_pointer_collection(
        memory_fd,
        module_base,
        FM20_4_4_STEAM.main_address_offset,
        FM20_4_4_STEAM.team_collection_offset,
        FM20_4_4_STEAM.collection_indirection_offset,
    )
    results: list[dict[str, object]] = []
    for address in teams:
        if not address:
            continue
        try:
            if read_exact(memory_fd, address + 0x30, 1) != b"\x00":
                continue
            start = read_u64(memory_fd, address + 0x38)
            end = read_u64(memory_fd, address + 0x40)
            if not start or end < start or (end - start) % 8:
                continue
            player_count = (end - start) // 8
            if player_count > 200:
                continue
            club = read_club_from_team(memory_fd, address)
            if club is None or not club.name:
                continue
        except (OSError, ProbeError):
            continue
        results.append(
            {
                "address": address,
                "id": club.id,
                "name": club.name,
                "playerCount": player_count,
            }
        )
    return tuple(results)


def list_full_visibility_teams(
    pid: int,
    *,
    query: str,
    limit: int = 50,
    proc_root: Path = Path("/proc"),
) -> tuple[dict[str, object], ...]:
    if not query.strip():
        raise ProbeError("full-visibility team search requires a query")
    if not 1 <= limit <= 100:
        raise ProbeError("team search limit must be between 1 and 100")
    module_base, executable = _process_mapping(pid, proc_root)
    validate_executable(executable)
    process_mem = proc_root / str(pid) / "mem"
    try:
        memory_fd = os.open(process_mem, os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ProbeError(f"cannot open process {pid} memory read-only: {exc}") from exc
    try:
        teams = _read_full_team_index(memory_fd, module_base)
    finally:
        os.close(memory_fd)
    wanted = query.casefold().strip()
    matches = [team for team in teams if wanted in str(team["name"]).casefold()]
    return tuple(
        {key: value for key, value in team.items() if key != "address"}
        for team in sorted(matches, key=lambda item: str(item["name"]).casefold())[
            :limit
        ]
    )


def resolve_full_team_name(pid: int, team_name: str) -> str:
    matches = tuple(
        team
        for team in list_full_visibility_teams(pid, query=team_name, limit=100)
        if str(team["name"]).casefold() == team_name.casefold().strip()
    )
    if len(matches) != 1:
        raise ProbeError(
            f"full-visibility team name {team_name!r} was not found uniquely; "
            "use --team-id"
        )
    return str(matches[0]["id"])


def _find_full_team(
    memory_fd: int,
    module_base: int,
    team_id: str,
) -> dict[str, object]:
    matches = [
        team
        for team in _read_full_team_index(memory_fd, module_base)
        if team["id"] == team_id
    ]
    if len(matches) != 1:
        raise ProbeError(f"full-visibility team ID {team_id!r} was not found uniquely")
    return matches[0]


def list_full_team_players(
    pid: int,
    *,
    team_id: str,
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    state = probe(pid, proc_root)
    module_base, executable = _process_mapping(pid, proc_root)
    validate_executable(executable)
    try:
        memory_fd = os.open(
            proc_root / str(pid) / "mem", os.O_RDONLY | os.O_CLOEXEC
        )
    except OSError as exc:
        raise ProbeError(f"cannot open process {pid} memory read-only: {exc}") from exc
    try:
        team = _find_full_team(memory_fd, module_base, team_id)
        players = read_first_team_squad(
            memory_fd,
            module_base,
            int(team["address"]),
            date.fromisoformat(state.game_date),
        )
    finally:
        os.close(memory_fd)
    return {
        "team": {"id": team["id"], "name": team["name"]},
        "players": tuple({"id": player.id, "name": player.name} for player in players),
    }


def _read_attributes(
    memory_fd: int,
    player_address: int,
    attributes: Sequence[str],
) -> dict[str, dict[str, object]]:
    observations: dict[str, dict[str, object]] = {}
    for attribute in attributes:
        address = (
            player_address
            + PLAYER_ATTRIBUTE_BLOCK_OFFSET
            + ATTRIBUTE_OFFSETS[attribute]
        )
        raw_value = int.from_bytes(
            read_exact(memory_fd, address, 1), "little", signed=True
        )
        observations[attribute] = {
            "visibility": "known",
            "value": normalize_attribute_byte(raw_value),
        }
    return observations


def source_owned_visible_data(
    pid: int,
    *,
    team_id: str | None = None,
    team_name: str | None = None,
    player_id: int | None = None,
    player_name: str | None = None,
    attributes: Sequence[str] = (),
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    before = probe(pid, proc_root)
    active = next(
        (manager for manager in before.human_managers if manager.active), None
    )
    if active is None or active.club is None:
        raise ProbeError("FM20 has no active employed human manager")
    if team_id is not None and active.club.id != team_id:
        raise ProbeError(
            f"only the managed team {active.club.name!r} is supported; "
            f"requested team ID {team_id!r}"
        )
    if team_name is not None and active.club.name.casefold() != team_name.casefold():
        raise ProbeError(
            f"only the managed team {active.club.name!r} is supported; "
            f"requested {team_name!r}"
        )
    selected = select_players(
        before.first_team_squad,
        player_id=player_id,
        player_name=player_name,
    )
    selected_attributes = tuple(attributes) or tuple(
        sorted(ATTRIBUTE_OFFSETS, key=DISPLAY_ATTRIBUTE_IDS.__getitem__)
    )
    module_base, executable = _process_mapping(pid, proc_root)
    validate_executable(executable)
    process_mem = proc_root / str(pid) / "mem"
    try:
        memory_fd = os.open(process_mem, os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ProbeError(f"cannot open process {pid} memory read-only: {exc}") from exc
    try:
        addresses = _resolve_player_addresses(
            memory_fd,
            module_base,
            {int(player.id) for player in selected},
        )
        players = [
            {
                **asdict(player),
                "attributes": _read_attributes(
                    memory_fd,
                    addresses[int(player.id)],
                    selected_attributes,
                ),
            }
            for player in selected
        ]
    finally:
        os.close(memory_fd)
    after = probe(pid, proc_root)
    if (
        after.game_date != before.game_date
        or {player.id for player in after.first_team_squad}
        != {player.id for player in before.first_team_squad}
    ):
        raise ProbeError("FM20 changed during the read; discard this snapshot")
    return {
        "source": "live-owned-squad",
        "visibilityGuarantee": "managed-player-exact",
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pid": pid,
        "profile": before.profile,
        "gameDate": before.game_date,
        "manager": {"id": active.id, "name": active.name},
        "team": asdict(active.club),
        "players": players,
    }


def source_full_visibility_data(
    pid: int,
    *,
    team_id: str,
    player_id: int | None = None,
    player_name: str | None = None,
    attributes: Sequence[str] = (),
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    """Read underlying values for an explicitly acknowledged diagnostic query."""
    state = probe(pid, proc_root)
    selected_attributes = tuple(attributes) or tuple(
        sorted(ATTRIBUTE_OFFSETS, key=DISPLAY_ATTRIBUTE_IDS.__getitem__)
    )
    module_base, executable = _process_mapping(pid, proc_root)
    validate_executable(executable)
    process_mem = proc_root / str(pid) / "mem"
    try:
        memory_fd = os.open(process_mem, os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ProbeError(f"cannot open process {pid} memory read-only: {exc}") from exc
    try:
        team = _find_full_team(memory_fd, module_base, team_id)
        before_players = read_first_team_squad(
            memory_fd,
            module_base,
            int(team["address"]),
            date.fromisoformat(state.game_date),
        )
        selected = select_players(
            before_players,
            player_id=player_id,
            player_name=player_name,
            scope_label=f"selected team {team['name']!r}",
        )
        addresses = _resolve_player_addresses(
            memory_fd,
            module_base,
            {int(player.id) for player in selected},
        )
        players = [
            {
                **asdict(player),
                "attributes": _read_attributes(
                    memory_fd,
                    addresses[int(player.id)],
                    selected_attributes,
                ),
            }
            for player in selected
        ]
        after_players = read_first_team_squad(
            memory_fd,
            module_base,
            int(team["address"]),
            date.fromisoformat(state.game_date),
        )
    finally:
        os.close(memory_fd)
    if {player.id for player in before_players} != {
        player.id for player in after_players
    }:
        raise ProbeError("FM20 team changed during the read; discard this snapshot")
    return {
        "source": "live-full-visibility-diagnostic",
        "visibilityGuarantee": "underlying-exact-not-manager-visible",
        "warning": (
            "Diagnostic full visibility may reveal attributes hidden from the "
            "human manager. Do not use this output for analytics."
        ),
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pid": pid,
        "profile": state.profile,
        "gameDate": state.game_date,
        "team": {"id": team["id"], "name": team["name"]},
        "players": players,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read visible exact attributes for the managed FM20 squad"
    )
    parser.add_argument("--pid", type=int, help="FM20 host PID; auto-detected")
    parser.add_argument(
        "--visibility",
        choices=("in-game", "full"),
        default="in-game",
        help="visibility policy (default: %(default)s)",
    )
    parser.add_argument(
        "--acknowledge-hidden-data",
        action="store_true",
        help="required with --visibility full",
    )
    team = parser.add_mutually_exclusive_group()
    team.add_argument("--team", help="team name")
    team.add_argument("--team-id", help="numeric team ID")
    player = parser.add_mutually_exclusive_group()
    player.add_argument("--player-id", type=int)
    player.add_argument("--player-name")
    parser.add_argument(
        "--attribute",
        action="append",
        choices=tuple(sorted(ATTRIBUTE_OFFSETS)),
        help="attribute to read; repeatable; defaults to all supported attributes",
    )
    parser.add_argument("--output", type=Path, help="also write JSON to this file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pid = choose_pid(args.pid)
        if args.visibility == "full":
            if not args.acknowledge_hidden_data:
                raise ProbeError(
                    "--visibility full requires --acknowledge-hidden-data"
                )
            team_id = args.team_id
            if team_id is None:
                if args.team is None:
                    raise ProbeError("full visibility requires --team or --team-id")
                team_id = resolve_full_team_name(pid, args.team)
            if not team_id.isdecimal():
                raise ProbeError("--team-id must be numeric")
            result = source_full_visibility_data(
                pid,
                team_id=team_id,
                player_id=args.player_id,
                player_name=args.player_name,
                attributes=args.attribute or (),
            )
        else:
            if args.acknowledge_hidden_data:
                raise ProbeError(
                    "--acknowledge-hidden-data is valid only with full visibility"
                )
            result = source_owned_visible_data(
                pid,
                team_id=args.team_id,
                team_name=args.team,
                player_id=args.player_id,
                player_name=args.player_name,
                attributes=args.attribute or (),
            )
    except ProbeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
