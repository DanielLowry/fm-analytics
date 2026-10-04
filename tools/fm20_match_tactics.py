"""Research decoder for FM20's archived tactic arrays.

The full role/duty word is preserved here, unlike GAME_MATCH_PLAYER_STATS.
This is NOT yet an appearance duty reader: a chunk can contain many arrays,
and their team, time and player associations still require proof. It must not
be used to choose a tactic by name, proximity, or catalogue similarity.

Layout derived from the pinned executable's serializers at RVAs 0x46712d0
(array), 0x46803b0 (team settings), and 0x46b9350 (slot). Reads existing bytes
only. Instruction payloads are skipped, not exposed in research reports.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


ARRAY_HEADER = b"\x22\x21\x00\xf8\x07"
DUTY_MASK = 0x406E00000
ROLE_MASK = 0x7FFFBF91FDEFF
# The first three labels are grounded by FM's UI getters and known tactics.
# Keep the remaining values raw until their display labels are verified.
DUTY_LABELS = {0x200000: "Defend", 0x400000: "Support", 0x800000: "Attack"}
MAX_STRING_BYTES = 4096
MAX_INSTRUCTIONS = 256
MAX_OVERRIDES = 128
MAX_OVERRIDE_SLOTS = 32


class TacticDecodeError(ValueError):
    """A candidate does not satisfy the pinned serializer's structure."""


@dataclass(frozen=True)
class Slot:
    position: int
    role_and_duty: int

    @property
    def role(self) -> int:
        return self.role_and_duty & ROLE_MASK

    @property
    def duty(self) -> int:
        return self.role_and_duty & DUTY_MASK


@dataclass(frozen=True)
class TacticPrefix:
    offset: int
    name: str
    slots: tuple[Slot, ...]
    overrides: tuple[tuple[int, tuple[Slot, ...]], ...]
    prefix_end: int


class _Reader:
    def __init__(self, data: bytes, offset: int):
        if not 0 <= offset <= len(data):
            raise TacticDecodeError("invalid start offset")
        self.data = data
        self.at = offset

    def take(self, size: int) -> bytes:
        if size < 0 or self.at + size > len(self.data):
            raise TacticDecodeError("truncated tactic")
        value = self.data[self.at:self.at + size]
        self.at += size
        return value

    def expect(self, value: bytes) -> None:
        if self.take(len(value)) != value:
            raise TacticDecodeError("unexpected serializer marker")

    def integer(self, fmt: str) -> int:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def count(self, maximum: int) -> int:
        count = self.integer("<I")
        if count > maximum:
            raise TacticDecodeError("unbounded tactic count")
        return count

    def string(self) -> str:
        try:
            return self.take(self.count(MAX_STRING_BYTES)).decode("utf-8")
        except UnicodeDecodeError as error:
            raise TacticDecodeError("invalid tactic string") from error

    def slot(self) -> Slot:
        self.expect(b"\x21\x00\x02")
        position = self.integer("<I")
        role = self.integer("<Q")
        if role & ~(ROLE_MASK | DUTY_MASK):
            raise TacticDecodeError("unknown role/duty bits")
        self.expect(b"\x01")
        self.take(1)
        for _ in range(self.count(MAX_INSTRUCTIONS)):
            self.take(8)
            self.expect(b"\x01\x02\x02")
            self.take(13)  # two u32 bitmap words, byte value, u32 extra
        self.take(self.count(MAX_INSTRUCTIONS) * 12)
        self.take(2)
        return Slot(position, role)


def decode_prefix(data: bytes, offset: int = 0) -> TacticPrefix:
    """Decode eleven slots and player overrides, without claiming an array end.

    Set pieces and trailing settings follow ``prefix_end``. Their variable
    serialization is deliberately not guessed or used to link adjacent arrays.
    """
    reader = _Reader(data, offset)
    reader.expect(ARRAY_HEADER)
    reader.take(1)
    name = reader.string()
    reader.take(1)
    for _ in range(3):
        reader.string()
    reader.expect(b"\x03")
    reader.take(8)
    reader.expect(b"\x01\x02\x03")
    reader.take(13)
    reader.string()
    reader.take(4)
    slots = tuple(reader.slot() for _ in range(11))
    has_overrides = reader.integer("<B")
    if has_overrides not in (0, 1):
        raise TacticDecodeError("invalid override flag")
    overrides = []
    if has_overrides:
        for _ in range(reader.count(MAX_OVERRIDES)):
            player_id = reader.integer("<I")
            entries = tuple(reader.slot() for _ in range(reader.count(MAX_OVERRIDE_SLOTS)))
            overrides.append((player_id, entries))
    return TacticPrefix(offset, name, slots, tuple(overrides), reader.at)


def candidate_prefixes(data: bytes) -> tuple[TacticPrefix, ...]:
    """Structurally valid candidates, still unlinked to an appearance."""
    found = []
    at = data.find(ARRAY_HEADER)
    while at != -1:
        try:
            found.append(decode_prefix(data, at))
        except TacticDecodeError:
            pass
        at = data.find(ARRAY_HEADER, at + 1)
    return tuple(found)
