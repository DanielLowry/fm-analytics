#!/usr/bin/env python3
"""Read the current date from an FM20 process running through Proton.

This is a deliberately narrow Phase 00 probe, not a production extraction
source. It reads only the mapped PE signature and the documented current-date
field. It does not scan memory or expose player data.
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


# Source: AppCakeLtd/FMScoutFramework at commit 9fb3904 (FMSE20 Final),
# Defines/Versions/Steam_20_4_4_Windows.cs. Proton runs the Windows executable,
# so its Windows module-relative offset is the relevant one.
FM20_4_4_STEAM = Fm20Profile(
    name="FM20 20.4.4 Steam/Windows executable",
    expected_product_version="20.4.4-1442341",
    current_date_offset=0x7386EE0,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

