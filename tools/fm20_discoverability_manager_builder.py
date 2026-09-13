#!/usr/bin/env python3
"""Probe FM20's player-search source from the active manager, without saved pointers.

Research only: the source is upstream of the final discoverability filter and
must never be published as an application player list. ``--guided-ab`` tests
fresh-process construction and package-sensitive recomputation in one run;
Player Search is used only for a final operator-reported verification count.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_cold_visibility_call import EXPECTED_SHA256
from tools.fm20_discoverability_cold_builder import cold_build
from tools.fm20_discoverability_experiment import (
    _write_report,
    resolve_source_vector_ids,
)
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    read_exact,
    read_human_manager_contexts,
    read_pointer_collection,
)
from tools.fm20_linux_probe_runtime import choose_pid, probe

SEARCH_MANAGER_FROM_PERSON = 0x480
SEARCH_SOURCES_OFFSET = 0x190
SEARCH_MANAGER_VTABLE_RVA = 0x6D80CA0
TEAM_VTABLE_RVA = 0x6D8DBC0
PLAYER_SOURCE_KIND = 1
MAX_SEARCH_SOURCES = 100
SCHEMA_VERSION = 1


def resolve_manager_source(
    read_bytes: Callable[[int, int], bytes],
    module_base: int,
    person: int,
    team: int,
) -> tuple[int, int, int]:
    """Resolve native (player source, search-manager interface, managed team)."""
    u64 = lambda address: struct.unpack("<Q", read_bytes(address, 8))[0]
    manager_interface = person - SEARCH_MANAGER_FROM_PERSON
    if person <= SEARCH_MANAGER_FROM_PERSON or team <= 0:
        raise ProbeError("active manager person/team pointer is missing")
    if u64(person) != module_base + FM20_4_4_STEAM.human_manager_type_offset:
        raise ProbeError("active manager person has unexpected vtable")
    if u64(manager_interface) != module_base + SEARCH_MANAGER_VTABLE_RVA:
        raise ProbeError("active manager search interface has unexpected vtable")
    if u64(team) != module_base + TEAM_VTABLE_RVA:
        raise ProbeError("managed team has unexpected vtable")
    if u64(team + 0x80) != manager_interface:
        raise ProbeError("managed team does not point back to active manager")
    begin, end, capacity = struct.unpack(
        "<QQQ", read_bytes(manager_interface + SEARCH_SOURCES_OFFSET, 24)
    )
    if begin <= 0 or end < begin or capacity < end or (end - begin) % 8:
        raise ProbeError("active manager search-source array is absent or invalid")
    count = (end - begin) // 8
    if not 1 <= count <= MAX_SEARCH_SOURCES:
        raise ProbeError(f"unexpected manager search-source count: {count}")
    sources = struct.unpack(f"<{count}Q", read_bytes(begin, count * 8))
    matches = [source for source in sources if source and
               read_bytes(source + 0x24, 1) == bytes([PLAYER_SOURCE_KIND]) and
               u64(source) == manager_interface]
    if len(matches) != 1:
        raise ProbeError(f"expected one manager-owned player source, found {len(matches)}")
    return matches[0], manager_interface, team


def resolve_active_person(fd: int, module_base: int, manager_id: str) -> int:
    profile = FM20_4_4_STEAM
    people = read_pointer_collection(
        fd, module_base, profile.main_address_offset,
        profile.person_collection_offset, profile.collection_indirection_offset,
    )
    expected_vtable = module_base + profile.human_manager_type_offset
    matches = [person for person in people if person and
               struct.unpack("<Q", read_exact(fd, person, 8))[0] == expected_vtable and
               str(struct.unpack("<i", read_exact(fd, person + 0xC, 4))[0]) == manager_id]
    if len(matches) != 1:
        raise ProbeError(f"expected one active manager person, found {len(matches)}")
    return matches[0]


def read_source_ids(
    read_bytes: Callable[[int, int], bytes], module_base: int, source: int
) -> list[int]:
    begin, end = struct.unpack("<QQ", read_bytes(source + 0xD0, 16))
    if begin == end == 0:
        return []
    return resolve_source_vector_ids(read_bytes, module_base, [{
        "source_pointer": source,
        "vector_begin": begin,
        "vector_end": end,
        "vector_count": (end - begin) // 8 if end >= begin else -1,
    }])


def _live_context(pid: int) -> tuple[Any, tuple[int, int, int], list[int]]:
    state = probe(pid)
    active = [manager for manager in state.human_managers if manager.active]
    if len(active) != 1:
        raise ProbeError("expected exactly one active human manager")
    with Path(state.executable).open("rb") as image:
        if hashlib.file_digest(image, "sha256").hexdigest() != EXPECTED_SHA256:
            raise ProbeError("FM executable hash differs from the pinned build")
    module_base = int(state.module_base, 0)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        contexts = read_human_manager_contexts(fd, module_base)
        team = [context.team_address for context in contexts
                if context.manager.id == active[0].id and context.manager.active]
        if len(team) != 1 or not team[0]:
            raise ProbeError("active manager has no managed team pointer")
        person = resolve_active_person(fd, module_base, active[0].id)
        reader = lambda address, size: read_exact(fd, address, size)
        arguments = resolve_manager_source(reader, module_base, person, team[0])
        before_ids = read_source_ids(reader, module_base, arguments[0])
    finally:
        os.close(fd)
    return state, arguments, before_ids


def run_phase(
    pid: int, state_label: str, expected_ids: list[int] | None, invoke: bool,
) -> dict[str, Any]:
    before, arguments, before_ids = _live_context(pid)
    source, manager_interface, team = arguments
    phase: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "script": "fm20_discoverability_manager_builder.py",
        "stateLabel": state_label,
        "packageEvidence": "operator-declared; not natively decoded",
        "pid": pid,
        "buildProfile": before.profile,
        "productVersion": before.expected_product_version,
        "gameDate": before.game_date,
        "activeManagerId": next(manager.id for manager in before.human_managers
                                if manager.active),
        "managerRooted": True,
        "sourcePointer": source,
        "managerSearchInterface": manager_interface,
        "managedTeamPointer": team,
        "beforeCount": len(before_ids),
        "beforePlayerIds": before_ids,
        "expectedSourceCount": len(expected_ids) if expected_ids is not None else None,
        "beforeMatchesOracle": before_ids == expected_ids if expected_ids is not None else None,
        "invoked": invoke,
    }
    if not invoke:
        phase["passed"] = phase["beforeMatchesOracle"] is not False
        return phase
    phase["nativeReturnValue"] = cold_build(pid, int(before.module_base, 0), arguments)
    after, after_args, after_ids = _live_context(pid)
    phase.update({
        "afterCount": len(after_ids),
        "afterPlayerIds": after_ids,
        "addedPlayerIds": sorted(set(after_ids) - set(before_ids)),
        "removedPlayerIds": sorted(set(before_ids) - set(after_ids)),
        "afterMatchesOracle": after_ids == expected_ids if expected_ids is not None else None,
        "sameManager": phase["activeManagerId"] == next(
            manager.id for manager in after.human_managers if manager.active
        ),
        "sameGameDate": before.game_date == after.game_date,
        "sameNativeArguments": arguments == after_args,
    })
    phase["passed"] = all((phase["sameManager"], phase["sameGameDate"],
                           phase["sameNativeArguments"],
                           phase["afterMatchesOracle"] is not False))
    return phase


def _oracle_ids(path: Path) -> dict[str, list[int]]:
    with path.open(encoding="utf-8") as source:
        report = json.load(source)
    phases = report.get("phases", [])
    if any(not phase.get("sourceCapture", {}).get("passed") for phase in phases):
        raise ProbeError("saved package-study source capture did not pass")
    result = {phase["stateLabel"]: phase["sourcePlayerIds"] for phase in phases}
    if set(result) != {"no-package", "senior-vanarama"}:
        raise ProbeError("saved oracle lacks the two package source sets")
    if len(result["no-package"]) != 4340 or len(result["senior-vanarama"]) != 4953:
        raise ProbeError("saved oracle source counts differ from validated observations")
    if not set(result["no-package"]) <= set(result["senior-vanarama"]):
        raise ProbeError("saved source oracle is not package-monotonic")
    return result


def _prompt(message: str) -> None:
    print(message, flush=True)
    input("READY: ")


def _guided_ab(args: argparse.Namespace, pid: int, oracle: dict[str, list[int]]) -> dict[str, Any]:
    if not sys.stdin.isatty():
        raise ProbeError("--guided-ab requires an interactive terminal")
    if args.previous_report is None:
        raise ProbeError("--guided-ab requires --previous-report to prove a new FM process")
    with args.previous_report.open(encoding="utf-8") as source:
        previous = json.load(source)
    previous_pid = previous.get("pid")
    if not isinstance(previous_pid, int) or pid == previous_pid:
        raise ProbeError("FM PID must differ from the previous off-screen run")
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "script": "fm20_discoverability_manager_builder.py",
        "researchOnly": True,
        "hypothesis": "manager-rooted source exists without Player Search and changes with package",
        "previousPid": previous_pid,
        "pid": pid,
        "screenEvidence": "operator-declared, not independently captured",
        "phases": [],
        "passed": False,
    }
    sequence = [
        ("senior-vanarama", "Senior Players → Vanarama North/South"),
        ("no-package", "No Package"),
        ("senior-vanarama", "Senior Players → Vanarama North/South"),
    ]
    try:
        report["currentStage"] = "initial-manager-source-before-relevant-screens"
        _prompt(
            "INITIAL CHECK: After restarting and loading the save, leave FM "
            "on Inbox or another unrelated screen. Do NOT open Player Search "
            "or Scouting Packages yet. Press Enter to check whether the active "
            "manager already owns a player-search source."
        )
        try:
            initial_state, initial_args, initial_ids = _live_context(pid)
        except ProbeError as exc:
            if not ("search-source array" in str(exc) or
                    "manager-owned player source" in str(exc)):
                raise
            report["initialSource"] = {
                "available": False,
                "error": str(exc),
                "screenEvidence": "operator-declared unrelated screen before package UI",
            }
            print(f"INITIAL CHECK RESULT: source absent ({exc}); continuing "
                  "to test whether package UI initializes it", flush=True)
        else:
            report["initialSource"] = {
                "available": True,
                "gameDate": initial_state.game_date,
                "activeManagerId": next(manager.id for manager in initial_state.human_managers
                                        if manager.active),
                "sourcePointer": initial_args[0],
                "managerSearchInterface": initial_args[1],
                "managedTeamPointer": initial_args[2],
                "count": len(initial_ids),
                "playerIds": initial_ids,
                "screenEvidence": "operator-declared unrelated screen before package UI",
            }
            print(f"INITIAL CHECK RESULT: manager-owned player source exists "
                  f"with {len(initial_ids)} cached IDs", flush=True)
        for index, (state, package_name) in enumerate(sequence, 1):
            report["currentStage"] = f"package-step-{index}-{state}"
            _prompt(
                f"STEP {index}/3: Select {package_name} in Scouting Packages. "
                "Keep Player Search CLOSED and do not advance the in-game date. "
                "Press Enter when the package selection has finished."
            )
            phase = run_phase(pid, state, oracle[state], True)
            report["phases"].append(phase)
            print(f"STEP {index} RESULT: source {phase['beforeCount']} → "
                  f"{phase['afterCount']}; exact oracle match={phase['afterMatchesOracle']}",
                  flush=True)
            if not phase["passed"]:
                raise ProbeError(f"step {index} did not match the saved exact-ID oracle")
        report["currentStage"] = "final-ui-count-after-native-query"
        _prompt(
            "NATIVE TEST COMPLETE. You may NOW open Player Search, clear all "
            "criteria to Any, and wait for the count. Press Enter to record it."
        )
        raw_count = input("FM players found (number): ").strip()
        if not raw_count.isdigit():
            raise ProbeError("UI count must be a nonnegative integer")
        report["uiReportedCount"] = int(raw_count)
        report["uiEvidence"] = "operator-reported after native phases"
        report["passed"] = (report["uiReportedCount"] == 4933 and
                            report["initialSource"]["available"])
        if not report["passed"]:
            report["error"] = (
                "initial source was absent before package UI or final FM UI count "
                "differs from the Senior-package oracle"
            )
        else:
            report["currentStage"] = "complete"
    except (ProbeError, OSError, ValueError, EOFError) as exc:
        report["error"] = str(exc)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, required=True,
                        help="passing package-study report, used only as an exact-ID oracle")
    parser.add_argument("--previous-report", type=Path,
                        help="previous off-screen report; guided A/B requires a different PID")
    parser.add_argument("--state", choices=("no-package", "senior-vanarama"),
                        default="senior-vanarama")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--invoke", action="store_true",
                        help="single current-state native builder call; default is dry-run")
    parser.add_argument("--guided-ab", action="store_true",
                        help="fresh-process Senior → None → Senior test, then UI count")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        pid = choose_pid(args.pid)
        oracle = _oracle_ids(args.oracle)
        result = (_guided_ab(args, pid, oracle) if args.guided_ab else
                  run_phase(pid, args.state, oracle[args.state], args.invoke))
        if not args.guided_ab:
            result = {"schemaVersion": SCHEMA_VERSION,
                      "script": "fm20_discoverability_manager_builder.py",
                      "researchOnly": True, "pid": pid, "phase": result,
                      "passed": result.get("passed", True)}
        path = _write_report(result, args.output, "manager-rooted-source")
        summary = {"report": str(path), "passed": result["passed"], "pid": pid}
        if not args.guided_ab:
            summary.update({"beforeCount": result["phase"]["beforeCount"],
                            "afterCount": result["phase"].get("afterCount")})
        print("RESULT " + json.dumps(summary, sort_keys=True), flush=True)
        return 0 if result["passed"] else 2
    except (OSError, ProbeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        failure = {"researchOnly": True, "passed": False, "error": str(exc)}
        path = _write_report(failure, args.output, "manager-rooted-source-failed")
        print("RESULT " + json.dumps({"report": str(path), **failure},
                                      sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
