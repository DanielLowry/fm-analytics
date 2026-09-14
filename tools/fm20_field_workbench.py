#!/usr/bin/env python3
"""Batch, research-only field discovery for the pinned FM20 executable.

Static mode finds field-specific UI/RTTI anchors and their candidate virtual
methods. Run mode also surveys the managed squad through the existing probe.
Neither mode reads or publishes unverified raw player-field values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import struct
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools.fm20_linux_probe import FM20_4_4_STEAM, ProbeError, validate_executable
from tools.fm20_linux_probe_runtime import choose_pid, probe
from tools.fm20_cold_visibility_call import EXPECTED_SHA256
from tools.fm20_search_caller_trace import trace_callers
from tools.fm20_visibility_capture import CaptureError


DEFAULT_EXECUTABLE = Path(
    "/games/SteamLibrary/steamapps/common/Football Manager 2020/fm.exe"
)
DEFAULT_REPORT_DIR = Path("data/research/fields")
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FieldSpec:
    key: str
    anchors: tuple[str, ...]
    rtti_classes: tuple[str, ...]
    visible_question: str


FIELD_SPECS = {
    spec.key: spec
    for spec in (
        FieldSpec(
            "footedness",
            ("FOOTEDNESS_LABEL", "FOOT_LABEL", "preferred_foot"),
            ("FOOTEDNESS_LABEL", "FOOT_LABEL"),
            "What foot/feet does FM show for this player?",
        ),
        FieldSpec(
            "position_proficiency",
            (
                "PLAYER_POSITION_LEVEL_LABEL",
                "PLAYER_POSITIONS_DETAILS_PANEL",
                "PLAYER_POSITIONS_INDICATOR_PANEL",
            ),
            (
                "PLAYER_POSITION_LEVEL_LABEL",
                "PLAYER_POSITIONS_DETAILS_PANEL",
                "PLAYER_POSITIONS_INDICATOR_PANEL",
            ),
            "What position-proficiency labels does FM show for this player?",
        ),
    )
}


@dataclass(frozen=True)
class Section:
    name: str
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    characteristics: int


@dataclass(frozen=True)
class PeImage:
    image_base: int
    sections: tuple[Section, ...]

    @classmethod
    def parse(cls, data: bytes | mmap.mmap) -> PeImage:
        if len(data) < 0x100 or data[:2] != b"MZ":
            raise ValueError("not a PE executable")
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_offset + 0x18 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
            raise ValueError("missing PE header")
        machine, section_count = struct.unpack_from("<HH", data, pe_offset + 4)
        optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
        optional_offset = pe_offset + 24
        if machine != 0x8664 or optional_size < 0x20 or optional_offset + optional_size > len(data):
            raise ValueError("expected a complete x64 PE32+ header")
        if struct.unpack_from("<H", data, optional_offset)[0] != 0x20B:
            raise ValueError("expected PE32+ optional header")
        image_base = struct.unpack_from("<Q", data, optional_offset + 24)[0]
        section_offset = optional_offset + optional_size
        if section_offset + section_count * 40 > len(data):
            raise ValueError("truncated PE section table")
        sections = []
        for index in range(section_count):
            offset = section_offset + 40 * index
            name = bytes(data[offset:offset + 8]).split(b"\0", 1)[0].decode("ascii", "replace")
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII", data, offset + 8
            )
            characteristics = struct.unpack_from("<I", data, offset + 36)[0]
            if raw_offset + raw_size > len(data):
                raise ValueError(f"section {name} exceeds executable size")
            sections.append(Section(
                name, virtual_address, virtual_size, raw_offset, raw_size,
                characteristics,
            ))
        return cls(image_base, tuple(sections))

    def offset_to_rva(self, offset: int) -> int | None:
        for section in self.sections:
            if section.raw_offset <= offset < section.raw_offset + section.raw_size:
                return section.virtual_address + offset - section.raw_offset
        return None

    def rva_to_offset(self, rva: int) -> int | None:
        for section in self.sections:
            if section.virtual_address <= rva < section.virtual_address + section.raw_size:
                return section.raw_offset + rva - section.virtual_address
        return None

    def is_executable_rva(self, rva: int) -> bool:
        return any(
            section.virtual_address <= rva < section.virtual_address + section.raw_size
            and bool(section.characteristics & 0x20000000)
            for section in self.sections
        )


def find_offsets(data: bytes | mmap.mmap, needle: bytes, *, limit: int = 32) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    while len(offsets) < limit:
        found = data.find(needle, cursor)
        if found < 0:
            break
        offsets.append(found)
        cursor = found + 1
    return offsets


def _location(image: PeImage, offset: int) -> dict[str, str | int | None]:
    rva = image.offset_to_rva(offset)
    return {
        "fileOffset": f"0x{offset:x}",
        "rva": f"0x{rva:x}" if rva is not None else None,
    }


def find_rtti_vtables(
    data: bytes | mmap.mmap, image: PeImage, class_name: str
) -> list[dict[str, Any]]:
    """Follow MSVC x64 type descriptor -> COL -> vtable pointer, if present.

    These are structural candidates, not evidence that any method returns a
    manager-visible field or can safely be invoked outside a UI call.
    """
    token = f".?AV{class_name}@@".encode("ascii")
    results: list[dict[str, Any]] = []
    for name_offset in find_offsets(data, token, limit=8):
        descriptor_offset = name_offset - 16
        descriptor_rva = image.offset_to_rva(descriptor_offset)
        if descriptor_rva is None:
            continue
        collectors: list[dict[str, Any]] = []
        for reference in find_offsets(data, struct.pack("<I", descriptor_rva), limit=128):
            col_offset = reference - 12
            if col_offset < 0 or col_offset + 24 > len(data):
                continue
            col_rva = image.offset_to_rva(col_offset)
            if col_rva is None:
                continue
            signature, _object_offset, _constructor_offset, type_rva, _hierarchy, self_rva = (
                struct.unpack_from("<IIIIII", data, col_offset)
            )
            if signature != 1 or type_rva != descriptor_rva or self_rva != col_rva:
                continue
            vtables = []
            col_va = image.image_base + col_rva
            for pointer_offset in find_offsets(data, struct.pack("<Q", col_va), limit=64):
                table_offset = pointer_offset + 8
                if table_offset + 8 > len(data):
                    continue
                first_va = struct.unpack_from("<Q", data, table_offset)[0]
                first_rva = first_va - image.image_base
                if not image.is_executable_rva(first_rva):
                    continue
                methods = []
                for index in range(32):
                    entry_offset = table_offset + 8 * index
                    if entry_offset + 8 > len(data):
                        break
                    function_va = struct.unpack_from("<Q", data, entry_offset)[0]
                    function_rva = function_va - image.image_base
                    if not image.is_executable_rva(function_rva):
                        break
                    methods.append(f"0x{function_rva:x}")
                vtables.append({
                    **_location(image, table_offset),
                    "firstMethodRvas": methods,
                })
            collectors.append({
                **_location(image, col_offset),
                "vtables": vtables,
            })
        results.append({
            "className": class_name,
            "typeDescriptor": _location(image, descriptor_offset),
            "completeObjectLocators": collectors,
        })
    return results


def rank_method_leads(rtti: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer class-specific non-destructor slots; never call them here."""
    appearances: dict[str, list[tuple[str, int]]] = {}
    for class_info in rtti:
        for locator in class_info["completeObjectLocators"]:
            for vtable in locator["vtables"]:
                for slot, rva in enumerate(vtable["firstMethodRvas"]):
                    appearances.setdefault(rva, []).append((class_info["className"], slot))
    ranked = sorted(
        (
            (rva, uses) for rva, uses in appearances.items()
            if any(slot > 0 for _name, slot in uses)
        ),
        key=lambda item: (
            len({name for name, _slot in item[1]}),
            len(item[1]),
            min(slot for _name, slot in item[1]),
            item[0],
        ),
    )
    return [
        {
            "rva": rva,
            "classes": sorted({name for name, _slot in appearances_list}),
            "vtableOccurrences": len(appearances_list),
            "slotIndices": sorted({slot for _name, slot in appearances_list}),
        }
        for rva, appearances_list in ranked[:24]
    ]


def find_property_selector_leads(
    data: bytes | mmap.mmap,
    image: PeImage,
    methods: Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    """Look for FM UI's `cmp edx, 'valu'/'fmat'` near candidate methods.

    A match is a possible property-dispatch site, not a player-field getter.
    """
    signatures = {
        "value": b"\x81\xfa\x75\x6c\x61\x76",
        "format": b"\x81\xfa\x74\x61\x6d\x66",
    }
    found: set[tuple[str, int, str]] = set()
    for method in methods:
        method_rva = int(method["rva"], 0)
        offset = image.rva_to_offset(method_rva)
        if offset is None:
            continue
        # Include a small neighborhood to catch an adjacent override body or
        # a thunk target without scanning unrelated parts of the executable.
        start = max(0, offset - 256)
        end = min(len(data), offset + 1024)
        window = data[start:end]
        for selector, signature in signatures.items():
            cursor = 0
            while (hit := window.find(signature, cursor)) >= 0:
                hit_rva = image.offset_to_rva(start + hit)
                if hit_rva is not None:
                    found.add((method["rva"], hit_rva, selector))
                cursor = hit + 1
    return [
        {
            "nearMethodRva": method,
            "comparisonRva": f"0x{rva:x}",
            "selector": selector,
        }
        for method, rva, selector in sorted(found, key=lambda item: (item[1], item[0], item[2]))[:48]
    ]


def scan_static(data: bytes | mmap.mmap, fields: Sequence[FieldSpec]) -> dict[str, Any]:
    image = PeImage.parse(data)
    field_results: dict[str, Any] = {}
    for spec in fields:
        rtti = [
            item
            for class_name in spec.rtti_classes
            for item in find_rtti_vtables(data, image, class_name)
        ]
        method_leads = rank_method_leads(rtti)
        field_results[spec.key] = {
            "visibleQuestion": spec.visible_question,
            "anchors": {
                anchor: [_location(image, offset) for offset in find_offsets(
                    data, anchor.encode("ascii"), limit=12
                )]
                for anchor in spec.anchors
            },
            "rtti": rtti,
            "rareMethodLeads": method_leads,
            "propertySelectorLeads": find_property_selector_leads(
                data, image, method_leads
            ),
        }
    return {
        "imageBase": f"0x{image.image_base:x}",
        "fields": field_results,
    }


def disassemble_leads(
    executable: Path, static_report: dict[str, Any], *, per_field: int
) -> dict[str, list[dict[str, Any]]]:
    """Collect short, bounded offline code excerpts for leading method RVAs."""
    if not 0 <= per_field <= 8:
        raise ValueError("--disassemble-top must be between 0 and 8")
    image_base = int(static_report["imageBase"], 0)
    excerpts: dict[str, list[dict[str, Any]]] = {}
    for field, info in static_report["fields"].items():
        entries = []
        for lead in info["rareMethodLeads"][:per_field]:
            address = image_base + int(lead["rva"], 0)
            try:
                completed = subprocess.run(
                    [
                        "objdump", "-D", "-M", "intel",
                        f"--start-address=0x{address:x}",
                        f"--stop-address=0x{address + 96:x}",
                        str(executable),
                    ],
                    check=True, capture_output=True, text=True, timeout=10,
                )
                lines = completed.stdout.splitlines()
                entries.append({
                    "rva": lead["rva"],
                    "lines": lines[-32:],
                    "interpretation": "unclassified static method; may be UI plumbing",
                })
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                entries.append({"rva": lead["rva"], "error": type(exc).__name__})
        excerpts[field] = entries
    return excerpts


def verified_executable_digest(executable: Path) -> str:
    """Use the same exact-build fingerprint as the proven cold-call tools."""
    validate_executable(str(executable))
    with executable.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise ProbeError("FM executable hash differs from the traced build")
    return digest


def select_trace_targets(
    static_report: dict[str, Any], *, per_field: int = 5
) -> dict[str, str]:
    """Choose bounded, field-labelled property handlers from static evidence."""
    if not 1 <= per_field <= 8:
        raise ValueError("trace target count per field must be 1 to 8")
    selected: dict[str, str] = {}
    for field, info in static_report["fields"].items():
        seen: set[str] = set()
        for lead in info["propertySelectorLeads"]:
            if lead["selector"] != "value":
                continue
            method = lead["nearMethodRva"]
            distance = int(lead["comparisonRva"], 0) - int(method, 0)
            if method in seen or not 0 <= distance <= 128:
                continue
            selected[f"{field}_{method}"] = method
            seen.add(method)
            if len(seen) >= per_field:
                break
    if not selected:
        raise ValueError("no value-property methods were found for tracing")
    if len(selected) > 16:
        raise ValueError("trace target selection exceeded 16 methods")
    return selected


def choose_validation_players(players: Sequence[Any], *, limit: int = 6) -> list[Any]:
    """Pick diverse owned-player position shapes without guessing footedness."""
    remaining = sorted(players, key=lambda item: (str(item.name).casefold(), str(item.id)))
    chosen: list[Any] = []
    covered: set[str] = set()
    while remaining and len(chosen) < limit:
        def coverage(player: Any) -> tuple[int, int]:
            positions = set(player.positions)
            groups = {
                "left" if code in {"DL", "ML", "AML", "WBL"} else
                "right" if code in {"DR", "MR", "AMR", "WBR"} else
                "central"
                for code in positions
            }
            tags = positions | groups | ({"multi-position"} if len(positions) > 1 else set())
            return len(tags - covered), len(positions)

        best = max(remaining, key=coverage)
        remaining.remove(best)
        chosen.append(best)
        positions = set(best.positions)
        covered.update(positions)
        covered.update(
            "left" if code in {"DL", "ML", "AML", "WBL"} else
            "right" if code in {"DR", "MR", "AMR", "WBR"} else "central"
            for code in positions
        )
        if len(positions) > 1:
            covered.add("multi-position")
    return chosen


def survey_owned_squad(pid: int) -> dict[str, Any]:
    before = probe(pid)
    active = [manager for manager in before.human_managers if manager.active]
    if len(active) != 1 or active[0].club is None:
        raise ProbeError("exactly one active manager with a club is required")
    after = probe(pid)
    after_active = [manager for manager in after.human_managers if manager.active]
    if (before.game_date != after.game_date or len(after_active) != 1
            or active[0].id != after_active[0].id
            or after_active[0].club is None
            or active[0].club.id != after_active[0].club.id
            or {item.id for item in before.first_team_squad}
            != {item.id for item in after.first_team_squad}):
        raise ProbeError("FM manager, date, or squad changed during the survey")
    players = before.first_team_squad
    if not players:
        raise ProbeError("active manager's first-team squad is empty")
    samples = choose_validation_players(players)
    return {
        "pid": pid,
        "gameDate": before.game_date,
        "managerId": active[0].id,
        "clubId": active[0].club.id,
        "clubName": active[0].club.name,
        "playerCount": len(players),
        "squadIdHash": hashlib.sha256(
            ",".join(sorted(item.id for item in players)).encode("ascii")
        ).hexdigest(),
        "positionCounts": {
            code: sum(code in item.positions for item in players)
            for code in sorted({position for item in players for position in item.positions})
        },
        "samplePlayers": [
            {"id": item.id, "name": item.name, "positions": list(item.positions)}
            for item in samples
        ],
        "limitations": [
            "Position codes are the existing >=15 threshold approximation, not UI proficiency labels.",
            "No footedness value, raw position rating, or hidden player field is read or reported.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("static", "run", "trace"))
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--field", action="append", choices=tuple(FIELD_SPECS))
    parser.add_argument("--pid", type=int)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--disassemble-top", type=int, default=0)
    parser.add_argument("--duration", type=float, default=120.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "static" and (args.pid is not None or args.require_live):
        print("--pid/--require-live require run or trace mode", file=sys.stderr)
        return 2
    if args.mode == "trace" and not 5 <= args.duration <= 300:
        print("--duration must be between 5 and 300 seconds", file=sys.stderr)
        return 2
    selected = [FIELD_SPECS[key] for key in dict.fromkeys(args.field or FIELD_SPECS)]
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "createdAt": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "buildProfile": FM20_4_4_STEAM.name,
        "productVersion": FM20_4_4_STEAM.expected_product_version,
        "status": "started",
        "productionFieldQueryProven": False,
        "hypothesis": (
            "Pinned FM UI class metadata can narrow passive getter tracing; "
            "a live owned-squad survey can select diverse verification players."
        ),
        "decisionRules": {
            "staticLead": "at least one mapped anchor and valid RTTI/vtable candidate",
            "liveSurvey": "same active manager, in-game date, and squad IDs before/after",
            "fieldQuery": "not attempted by this workbench version",
        },
    }
    try:
        report["executableSha256"] = verified_executable_digest(args.executable)
        with args.executable.open("rb") as file:
            with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
                report["static"] = scan_static(data, selected)
        if args.disassemble_top:
            report["disassembly"] = disassemble_leads(
                args.executable, report["static"], per_field=args.disassemble_top
            )
        if args.mode in {"run", "trace"}:
            try:
                pid = choose_pid(args.pid)
                report["live"] = survey_owned_squad(pid)
                report["liveStatus"] = "surveyed"
            except ProbeError as exc:
                report["liveStatus"] = "unavailable"
                report["liveError"] = str(exc)
                if args.require_live or args.mode == "trace":
                    raise
        if args.mode == "trace":
            if not sys.stdin.isatty():
                raise ValueError("guided trace requires an interactive terminal")
            targets = select_trace_targets(report["static"])
            report["traceTargets"] = targets
            finished = threading.Event()
            operator: dict[str, str] = {}

            def arm_prompt() -> None:
                print("ARMED: open each listed player's Positions/profile page in FM.", flush=True)
                for item in report["live"]["samplePlayers"]:
                    print(f"  {item['name']} (ID {item['id']}; {', '.join(item['positions'])})", flush=True)

                def accept_done() -> None:
                    try:
                        operator["reply"] = input("Type done when finished: ").strip()
                    except EOFError:
                        operator["reply"] = "eof"
                    finished.set()

                threading.Thread(target=accept_done, daemon=True).start()

            report["trace"] = trace_callers(
                pid,
                duration_seconds=args.duration,
                targets=targets,
                stop_requested=finished.is_set,
                settle_seconds=0.5,
                ready_callback=arm_prompt,
            )
            report["operatorReply"] = operator.get("reply", "timeout")
            report["afterTrace"] = survey_owned_squad(pid)
            report["sameManagerDateSquad"] = all(
                report["live"][key] == report["afterTrace"][key]
                for key in ("managerId", "clubId", "gameDate", "squadIdHash")
            )
            if not report["sameManagerDateSquad"]:
                raise ProbeError("manager, club, date, or squad IDs changed during trace")
            report["traceHitTargets"] = sorted(report["trace"])
            report["traceStatus"] = (
                "observed" if report["trace"] and report["operatorReply"] == "done"
                else "no-hits" if not report["trace"] else "operator-unconfirmed"
            )
            report["uiStateEvidence"] = "operator-declared; no screen pixels read"
        report["status"] = (
            "partial" if (
                args.mode == "run" and report.get("liveStatus") == "unavailable"
            ) or (
                args.mode == "trace" and report.get("traceStatus") != "observed"
            )
            else "complete"
        )
    except (OSError, ValueError, ProbeError, CaptureError) as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
    report["conclusion"] = (
        "Static leads and optional call counts only; no footedness or graded position field is resolved."
        if report["status"] in {"complete", "partial"}
        else "Workbench failed; do not infer a field mapping."
    )
    target = args.report or DEFAULT_REPORT_DIR / (
        f"field-workbench-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
        file.write("\n")
    counts = {
        key: sum(len(hits) for hits in value["anchors"].values())
        for key, value in report.get("static", {}).get("fields", {}).items()
    }
    print(f"RESULT {target} status={report['status']} live={report.get('liveStatus', 'not-requested')} anchors={counts}")
    return 0 if report["status"] in {"complete", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
