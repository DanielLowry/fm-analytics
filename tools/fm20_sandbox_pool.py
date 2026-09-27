#!/usr/bin/env python3
"""Build FM's Player Search list in the sandbox, so a refresh never needs FM's UI.

FM keeps the Player Search list (the "pool") in process memory only: it is
empty after every launch until the manager opens Player Search, and until 27
September 2026 the only alternative to asking the product owner to do that was
running FM's own list builder inside the live game (``--allow-rebuild``, via
Frida) -- the class of in-game call implicated in the broken saves recorded in
``docs/scouting-workspace.md``.

This runs that same builder (``fm.exe+0x52778C0``, arguments: the manager's
player-search source, the manager's search interface, the managed team) in
``tools.fm20_sandbox`` instead. The builder writes its result into the
sandbox's copy of the source object; the live game's list is untouched.

First trial, 27 September 2026, on a freshly started FM whose own list was
empty: 3,411 players in 8.3 seconds (about 250 MB of FM's memory copied), the
same count FM's own builder had produced live earlier that day on the same
save, and the same set on a second run. Not yet diffed player-by-player
against FM's own list for the same moment -- see the "Player Search without
opening Player Search" section of ``docs/scouting-workspace.md``.
"""

from __future__ import annotations

import os
import struct

from tools.fm20_discoverability_cold_filter import _source_records
from tools.fm20_linux_probe import ProbeError, read_exact
from tools.fm20_sandbox import FmSandbox, SandboxError
from tools.fm20_sandbox_queries import SandboxQueryError

PLAYER_SEARCH_BUILDER_RVA = 0x52778C0
# 8.3 s on the test save; the headroom is for bigger saves and slower machines.
BUILD_TIMEOUT_SECONDS = 120.0


def build_pool_in_sandbox(
    pid: int, module_base: int, arguments: tuple[int, int, int]
) -> dict[int, int]:
    """``{player ID: live Person address}`` for FM's Player Search list, built now.

    ``arguments`` is ``(source, manager_interface, team)`` exactly as
    ``fm20_discoverability_manager_builder._live_context`` resolves them. The
    list's own entries are new objects that exist only in the sandbox, but
    each points at a Person FM already has, so the rest of a refresh reads
    those Persons from the live game as it always has.
    """
    source, manager_interface, team = arguments
    box = FmSandbox(pid, module_base)
    try:
        box.call(
            module_base + PLAYER_SEARCH_BUILDER_RVA, source, manager_interface, team,
            timeout_seconds=BUILD_TIMEOUT_SECONDS,
        )
        try:
            records = _source_records(box.read, source)
        except (ProbeError, SandboxError) as error:
            raise SandboxQueryError(f"the sandboxed Player Search list is unreadable: {error}") from error
    finally:
        box.close()
    confirmed = _confirmed_live(pid, records)
    if not confirmed:
        raise SandboxQueryError("the sandboxed Player Search builder produced no players")
    return confirmed


def _confirmed_live(pid: int, records: dict[int, int]) -> dict[int, int]:
    """Only players whose Person is still that same player in the live game.

    The sandbox copies pages as they are first touched while FM keeps running,
    so a Person read late could in principle have moved; everything after this
    reads the live game, so check each one there rather than trust the copy.
    """
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        confirmed: dict[int, int] = {}
        for player_id, person in records.items():
            try:
                live_id = struct.unpack("<i", read_exact(fd, person + 0xC, 4))[0]
            except (OSError, ProbeError):
                continue
            if live_id == player_id:
                confirmed[player_id] = person
        return confirmed
    finally:
        os.close(fd)
