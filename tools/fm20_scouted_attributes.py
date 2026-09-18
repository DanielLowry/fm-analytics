#!/usr/bin/env python3
"""Read-only visible attributes for every player on the manager's scout list.

Verified 18 September 2026 against three real attributes for a live, scouted
player (Jordan Richards -- Pace, Determination, Passing all matched FM's
displayed ranges exactly, once a scout report was accounted for). See
``docs/scouting-workspace.md`` for the fuller derivation and the remaining
gap this still carries.

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

**Known gap.** FM also raises a scouted attribute's precision when a scout
report exists, via two report-quality fields whose location in memory is not
yet found (see ``docs/phases/03-information-visibility/03.2-fm-representation-research.md``,
around "the ranged-bound path also needs the verified report-quality
fields"). Every call here treats every player as if no report exists, which
the same research proved only ever WIDENS a range relative to FM's true,
report-informed one -- it can misstate as "less certain than FM shows",
never as "more certain" or "visible when FM would hide it". This is a
deliberate, safe default, not a shortcut past the underlying question.
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
                # Report quality is not yet safely readable -- see module
                # docstring. Treating it as absent only ever widens a range
                # relative to FM's true, report-informed one.
                report_quality_sum=None,
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
                age, observations = _read_visible_attributes_for_person(fd, person, row_id, level, as_of)
            except (OSError, ProbeError, ValueError) as error:
                issues[player_id] = str(error)
                continue
            if not name:
                issues[player_id] = "identity lookup failed for a scouted player"
                continue
            players[player_id] = ScoutedPlayer(
                row_id=row_id, player_id=player_id, name=name, age=age,
                knowledge=level, observations=observations,
            )
        return players, issues
    finally:
        os.close(fd)
