#!/usr/bin/env python3
"""Read-only backlink scan for FM20's previously observed search context.

This is research instrumentation, not a discoverability source. It preflights
the live search object against a saved A/B report, then scans bounded writable
memory for references to that object and its call arguments. The result helps
identify an owner accessible without opening Player Search in a new process.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any, Iterator, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_discoverability_cold_builder import run as builder_preflight
from tools.fm20_discoverability_experiment import _write_report
from tools.fm20_linux_probe import ProbeError
from tools.fm20_linux_probe_runtime import choose_pid

CHUNK_BYTES = 4 * 1024 * 1024
MAX_HITS_PER_TARGET = 500
MAX_ADDRESS = 0x1_0000_0000
MAX_SCAN_BYTES = 3 * 1024 * 1024 * 1024


def writable_regions(maps_text: str, max_address: int) -> Iterator[tuple[int, int, str]]:
    for line in maps_text.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 2 or not fields[1].startswith("rw"):
            continue
        start_text, end_text = fields[0].split("-", 1)
        start, end = int(start_text, 16), int(end_text, 16)
        if start >= max_address:
            continue
        yield start, min(end, max_address), fields[5] if len(fields) > 5 else ""


def scan_backlinks(
    fd: int,
    regions: Sequence[tuple[int, int, str]],
    targets: dict[str, int],
    *,
    max_bytes: int = MAX_SCAN_BYTES,
) -> dict[str, Any]:
    needles = {name: struct.pack("<Q", pointer) for name, pointer in targets.items()}
    hits: dict[str, list[dict[str, Any]]] = {name: [] for name in targets}
    overflow: dict[str, int] = {name: 0 for name in targets}
    scanned = 0
    skipped_regions: list[dict[str, Any]] = []
    for start, end, label in regions:
        length = end - start
        if length <= 0:
            continue
        if scanned + length > max_bytes:
            skipped_regions.append({"start": start, "end": end, "reason": "scan cap"})
            continue
        previous = b""
        for position in range(start, end, CHUNK_BYTES):
            size = min(CHUNK_BYTES, end - position)
            try:
                block = os.pread(fd, size, position)
            except OSError as exc:
                skipped_regions.append({
                    "start": position, "end": position + size,
                    "reason": f"memory read failed: {exc}",
                })
                previous = b""
                continue
            if len(block) != size:
                skipped_regions.append({
                    "start": position, "end": position + size,
                    "reason": "short memory read",
                })
                previous = b""
                continue
            window = previous + block
            base = position - len(previous)
            for name, needle in needles.items():
                offset = window.find(needle)
                while offset != -1:
                    address = base + offset
                    if address >= position or offset + 8 > len(previous):
                        item = {"address": address, "mappingStart": start,
                                "mappingEnd": end, "mappingLabel": label}
                        if len(hits[name]) < MAX_HITS_PER_TARGET:
                            hits[name].append(item)
                        else:
                            overflow[name] += 1
                    offset = window.find(needle, offset + 1)
            previous = block[-7:]
            scanned += size
    return {
        "scannedBytes": scanned,
        "skippedRegions": skipped_regions,
        "hits": hits,
        "overflowHitCounts": overflow,
    }


def parse_extra_target(value: str) -> tuple[str, int]:
    try:
        name, address = value.split("=", 1)
        pointer = int(address, 0)
    except ValueError as exc:
        raise ValueError("--target must be NAME=ADDRESS") from exc
    if not name.isidentifier() or pointer <= 0:
        raise ValueError("--target must have a valid name and positive address")
    return name, pointer


def run(
    report_path: Path, state: str, pid: int,
    extra_targets: dict[str, int] | None = None,
) -> dict[str, Any]:
    preflight = builder_preflight(report_path, state, pid, False)
    targets = {
        "source": preflight["sourcePointer"],
        "filterContext": preflight["filterContextPointer"],
        "scope": preflight["scopePointer"],
    }
    for name, pointer in (extra_targets or {}).items():
        if name in targets:
            raise ValueError(f"--target name conflicts with built-in target: {name}")
        targets[name] = pointer
    maps_text = Path(f"/proc/{pid}/maps").read_text(encoding="utf-8")
    regions = list(writable_regions(maps_text, MAX_ADDRESS))
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        result = scan_backlinks(fd, regions, targets)
    finally:
        os.close(fd)
    return {
        "researchOnly": True,
        "hypothesis": "A persistent native owner references the observed search source",
        "pid": pid,
        "stateLabel": state,
        "preflight": preflight,
        "targets": targets,
        "regionCount": len(regions),
        **result,
        "passed": not result["skippedRegions"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--state", choices=("no-package", "senior-vanarama"),
                        default="senior-vanarama")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--target", action="append", default=[],
                        help="additional NAME=ADDRESS backlink target")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        extra_targets = dict(parse_extra_target(item) for item in args.target)
        if len(extra_targets) != len(args.target):
            raise ValueError("duplicate --target name")
        result = run(args.report, args.state, choose_pid(args.pid), extra_targets)
        path = _write_report(result, args.output, "search-context-backlinks")
        print("RESULT " + json.dumps({
            "report": str(path),
            "passed": result["passed"],
            "scannedBytes": result["scannedBytes"],
            "hitCounts": {name: len(items) + result["overflowHitCounts"][name]
                          for name, items in result["hits"].items()},
        }, sort_keys=True), flush=True)
        return 0 if result["passed"] else 2
    except (OSError, ProbeError, ValueError, KeyError) as exc:
        failure = {"researchOnly": True, "passed": False, "error": str(exc)}
        path = _write_report(failure, args.output, "search-context-backlinks-failed")
        print("RESULT " + json.dumps({"report": str(path), **failure},
                                      sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
