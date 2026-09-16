#!/usr/bin/env python3
"""Capture FM's manager-rooted Player Search pool for the Scouting page.

This is the product-facing, bounded use of the proven Frida source builder.
It asks FM to rebuild the manager's own Player Search pool, removes players
contracted to the managed club, and writes ``--scouting-json`` input.  It does
not replay FM's temporary search-form filters or read position-familiarity
bytes. ``--hydrate-player-id`` may additionally read only FM's visible
attribute bounds for a small, already-discoverable subset.

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
from typing import Any, Iterable, Mapping, Sequence

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
from tools.fm20_frida_attribute_sweep import (
    MAX_PEOPLE as MAX_HYDRATED_PLAYERS,
    build_agent_source as attribute_agent_source,
    decode_capture as decode_attribute_capture,
    extract as extract_attribute_capture,
)
from tools.fm20_frida_property import (
    build_agent_source as footedness_agent_source,
    extract as extract_footedness_capture,
    summarize_footedness,
)
from tools.fm20_frida_server import FridaServerError, frida_server_session
from tools.fm20_frida_trace import FridaTraceError, preflight, process_alive
from tools.fm20_linux_probe import ProbeError, read_exact, read_fm_string
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_cold_query_cache import resolve_context_and_manager, resolve_player_interfaces
from tools.fm20_visibility_trace import DISPLAY_ATTRIBUTE_IDS


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
    attributes_by_id: dict[int, dict[str, Any]] | None = None,
    footedness_by_id: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Build the stable JSON contract consumed by ``fm-web --scouting-json``."""
    ids = tuple(sorted(set(player_ids)))
    missing_names = [player_id for player_id in ids if not names.get(player_id)]
    if missing_names:
        raise ScoutingFeedError(
            f"identity lookup failed for {len(missing_names)} discovered player(s)"
        )
    excluded = tuple(sorted(set(excluded_own_ids)))
    attributes_by_id = attributes_by_id or {}
    footedness_by_id = footedness_by_id or {}
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
                "attributes": (
                    f"manager-visible native builder for {len(attributes_by_id)}/{len(ids)} candidates"
                    if attributes_by_id else "not yet externally visibility-verified"
                ),
                "footedness": (
                    f"manager-visible property getter for {len(footedness_by_id)}/{len(ids)} candidates"
                    if footedness_by_id else "not yet externally visibility-verified"
                ),
            },
        },
        "players": [
            {
                "id": str(player_id),
                "name": names[player_id],
                "positions": [],
                "attributes": attributes_by_id.get(player_id, {}),
                **({"footedness": footedness_by_id[player_id]} if player_id in footedness_by_id else {}),
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


def load_prior_visibility(path: Path) -> tuple[str, dict[int, dict[str, Any]], dict[int, str]]:
    """Load only previously captured visible fields, rejecting an ambiguous file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        game_date = raw["gameDate"]
        rows = raw["players"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ScoutingFeedError(f"cannot read prior scouting feed {path}: {error}") from error
    if not isinstance(game_date, str) or not isinstance(rows, list):
        raise ScoutingFeedError("prior scouting feed has an invalid game date or player list")
    attributes: dict[int, dict[str, Any]] = {}
    footedness: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ScoutingFeedError("prior scouting feed contains an invalid player")
        try:
            player_id = int(row["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ScoutingFeedError("prior scouting feed contains an invalid player ID") from error
        observed_attributes = row.get("attributes", {})
        if not isinstance(observed_attributes, Mapping):
            raise ScoutingFeedError("prior scouting feed contains an invalid attribute map")
        if observed_attributes:
            attributes[player_id] = dict(observed_attributes)
        observed_foot = row.get("footedness")
        if observed_foot is not None:
            if not isinstance(observed_foot, str):
                raise ScoutingFeedError("prior scouting feed contains an invalid footedness value")
            footedness[player_id] = observed_foot
    return game_date, attributes, footedness


def hydrate_visible_attributes(
    pid: int,
    *,
    module_base: str,
    player_ids: Sequence[int],
    device: Any,
    target_pid: int,
) -> dict[int, dict[str, Any]]:
    """Read FM's visible attribute bounds for a small, known candidate set.

    The IDs must already have passed the manager's Player Search pool gate.
    This resolves only the player interface required by FM's visibility
    builder, and returns its two visible bounds per attribute. It never reads
    raw attribute storage or the builder result's concealed third byte.
    """
    selected = tuple(dict.fromkeys(player_ids))
    if not selected:
        return {}
    if len(selected) > MAX_HYDRATED_PLAYERS:
        raise ScoutingFeedError(
            f"at most {MAX_HYDRATED_PLAYERS} players can be hydrated in one bounded capture"
        )
    numeric_base = int(module_base, 0)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        context, _manager_interface = resolve_context_and_manager(fd, numeric_base)
        interfaces = resolve_player_interfaces(pid, fd, numeric_base, selected)
    finally:
        os.close(fd)
    missing = sorted(set(selected) - set(interfaces))
    if missing:
        raise ScoutingFeedError(
            f"{len(missing)} discovered player(s) could not be resolved for visible attributes"
        )
    people = [
        {"id": str(player_id), "interface": f"0x{interfaces[player_id]:x}"}
        for player_id in selected
    ]
    attributes = tuple(sorted(DISPLAY_ATTRIBUTE_IDS))
    capture = extract_attribute_capture(
        device,
        target_pid,
        attribute_agent_source(module_base, context, people, attributes),
        timeout_seconds=30.0,
    )
    if not (
        capture["attached"]
        and capture["agentReady"]
        and capture["scriptUnloaded"]
        and capture["detached"]
        and not capture["agentErrors"]
        and process_alive(pid)
    ):
        detail = next(
            (item.get("description") for item in capture["agentErrors"] if item.get("description")),
            "unknown Frida lifecycle failure",
        )
        raise ScoutingFeedError(f"Frida visible-attribute capture did not complete cleanly: {detail}")
    decoded = decode_attribute_capture(people, attributes, capture)
    if decoded["resolvedCount"] != len(people):
        raise ScoutingFeedError("not every requested player returned a complete visible attribute set")
    return {
        int(row["id"]): row["attributes"]
        for row in decoded["players"]
        if row["error"] is None and row["attributes"] is not None
    }


def hydrate_visible_footedness(
    pid: int,
    *,
    module_base: str,
    player_ids: Sequence[int],
    names: dict[int, str],
    records: dict[int, int],
    device: Any,
    target_pid: int,
) -> dict[int, str]:
    """Read FM's manager-visible footedness label for known candidates only."""
    selected = tuple(dict.fromkeys(player_ids))
    if not selected:
        return {}
    people = [
        {"id": str(player_id), "name": names[player_id], "address": f"0x{records[player_id]:x}"}
        for player_id in selected
    ]
    capture = extract_footedness_capture(
        device,
        target_pid,
        footedness_agent_source(module_base, people),
        timeout_seconds=20.0,
    )
    if not (
        capture["attached"]
        and capture["agentReady"]
        and capture["scriptUnloaded"]
        and capture["detached"]
        and not capture["agentErrors"]
        and process_alive(pid)
    ):
        detail = next(
            (item.get("description") for item in capture["agentErrors"] if item.get("description")),
            "unknown Frida lifecycle failure",
        )
        raise ScoutingFeedError(f"Frida visible-footedness capture did not complete cleanly: {detail}")
    decoded = summarize_footedness(people, capture)
    if not decoded["labelsVerified"]:
        raise ScoutingFeedError("FM's footedness labels did not match the verified label set")
    return {
        int(row["id"]): row["footedness"]
        for row in decoded["players"]
        if row["status"] == "visible" and row["footedness"] is not None
    }


def capture_pool(
    pid: int,
    *,
    remote_address: str,
    hydrate_player_ids: Sequence[int] = (),
    prior_game_date: str | None = None,
    prior_attributes_by_id: Mapping[int, dict[str, Any]] | None = None,
    prior_footedness_by_id: Mapping[int, str] | None = None,
) -> dict[str, Any]:
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
    if prior_game_date is not None and after.game_date != prior_game_date:
        raise ScoutingFeedError("prior scouting feed is from a different game date")
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
    requested_hydration = tuple(dict.fromkeys(hydrate_player_ids))
    non_candidates = sorted(set(requested_hydration) - set(external_ids))
    if non_candidates:
        raise ScoutingFeedError(
            "requested attribute hydration includes a player outside the manager's discovery pool"
        )
    names = resolve_source_player_names(
        pid, {player_id: records[player_id] for player_id in external_ids}
    )
    attributes_by_id = dict(prior_attributes_by_id or {})
    attributes_by_id.update(hydrate_visible_attributes(
        pid,
        module_base=before.module_base,
        player_ids=requested_hydration,
        device=device,
        target_pid=matches[0].pid,
    ))
    footedness_by_id = dict(prior_footedness_by_id or {})
    footedness_by_id.update(hydrate_visible_footedness(
        pid,
        module_base=before.module_base,
        player_ids=requested_hydration,
        names=names,
        records=records,
        device=device,
        target_pid=matches[0].pid,
    ))
    attributes_by_id = {
        player_id: value for player_id, value in attributes_by_id.items()
        if player_id in set(external_ids)
    }
    footedness_by_id = {
        player_id: value for player_id, value in footedness_by_id.items()
        if player_id in set(external_ids)
    }
    final, final_arguments, final_pool_ids = _live_context(pid)
    if (
        final_arguments != arguments
        or _active_manager(final).id != manager.id
        or final.game_date != before.game_date
        or set(final_pool_ids) != set(pool_ids)
        or not process_alive(pid)
    ):
        raise ScoutingFeedError("FM state changed while visible attributes were captured")
    return feed_document(
        external_ids,
        names,
        game_date=after.game_date,
        managed_club={"id": manager.club.id, "name": manager.club.name},
        source_count=len(set(pool_ids)),
        excluded_own_ids=set(pool_ids) & own_ids,
        attributes_by_id=attributes_by_id,
        footedness_by_id=footedness_by_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-feed", type=Path, help="preserve visible fields from this same-date feed")
    parser.add_argument("--replace", action="store_true", help="replace the explicit --output capture")
    parser.add_argument(
        "--hydrate-player-id", type=int, action="append", default=[],
        help=(
            "read all manager-visible attributes for one discovered player "
            f"(repeat up to {MAX_HYDRATED_PLAYERS} times)"
        ),
    )
    args = parser.parse_args(argv)
    if args.output.exists() and not args.replace:
        parser.error(f"output already exists: {args.output}")
    if args.replace and not args.output.exists():
        parser.error("--replace requires an existing --output file")
    try:
        prior_game_date, prior_attributes, prior_footedness = (
            load_prior_visibility(args.base_feed)
            if args.base_feed else (None, {}, {})
        )
        pid = choose_pid(args.pid)
        executable = Path(preflight(pid)["executable"])
        with frida_server_session(executable) as address:
            document = capture_pool(
                pid, remote_address=address, hydrate_player_ids=args.hydrate_player_id,
                prior_game_date=prior_game_date,
                prior_attributes_by_id=prior_attributes,
                prior_footedness_by_id=prior_footedness,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w" if args.replace else "x", encoding="utf-8") as stream:
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
        f"Visible attributes hydrated for {len(args.hydrate_player_id)} player(s); positions remain unknown.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
