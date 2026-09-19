#!/usr/bin/env python3
"""Per-player, read-only memory readers for the scouting capture.

Split out of ``fm20_scouting_feed.py`` on 19 September 2026 to keep that module
under this project's line cap. These four functions share one job -- given a
map of player ID to that player's Person address, read a fact about each from
FM's memory with no call into the game -- while the capture module decides
*which* players to read and assembles the feed. Each is tolerant of a single
unreadable player (skipped, not fatal) except ``read_raw_external_positions``,
which fails closed because its output is published as position data.
"""

from __future__ import annotations

import os
import struct
from datetime import date
from typing import Any, Mapping

from tools.fm20_linux_probe import (
    POSITION_CODES,
    ProbeError,
    calculate_age,
    decode_fm_date,
    decode_positions,
    read_exact,
    read_fm_string,
    read_player_contract,
)
from tools.fm20_scouting_feed_contract import ScoutingFeedError


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


# The player's transfer value in pounds, as FM prints it in the Value column of
# Player Search and on his profile -- a manager-visible figure, not a hidden
# rating. Verified 19 September 2026 against ten exported players whose Value
# column matches this field once FM's own display rounding is applied (e.g.
# 14,435 -> "PS14.5K", 3,589 -> "PS3.6K").
PLAYER_VALUE_FROM_PERSON = -0x98


def read_player_value(memory_fd: int, person: int) -> int | None:
    """Pounds, or None when the field does not read as a plausible value."""
    try:
        raw = struct.unpack("<I", read_exact(memory_fd, person + PLAYER_VALUE_FROM_PERSON, 4))[0]
    except (OSError, ProbeError):
        return None
    # FM's own ceiling for a player valuation is far below this; anything
    # larger means the field was not what we think it is for this record.
    return raw if raw <= 500_000_000 else None


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
            value = read_player_value(fd, person)
            if value is not None:
                entry["value"] = value
            contract_read_failed = False
            try:
                contract = read_player_contract(fd, actual_person)
            except (OSError, ProbeError):
                contract, contract_read_failed = None, True
            if contract is not None:
                if contract.contracted_club is not None:
                    entry["club"] = contract.contracted_club.name
                if contract.transfer_status is not None:
                    entry["transferStatus"] = contract.transfer_status
                # Contract expiry and type are what make "is he actually gettable"
                # answerable: a deal about to run out costs nothing. Read from the
                # same contract object as the club and transfer status above.
                if contract.end_date is not None:
                    entry["contractEnd"] = contract.end_date
                if contract.contract_type is not None:
                    entry["contractType"] = contract.contract_type
            elif not contract_read_failed:
                # A successful read that found no contract at all: an unattached
                # player. Recorded as a fact so a free agent is distinguishable
                # from a player whose contract simply could not be read.
                entry["hasContract"] = False
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

    This function keeps only the eligibility projection; the individual
    ratings are read separately by ``read_raw_position_familiarity``, under the
    same opt-in. Call it only for
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


def read_raw_position_familiarity(
    pid: int, records: Mapping[int, int]
) -> dict[int, dict[str, int]]:
    """Read each player's 15 raw position ratings, keyed by position code.

    Same bytes, same offset (``person - 0x5C``) as ``read_raw_external_positions``
    -- that function keeps only the eligibility cut; this keeps the ratings.
    For a player outside the manager's own club this is finer-grained than
    FM's own screens necessarily show, so it sits behind the same opt-in as
    the raw positions: the product owner confirmed on 19 September 2026 that
    the existing "Use raw external positions (accepted visibility gap)" tick
    covers it, with no second checkbox. The feed stores it separately as
    ``rawPositionFamiliarity`` so it can never be mistaken for a verified
    position. A player whose bytes cannot be read is skipped, not fatal.
    """
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        ratings: dict[int, dict[str, int]] = {}
        for player_id, person in records.items():
            try:
                raw = read_exact(fd, person - 0x5C, len(POSITION_CODES))
            except (OSError, ProbeError):
                continue
            if max(raw) > 20:  # not a rating array -- refuse rather than publish noise
                continue
            ratings[player_id] = dict(zip(POSITION_CODES, raw))
        return ratings
    finally:
        os.close(fd)
