#!/usr/bin/env python3
"""Guided, single-round-trip probe of PERSON_INTERESTED_FILTER_RULE.

Earlier native-call testing of the full discoverability filter found that
this rule's real per-player computation -- only engaged once Player
Search actually has an "interested" criterion active, otherwise every
player short-circuits to a fixed answer -- faults for at least some
contract-less players (free agents, non-playing database entries). See
docs/phases/03-information-visibility/03.2-fm-representation-research.md
for the full trail. This tool exists to answer, in exactly one attended
round trip, whether excluding contract-less players from the batch lets
every remaining (contracted) player evaluate safely and produce a real
answer -- without needing anything read off FM's own screen and reported
back: every check here is either a memory read or a native call whose
result (or fault) is captured directly.

Usage: with FM running, open Player Search and set "Interested in
Transfer" on (leave everything else at Any), then run

    python3 -m tools.fm20_interested_filter_probe

and press Enter once when ready. Everything after that -- rebuilding the
source, partitioning by contract status, running the batch, and (if it
still faults) identifying exactly which player and why -- happens
automatically in one pass, with one JSON report at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_discoverability_cold_builder import cold_build
from tools.fm20_discoverability_cold_filter import (
    FILTER_EVALUATOR_RVA,
    FILTER_RETURN_TRAP_RVA,
    _source_records,
    native_filter_batch,
    resolve_full_filter,
    resolve_knowledge_context,
)
from tools.fm20_discoverability_cold_query import (
    own_contracted_ids,
    resolve_player_names,
    select_expected_exclusions,
)
from tools.fm20_discoverability_experiment import _write_report
from tools.fm20_discoverability_manager_builder import _live_context
from tools.fm20_guarded_native_call import verify_process_alive
from tools.fm20_linux_probe import ProbeError, read_exact, read_player_contract
from tools.fm20_linux_probe_runtime import choose_pid

_FAULT_PLAYER_RE = re.compile(r"for player (-?\d+)")


def partition_by_contract(
    memory_fd: int, records: dict[int, int]
) -> tuple[dict[int, int], dict[int, int]]:
    """Split source records into (contracted, contract-less) -- read-only.

    A contract-less record (free agent, retired/legendary DB entry, staff
    without a playing contract) is exactly the shape that crashed the
    rule's real per-player evaluator; this lets the caller exclude them
    from a native-call batch before ever resuming FM, rather than finding
    out mid-batch.
    """
    contracted: dict[int, int] = {}
    contractless: dict[int, int] = {}
    for player_id, person in records.items():
        actual_person = person + 0x28
        try:
            has_contract = read_player_contract(memory_fd, actual_person) is not None
        except (OSError, ProbeError):
            has_contract = False
        (contracted if has_contract else contractless)[player_id] = person
    return contracted, contractless


def _identify_fault(pid: int, memory_fd: int, error_message: str) -> dict[str, Any] | None:
    """Best-effort identity/contract lookup for whichever player a fault named."""
    match = _FAULT_PLAYER_RE.search(error_message)
    if not match:
        return None
    player_id = int(match.group(1))
    names = resolve_player_names(pid, [player_id])
    return {"playerId": player_id, "name": names.get(player_id)}


def run(pid: int) -> dict[str, Any]:
    state, arguments, _before_ids = _live_context(pid)
    source, manager_interface, team = arguments
    module_base = int(state.module_base, 0)
    active = [manager for manager in state.human_managers if manager.active]
    if len(active) != 1 or active[0].club is None:
        raise ProbeError("expected exactly one active human manager with a club")
    manager = active[0]
    squad = [
        (
            int(player.id),
            player.contract.contracted_club.id
            if player.contract and player.contract.contracted_club else None,
        )
        for player in state.first_team_squad
    ]
    own_ids = own_contracted_ids(squad, manager.club.id)

    report: dict[str, Any] = {
        "schemaVersion": 1,
        "script": "fm20_interested_filter_probe.py",
        "researchOnly": True,
        "pid": pid,
        "gameDate": state.game_date,
        "managedClub": {"id": manager.club.id, "name": manager.club.name},
    }

    report["builderReturnValue"] = cold_build(pid, module_base, arguments)
    _, rebuilt_arguments, source_ids = _live_context(pid)
    if rebuilt_arguments != arguments:
        raise ProbeError("native search arguments changed after the source rebuild")

    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        reader = lambda address, size: read_exact(fd, address, size)
        filter_object = resolve_full_filter(reader, module_base, source)
        records = _source_records(reader, source)
        knowledge_context = resolve_knowledge_context(reader, module_base, manager.id)
        contracted, contractless = partition_by_contract(fd, records)
    finally:
        os.close(fd)

    if sorted(records) != sorted(source_ids):
        raise ProbeError("source records differ from the manager-rooted source IDs")

    report.update({
        "sourceCount": len(records),
        "contractedCount": len(contracted),
        "contractlessCount": len(contractless),
        "contractlessSample": sorted(contractless)[:10],
    })

    expected_exclusions = select_expected_exclusions(set(contracted), own_ids)
    try:
        evaluations, complete = native_filter_batch(
            pid, module_base, filter_object, FILTER_EVALUATOR_RVA,
            FILTER_RETURN_TRAP_RVA, manager_interface, team, contracted,
            expected_exclusions, knowledge_context,
        )
    except ProbeError as exc:
        report["batchSucceeded"] = False
        report["error"] = str(exc)
        report["fmSurvived"] = verify_process_alive(pid)
        if report["fmSurvived"]:
            fault_fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
            try:
                report["faultedPlayer"] = _identify_fault(pid, fault_fd, str(exc))
            finally:
                os.close(fault_fd)
        return report

    interested = {player_id for player_id, included in evaluations.items() if included}
    after_state = _live_context(pid)[0]
    after_active = [manager for manager in after_state.human_managers if manager.active]
    report.update({
        "batchSucceeded": True,
        "complete": complete,
        "evaluatedCount": len(evaluations),
        "interestedCount": len(interested),
        "interestedPlayerIds": sorted(interested),
        "sameActiveManager": len(after_active) == 1 and after_active[0].id == manager.id,
        "sameGameDate": after_state.game_date == state.game_date,
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--no-wait", action="store_true",
        help="skip the confirmation prompt (assumes Player Search is already set up)",
    )
    args = parser.parse_args(argv)
    pid = choose_pid(args.pid)

    if not args.no_wait:
        print(
            "In FM: open Player Search, set 'Interested in Transfer' on "
            "(everything else at Any), then come back here.\n"
            "Press Enter when ready -- everything after that is automatic.",
            file=sys.stderr,
        )
        try:
            input()
        except EOFError:
            pass

    try:
        report = run(pid)
    except (OSError, ProbeError, TimeoutError, ValueError) as exc:
        report = {
            "researchOnly": True, "pid": pid, "batchSucceeded": False,
            "error": str(exc), "fmSurvived": verify_process_alive(pid),
        }

    path = _write_report(report, args.output, "interested-filter-probe")
    report["report"] = str(path)
    print("RESULT", json.dumps(report, sort_keys=True))
    return 0 if report.get("batchSucceeded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
