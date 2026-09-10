"""Process-level orchestration for the low-level FM20 memory probe."""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

try:
    import tools.fm20_linux_probe as _probe_module
except ModuleNotFoundError:
    _probe_module = sys.modules.get("fm20_linux_probe", sys.modules["__main__"])

FM20_4_4_STEAM = _probe_module.FM20_4_4_STEAM
ProbeError = _probe_module.ProbeError
ProbeResult = _probe_module.ProbeResult
find_fm20_processes = _probe_module.find_fm20_processes
parse_module_mapping = _probe_module.parse_module_mapping
read_exact = _probe_module.read_exact
read_first_team_squad = _probe_module.read_first_team_squad
read_human_manager_contexts = _probe_module.read_human_manager_contexts
validate_executable = _probe_module.validate_executable


def decode_fm_date(
    raw: bytes,
    *,
    minimum_year: int = 1900,
    maximum_year: int = 2300,
) -> date:
    if len(raw) != 4:
        raise ProbeError(f"FM date requires four bytes, got {len(raw)}")
    encoded_day, year = struct.unpack("<HH", raw)
    day_of_year = encoded_day & 0x01FF
    if not 1 <= day_of_year <= 366 or not minimum_year <= year <= maximum_year:
        raise ProbeError(f"invalid FM date components: day={day_of_year}, year={year}")
    try:
        return date(year, 1, 1) + timedelta(days=day_of_year - 1)
    except ValueError as exc:
        raise ProbeError(f"invalid FM date components: day={day_of_year}, year={year}") from exc


# The memory-oriented module calls this decoder while walking player records.
# Install the orchestration implementation there after the responsibilities are
# split, while preserving the original public tool imports.
_probe_module.decode_fm_date = decode_fm_date


def probe(pid: int, proc_root: Path = Path("/proc")) -> ProbeResult:
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
        raw_date = read_exact(memory_fd, module_base + FM20_4_4_STEAM.current_date_offset, 4)
        game_date = decode_fm_date(raw_date, minimum_year=2018)
        manager_contexts = read_human_manager_contexts(memory_fd, module_base)
        active_context = next(
            (context for context in manager_contexts if context.manager.active), None
        )
        first_team_squad = (
            read_first_team_squad(memory_fd, module_base, active_context.team_address, game_date)
            if active_context and active_context.team_address
            else ()
        )
    finally:
        os.close(memory_fd)
    return ProbeResult(
        pid=pid,
        executable=executable,
        module_base=f"0x{module_base:x}",
        profile=FM20_4_4_STEAM.name,
        expected_product_version=FM20_4_4_STEAM.expected_product_version,
        game_date=game_date.isoformat(),
        human_managers=tuple(context.manager for context in manager_contexts),
        first_team_squad=first_team_squad,
    )


def choose_pid(requested_pid: int | None) -> int:
    if requested_pid is not None:
        return requested_pid
    matches = find_fm20_processes()
    if not matches:
        raise ProbeError("no running FM20 process was found")
    if len(matches) > 1:
        raise ProbeError(f"multiple FM20 processes found ({', '.join(map(str, matches))}); pass --pid")
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
        return 0
    print(f"FM20 process: {result.pid}")
    print(f"Executable: {result.executable}")
    print(f"Module base: {result.module_base}")
    print(f"Profile: {result.profile}")
    print(f"Expected product version: {result.expected_product_version}")
    print(f"Game date: {result.game_date}")
    for manager in result.human_managers:
        role = "Active human manager" if manager.active else "Human manager"
        print(f"{role}: {manager.name} (ID {manager.id})")
        print(
            f"Controlled club: {manager.club.name} (ID {manager.club.id})"
            if manager.club else "Controlled club: none"
        )
    if not result.human_managers:
        print("Human manager: not found")
    print(f"First-team squad: {len(result.first_team_squad)} players")
    for player in result.first_team_squad:
        age = str(player.age) if player.age is not None else "unknown"
        condition = f"{player.condition_percent}%" if player.condition_percent is not None else "unknown"
        fitness = f"{player.match_fitness_percent}%" if player.match_fitness_percent is not None else "unknown"
        print(
            f"- {player.name} (ID {player.id}; age {age}; {', '.join(player.positions)}; "
            f"condition {condition}; match fitness {fitness}; {player.availability})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
