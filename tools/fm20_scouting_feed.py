#!/usr/bin/env python3
"""Capture FM's manager-rooted Player Search pool for the Scouting page.

This is the product-facing, bounded use of the proven Frida source builder.
It asks FM to rebuild the manager's own Player Search pool, removes players
contracted to the managed club, and writes ``--scouting-json`` input.  It does
not replay FM's temporary search-form filters. It records derived non-owned
position labels under the product owner's documented accepted short-term
visibility gap, separately from manager-visible positions.
``--hydrate-player-id`` may additionally read only FM's visible attribute
bounds for a small, already-discoverable subset.

The resulting candidates intentionally have empty ``positions`` and
``attributes`` until their corresponding manager-visible extractors have been
proved for external players. The raw position capture stores its data as
``rawPositions``, so the Scouting page can keep it off by default and require
its own explicit accepted-gap checkbox before displaying or using it. The page
renders all other unknowns as "Scout first" rather than manufacturing values.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

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
from tools.fm20_linux_probe import (
    ProbeError,
    calculate_age,
    decode_fm_date,
    decode_positions,
    read_exact,
    read_fm_string,
    read_player_contract,
)
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_cold_query_cache import resolve_context_and_manager, resolve_player_interfaces
from tools.fm20_native_call_log import log_event, next_call_number
from tools.fm20_visibility_trace import DISPLAY_ATTRIBUTE_IDS


SCHEMA_VERSION = 1


class ScoutingFeedError(RuntimeError):
    """A scouting feed could not be captured without crossing a safety boundary."""


class PoolNotBuiltError(ScoutingFeedError):
    """FM has not built this manager's Player Search pool in this process yet.

    Separate from its base class because it is the one failure a caller can
    offer a choice about: open Player Search in FM (no native call), or
    approve asking FM to build the pool.  Everything else is fail-closed.
    """


def feed_document(
    player_ids: Iterable[int],
    names: dict[int, str],
    *,
    game_date: str,
    managed_club: dict[str, str],
    source_count: int,
    excluded_own_ids: Iterable[int],
    attributes_by_id: dict[int, dict[str, Any]] | None = None,
    attributes_observed_at: dict[int, str] | None = None,
    footedness_by_id: dict[int, str] | None = None,
    footedness_observed_at: dict[int, str] | None = None,
    raw_positions_by_id: dict[int, tuple[str, ...]] | None = None,
    identity_facts_by_id: Mapping[int, dict[str, Any]] | None = None,
    rebuilt: bool = False,
) -> dict[str, Any]:
    """Build the stable JSON contract consumed by ``fm-web --scouting-json``.

    ``gameDate`` is always the date this capture actually read live, even when
    most players' facts were carried forward from an earlier capture rather
    than re-observed today -- the file's own date always advances. Each
    carried-forward attribute/footedness observation keeps the date it was
    actually seen on in ``attributesObservedAt``/``footednessObservedAt``, so
    a stale-looking value is visible as stale rather than silently relabelled
    as current. A player hydrated in this run gets ``game_date`` for both.
    """
    ids = tuple(sorted(set(player_ids)))
    missing_names = [player_id for player_id in ids if not names.get(player_id)]
    if missing_names:
        raise ScoutingFeedError(
            f"identity lookup failed for {len(missing_names)} discovered player(s)"
        )
    excluded = tuple(sorted(set(excluded_own_ids)))
    attributes_by_id = attributes_by_id or {}
    attributes_observed_at = attributes_observed_at or {}
    footedness_by_id = footedness_by_id or {}
    footedness_observed_at = footedness_observed_at or {}
    raw_positions_by_id = raw_positions_by_id or {}
    identity_facts_by_id = identity_facts_by_id or {}
    with_age = sum(1 for player_id in ids if "age" in identity_facts_by_id.get(player_id, {}))
    with_club = sum(1 for player_id in ids if "club" in identity_facts_by_id.get(player_id, {}))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "gameDate": game_date,
        "source": {
            "kind": "manager-rooted-player-search-pool",
            "transport": "windows-frida-server" if rebuilt else "read-only-process-memory",
            "poolRebuiltByCapture": rebuilt,
            "sourceCount": source_count,
            "excludedOwnContractedCount": len(excluded),
            "managedClub": managed_club,
            "fieldCoverage": {
                "identity": (
                    "manager-search-pool plus read-only identity lookup "
                    f"(age {with_age}/{len(ids)}, club/transfer status {with_club}/{len(ids)}); "
                    "availability is not captured yet -- its read is unreliable for some pool "
                    "records (see resolve_source_identity_facts)"
                ),
                "positions": (
                    "raw external position data accepted under the documented short-term "
                    f"visibility gap for {len(raw_positions_by_id)}/{len(ids)} candidates"
                    if raw_positions_by_id else "not yet externally visibility-verified"
                ),
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
                **identity_facts_by_id.get(player_id, {}),
                **({"rawPositions": list(raw_positions_by_id[player_id])}
                   if player_id in raw_positions_by_id else {}),
                "attributes": attributes_by_id.get(player_id, {}),
                **(
                    {"attributesObservedAt": attributes_observed_at.get(player_id, game_date)}
                    if player_id in attributes_by_id else {}
                ),
                **({"footedness": footedness_by_id[player_id]} if player_id in footedness_by_id else {}),
                **(
                    {"footednessObservedAt": footedness_observed_at.get(player_id, game_date)}
                    if player_id in footedness_by_id else {}
                ),
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


def resolve_source_identity_facts(
    pid: int, records: Mapping[int, int], game_date: str
) -> dict[int, dict[str, Any]]:
    """Read age, club, and transfer status -- basic facts, always visible.

    Added 18 September 2026 in response to every scouted candidate showing no
    club and no age, which every one of them plainly has in FM's own search
    and scouting lists with no additional knowledge required. Unlike a
    position eligibility projection or a football attribute, club, date of
    birth, and transfer status are not gated behind any scouting-depth
    concept in FM -- they are exactly what a manager sees for any player a
    search surfaces -- so they need no opt-in checkbox, the same footing as
    the identity resolver above.

    Uses the same ``actual_person = person + 0x28`` relationship that
    resolver already established and the proven, production owned-squad
    reader (`fm20_linux_probe.read_first_team_squad`) already reads both
    fields from. Sampling 800 live pool records found zero failures for
    either field, so a single player's read failing is treated as a genuine
    anomaly for that player, not swallowed as an expected gap: skip that one
    player's identity facts rather than failing the whole capture, mirroring
    the owned-squad reader's own per-field degrade-to-unknown behaviour.

    Deliberately does not attempt availability/injury status: the same
    sampling found its read failing for 222 of 800 players (its pointer sits
    behind a different, less reliably populated field for pool records), so
    it needs more research before it is safe to publish, not a guess shipped
    alongside the two fields that are actually solid.
    """
    as_of = date.fromisoformat(game_date)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        facts: dict[int, dict[str, Any]] = {}
        for player_id, person in records.items():
            actual_person = person + 0x28
            entry: dict[str, Any] = {}
            try:
                dob = decode_fm_date(read_exact(fd, actual_person + 0x1C, 4), maximum_year=as_of.year)
                entry["age"] = calculate_age(dob, as_of)
            except (OSError, ProbeError):
                pass
            try:
                contract = read_player_contract(fd, actual_person)
            except (OSError, ProbeError):
                contract = None
            if contract is not None:
                if contract.contracted_club is not None:
                    entry["club"] = contract.contracted_club.name
                if contract.transfer_status is not None:
                    entry["transferStatus"] = contract.transfer_status
            if entry:
                facts[player_id] = entry
        return facts
    finally:
        os.close(fd)


def read_raw_external_positions(pid: int, records: Mapping[int, int]) -> dict[int, tuple[str, ...]]:
    """Read raw non-owned position labels for the explicitly accepted gap.

    Corrected 18 September 2026 -- was off by exactly one pointer width
    (0x08), and every capture taken before this fix has wrong `rawPositions`
    for some players (see below).

    A search-source record's ``person`` pointer is the same one
    ``resolve_source_player_names`` reaches identity fields from via
    ``person + 0x28``, i.e. it is the owned-squad reader's own
    ``person_address`` (`fm20_linux_probe.read_first_team_squad`:
    ``person_address = player_address + 0x1C0``). That reader's proven,
    production ratings offset is ``player_address + 0x164``, which in terms
    of ``person`` is ``person - 0x1C0 + 0x164`` = **``person - 0x5C``**.

    The previous derivation instead subtracted 0x1C8 -- the *attribute
    builder's* separate ``player_interface`` convention used elsewhere in
    this project (`fm20_frida_attribute_sweep.py`), which is a different
    pointer, one 8-byte pointer width away from ``player_address`` above --
    giving ``person - 0x64``, eight bytes too early. Verified by sampling
    500 live pool records at both offsets: 708 of the resulting 7,500 bytes
    (9.4%) exceeded the valid 1-20 rating range at ``person - 0x64``, and
    zero did at ``person - 0x5C``. The reported symptom (a player visibly
    eligible for a position in FM reading as ineligible here) matched
    exactly: Ashley Wells read DR=0 at the old offset and DR=20 at the
    corrected one.

    This deliberately does not read or publish the individual familiarity
    ratings, only the existing eligibility projection. Call it only for
    manager-discoverable players and only after the user has explicitly
    opted into the accepted visibility gap.
    """
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        positions: dict[int, tuple[str, ...]] = {}
        for player_id, person in records.items():
            try:
                positions[player_id] = decode_positions(read_exact(fd, person - 0x5C, 15))
            except (OSError, ProbeError) as error:
                raise ScoutingFeedError(
                    f"could not read raw positions for discovered player {player_id}: {error}"
                ) from error
        return positions
    finally:
        os.close(fd)


class PriorVisibility(NamedTuple):
    """Everything reusable from an earlier capture, dated per field.

    ``game_date`` is that capture's own top-level date, kept only so a caller
    can log how far it has drifted from today's live read -- it is no longer
    used to refuse a refresh. Each attribute/footedness map's *_observed_at
    counterpart records when that specific fact was actually seen, which for
    a file written before this field existed falls back to the whole prior
    capture's date (the best available answer at migration time).
    """

    game_date: str
    attributes: dict[int, dict[str, Any]]
    attributes_observed_at: dict[int, str]
    footedness: dict[int, str]
    footedness_observed_at: dict[int, str]
    raw_positions: dict[int, tuple[str, ...]]


def load_prior_visibility(path: Path) -> PriorVisibility:
    """Load prior captured fields, including explicitly accepted raw positions."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        game_date = raw["gameDate"]
        rows = raw["players"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ScoutingFeedError(f"cannot read prior scouting feed {path}: {error}") from error
    if not isinstance(game_date, str) or not isinstance(rows, list):
        raise ScoutingFeedError("prior scouting feed has an invalid game date or player list")
    attributes: dict[int, dict[str, Any]] = {}
    attributes_observed_at: dict[int, str] = {}
    footedness: dict[int, str] = {}
    footedness_observed_at: dict[int, str] = {}
    raw_positions: dict[int, tuple[str, ...]] = {}

    def observed_at(row: Mapping[str, Any], field: str) -> str:
        value = row.get(field)
        if value is None:
            return game_date  # pre-dating field: the whole capture's date is all we have
        if not isinstance(value, str):
            raise ScoutingFeedError(f"prior scouting feed has an invalid {field}")
        return value

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
            attributes_observed_at[player_id] = observed_at(row, "attributesObservedAt")
        observed_foot = row.get("footedness")
        if observed_foot is not None:
            if not isinstance(observed_foot, str):
                raise ScoutingFeedError("prior scouting feed contains an invalid footedness value")
            footedness[player_id] = observed_foot
            footedness_observed_at[player_id] = observed_at(row, "footednessObservedAt")
        observed_raw_positions = row.get("rawPositions")
        if observed_raw_positions is not None:
            if not (
                isinstance(observed_raw_positions, list)
                and all(isinstance(position, str) and position for position in observed_raw_positions)
            ):
                raise ScoutingFeedError(
                    "prior scouting feed contains an invalid raw position list"
                )
            raw_positions[player_id] = tuple(observed_raw_positions)
    return PriorVisibility(
        game_date, attributes, attributes_observed_at, footedness, footedness_observed_at, raw_positions,
    )


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


def connect_to_fm(remote_address: str) -> tuple[Any, int]:
    """Attach to the Windows Frida server and resolve the single FM process."""
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
    return device, matches[0].pid


def capture_pool(
    pid: int,
    *,
    remote_address: str | None = None,
    allow_rebuild: bool = False,
    hydrate_player_ids: Sequence[int] = (),
    prior_game_date: str | None = None,
    prior_attributes_by_id: Mapping[int, dict[str, Any]] | None = None,
    prior_attributes_observed_at: Mapping[int, str] | None = None,
    prior_footedness_by_id: Mapping[int, str] | None = None,
    prior_footedness_observed_at: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Read the manager's Player Search pool, asking FM to build it only if needed.

    FM keeps this pool in process memory, so a session that has already used
    Player Search can be read with no native call at all -- the same read-only
    footing as the rest of the bridge.  That is the normal case and it is what
    this function tries first.

    A freshly started FM has an empty pool: research report
    ``manager-rooted-source-20260913T185503Z.json`` recorded 0 players before
    the builder and 4340 after, on a new PID for the same manager and the same
    in-game date that read 4953 cold in the previous process.  Only then is
    running FM's own builder worth considering, because that executes FM code
    inside the live game and can leave a save that will not reload.  It
    therefore needs an explicit ``allow_rebuild``; without it an empty pool
    raises ``PoolNotBuiltError`` so the caller can offer the safer choice of
    opening Player Search in FM instead.

    A base feed from an earlier in-game date no longer blocks the refresh --
    the game date always moves on and refusing here just left a stale file on
    disk until someone deleted it by hand. Prior attributes/footedness are
    still carried forward regardless of date drift; each keeps the date it was
    actually observed (see ``feed_document``), and the returned document's own
    ``gameDate`` is always today's live read. A drift is only logged, not
    enforced -- diagnosing a bad refresh from ``data/logs/fm20-native-calls.jsonl``
    should never require reading the live game by hand.
    """
    call_number = next_call_number()
    started_at = time.monotonic()
    log_event(
        "scouting_refresh_started", call_number=call_number, pid=pid,
        allow_rebuild=allow_rebuild, hydrate_count=len(hydrate_player_ids),
        prior_game_date=prior_game_date,
    )
    try:
        before, arguments, before_ids = _live_context(pid)
        log_event(
            "scouting_pool_read", call_number=call_number, pid=pid,
            pool_count=len(before_ids), game_date=before.game_date,
        )
        manager = _active_manager(before)
        if manager.club is None:
            raise ScoutingFeedError("the active manager has no controlled club")
        expected_base = int(preflight(pid)["moduleBase"], 0)
        if expected_base != int(before.module_base, 0):
            raise ScoutingFeedError("probe and Frida preflight module bases differ")

        device: Any | None = None
        target_pid: int | None = None
        if before_ids:
            after, pool_ids, rebuilt = before, before_ids, False
        else:
            if not allow_rebuild:
                log_event(
                    "scouting_refresh_refused_pool_not_built",
                    call_number=call_number, pid=pid,
                    duration_seconds=time.monotonic() - started_at,
                )
                raise PoolNotBuiltError(
                    "FM has not built this manager's Player Search pool in this process yet. "
                    "Open Player Search in FM once and retry, or approve asking FM to build it."
                )
            if remote_address is None:
                raise ScoutingFeedError("a Frida server address is required to rebuild the pool")
            log_event(
                "scouting_pool_rebuild_started", call_number=call_number, pid=pid,
                remote_address=remote_address,
            )
            device, target_pid = connect_to_fm(remote_address)
            builder = extract(
                device,
                target_pid,
                builder_agent_source(before.module_base, arguments),
                script_name="fm20-scouting-pool-builder",
            )
            hook_info = builder.get("thread") or {}
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
                log_event(
                    "scouting_pool_rebuild_failed", call_number=call_number, pid=pid,
                    hook=hook_info.get("hook"), resting_point=hook_info.get("restingPoint"),
                    agent_errors=builder["agentErrors"],
                    duration_seconds=time.monotonic() - started_at,
                )
                raise ScoutingFeedError(
                    f"Frida Player Search pool builder did not complete cleanly: {detail}"
                )
            after, after_arguments, pool_ids = _live_context(pid)
            if after_arguments != arguments:
                raise ScoutingFeedError("manager-rooted search arguments changed during pool capture")
            if _active_manager(after).id != manager.id:
                raise ScoutingFeedError("the active manager changed during pool capture")
            if after.game_date != before.game_date:
                raise ScoutingFeedError("the game date changed during pool capture")
            if not pool_ids:
                raise ScoutingFeedError("FM's builder returned an empty Player Search pool")
            rebuilt = True
            log_event(
                "scouting_pool_rebuild_completed", call_number=call_number, pid=pid,
                hook=hook_info.get("hook"), resting_point=hook_info.get("restingPoint"),
                pool_count_before=len(before_ids), pool_count_after=len(pool_ids),
            )
        if prior_game_date is not None and after.game_date != prior_game_date:
            log_event(
                "scouting_refresh_date_drift", call_number=call_number, pid=pid,
                prior_game_date=prior_game_date, live_game_date=after.game_date,
            )
        if not process_alive(pid):
            raise ScoutingFeedError("FM is not healthy after its Player Search pool was read")

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
        raw_positions_by_id = read_raw_external_positions(
            pid,
            {player_id: records[player_id] for player_id in external_ids},
        )
        identity_facts_by_id = resolve_source_identity_facts(
            pid,
            {player_id: records[player_id] for player_id in external_ids},
            after.game_date,
        )
        if requested_hydration and device is None:
            # Only the hydration paths still need Frida once the pool is warm, so
            # a plain refresh never attaches to FM at all.
            if remote_address is None:
                raise ScoutingFeedError(
                    "a Frida server address is required to hydrate visible attributes"
                )
            device, target_pid = connect_to_fm(remote_address)
        if requested_hydration:
            log_event(
                "scouting_hydration_started", call_number=call_number, pid=pid,
                player_ids=list(requested_hydration),
            )
        attributes_by_id = dict(prior_attributes_by_id or {})
        attributes_observed_at = dict(prior_attributes_observed_at or {})
        newly_hydrated_attributes = hydrate_visible_attributes(
            pid,
            module_base=before.module_base,
            player_ids=requested_hydration,
            device=device,
            target_pid=target_pid,
        )
        attributes_by_id.update(newly_hydrated_attributes)
        attributes_observed_at.update(dict.fromkeys(newly_hydrated_attributes, after.game_date))
        footedness_by_id = dict(prior_footedness_by_id or {})
        footedness_observed_at = dict(prior_footedness_observed_at or {})
        newly_hydrated_footedness = hydrate_visible_footedness(
            pid,
            module_base=before.module_base,
            player_ids=requested_hydration,
            names=names,
            records=records,
            device=device,
            target_pid=target_pid,
        )
        footedness_by_id.update(newly_hydrated_footedness)
        footedness_observed_at.update(dict.fromkeys(newly_hydrated_footedness, after.game_date))
        if requested_hydration:
            log_event(
                "scouting_hydration_completed", call_number=call_number, pid=pid,
                attributes_hydrated=len(newly_hydrated_attributes),
                footedness_hydrated=len(newly_hydrated_footedness),
            )
        external_id_set = set(external_ids)
        attributes_by_id = {
            player_id: value for player_id, value in attributes_by_id.items()
            if player_id in external_id_set
        }
        attributes_observed_at = {
            player_id: value for player_id, value in attributes_observed_at.items()
            if player_id in external_id_set
        }
        footedness_by_id = {
            player_id: value for player_id, value in footedness_by_id.items()
            if player_id in external_id_set
        }
        footedness_observed_at = {
            player_id: value for player_id, value in footedness_observed_at.items()
            if player_id in external_id_set
        }
        raw_positions_by_id = {
            player_id: value for player_id, value in raw_positions_by_id.items()
            if player_id in external_id_set
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
        document = feed_document(
            external_ids,
            names,
            game_date=after.game_date,
            managed_club={"id": manager.club.id, "name": manager.club.name},
            source_count=len(set(pool_ids)),
            excluded_own_ids=set(pool_ids) & own_ids,
            attributes_by_id=attributes_by_id,
            attributes_observed_at=attributes_observed_at,
            footedness_by_id=footedness_by_id,
            footedness_observed_at=footedness_observed_at,
            raw_positions_by_id=raw_positions_by_id,
            identity_facts_by_id=identity_facts_by_id,
            rebuilt=rebuilt,
        )
    except BaseException as error:
        log_event(
            "scouting_refresh_failed", call_number=call_number, pid=pid,
            duration_seconds=time.monotonic() - started_at,
            exception_type=type(error).__name__, exception=str(error),
        )
        raise
    log_event(
        "scouting_refresh_completed", call_number=call_number, pid=pid,
        rebuilt=rebuilt, player_count=len(external_ids),
        duration_seconds=time.monotonic() - started_at,
    )
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-feed", type=Path,
        help=(
            "preserve visible fields from an earlier feed, even one from a different "
            "in-game date; each field keeps the date it was actually observed"
        ),
    )
    parser.add_argument("--replace", action="store_true", help="replace the explicit --output capture")
    parser.add_argument(
        "--hydrate-player-id", type=int, action="append", default=[],
        help=(
            "read all manager-visible attributes for one discovered player "
            f"(repeat up to {MAX_HYDRATED_PLAYERS} times)"
        ),
    )
    parser.add_argument(
        "--allow-rebuild", action="store_true",
        help=(
            "if FM has not built its Player Search pool yet, run FM's own builder "
            "inside the live game to build it. This executes FM code in your "
            "running save and has been observed to be the risky step; opening "
            "Player Search in FM once achieves the same thing without it. "
            "Without this flag an unbuilt pool exits 3 and changes nothing."
        ),
    )
    args = parser.parse_args(argv)
    if args.output.exists() and not args.replace:
        parser.error(f"output already exists: {args.output}")
    if args.replace and not args.output.exists():
        parser.error("--replace requires an existing --output file")
    try:
        prior = load_prior_visibility(args.base_feed) if args.base_feed else None
        pid = choose_pid(args.pid)
        capture = dict(
            hydrate_player_ids=args.hydrate_player_id,
            allow_rebuild=args.allow_rebuild,
            prior_game_date=prior.game_date if prior else None,
            prior_attributes_by_id=prior.attributes if prior else {},
            prior_attributes_observed_at=prior.attributes_observed_at if prior else {},
            prior_footedness_by_id=prior.footedness if prior else {},
            prior_footedness_observed_at=prior.footedness_observed_at if prior else {},
        )
        # Reading a pool FM has already built needs no Frida server at all, so
        # decide that up front rather than starting one we will not use. The
        # check is an ordinary read-only probe.
        _state, _arguments, pool_ids = _live_context(pid)
        if pool_ids and not args.hydrate_player_id:
            document = capture_pool(pid, **capture)
        else:
            executable = Path(preflight(pid)["executable"])
            with frida_server_session(executable) as address:
                document = capture_pool(pid, remote_address=address, **capture)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w" if args.replace else "x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2)
            stream.write("\n")
    except PoolNotBuiltError as error:
        print(f"error: {error}", file=sys.stderr)
        return 3
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
        + (
            "FM's own builder was run inside the live game to build the pool."
            if document["source"]["poolRebuiltByCapture"]
            else "Read from the pool FM had already built; nothing was written to FM."
        )
        + f" Visible attributes hydrated for {len(args.hydrate_player_id)} player(s); "
        "raw external positions captured under the accepted visibility gap.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
