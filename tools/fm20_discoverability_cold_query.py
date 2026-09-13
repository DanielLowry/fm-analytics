#!/usr/bin/env python3
"""Research-only cold discoverability query for the active FM20 manager.

Resolves the manager-owned Player Search source from live manager state (no
saved pointers or reports), asks FM's own source builder to refresh it, then
runs FM's own active search-filter list over every source player. The result
is the player-ID set FM's Player Search lists with all criteria at Any, for
whichever scouting package is currently selected.

Not an application source yet: package state is not decoded natively, loan
edge cases are unverified, and results should still be checked against FM's
UI count afterwards. Never reads attribute values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fm20_discoverability_cold_builder import cold_build
from tools.fm20_discoverability_cold_filter import (
    FILTER_EVALUATOR_RVA,
    FILTER_RETURN_TRAP_RVA,
    _source_records,
    native_filter_batch,
    resolve_full_filter,
)
from tools.fm20_discoverability_experiment import _write_report
from tools.fm20_discoverability_manager_builder import _live_context
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    parse_module_mapping,
    read_exact,
    read_fm_string,
    read_pointer_collection,
    read_u64,
)
from tools.fm20_linux_probe_runtime import choose_pid

SAMPLE_SIZE = 3
SCHEMA_VERSION = 1


def own_contracted_ids(
    squad: Iterable[tuple[int, str | None]], club_id: str
) -> set[int]:
    """First-team players contracted to the managed club (loaned-in players excluded)."""
    return {player_id for player_id, contracted in squad if contracted == club_id}


def select_expected_exclusions(source_ids: set[int], own_ids: set[int]) -> set[int]:
    """Own-contracted players present in the source; FM must exclude each of them."""
    expected = own_ids & source_ids
    if len(expected) < SAMPLE_SIZE:
        raise ProbeError("fewer than three own-contracted first-team players in the source")
    if len(source_ids - own_ids) < SAMPLE_SIZE:
        raise ProbeError("fewer than three non-own players in the source")
    return expected


def summarize(
    source_ids: Sequence[int],
    evaluations: dict[int, bool],
    complete: bool,
    own_ids: set[int],
) -> dict[str, Any]:
    source = set(source_ids)
    excluded = {player_id for player_id, included in evaluations.items() if not included}
    own_in_source = own_ids & source
    final = sorted(source - excluded) if complete else None
    return {
        "complete": complete,
        "sourceCount": len(source),
        "evaluatedCount": len(evaluations),
        "excludedCount": len(excluded),
        "excludedPlayerIds": sorted(excluded),
        "ownFirstTeamInSource": sorted(own_in_source),
        "allOwnFirstTeamExcluded": own_in_source <= excluded,
        "excludedNotOwnFirstTeam": sorted(excluded - own_ids),
        "discoverableCount": len(final) if final is not None else None,
        "discoverablePlayerIds": final,
    }


def resolve_player_names(
    pid: int, player_ids: Iterable[int], *, proc_root: Path = Path("/proc")
) -> dict[int, str]:
    """Read-only name lookup for a set of already-known player IDs.

    Identity fields only (type tag, ID, first/last name) -- never an
    attribute value. This does not establish discoverability; it only
    labels IDs a discoverability query already returned.
    """

    wanted = set(player_ids)
    if not wanted:
        return {}
    process = proc_root / str(pid)
    with (process / "maps").open(encoding="utf-8") as mappings:
        module_base, _ = parse_module_mapping(mappings)
    fd = os.open(process / "mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        people = read_pointer_collection(
            fd, module_base,
            FM20_4_4_STEAM.main_address_offset,
            FM20_4_4_STEAM.person_collection_offset,
            FM20_4_4_STEAM.collection_indirection_offset,
        )
        expected_type = module_base + FM20_4_4_STEAM.player_type_offset
        names: dict[int, str] = {}
        for address in people:
            if not address or len(names) == len(wanted):
                continue
            try:
                if read_u64(fd, address) != expected_type:
                    continue
                player_id = int.from_bytes(read_exact(fd, address + 0xC, 4), "little", signed=True)
                if player_id not in wanted:
                    continue
                actual_person = address + 0x28
                first = read_fm_string(fd, actual_person + 0x30)
                last = read_fm_string(fd, actual_person + 0x38)
                names[player_id] = f"{first} {last}".strip()
            except (OSError, ProbeError):
                continue
    finally:
        os.close(fd)
    return names


def _active(state: Any) -> Any:
    active = [manager for manager in state.human_managers if manager.active]
    if len(active) != 1 or active[0].club is None:
        raise ProbeError("expected one active human manager with a club")
    return active[0]


def run(
    pid: int,
    invoke: bool,
    rebuild: bool,
    expected_count: int | None,
    *,
    with_names: bool = False,
) -> dict[str, Any]:
    before, arguments, before_ids = _live_context(pid)
    source, manager_interface, team = arguments
    module_base = int(before.module_base, 0)
    manager = _active(before)
    squad = [
        (int(player.id),
         player.contract.contracted_club.id
         if player.contract and player.contract.contracted_club else None)
        for player in before.first_team_squad
    ]
    own_ids = own_contracted_ids(squad, manager.club.id)
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "script": "fm20_discoverability_cold_query.py",
        "researchOnly": True,
        "pid": pid,
        "buildProfile": before.profile,
        "gameDate": before.game_date,
        "activeManagerId": manager.id,
        "managedClub": {"id": manager.club.id, "name": manager.club.name},
        "packageEvidence": "not natively decoded",
        "managerRooted": True,
        "sourcePointer": source,
        "managerSearchInterface": manager_interface,
        "managedTeamPointer": team,
        "sourceCountBeforeRebuild": len(before_ids),
        "ownContractedFirstTeamCount": len(own_ids),
        "invoked": invoke,
        "rebuild": rebuild,
        "expectedCount": expected_count,
        "passed": False,
    }
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        reader = lambda address, size: read_exact(fd, address, size)
        report["filterObject"] = resolve_full_filter(reader, module_base, source)
    finally:
        os.close(fd)
    if not invoke:
        report["passed"] = True
        return report

    if rebuild:
        report["builderReturnValue"] = cold_build(pid, module_base, arguments)
    _, rebuilt_arguments, source_ids = _live_context(pid)
    if rebuilt_arguments != arguments:
        raise ProbeError("native search arguments changed after the source rebuild")
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        reader = lambda address, size: read_exact(fd, address, size)
        filter_object = resolve_full_filter(reader, module_base, source)
        records = _source_records(reader, source)
    finally:
        os.close(fd)
    if sorted(records) != sorted(source_ids):
        raise ProbeError("source records differ from the manager-rooted source IDs")
    expected_exclusions = select_expected_exclusions(set(records), own_ids)
    evaluations, complete = native_filter_batch(
        pid, module_base, filter_object, FILTER_EVALUATOR_RVA,
        FILTER_RETURN_TRAP_RVA, manager_interface, team, records,
        expected_exclusions,
    )
    after = _live_context(pid)[0]
    report.update(summarize(list(records), evaluations, complete, own_ids))
    report.update({
        "sameActiveManager": manager.id == _active(after).id,
        "sameGameDate": before.game_date == after.game_date,
        "matchesExpectedCount": (
            report["discoverableCount"] == expected_count
            if expected_count is not None else None
        ),
    })
    report["passed"] = bool(
        complete
        and report["sameActiveManager"]
        and report["sameGameDate"]
        and report["allOwnFirstTeamExcluded"]
        and report["matchesExpectedCount"] is not False
    )
    if with_names and report["discoverablePlayerIds"] is not None:
        names = resolve_player_names(pid, report["discoverablePlayerIds"])
        report["discoverablePlayers"] = [
            {"id": player_id, "name": names.get(player_id)}
            for player_id in report["discoverablePlayerIds"]
        ]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--invoke", action="store_true",
                        help="call FM's builder and filter; default is a read-only preflight")
    parser.add_argument("--no-rebuild", action="store_true",
                        help="filter the existing source without calling FM's builder first")
    parser.add_argument("--expected-count", type=int,
                        help="FM Player Search 'players found' count to verify against")
    parser.add_argument("--with-names", action="store_true",
                        help="resolve player names for the discoverable ID list")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run(choose_pid(args.pid), args.invoke, not args.no_rebuild,
                     args.expected_count, with_names=args.with_names)
    except (OSError, ProbeError, TimeoutError, ValueError) as exc:
        report = {"researchOnly": True, "invoked": args.invoke,
                  "passed": False, "error": str(exc)}
    path = _write_report(report, args.output, "cold-discoverability-query")
    summary = {key: report.get(key) for key in (
        "passed", "error", "gameDate", "sourceCountBeforeRebuild", "sourceCount",
        "excludedCount", "discoverableCount", "allOwnFirstTeamExcluded",
        "excludedNotOwnFirstTeam", "matchesExpectedCount",
    ) if key in report}
    if args.with_names and "discoverablePlayers" in report:
        summary["discoverablePlayers"] = report["discoverablePlayers"]
    print("RESULT " + json.dumps({"report": str(path), **summary}, sort_keys=True), flush=True)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
