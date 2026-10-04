#!/usr/bin/env python3
"""Which positions FM shows the manager for a player, decided by FM's own code.

FM keeps every player's 15 position ratings, but shows another club's player
only as well as the manager knows him (03.2, "Position familiarity: accepted
short-term gap": Adam Mann's two Accomplished positions were shown as
Ineffectual). Found 3 October 2026 by offline disassembly of fm.exe 20.4.4:

- FM+0x1fb1910 takes (manager interface, a default, player interface), asks
  the manager's knowledge context about the player's position knowledge (the
  same classification core, FM+0x15a4dc0, the visible-attribute builder uses,
  with fact 0x50) and returns the lowest rating FM will show: 18 (Natural
  only) when nothing is known, 16 when partly known, else the caller's default.
- Player Search's position filter (PERSON_POSITION_FILTER_RULE, evaluator
  FM+0x547c390), GAME_PLAYER slot 0x98 and GAME_SCOUTED_PERSON_TAG's property
  getter all call it, and compare the plain rating against its answer.
- The rating those callers compare is FM's own getter (the person's virtual
  slot 0x728 gives the player record, whose slot 0x40 takes a position
  index), which returned exactly the bytes at ``person - 0x5C`` for all 72
  ordinary players checked live (the owned squad and two rivals), with either
  flag value. It also answers for players who hold a staff role too
  (``ACTUAL_PLAYER_AND_NON_PLAYER``), whose record has a different layout, so
  the league capture reads ratings through it rather than through the offset.

This module runs that function in the sandbox (``tools.fm20_sandbox``: FM's own
code over a read-only copy of its memory; nothing runs inside the game) and
publishes only the positions at or above its answer. The ratings themselves
stay here. A position below FM's answer is one FM shows as Ineffectual, so it
is not offered as playable -- exactly as for the manager looking at FM.
"""

from __future__ import annotations

from tools.fm20_linux_probe import POSITION_CODES, POSITION_ELIGIBILITY_MINIMUM, decode_positions, read_exact
from tools.fm20_sandbox import FmSandbox

POSITION_THRESHOLD_RVA = 0x1FB1910
# The default FM's own Player Search filter passes: "show everything" once a
# player is fully known. Our eligibility cut (10) then applies, as for our squad.
FULL_KNOWLEDGE_DEFAULT = 1
# Ratings sit at the owned-squad reader's proven ``player_address + 0x164``,
# i.e. ``person - 0x5C`` (see fm20_scouting_identity.read_raw_external_positions),
# for an ordinary player only.
RATINGS_FROM_PERSON = -0x5C
PERSON_PLAYER_RECORD_SLOT = 0x728
PLAYER_POSITION_RATING_SLOT = 0x40
PLAYER_PERSON_OFFSET = 0x1C8  # person - interface for an ordinary player
# What FM's function can answer, for labelling only; FM decides, not this table.
KNOWLEDGE_BY_THRESHOLD = {18: "natural-only", 16: "partial", FULL_KNOWLEDGE_DEFAULT: "full"}


class PositionReadError(RuntimeError):
    """A player's visible positions could not be established."""


def read_position_ratings(fd: int, person: int) -> bytes:
    return read_exact(fd, person + RATINGS_FROM_PERSON, len(POSITION_CODES))


def _slot(box: FmSandbox, obj: int, offset: int) -> int:
    return int.from_bytes(box.read(int.from_bytes(box.read(obj, 8), "little") + offset, 8), "little")


def read_ratings_in_sandbox(box: FmSandbox, person: int) -> bytes:
    """The 15 position ratings through FM's own getter, for any kind of player."""
    record = box.call(_slot(box, person, PERSON_PLAYER_RECORD_SLOT), person)
    if not record:
        raise PositionReadError("FM has no player record for this person")
    getter = _slot(box, record, PLAYER_POSITION_RATING_SLOT)
    return bytes(box.call(getter, record, index, 1, 0) & 0xFF for index in range(len(POSITION_CODES)))


def read_position_threshold(box: FmSandbox, manager_interface: int, player_interface: int) -> int:
    """FM's own lowest shown rating for this player, for the active manager."""
    threshold = box.call(
        box.module_base + POSITION_THRESHOLD_RVA, manager_interface, FULL_KNOWLEDGE_DEFAULT, player_interface
    ) & 0xFF
    if threshold not in KNOWLEDGE_BY_THRESHOLD:
        raise PositionReadError(f"FM answered an unrecognised position threshold {threshold}")
    return threshold


def visible_positions(ratings: bytes, threshold: int) -> tuple[str, ...]:
    """The playable positions the manager can see in FM.

    With full knowledge this is exactly the owned squad's rule
    (``decode_positions``). Otherwise only positions FM shows qualify; when it
    shows none at a playable level, the answer is empty -- "position needed",
    never the hidden best rating.
    """
    if len(ratings) != len(POSITION_CODES) or any(not 0 <= value <= 20 for value in ratings):
        raise PositionReadError("position ratings are not 15 values from 0 to 20")
    if threshold <= POSITION_ELIGIBILITY_MINIMUM:
        return decode_positions(ratings)
    return tuple(code for code, value in zip(POSITION_CODES, ratings) if value >= threshold)
