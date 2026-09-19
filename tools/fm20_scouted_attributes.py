#!/usr/bin/env python3
"""Read-only visible attributes for every player on the manager's scout list.

Verified against FM's own exported profiles for four scouted players -- see
the scout-reports paragraph below and ``docs/scouting-workspace.md``.

This makes **no calls into FM and no native invocation of any kind**. It
reads three things FM already keeps in its own memory, at rest:

- the manager's explicit scouting-knowledge list (a plain ``{RowID, level}``
  vector on the manager's knowledge context -- see
  ``docs/phases/03-information-visibility/03.2-fm-representation-research.md``,
  "The explicit-knowledge writer and store");
- each such player's true attribute bytes, position ratings, and date of
  birth, at the same offsets the proven owned-squad reader already uses
  (``tools.fm20_owned_visible_source``, ``tools.fm20_visibility_trace``);
- FM's own visibility formula, independently recovered from the supported
  executable and already implemented at
  ``fm_analytics.bridge.fm20_visibility_algorithm``.

The true attribute byte is read only to feed that formula. It is converted
to a visible observation before this module returns anything, and the
formula's own output type (``AttributeObservation``) cannot represent an
exact hidden value unless FM's own classification says the value is exactly
known -- the same guarantee ``fm_analytics.bridge.visibility_result``
documents for the Frida/ptrace route. Nothing here can leak more than the
formula computes as visible.

**Scout reports (added 19 September 2026).** FM does not use the explicit
list's percentage alone. Each scouted player also has a report record (see
``read_report_records``) naming the staff member who covers him and carrying
the knowledge level FM actually uses, and the width of every range depends on
that scout's two judging ratings (``read_scout_quality_sum``). With both
read, this reproduces every attribute in FM's own exported profiles for four
real scouted players (47 of 47 ranges, and every attribute FM hides stays
hidden). If a player's record or scout cannot be read, this falls back to the
explicit level and "no report", which can only widen a range -- never narrow
one -- so an unreadable input still fails in the safe direction.

**Still to confirm.** The offset of a scout's two ratings was found by fitting
three scouts to the width brackets those four players imply, not read from a
documented structure; it should be confirmed against the staff profiles in the
game (see ``STAFF_RATING_OFFSET``).
"""

from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from fm_analytics.bridge.fm20_visibility_algorithm import build_visible_observation, select_position_family
from fm_analytics.domain import AttributeObservation
from tools.fm20_discoverability_experiment import PERSON_TYPE_RVAS
from tools.fm20_linux_probe import (
    FM20_4_4_STEAM,
    ProbeError,
    calculate_age,
    decode_fm_date,
    read_exact,
    read_fm_string,
    read_pointer_collection,
    read_u64,
)
from tools.fm20_owned_visible_source import normalize_attribute_byte
from tools.fm20_visibility_trace import ATTRIBUTE_OFFSETS, DISPLAY_ATTRIBUTE_IDS, PLAYER_ATTRIBUTE_BLOCK_OFFSET

# Verified against `fm20_owned_visible_source.py`'s own reader (the same
# offsets that module's docstring calls proven for the owned squad):
# person_address = player_address + 0x1C0, actual_person = person + 0x28.
PERSON_FROM_PLAYER_ADDRESS = 0x1C0
ACTUAL_PERSON_FROM_PERSON = 0x28
POSITION_RATINGS_FROM_PERSON = 0x5C  # person - 0x5C == player_address + 0x164
DATE_OF_BIRTH_OFFSET = 0x1C
KNOWLEDGE_CONTEXT_VECTOR_OFFSET = 0x0
KNOWLEDGE_RECORD_ROW_ID_OFFSET = 0x0
KNOWLEDGE_RECORD_LEVEL_OFFSET = 0x8

# The manager's per-player scout-report records (found 19 September 2026).
# `knowledge context + 0x18` is the manager's Person pointer; a vector of
# report-record pointers sits 0x2a0 below it. Each record is
# {player Person*, staff Person*, club*, date, ..., 4 level bytes}, and the last
# level byte (+0x3f) is the knowledge FM actually used for visibility -- one
# above the explicit list's figure for 19 of 22 scouted players, equal for
# the other 3, and equal to the exact effective knowledge each of four real
# players' FM exports implied.
CONTEXT_MANAGER_PERSON_OFFSET = 0x18
REPORT_VECTOR_FROM_MANAGER_PERSON = 0x2A0
REPORT_STAFF_OFFSET = 0x8
REPORT_LEVEL_OFFSET = 0x3F
STAFF_TYPE_RVA = 0x6D817A8
# Two signed rating bytes on a staff Person, read the way the range-width code
# reads them (RVA 0x15a4c2e: `movsx [obj+0x2c]`, `+0x2d`, each `(b+2)*0.2`
# clamped to 1..20). Only the *sum* matters. Located by fitting three scouts
# to the width brackets four real players imply, then to be confirmed against
# the staff profiles in the game -- see `read_scout_quality_sum`.
STAFF_RATING_OFFSET = -0xB4


class ScoutedAttributesError(RuntimeError):
    """A read-only scouted-attribute pass failed a safety or evidence check."""


@dataclass(frozen=True)
class ScoutedPlayer:
    """One scouted player's visible attributes, computed without calling FM."""

    row_id: int
    player_id: int
    name: str
    age: int
    knowledge: int
    observations: dict[str, AttributeObservation]
    # What the formula was actually given, kept for diagnosis: the effective
    # knowledge (never below ``knowledge``) and the scout-rating sum, or None
    # when no readable report was found for this player.
    effective_knowledge: int = 0
    report_quality_sum: int | None = None


def read_explicit_knowledge(memory_fd: int, context: int) -> dict[int, int]:
    """The manager's ``{RowID, level}`` scouting list -- a plain vector, no calls."""
    begin = read_u64(memory_fd, context + KNOWLEDGE_CONTEXT_VECTOR_OFFSET)
    end = read_u64(memory_fd, context + KNOWLEDGE_CONTEXT_VECTOR_OFFSET + 8)
    if begin == 0 and end == 0:
        return {}
    if end < begin or (end - begin) % 8:
        raise ScoutedAttributesError("manager's explicit-knowledge vector is malformed")
    count = (end - begin) // 8
    if count > 100_000:
        raise ScoutedAttributesError(f"implausible explicit-knowledge record count: {count}")
    knowledge: dict[int, int] = {}
    for index in range(count):
        record = read_u64(memory_fd, begin + index * 8)
        if not record:
            continue
        row_id = struct.unpack(
            "<I", read_exact(memory_fd, record + KNOWLEDGE_RECORD_ROW_ID_OFFSET, 4)
        )[0]
        level = read_exact(memory_fd, record + KNOWLEDGE_RECORD_LEVEL_OFFSET, 1)[0]
        knowledge[row_id] = level
    return knowledge


@dataclass(frozen=True)
class ReportRecord:
    """The manager's scout-report record for one player."""

    level: int
    staff_person: int


def read_report_records(
    memory_fd: int, module_base: int, context: int
) -> dict[int, ReportRecord]:
    """The report record for each player the manager has one for, by RowID.

    Read-only and cheap: the vector is reached from the knowledge context
    already used for the explicit list, with no memory scan. Anything that
    does not look like a report record is skipped rather than guessed at, so
    a layout that differs on another build simply yields no records and the
    caller falls back to the explicit level alone.
    """
    manager_person = read_u64(memory_fd, context + CONTEXT_MANAGER_PERSON_OFFSET)
    if not manager_person:
        return {}
    begin = read_u64(memory_fd, manager_person - REPORT_VECTOR_FROM_MANAGER_PERSON)
    end = read_u64(memory_fd, manager_person - REPORT_VECTOR_FROM_MANAGER_PERSON + 8)
    if not begin or end < begin or (end - begin) % 8 or (end - begin) // 8 > 100_000:
        return {}
    player_types = {module_base + rva for rva in PERSON_TYPE_RVAS}
    staff_type = module_base + STAFF_TYPE_RVA
    records: dict[int, ReportRecord] = {}
    for index in range((end - begin) // 8):
        try:
            record = read_u64(memory_fd, begin + index * 8)
            player = read_u64(memory_fd, record)
            staff = read_u64(memory_fd, record + REPORT_STAFF_OFFSET)
            if read_u64(memory_fd, player) not in player_types:
                continue
            if read_u64(memory_fd, staff) != staff_type:
                continue
            row_id = struct.unpack("<I", read_exact(memory_fd, player + 0x8, 4))[0]
            level = read_exact(memory_fd, record + REPORT_LEVEL_OFFSET, 1)[0]
        except (OSError, ProbeError):
            continue
        if 0 <= level <= 100:
            records[row_id] = ReportRecord(level=level, staff_person=staff)
    return records


def read_scout_quality_sum(memory_fd: int, staff_person: int) -> int | None:
    """The sum of the scout's two rating bytes, as the width code computes it.

    ``None`` when the bytes are not both plausible ratings, so an unreadable
    scout degrades to "no report" -- the widest, safest reading -- instead of
    producing a number FM would not.
    """
    try:
        raw = read_exact(memory_fd, staff_person + STAFF_RATING_OFFSET, 2)
    except (OSError, ProbeError):
        return None
    normalized = [max(1, min(20, (b + 2) // 5)) for b in struct.unpack("<bb", raw)]
    if min(normalized) < 2:  # a real scout is never this poor at both judging skills
        return None
    return sum(normalized)


def resolve_persons_by_row_id(
    memory_fd: int, module_base: int, wanted_row_ids: set[int]
) -> dict[int, int]:
    """Find each RowID's person address by scanning FM's loaded-people list.

    Accepts both known person-type vtables (``PERSON_TYPE_RVAS``) -- the same
    pair the Player Search source reader already accepts -- so a player like
    a player-coach, resolved under the second vtable, is found rather than
    silently skipped.
    """
    people = read_pointer_collection(
        memory_fd,
        module_base,
        FM20_4_4_STEAM.main_address_offset,
        FM20_4_4_STEAM.person_collection_offset,
        FM20_4_4_STEAM.collection_indirection_offset,
    )
    valid_types = {module_base + rva for rva in PERSON_TYPE_RVAS}
    found: dict[int, int] = {}
    for person in people:
        if not person or len(found) == len(wanted_row_ids):
            continue
        try:
            if read_u64(memory_fd, person) not in valid_types:
                continue
            row_id = struct.unpack("<I", read_exact(memory_fd, person + 0x8, 4))[0]
        except (OSError, ProbeError):
            continue
        if row_id in wanted_row_ids and row_id not in found:
            found[row_id] = person
    return found


def _read_visible_attributes_for_person(
    memory_fd: int,
    person: int,
    row_id: int,
    knowledge: int,
    as_of: date,
    report_quality_sum: int | None = None,
) -> tuple[int, dict[str, AttributeObservation]]:
    """One player's full visible attribute sheet, from raw memory to observations.

    Raises ``ProbeError``/``ScoutedAttributesError`` on malformed data (e.g.
    all-zero position ratings, seen for at least one player with an unusual
    person record); the caller decides whether to skip that one player.
    """
    actual_person = person + ACTUAL_PERSON_FROM_PERSON
    player_address = person - PERSON_FROM_PLAYER_ADDRESS
    ratings = list(read_exact(memory_fd, person - POSITION_RATINGS_FROM_PERSON, 15))
    family = select_position_family(ratings)  # raises if ratings are not all 1-20
    dob = decode_fm_date(
        read_exact(memory_fd, actual_person + DATE_OF_BIRTH_OFFSET, 4),
        maximum_year=as_of.year,
    )
    age = calculate_age(dob, as_of)

    observations: dict[str, AttributeObservation] = {}
    for attribute, byte_offset in ATTRIBUTE_OFFSETS.items():
        raw = struct.unpack(
            "<b",
            read_exact(memory_fd, player_address + PLAYER_ATTRIBUTE_BLOCK_OFFSET + byte_offset, 1),
        )[0]
        exact_value = normalize_attribute_byte(raw)
        try:
            observations[attribute] = build_visible_observation(
                attribute=attribute,
                exact_value=exact_value,
                player_row_id=row_id,
                display_attribute_id=DISPLAY_ATTRIBUTE_IDS[attribute],
                position_ratings=ratings,
                age=age,
                effective_knowledge=knowledge,
                report_quality_sum=report_quality_sum,
            )
        except ValueError:
            # Attribute not supported for this position family (e.g. a
            # goalkeeping attribute on an outfield player) -- not a fact
            # about visibility, so it is simply omitted rather than guessed.
            continue
    return age, observations


def capture_scouted_attributes(
    pid: int, module_base: int, context: int, game_date: str
) -> tuple[dict[int, ScoutedPlayer], dict[int, str]]:
    """Every scouted player's visible attributes, plus per-player read issues.

    Returns ``(players, issues)``: ``players`` keyed by player ID (not RowID,
    to match the rest of the scouting feed contract); ``issues`` names any
    player whose record could not be read cleanly, keyed the same way, so one
    unusual player (an all-zero-rated player-coach was seen once) cannot take
    down the whole capture.
    """
    as_of = date.fromisoformat(game_date)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        knowledge = read_explicit_knowledge(fd, context)
        if not knowledge:
            return {}, {}
        persons = resolve_persons_by_row_id(fd, module_base, set(knowledge))
        reports = read_report_records(fd, module_base, context)
        players: dict[int, ScoutedPlayer] = {}
        issues: dict[int, str] = {}
        for row_id, level in knowledge.items():
            person = persons.get(row_id)
            if person is None:
                # Not an error: a scouted player who has left the loaded-people
                # set (e.g. retired, or database-only) simply cannot be read
                # this way. The scouting feed treats an unreadable-but-known
                # RowID as a "dropped from scout reports" case using its own
                # prior-capture comparison, not this function.
                continue
            try:
                player_id = struct.unpack("<i", read_exact(fd, person + 0xC, 4))[0]
            except (OSError, ProbeError):
                continue
            try:
                actual_person = person + ACTUAL_PERSON_FROM_PERSON
                name = f"{read_fm_string(fd, actual_person + 0x30)} {read_fm_string(fd, actual_person + 0x38)}".strip()
                report = reports.get(row_id)
                # FM merges the explicit level with the report's own (see
                # `calculate_effective_knowledge`); the report's is never lower
                # in anything observed, but max() keeps that a guarantee.
                effective = max(level, report.level) if report else level
                quality = read_scout_quality_sum(fd, report.staff_person) if report else None
                age, observations = _read_visible_attributes_for_person(
                    fd, person, row_id, effective, as_of, quality,
                )
            except (OSError, ProbeError, ValueError) as error:
                issues[player_id] = str(error)
                continue
            if not name:
                issues[player_id] = "identity lookup failed for a scouted player"
                continue
            players[player_id] = ScoutedPlayer(
                row_id=row_id, player_id=player_id, name=name, age=age,
                knowledge=level, observations=observations,
                effective_knowledge=effective, report_quality_sum=quality,
            )
        return players, issues
    finally:
        os.close(fd)
