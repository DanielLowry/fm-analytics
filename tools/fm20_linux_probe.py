#!/usr/bin/env python3
"""Read basic manager-visible context from FM20 running through Proton.

This is a deliberately narrow Phase 00 probe, not a production extraction
source. It reads the active manager, controlled club, and first-team identities
without exposing hidden player attributes.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence


FM20_EXECUTABLE_SUFFIX = "/Football Manager 2020/fm.exe"


@dataclass(frozen=True)
class Fm20Profile:
    name: str
    expected_product_version: str
    current_date_offset: int
    active_object_offset: int
    main_address_offset: int
    club_collection_offset: int
    person_collection_offset: int
    team_collection_offset: int
    collection_indirection_offset: int
    player_type_offset: int
    human_manager_type_offset: int


# Source: AppCakeLtd/FMScoutFramework at commit 9fb3904 (FMSE20 Final),
# Defines/Versions/Steam_20_4_4_Windows.cs. Proton runs the Windows executable,
# so its Windows module-relative offset is the relevant one.
FM20_4_4_STEAM = Fm20Profile(
    name="FM20 20.4.4 Steam/Windows executable",
    expected_product_version="20.4.4-1442341",
    current_date_offset=0x7386EE0,
    active_object_offset=0x75FC4B0,
    main_address_offset=0x748F280,
    club_collection_offset=0x20,
    person_collection_offset=0x70,
    team_collection_offset=0xA0,
    collection_indirection_offset=0x90,
    player_type_offset=0x6D92778,
    human_manager_type_offset=0x6D80CE0,
)


class ProbeError(RuntimeError):
    """The process could not be found, opened, or validated."""


@dataclass(frozen=True)
class ProbeResult:
    pid: int
    executable: str
    module_base: str
    profile: str
    expected_product_version: str
    game_date: str
    human_managers: tuple[HumanManagerResult, ...]
    first_team_squad: tuple[SquadPlayerResult, ...]


@dataclass(frozen=True)
class ClubResult:
    id: str
    name: str


@dataclass(frozen=True)
class HumanManagerResult:
    id: str
    name: str
    club: ClubResult | None
    active: bool


@dataclass(frozen=True)
class SquadPlayerResult:
    id: str
    name: str
    positions: tuple[str, ...]


@dataclass(frozen=True)
class _ManagerContext:
    manager: HumanManagerResult
    team_address: int | None


POSITION_CODES = (
    "GK",
    "SW",
    "DL",
    "DC",
    "DR",
    "DM",
    "ML",
    "MC",
    "MR",
    "AML",
    "AMC",
    "AMR",
    "ST",
    "WBL",
    "WBR",
)


def parse_module_mapping(lines: Iterable[str]) -> tuple[int, str]:
    candidates: list[tuple[int, str]] = []
    for line in lines:
        columns = line.rstrip().split(maxsplit=5)
        if len(columns) != 6:
            continue
        address_range, _permissions, offset, _device, _inode, path = columns
        if offset != "00000000" or not path.endswith(FM20_EXECUTABLE_SUFFIX):
            continue
        start_text, _end_text = address_range.split("-", maxsplit=1)
        candidates.append((int(start_text, 16), path))

    if not candidates:
        raise ProbeError("FM20 executable mapping was not found")
    return min(candidates)


def find_fm20_processes(proc_root: Path = Path("/proc")) -> list[int]:
    matches: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            with (entry / "maps").open(encoding="utf-8") as maps_file:
                parse_module_mapping(maps_file)
        except (OSError, UnicodeError, ProbeError):
            continue
        matches.append(int(entry.name))
    return sorted(matches)


def read_exact(memory_fd: int, address: int, size: int) -> bytes:
    data = os.pread(memory_fd, size, address)
    if len(data) != size:
        raise ProbeError(
            f"short memory read at 0x{address:x}: expected {size}, got {len(data)}"
        )
    return data


def read_i32(memory_fd: int, address: int) -> int:
    return struct.unpack("<i", read_exact(memory_fd, address, 4))[0]


def read_u64(memory_fd: int, address: int) -> int:
    return struct.unpack("<Q", read_exact(memory_fd, address, 8))[0]


def read_fm_string(
    memory_fd: int, field_address: int, *, indirect: bool = True
) -> str:
    string_address = read_u64(memory_fd, field_address)
    if string_address == 0:
        return ""
    if indirect:
        string_address = read_u64(memory_fd, string_address)
        if string_address == 0:
            return ""
    length = read_i32(memory_fd, string_address)
    if length <= 0:
        return ""
    if length > 1024:
        raise ProbeError(f"implausible FM string length {length} at 0x{string_address:x}")
    raw = read_exact(memory_fd, string_address + 4, length)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProbeError(f"invalid FM string at 0x{string_address:x}") from exc


def read_pointer_collection(
    memory_fd: int,
    module_base: int,
    root_offset: int,
    collection_offset: int,
    indirection_offset: int,
) -> tuple[int, ...]:
    root_field = module_base + root_offset + collection_offset
    first_pointer = read_u64(memory_fd, root_field)
    collection = read_u64(memory_fd, first_pointer + indirection_offset)
    start = read_u64(memory_fd, collection)
    end = read_u64(memory_fd, collection + 8)
    if start == 0 or end < start or (end - start) % 8 != 0:
        raise ProbeError(
            f"invalid pointer collection bounds 0x{start:x}-0x{end:x}"
        )
    count = (end - start) // 8
    if count > 1_000_000:
        raise ProbeError(f"implausible pointer collection size {count}")
    if count == 0:
        return ()
    return struct.unpack(f"<{count}Q", read_exact(memory_fd, start, count * 8))


def read_human_manager_contexts(
    memory_fd: int, module_base: int
) -> tuple[_ManagerContext, ...]:
    profile = FM20_4_4_STEAM
    people = read_pointer_collection(
        memory_fd,
        module_base,
        profile.main_address_offset,
        profile.person_collection_offset,
        profile.collection_indirection_offset,
    )
    expected_type = module_base + profile.human_manager_type_offset
    active_manager_id = read_i32(
        memory_fd, module_base + profile.active_object_offset
    )
    results: list[_ManagerContext] = []

    for person_address in people:
        if person_address == 0:
            continue
        try:
            if read_u64(memory_fd, person_address) != expected_type:
                continue

            # The human-manager structure begins 0x458 bytes before its shared
            # Person structure. Its embedded ActualPerson begins at +0x480.
            manager_base = person_address - 0x458
            actual_person = manager_base + 0x480
            manager_id = read_i32(memory_fd, person_address + 0xC)
            first_name = read_fm_string(memory_fd, actual_person + 0x30)
            last_name = read_fm_string(memory_fd, actual_person + 0x38)
            name = " ".join(part for part in (first_name, last_name) if part).strip()
            if not name:
                name = read_fm_string(
                    memory_fd, actual_person + 0x20, indirect=False
                )

            club: ClubResult | None = None
            team: int | None = None
            contract = read_u64(memory_fd, actual_person + 0xA0)
            if contract:
                team = read_u64(memory_fd, contract + 0x10) or None
                if team:
                    club = read_club_from_team(memory_fd, team)

            if club is None:
                club = find_managed_club(
                    memory_fd, module_base, person_address, expected_type
                )

            manager = HumanManagerResult(
                id=str(manager_id),
                name=name,
                club=club,
                active=manager_id == active_manager_id,
            )
            results.append(_ManagerContext(manager=manager, team_address=team))
        except (OSError, ProbeError):
            # One stale person entry should not prevent finding another human
            # manager during a game-state transition.
            continue

    return tuple(sorted(results, key=lambda item: not item.manager.active))


def read_human_managers(
    memory_fd: int, module_base: int
) -> tuple[HumanManagerResult, ...]:
    return tuple(
        context.manager
        for context in read_human_manager_contexts(memory_fd, module_base)
    )


def read_club_from_team(memory_fd: int, team_address: int) -> ClubResult | None:
    club_address = read_u64(memory_fd, team_address + 0x18)
    if club_address == 0:
        return None
    return ClubResult(
        id=str(read_i32(memory_fd, club_address + 0xC)),
        name=read_fm_string(memory_fd, club_address + 0xB8, indirect=False),
    )


def decode_positions(ratings: bytes) -> tuple[str, ...]:
    if len(ratings) != len(POSITION_CODES):
        raise ProbeError(
            f"position data requires {len(POSITION_CODES)} bytes, got {len(ratings)}"
        )
    positions = tuple(
        code for code, rating in zip(POSITION_CODES, ratings) if rating >= 15
    )
    if positions:
        return positions
    highest = max(range(len(ratings)), key=ratings.__getitem__)
    return (POSITION_CODES[highest],)


def read_first_team_squad(
    memory_fd: int, module_base: int, team_address: int
) -> tuple[SquadPlayerResult, ...]:
    if read_exact(memory_fd, team_address + 0x30, 1) != b"\x00":
        raise ProbeError("active manager contract does not point to a first team")
    start = read_u64(memory_fd, team_address + 0x38)
    end = read_u64(memory_fd, team_address + 0x40)
    if start == 0 or end < start or (end - start) % 8 != 0:
        raise ProbeError(f"invalid squad bounds 0x{start:x}-0x{end:x}")
    count = (end - start) // 8
    if count > 200:
        raise ProbeError(f"implausible first-team squad size {count}")

    expected_type = module_base + FM20_4_4_STEAM.player_type_offset
    players: dict[str, SquadPlayerResult] = {}
    for index in range(count):
        try:
            slot_address = read_u64(memory_fd, start + index * 8)
            player_address = slot_address + 0x8
            person_address = player_address + 0x1C0
            if read_u64(memory_fd, person_address) != expected_type:
                continue
            actual_person = player_address + 0x1E8
            player_id = str(read_i32(memory_fd, person_address + 0xC))
            first_name = read_fm_string(memory_fd, actual_person + 0x30)
            last_name = read_fm_string(memory_fd, actual_person + 0x38)
            name = " ".join(
                part for part in (first_name, last_name) if part
            ).strip()
            if not name:
                name = read_fm_string(
                    memory_fd, actual_person + 0x20, indirect=False
                )
            ratings = read_exact(memory_fd, player_address + 0x164, 15)
            players[player_id] = SquadPlayerResult(
                id=player_id,
                name=name,
                positions=decode_positions(ratings),
            )
        except (OSError, ProbeError):
            continue
    return tuple(sorted(players.values(), key=lambda player: player.name.casefold()))


def find_managed_club(
    memory_fd: int,
    module_base: int,
    human_person_address: int,
    expected_human_type: int,
) -> ClubResult | None:
    profile = FM20_4_4_STEAM
    teams = read_pointer_collection(
        memory_fd,
        module_base,
        profile.main_address_offset,
        profile.team_collection_offset,
        profile.collection_indirection_offset,
    )
    for team_address in teams:
        if team_address == 0:
            continue
        try:
            manager_pointer = read_u64(memory_fd, team_address + 0x78)
            if manager_pointer == 0:
                continue
            if read_u64(memory_fd, manager_pointer) == expected_human_type:
                candidate_person = manager_pointer
            elif read_u64(memory_fd, manager_pointer + 0x458) == expected_human_type:
                candidate_person = manager_pointer + 0x458
            else:
                continue
            if candidate_person == human_person_address:
                return read_club_from_team(memory_fd, team_address)
        except (OSError, ProbeError):
            continue
    return None


def decode_fm_date(raw: bytes) -> date:
    if len(raw) != 4:
        raise ProbeError(f"FM date requires four bytes, got {len(raw)}")
    encoded_day, year = struct.unpack("<HH", raw)
    day_of_year = encoded_day & 0x01FF
    if not 1 <= day_of_year <= 366 or not 2018 <= year <= 2300:
        raise ProbeError(
            f"invalid FM date components: day={day_of_year}, year={year}"
        )
    try:
        return date(year, 1, 1) + timedelta(days=day_of_year - 1)
    except ValueError as exc:
        raise ProbeError(
            f"invalid FM date components: day={day_of_year}, year={year}"
        ) from exc


def probe(pid: int, proc_root: Path = Path("/proc")) -> ProbeResult:
    process_dir = proc_root / str(pid)
    try:
        with (process_dir / "maps").open(encoding="utf-8") as maps_file:
            module_base, executable = parse_module_mapping(maps_file)
    except OSError as exc:
        raise ProbeError(f"cannot read process {pid} mappings: {exc}") from exc

    try:
        memory_fd = os.open(process_dir / "mem", os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ProbeError(
            f"cannot open process {pid} memory read-only: {exc}; "
            "check process ownership and ptrace policy"
        ) from exc

    try:
        signature = read_exact(memory_fd, module_base, 2)
        if signature != b"MZ":
            raise ProbeError(
                f"mapping at 0x{module_base:x} is not a PE image (got {signature!r})"
            )
        raw_date = read_exact(
            memory_fd, module_base + FM20_4_4_STEAM.current_date_offset, 4
        )
        manager_contexts = read_human_manager_contexts(memory_fd, module_base)
        human_managers = tuple(context.manager for context in manager_contexts)
        active_context = next(
            (context for context in manager_contexts if context.manager.active), None
        )
        first_team_squad = (
            read_first_team_squad(
                memory_fd, module_base, active_context.team_address
            )
            if active_context and active_context.team_address
            else ()
        )
    finally:
        os.close(memory_fd)

    game_date = decode_fm_date(raw_date)
    return ProbeResult(
        pid=pid,
        executable=executable,
        module_base=f"0x{module_base:x}",
        profile=FM20_4_4_STEAM.name,
        expected_product_version=FM20_4_4_STEAM.expected_product_version,
        game_date=game_date.isoformat(),
        human_managers=human_managers,
        first_team_squad=first_team_squad,
    )


def choose_pid(requested_pid: int | None) -> int:
    if requested_pid is not None:
        return requested_pid
    matches = find_fm20_processes()
    if not matches:
        raise ProbeError("no running FM20 process was found")
    if len(matches) > 1:
        joined = ", ".join(str(pid) for pid in matches)
        raise ProbeError(f"multiple FM20 processes found ({joined}); pass --pid")
    return matches[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read the current date from FM20 running through Proton"
    )
    parser.add_argument("--pid", type=int, help="FM20 host PID; auto-detected by default")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = probe(choose_pid(args.pid))
    except ProbeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        print(f"FM20 process: {result.pid}")
        print(f"Executable: {result.executable}")
        print(f"Module base: {result.module_base}")
        print(f"Profile: {result.profile}")
        print(f"Expected product version: {result.expected_product_version}")
        print(f"Game date: {result.game_date}")
        if result.human_managers:
            for manager in result.human_managers:
                role = "Active human manager" if manager.active else "Human manager"
                print(f"{role}: {manager.name} (ID {manager.id})")
                if manager.club:
                    print(f"Controlled club: {manager.club.name} (ID {manager.club.id})")
                else:
                    print("Controlled club: none")
        else:
            print("Human manager: not found")
        print(f"First-team squad: {len(result.first_team_squad)} players")
        for player in result.first_team_squad:
            print(f"- {player.name} (ID {player.id}; {', '.join(player.positions)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
