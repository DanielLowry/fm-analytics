#!/usr/bin/env python3
"""Process-lifetime cache for cold-query identity resolution.

Every cold call previously re-verified the FM build by hashing its ~500MB
executable, and re-scanned the entire loaded-person collection (250,000+
entries) from scratch twice -- once to find the active manager, once to find
the target player -- even though none of that changes between calls in the
same game session. On a live squad of ~20 players and ~40 attributes each,
that was the difference between a few seconds and ten-plus minutes.

Each cached value gets its own cheap, direct re-check before use, rather
than a single coarse "has anything changed" signal:

- the build hash is checked once per process ID and never again -- a
  running process's backing executable cannot change;
- the active manager's identity is normally confirmed by a single O(1)
  memory read; a genuine mismatch (the field tracks UI selection, not just
  the manager -- see `resolve_context_and_manager`) falls back to one full
  scan instead of failing outright;
- a player's resolved interface address is cached per (pid, player_id) and
  re-verified with three O(1) reads on every reuse; a full scan runs only
  the first time a given player is requested in this process, or if that
  re-verification ever fails.

Every fast path re-checks the same invariants the slow path already
enforced, so a stale or wrong cache entry fails closed into a fresh scan
rather than ever returning unvalidated data.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from tools.fm20_cold_visibility_call import CONTEXT_ROOT_RVA, EXPECTED_SHA256
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    parse_module_mapping,
    read_human_managers,
    read_i32,
    read_pointer_collection,
    read_u64,
    select_active_manager_id,
    validate_executable,
)

_MODULE_BASE_CACHE: dict[int, int] = {}
_PLAYER_INTERFACE_CACHE: dict[int, dict[int, int]] = {}


def verified_module_base(pid: int, proc_root: Path = Path("/proc")) -> int:
    """FM's module base, hash-verified once per process ID and never again."""

    cached = _MODULE_BASE_CACHE.get(pid)
    if cached is not None:
        return cached
    process = proc_root / str(pid)
    with (process / "maps").open(encoding="utf-8") as mappings:
        module_base, executable = parse_module_mapping(mappings)
    validate_executable(executable)
    with Path(executable).open("rb") as image:
        digest = hashlib.file_digest(image, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise ProbeError("FM executable hash differs from the traced build")
    _MODULE_BASE_CACHE[pid] = module_base
    return module_base


def resolve_context_and_manager(memory_fd: int, module_base: int) -> tuple[int, int]:
    """(knowledge context, manager interface), usually via one O(1) identity check.

    FM's "active object" field reflects whatever the UI currently has
    selected -- a viewed player, a search result -- not reliably the active
    manager. It happens to equal the manager right after a save loads or on
    a manager-facing screen, which is why a direct comparison worked in
    earlier testing, but it silently stops matching as soon as the operator
    looks at anything else, such as Player Search. `select_active_manager_id`
    in `fm20_linux_probe` already treats this same field as a hint rather
    than ground truth for exactly this reason; this function used to skip
    that safeguard for speed. It no longer does: the O(1) comparison is
    tried first, and only a genuine mismatch falls back to the one full
    person-collection scan the rest of the codebase already pays for this
    resolution. A wrong context owner still fails closed either way.
    """

    root = read_u64(memory_fd, module_base + CONTEXT_ROOT_RVA)
    if not root:
        raise ProbeError("manager-knowledge context root is missing")
    start = read_u64(memory_fd, root + 0x18)
    end = read_u64(memory_fd, root + 0x20)
    if not start or end - start != 8:
        raise ProbeError("expected exactly one manager-knowledge context")
    context = read_u64(memory_fd, start)
    if not context:
        raise ProbeError("manager-knowledge context is null")
    manager_person = read_u64(memory_fd, context + 0x18)
    if read_u64(memory_fd, manager_person) != module_base + FM20_4_4_STEAM.human_manager_type_offset:
        raise ProbeError("knowledge-context owner is not a human manager")
    context_owner_id = read_i32(memory_fd, manager_person + 0xC)
    active_object_id = read_i32(memory_fd, module_base + FM20_4_4_STEAM.active_object_offset)
    if context_owner_id != active_object_id:
        try:
            managers = read_human_managers(memory_fd, module_base)
            resolved_id = select_active_manager_id(managers, active_object_id)
        except (OSError, ProbeError):
            resolved_id = None
        if resolved_id is None or int(resolved_id) != context_owner_id:
            raise ProbeError("knowledge-context owner is not the active manager")
    manager_interface = manager_person - 0x480
    manager_table = read_u64(memory_fd, manager_interface + 8)
    if manager_interface + 8 + read_i32(memory_fd, manager_table + 4) != manager_person:
        raise ProbeError("manager interface adjustment does not resolve to owner")
    return context, manager_interface


def _valid_player_interface(
    memory_fd: int, module_base: int, player_interface: int, player_id: int
) -> bool:
    try:
        player_person = player_interface + 0x1C8
        if read_u64(memory_fd, player_person) != module_base + FM20_4_4_STEAM.player_type_offset:
            return False
        if read_i32(memory_fd, player_person + 0xC) != player_id:
            return False
        player_table = read_u64(memory_fd, player_interface + 8)
        return player_interface + 8 + read_i32(memory_fd, player_table + 4) == player_person
    except (OSError, ProbeError):
        return False


def _scan_player_interfaces(
    memory_fd: int, module_base: int, wanted: set[int]
) -> dict[int, int]:
    people = read_pointer_collection(
        memory_fd, module_base,
        FM20_4_4_STEAM.main_address_offset,
        FM20_4_4_STEAM.person_collection_offset,
        FM20_4_4_STEAM.collection_indirection_offset,
    )
    expected_type = module_base + FM20_4_4_STEAM.player_type_offset
    found: dict[int, int] = {}
    for address in people:
        if not address or len(found) == len(wanted):
            continue
        if read_u64(memory_fd, address) != expected_type:
            continue
        player_id = read_i32(memory_fd, address + 0xC)
        if player_id in wanted and player_id not in found:
            found[player_id] = address - 0x1C8
    return found


def resolve_player_interfaces(
    pid: int, memory_fd: int, module_base: int, player_ids: Iterable[int]
) -> dict[int, int]:
    """Player interface addresses, cached per (pid, player_id).

    A cached address is re-verified with three O(1) reads before use; a
    full collection scan runs only for players never resolved before in
    this process, or whose cached address just failed re-verification --
    and it resolves every such player in one pass, not one scan each.
    """

    wanted = set(player_ids)
    cache = _PLAYER_INTERFACE_CACHE.setdefault(pid, {})
    resolved: dict[int, int] = {}
    misses: set[int] = set()
    for player_id in wanted:
        cached = cache.get(player_id)
        if cached is not None and _valid_player_interface(
            memory_fd, module_base, cached, player_id
        ):
            resolved[player_id] = cached
        else:
            misses.add(player_id)
    if misses:
        found = _scan_player_interfaces(memory_fd, module_base, misses)
        cache.update(found)
        resolved.update(found)
    return resolved
