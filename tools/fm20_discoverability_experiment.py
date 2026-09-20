#!/usr/bin/env python3
"""Guide a complete FM20 package A/B discoverability experiment.

``study`` walks through both package states in one terminal session, captures
the search result IDs and upstream source IDs together, and writes one
machine-readable report. It passively observes FM; HTML is never an input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_linux_probe import ProbeError, read_exact
from tools.fm20_linux_probe_runtime import choose_pid, probe
from tools.fm20_search_caller_trace import trace_callers
from tools.fm20_visibility_capture import CaptureError

STATE_PACKAGES = {
    "no-package": "No Package",
    "senior-vanarama": "Senior Players — Vanarama North/South",
}
SCHEMA_VERSION = 1
DEFAULT_REPORT_DIR = Path("data/research/discoverability")
PERSON_TYPE_RVAS = (0x6D92778, 0x6DA94A0)
MAX_SOURCE_PLAYERS = 200_000


def parse_done_line(line: str) -> int | None:
    match = re.fullmatch(r"\s*done\s+(\d+)\s*", line, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _active_manager_id(probe_result: Any) -> str | None:
    active = [manager.id for manager in probe_result.human_managers if manager.active]
    return active[0] if len(active) == 1 else None


def build_capture_report(
    *,
    state: str,
    kind: str,
    ui_count: int,
    trace: dict[str, object],
    before: Any,
    after: Any,
) -> dict[str, Any]:
    if state not in STATE_PACKAGES:
        raise ValueError(f"unsupported package state: {state}")
    if kind not in {"candidates", "source"}:
        raise ValueError(f"unsupported capture kind: {kind}")
    checks = {
        "sameGameDate": before.game_date == after.game_date,
        "sameActiveManager": (
            _active_manager_id(before) is not None
            and _active_manager_id(before) == _active_manager_id(after)
        ),
        "sameProcess": before.pid == after.pid,
        "sameBuild": before.expected_product_version == after.expected_product_version,
    }
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "captureKind": kind,
        "stateLabel": state,
        "packageLabel": STATE_PACKAGES[state],
        "packageEvidence": "operator-declared; native package state not yet resolved",
        "uiAction": "Player Search: Transfer Listed, then all Any",
        "uiReportedCount": ui_count,
        "pid": before.pid,
        "buildProfile": before.profile,
        "productVersion": before.expected_product_version,
        "gameDateBefore": before.game_date,
        "gameDateAfter": after.game_date,
        "activeManagerId": _active_manager_id(before),
        "checks": checks,
    }
    if kind == "candidates":
        raw_pairs = trace.get("_candidate_pointer_ids", [])
        pairs = [[int(pointer), int(player_id) if player_id is not None else None]
                 for pointer, player_id in raw_pairs]
        ids = [player_id for _, player_id in pairs if player_id is not None]
        report.update({
            "candidatePointerCount": len(pairs),
            "resolvedPlayerIdCount": len(ids),
            "candidatePointerIds": pairs,
            "playerIds": sorted(ids),
            "identityOffsets": trace.get("_candidate_identity_offsets", []),
        })
        checks.update({
            "allIdentitiesResolved": len(ids) == len(pairs),
            "uniquePlayerIds": len(set(ids)) == len(ids),
            "matchesUiCount": len(pairs) == ui_count and len(ids) == ui_count,
        })
    else:
        events = trace.get("_search_source_events", [])
        report["sourceEvents"] = events
        report["sourceVectorCounts"] = [event["vector_count"] for event in events]
        checks["sourceObserved"] = bool(events)
    report["passed"] = all(checks.values())
    return report


def compare_candidate_reports(base: dict[str, Any], expanded: dict[str, Any]) -> dict[str, Any]:
    if base.get("captureKind") != "candidates" or expanded.get("captureKind") != "candidates":
        raise ValueError("both reports must be candidate captures")
    if base.get("schemaVersion") != SCHEMA_VERSION or expanded.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported report schema")
    base_ids = set(base["playerIds"])
    expanded_ids = set(expanded["playerIds"])
    checks = {
        "bothCapturesPassed": bool(base.get("passed") and expanded.get("passed")),
        "sameGameDate": base["gameDateAfter"] == expanded["gameDateAfter"],
        "sameActiveManager": (
            base["activeManagerId"] is not None
            and base["activeManagerId"] == expanded["activeManagerId"]
        ),
        "sameBuild": base["productVersion"] == expanded["productVersion"],
        "baseIsSubset": base_ids <= expanded_ids,
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "baseState": base["stateLabel"],
        "expandedState": expanded["stateLabel"],
        "baseCount": len(base_ids),
        "expandedCount": len(expanded_ids),
        "sharedCount": len(base_ids & expanded_ids),
        "addedPlayerIds": sorted(expanded_ids - base_ids),
        "removedPlayerIds": sorted(base_ids - expanded_ids),
        "checks": checks,
        "passed": all(checks.values()),
    }


# FM's "no ID" sentinel. A genuine player record (valid player type, valid
# RowID) can carry it; every read of the Player Search source skips such a
# player the same way, so the two readers' ID sets still agree exactly.
NO_PLAYER_ID = -1


def resolve_source_vector_ids(
    read_bytes: Callable[[int, int], bytes],
    module_base: int,
    events: Sequence[dict[str, int]],
) -> list[int]:
    """Resolve FM's search-input vector, refusing ambiguous/stale snapshots."""
    if not events:
        raise ProbeError("search source vector was not observed")
    snapshots = {
        (event["source_pointer"], event["vector_begin"], event["vector_end"])
        for event in events
    }
    if len(snapshots) != 1:
        raise ProbeError("search source vector changed during capture")
    source, begin, end = snapshots.pop()
    if source <= 0 or begin <= 0 or end < begin or (end - begin) % 8:
        raise ProbeError("invalid search source vector bounds")
    count = (end - begin) // 8
    if count > MAX_SOURCE_PLAYERS or any(event["vector_count"] != count for event in events):
        raise ProbeError("search source vector count is inconsistent or excessive")
    current_begin, current_end = struct.unpack("<QQ", read_bytes(source + 0xD0, 16))
    if (current_begin, current_end) != (begin, end):
        raise ProbeError("search source vector moved after capture; repeat this phase")
    wrapper_bytes = read_bytes(begin, count * 8)
    wrappers = struct.unpack(f"<{count}Q", wrapper_bytes)
    valid_types = {module_base + rva for rva in PERSON_TYPE_RVAS}
    ids: list[int] = []
    for index, wrapper in enumerate(wrappers):
        if wrapper == 0:
            raise ProbeError(f"null wrapper at search source index {index}")
        person = struct.unpack("<Q", read_bytes(wrapper, 8))[0]
        if person == 0:
            raise ProbeError(f"null person at search source index {index}")
        type_pointer, row_id, player_id = struct.unpack("<Qii", read_bytes(person, 16))
        if type_pointer in valid_types and row_id >= 0 and player_id == NO_PLAYER_ID:
            # A real player FM has given no ID (seen: Bradley Bubb, 2019-09).
            # He cannot be keyed or tracked, so he is left out rather than
            # failing the whole search source -- see NO_PLAYER_ID.
            continue
        if type_pointer not in valid_types or row_id < 0 or player_id < 0:
            raise ProbeError(f"unresolved player at search source index {index}")
        ids.append(player_id)
    if len(ids) != len(set(ids)):
        raise ProbeError("duplicate player ID in search source vector")
    return sorted(ids)


def _read_source_vector_ids(
    pid: int, module_base: int, events: Sequence[dict[str, int]]
) -> list[int]:
    try:
        memory_fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ProbeError(f"cannot open FM process memory read-only: {exc}") from exc
    try:
        return resolve_source_vector_ids(
            lambda address, size: read_exact(memory_fd, address, size),
            module_base,
            events,
        )
    finally:
        os.close(memory_fd)


def build_study_report(
    base: dict[str, Any], expanded: dict[str, Any]
) -> dict[str, Any]:
    """Compare two combined captures, retaining exact membership evidence."""
    if base["stateLabel"] != "no-package" or expanded["stateLabel"] != "senior-vanarama":
        raise ValueError("study requires No Package followed by Senior Vanarama")
    comparison = compare_candidate_reports(
        base["candidateCapture"], expanded["candidateCapture"]
    )
    base_source = set(base["sourcePlayerIds"])
    expanded_source = set(expanded["sourcePlayerIds"])
    checks = {
        "bothPhasesPassed": bool(base["passed"] and expanded["passed"]),
        "candidateComparisonPassed": bool(comparison["passed"]),
        "sourceBaseIsSubset": base_source <= expanded_source,
        "sameGameDate": base["gameDate"] == expanded["gameDate"],
        "sameManager": base["activeManagerId"] == expanded["activeManagerId"]
        and base["activeManagerId"] is not None,
        "sameBuild": base["productVersion"] == expanded["productVersion"],
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "researchOnly": True,
        "purpose": "FM-native discoverability A/B; not an application data source",
        "phases": [base, expanded],
        "candidateComparison": comparison,
        "sourceComparison": {
            "baseCount": len(base_source),
            "expandedCount": len(expanded_source),
            "addedPlayerIds": sorted(expanded_source - base_source),
            "removedPlayerIds": sorted(base_source - expanded_source),
            "sourceOnlyBasePlayerIds": base["sourceOnlyPlayerIds"],
            "sourceOnlyExpandedPlayerIds": expanded["sourceOnlyPlayerIds"],
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
def _write_report(report: dict[str, Any], output: Path | None, stem: str) -> Path:
    if output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = DEFAULT_REPORT_DIR / f"{stem}-{timestamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, sort_keys=True)
        target.write("\n")
    return output.resolve()


def _capture(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty():
        print("error: live capture requires an interactive terminal", file=sys.stderr)
        return 2
    pid = choose_pid(args.pid)
    before = probe(pid)
    ui_count: int | None = None
    stdin_closed = False

    def operator_done() -> bool:
        nonlocal ui_count, stdin_closed
        if stdin_closed or not select.select([sys.stdin], [], [], 0)[0]:
            return False
        line = sys.stdin.readline()
        if not line:
            stdin_closed = True
            return False
        parsed = parse_done_line(line)
        if parsed is None:
            print("INPUT_ERROR: enter 'done <players-found-count>'", flush=True)
            return False
        ui_count = parsed
        return True

    print(
        f"PREPARE {args.state}: select {STATE_PACKAGES[args.state]}; "
        "set every Player Search criterion to Any.",
        flush=True,
    )
    trace = trace_callers(
        pid,
        duration_seconds=args.timeout,
        candidate_only=args.kind == "candidates",
        source_only=args.kind == "source",
        stop_requested=operator_done,
        ready_callback=lambda: print(
            f"ARMED {args.state}: set Transfer Listed, wait for results, "
            "then return to all Any; enter 'done <count>' when finished.",
            flush=True,
        ),
    )
    if ui_count is None:
        print("error: capture timed out without 'done <count>'", file=sys.stderr)
        return 2
    after = probe(pid)
    report = build_capture_report(
        state=args.state, kind=args.kind, ui_count=ui_count,
        trace=trace, before=before, after=after,
    )
    path = _write_report(report, args.output, f"{args.state}-{args.kind}")
    summary = {
        "report": str(path),
        "passed": report["passed"],
        "uiCount": ui_count,
        "capturedCount": (
            report.get("candidatePointerCount") if args.kind == "candidates"
            else report.get("sourceVectorCounts")
        ),
        "checks": report["checks"],
    }
    print("RESULT " + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if report["passed"] else 2


def _study_phase(pid: int, state: str, timeout: float, index: int) -> dict[str, Any]:
    print(
        f"\nSTEP {index}/2 — {STATE_PACKAGES[state]}\n"
        "In FM, select this package and leave Player Search with every criterion at Any.\n"
        "Do not refresh the search until the terminal says ARMED.",
        flush=True,
    )
    input("Press Enter when FM is ready: ")
    before = probe(pid)
    ui_count: int | None = None
    stdin_closed = False

    def operator_done() -> bool:
        nonlocal ui_count, stdin_closed
        if stdin_closed or not select.select([sys.stdin], [], [], 0)[0]:
            return False
        line = sys.stdin.readline()
        if not line:
            stdin_closed = True
            return False
        parsed = parse_done_line(line)
        if parsed is None:
            print("INPUT_ERROR: type 'done <players-found-count>'", flush=True)
            return False
        ui_count = parsed
        return True

    trace = trace_callers(
        pid,
        duration_seconds=timeout,
        combined_only=True,
        stop_requested=operator_done,
        ready_callback=lambda: print(
            "ARMED: set Transfer Listed, wait for results; then set every criterion "
            "back to Any, wait for the final count, and type 'done <count>' here.",
            flush=True,
        ),
    )
    if ui_count is None:
        raise CaptureError(f"{state} timed out without 'done <count>'")
    after = probe(pid)
    candidate = build_capture_report(
        state=state, kind="candidates", ui_count=ui_count,
        trace=trace, before=before, after=after,
    )
    source = build_capture_report(
        state=state, kind="source", ui_count=ui_count,
        trace=trace, before=before, after=after,
    )
    source_error: str | None = None
    try:
        source_ids = _read_source_vector_ids(
            pid, int(before.module_base, 0), source["sourceEvents"]
        )
    except (ProbeError, OSError, KeyError, ValueError) as exc:
        source_ids = []
        source_error = str(exc)
    candidate_ids = set(candidate["playerIds"])
    source_set = set(source_ids)
    first_team_ids = {int(player.id) for player in before.first_team_squad}
    checks = {
        "candidateCapturePassed": bool(candidate["passed"]),
        "sourceCapturePassed": bool(source["passed"]),
        "sourceResolved": source_error is None,
        "sourceCountMatchesVector": bool(
            source["sourceVectorCounts"]
            and len(source_ids) == source["sourceVectorCounts"][0]
        ),
        "visibleCandidatesInSource": candidate_ids <= source_set,
    }
    phase = {
        "stateLabel": state,
        "packageLabel": STATE_PACKAGES[state],
        "packageEvidence": "operator-declared; native package field not yet resolved",
        "uiReportedCount": ui_count,
        "gameDate": after.game_date,
        "activeManagerId": _active_manager_id(after),
        "productVersion": after.expected_product_version,
        "candidateCapture": candidate,
        "sourceCapture": source,
        "sourcePlayerIds": source_ids,
        "sourceOnlyPlayerIds": sorted(source_set - candidate_ids),
        "firstTeamPlayerIds": sorted(first_team_ids),
        "firstTeamInSourcePlayerIds": sorted(first_team_ids & source_set),
        "firstTeamInCandidatesPlayerIds": sorted(first_team_ids & candidate_ids),
        "firstTeamSourceOnlyPlayerIds": sorted(first_team_ids & (source_set - candidate_ids)),
        "sourceResolutionError": source_error,
        "checks": checks,
        "passed": all(checks.values()),
    }
    print(
        "PHASE_RESULT " + json.dumps({
            "state": state,
            "passed": phase["passed"],
            "uiCount": ui_count,
            "candidateCount": len(candidate_ids),
            "sourceCount": len(source_ids),
            "sourceOnlyCount": len(phase["sourceOnlyPlayerIds"]),
            "firstTeamSourceOnlyCount": len(phase["firstTeamSourceOnlyPlayerIds"]),
            "checks": checks,
        }, sort_keys=True),
        flush=True,
    )
    return phase


def _study(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty():
        print("error: study requires an interactive terminal", file=sys.stderr)
        return 2
    pid = choose_pid(args.pid)
    print(
        "FM20 DISCOVERABILITY STUDY — one guided run, two package states.\n"
        f"Attached process will be {pid}. No HTML/export is needed.\n"
        "The script reads FM only; it does not change the package or search filters.",
        flush=True,
    )
    completed: list[dict[str, Any]] = []
    try:
        base = _study_phase(pid, "no-package", args.timeout, 1)
    except (CaptureError, ProbeError, ValueError, OSError, KeyError) as exc:
        report = {"schemaVersion": SCHEMA_VERSION, "researchOnly": True,
                  "phases": completed, "passed": False, "error": str(exc)}
        path = _write_report(report, args.output, "package-study-incomplete")
        print("RESULT " + json.dumps({"report": str(path), "passed": False,
                                      "error": str(exc)}, sort_keys=True), flush=True)
        return 2
    completed.append(base)
    if not base["passed"]:
        report = {"schemaVersion": SCHEMA_VERSION, "researchOnly": True,
                  "phases": [base], "passed": False,
                  "error": "No Package phase failed validation; Senior phase was not run"}
        path = _write_report(report, args.output, "package-study-incomplete")
        print(f"RESULT {{\"passed\": false, \"report\": \"{path}\"}}", flush=True)
        return 2
    try:
        expanded = _study_phase(pid, "senior-vanarama", args.timeout, 2)
    except (CaptureError, ProbeError, ValueError, OSError, KeyError) as exc:
        report = {"schemaVersion": SCHEMA_VERSION, "researchOnly": True,
                  "phases": completed, "passed": False, "error": str(exc)}
        path = _write_report(report, args.output, "package-study-incomplete")
        print("RESULT " + json.dumps({"report": str(path), "passed": False,
                                      "error": str(exc)}, sort_keys=True), flush=True)
        return 2
    report = build_study_report(base, expanded)
    path = _write_report(report, args.output, "package-study")
    print("\nRESULT " + json.dumps({
        "report": str(path),
        "passed": report["passed"],
        "noPackageCount": report["candidateComparison"]["baseCount"],
        "seniorCount": report["candidateComparison"]["expandedCount"],
        "candidateAddedCount": len(report["candidateComparison"]["addedPlayerIds"]),
        "sourceAddedCount": len(report["sourceComparison"]["addedPlayerIds"]),
        "sourceOnlyNoPackageCount": len(base["sourceOnlyPlayerIds"]),
        "sourceOnlySeniorCount": len(expanded["sourceOnlyPlayerIds"]),
        "checks": report["checks"],
    }, sort_keys=True), flush=True)
    return 0 if report["passed"] else 2


def _compare(args: argparse.Namespace) -> int:
    with args.base.open(encoding="utf-8") as source:
        base = json.load(source)
    with args.expanded.open(encoding="utf-8") as source:
        expanded = json.load(source)
    report = compare_candidate_reports(base, expanded)
    path = _write_report(report, args.output, "package-comparison")
    print("RESULT " + json.dumps({
        "report": str(path), "passed": report["passed"],
        "baseCount": report["baseCount"],
        "expandedCount": report["expandedCount"],
        "addedCount": len(report["addedPlayerIds"]),
        "removedCount": len(report["removedPlayerIds"]),
        "checks": report["checks"],
    }, sort_keys=True))
    return 0 if report["passed"] else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    study = commands.add_parser("study", help="run the complete guided two-package experiment")
    study.add_argument("--pid", type=int, help="FM20 host PID; auto-detected by default")
    study.add_argument("--timeout", type=float, default=180.0,
                       help="seconds allowed for each armed search refresh")
    study.add_argument("--output", type=Path, help="report path; must not already exist")
    capture = commands.add_parser("capture", help="capture one stable package state")
    capture.add_argument("--state", choices=STATE_PACKAGES, required=True)
    capture.add_argument("--kind", choices=("candidates", "source"), required=True)
    capture.add_argument("--pid", type=int)
    capture.add_argument("--timeout", type=float, default=180.0)
    capture.add_argument("--output", type=Path)
    compare = commands.add_parser("compare", help="compare two candidate reports")
    compare.add_argument("base", type=Path)
    compare.add_argument("expanded", type=Path)
    compare.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "study":
            return _study(args)
        return _capture(args) if args.command == "capture" else _compare(args)
    except (CaptureError, ProbeError, ValueError, OSError, KeyError,
            json.JSONDecodeError, EOFError, KeyboardInterrupt) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
