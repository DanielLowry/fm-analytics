#!/usr/bin/env python3
"""Capture FM's manager-rooted Player Search pool for the Scouting page.

This is the product-facing, bounded use of the proven Frida source builder.
It asks FM to rebuild the manager's own Player Search pool, removes players
contracted to the managed club, and writes ``--scouting-json`` input.  It does
not replay FM's temporary search-form filters and never reads an attribute,
position-familiarity byte, or other concealed player field.

The resulting candidates intentionally have empty ``positions`` and
``attributes`` until their corresponding manager-visible extractors have been
proved for external players.  The Scouting page renders these as "Scout first"
instead of manufacturing values.  A position filter excludes candidates whose
position has not yet been captured.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools.fm20_discoverability_cold_filter import _source_records
from tools.fm20_discoverability_cold_query import own_contracted_ids
from tools.fm20_discoverability_manager_builder import _live_context
from tools.fm20_frida_discoverability import (
    DiscoverabilityError,
    _active_manager,
    builder_agent_source,
    extract,
)
from tools.fm20_frida_server import FridaServerError, frida_server_session
from tools.fm20_frida_trace import FridaTraceError, preflight, process_alive
from tools.fm20_linux_probe import ProbeError, read_exact, read_fm_string
from tools.fm20_linux_probe_runtime import choose_pid


SCHEMA_VERSION = 1


class ScoutingFeedError(RuntimeError):
    """A scouting feed could not be captured without crossing a safety boundary."""


def feed_document(
    player_ids: Iterable[int],
    names: dict[int, str],
    *,
    game_date: str,
    managed_club: dict[str, str],
    source_count: int,
    excluded_own_ids: Iterable[int],
) -> dict[str, Any]:
    """Build the stable JSON contract consumed by ``fm-web --scouting-json``."""
    ids = tuple(sorted(set(player_ids)))
    missing_names = [player_id for player_id in ids if not names.get(player_id)]
    if missing_names:
        raise ScoutingFeedError(
            f"identity lookup failed for {len(missing_names)} discovered player(s)"
        )
    excluded = tuple(sorted(set(excluded_own_ids)))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "gameDate": game_date,
        "source": {
            "kind": "manager-rooted-player-search-pool",
            "transport": "windows-frida-server",
            "sourceCount": source_count,
            "excludedOwnContractedCount": len(excluded),
            "managedClub": managed_club,
            "fieldCoverage": {
                "identity": "manager-search-pool plus read-only identity lookup",
                "positions": "not yet externally visibility-verified",
                "attributes": "not yet externally visibility-verified",
                "footedness": "not yet externally visibility-verified",
            },
        },
        "players": [
            {
                "id": str(player_id),
                "name": names[player_id],
                "positions": [],
                "attributes": {},
            }
            for player_id in ids
        ],
    }


def resolve_source_player_names(pid: int, records: dict[int, int]) -> dict[int, str]:
    """Label verified source records directly, avoiding a second global scan.

    The Player Search pool itself already has a checked person pointer for
    every ID.  Some valid source members do not appear in the generic loaded
    person collection used by the older name resolver, so resolving from this
    record is both more complete and less work.  Only first/last-name strings
    are read here; this is identity metadata, never a player rating.
    """
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        names: dict[int, str] = {}
        for player_id, person in records.items():
            try:
                actual_person = person + 0x28
                name = f"{read_fm_string(fd, actual_person + 0x30)} {read_fm_string(fd, actual_person + 0x38)}".strip()
            except (OSError, ProbeError):
                continue
            if name:
                names[player_id] = name
        return names
    finally:
        os.close(fd)


def capture_pool(pid: int, *, remote_address: str) -> dict[str, Any]:
    """Use Frida only for FM's builder, then read the rebuilt manager pool."""
    before, arguments, _before_ids = _live_context(pid)
    manager = _active_manager(before)
    if manager.club is None:
        raise ScoutingFeedError("the active manager has no controlled club")
    expected_base = int(preflight(pid)["moduleBase"], 0)
    if expected_base != int(before.module_base, 0):
        raise ScoutingFeedError("probe and Frida preflight module bases differ")
    try:
        frida_api = importlib.import_module("frida")
        device = frida_api.get_device_manager().add_remote_device(remote_address)
        matches = [
            process for process in device.enumerate_processes()
            if process.name.casefold() == "fm.exe"
        ]
    except Exception as error:  # Frida has binding-specific error classes.
        raise ScoutingFeedError(f"cannot connect to the Windows Frida server: {error}") from error
    if len(matches) != 1:
        raise ScoutingFeedError(f"expected one remote 'fm.exe' process, found {len(matches)}")

    builder = extract(
        device,
        matches[0].pid,
        builder_agent_source(before.module_base, arguments),
        script_name="fm20-scouting-pool-builder",
    )
    if not (
        builder["attached"]
        and builder["agentReady"]
        and builder["builderReturnValue"] is not None
        and builder["scriptUnloaded"]
        and builder["detached"]
        and not builder["agentErrors"]
    ):
        detail = next(
            (item.get("description") for item in builder["agentErrors"] if item.get("description")),
            "unknown Frida lifecycle failure",
        )
        raise ScoutingFeedError(f"Frida Player Search pool builder did not complete cleanly: {detail}")

    after, after_arguments, pool_ids = _live_context(pid)
    if after_arguments != arguments:
        raise ScoutingFeedError("manager-rooted search arguments changed during pool capture")
    if _active_manager(after).id != manager.id:
        raise ScoutingFeedError("the active manager changed during pool capture")
    if after.game_date != before.game_date:
        raise ScoutingFeedError("the game date changed during pool capture")
    if not process_alive(pid):
        raise ScoutingFeedError("FM is not healthy after Frida detached")

    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        records = _source_records(lambda address, size: read_exact(fd, address, size), arguments[0])
    finally:
        os.close(fd)
    if set(records) != set(pool_ids):
        raise ScoutingFeedError("rebuilt Player Search source records do not match its ID set")

    own_ids = own_contracted_ids(
        (
            (int(player.id), player.contract.contracted_club.id if player.contract and player.contract.contracted_club else None)
            for player in after.first_team_squad
        ),
        manager.club.id,
    )
    external_ids = sorted(set(pool_ids) - own_ids)
    names = resolve_source_player_names(
        pid, {player_id: records[player_id] for player_id in external_ids}
    )
    return feed_document(
        external_ids,
        names,
        game_date=after.game_date,
        managed_club={"id": manager.club.id, "name": manager.club.name},
        source_count=len(set(pool_ids)),
        excluded_own_ids=set(pool_ids) & own_ids,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    try:
        pid = choose_pid(args.pid)
        executable = Path(preflight(pid)["executable"])
        with frida_server_session(executable) as address:
            document = capture_pool(pid, remote_address=address)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2)
            stream.write("\n")
    except (
        DiscoverabilityError,
        FridaServerError,
        FridaTraceError,
        ProbeError,
        ScoutingFeedError,
        OSError,
        ValueError,
        TimeoutError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"Captured {len(document['players'])} manager-discoverable players to {args.output}. "
        "Attribute and position coverage remains explicitly unknown.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
