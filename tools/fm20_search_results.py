#!/usr/bin/env python3
"""Read the result list FM itself built for the Player Search on screen.

FM does not store "is this player interested in a transfer" anywhere. Its
``PERSON_INTERESTED_FILTER_RULE`` (evaluator at ``fm.exe+0x1fb27d0``) computes
the answer per player on every search, comparing a figure for the player
against a threshold derived from the managing club, and keeps no flag. A wide
read-only sweep over labelled players -- person record, contract, his club,
his scout report, at 1, 2 and 4 byte widths -- found nothing that separates
interested players from the rest, which agrees with that reading.

What FM *does* keep, for as long as the search is on screen, is the answer: the
list of players the applied filter matched. That list lives in a
``PERSON_SEARCH_EDIT_SESSION`` (despite the name this is only read here; no
call is made into the game and nothing is written). Several sessions exist at
once and all but the active one are empty, so the active one is found by
signature rather than by any fixed address:

  * scan writable memory for the session vtable (``VTABLE_RVA``)
  * read the results vector at ``RESULTS_VECTOR_OFFSET``
  * keep the session whose entries all dereference to players known through
    either the current Player Search pool or the manager's scouting records

A session allocates its own wrapper objects rather than reusing the pool's, so
an entry is matched by the player's stable ID, never by wrapper or Person
address. Both addresses can differ from the current pool's representation of
the same player; comparing either pointer silently loses valid results.

Verified 19 September 2026 against a live filter of "interested in transfer":
FM reported 1929 of 4090 players, exactly one session held 1929 entries, and
16 of 17 independently labelled players fell on the expected side (the 17th,
Niall McManus, had moved onto the list in the six game weeks since the label
was taken).

Re-verified 26 September 2026 against a 232-player scouted-player search. All
232 stable IDs belonged to current capture candidates (225 had current scout
reports), while only 39 of their Person addresses occurred in the current
Player Search source. This is why identity here is deliberately ID-based.

**This reads whichever filter the manager currently has applied.** It cannot
tell which criteria produced the list, so callers must describe the result as
"matched the search open in FM", never assume a particular filter.
"""

from __future__ import annotations

import os
import struct
from typing import Iterable

from tools.fm20_linux_probe import ProbeError, read_exact

VTABLE_RVA = 0x67529A0
RESULTS_VECTOR_OFFSET = 0x18
# The guard is deliberately generous but rules out nonsensical vectors.
_MAX_RESULTS = 200_000


def _writable_regions(pid: int) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    with open(f"/proc/{pid}/maps", encoding="utf-8") as maps:
        for line in maps:
            parts = line.split()
            if len(parts) < 2 or "w" not in parts[1]:
                continue
            low, high = (int(value, 16) for value in parts[0].split("-"))
            if high - low > 1 << 30:  # skip reserved-but-unbacked arenas
                continue
            regions.append((low, high))
    return regions


def _session_results(
    memory_fd: int, session: int, candidate_ids: frozenset[int]
) -> list[int] | None:
    """The session's result player IDs, or None when empty or not a match."""
    try:
        begin, end = struct.unpack("<QQ", read_exact(memory_fd, session + RESULTS_VECTOR_OFFSET, 16))
    except (OSError, OverflowError, ProbeError):
        return None
    if not begin or end < begin or (end - begin) % 8:
        return None
    count = (end - begin) // 8
    if not 0 < count <= _MAX_RESULTS:
        return None
    try:
        entries = struct.unpack(f"<{count}Q", read_exact(memory_fd, begin, count * 8))
        people = [struct.unpack("<Q", read_exact(memory_fd, entry, 8))[0] for entry in entries]
        resolved = [struct.unpack("<i", read_exact(memory_fd, person + 0xC, 4))[0] for person in people]
    except (OSError, OverflowError, ProbeError, struct.error):
        return None
    # Every entry must resolve to a player the capture can represent. A partial
    # match means this vector is something else holding pointers, so it is
    # rejected whole. Person pointer identity is deliberately not checked:
    # FM's scouted-player result list can use different Person instances from
    # the current Player Search source for the same stable player IDs.
    return resolved if all(player_id in candidate_ids for player_id in resolved) else None


def read_active_search_results(
    pid: int, module_base: int, candidate_player_ids: Iterable[int]
) -> tuple[int, ...] | None:
    """Stable IDs for the players FM's on-screen search currently matches.

    Returns None when no search is displaying results -- the ordinary case
    when the manager is not sitting on Player Search. Raises ``ProbeError``
    when more than one session holds results, because then there is no way to
    say which search the manager meant.
    """
    candidate_ids = frozenset(candidate_player_ids)
    if not candidate_ids:
        raise ProbeError("known candidate IDs are required to identify a result list")
    pattern = struct.pack("<Q", module_base + VTABLE_RVA)
    matches: list[list[int]] = []
    memory_fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        for low, high in _writable_regions(pid):
            address = low
            while address < high:
                size = min(1 << 22, high - address)
                try:
                    buffer = read_exact(memory_fd, address, size)
                except (OSError, ProbeError):
                    address += size
                    continue
                found = buffer.find(pattern)
                while found != -1:
                    results = _session_results(memory_fd, address + found, candidate_ids)
                    if results is not None:
                        matches.append(results)
                    found = buffer.find(pattern, found + 1)
                address += size
    finally:
        os.close(memory_fd)
    if not matches:
        return None
    if len(matches) > 1:
        raise ProbeError(f"{len(matches)} Player Search result lists are live; cannot choose one")
    return tuple(matches[0])
