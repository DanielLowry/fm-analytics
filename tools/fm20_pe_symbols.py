#!/usr/bin/env python3
"""Offline pseudo-symbols for the pinned FM20 executable.

This is the static half of the discovery method that found footedness: it turns
a raw address into a function, a function into the vtable slot that holds it,
and a vtable into the class name MSVC left behind in RTTI. Nothing here runs FM
or touches a live process; it only reads the executable file.

The three questions it answers are:

``function``  which function contains this address, using the PE exception
              table rather than guessing at prologues;
``owner``     which vtable slot holds this function, and which class owns that
              vtable, which is what turns "some foot code" into "virtual slot
              0x10 of db::PLAYER";
``key``       where a four-character FM property key appears in the image.
"""

from __future__ import annotations

import argparse
import bisect
import json
import mmap
import struct
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools.fm20_field_workbench import PeImage
from tools.fm20_linux_probe import validate_executable


EXCEPTION_DIRECTORY_INDEX = 3
DATA_DIRECTORY_OFFSET = 112
RUNTIME_FUNCTION_SIZE = 12
UNWIND_CHAIN_FLAG = 0x4
MAX_CHAIN_DEPTH = 8
MAX_VTABLE_SLOTS = 4096


class SymbolError(ValueError):
    """The executable could not be interpreted as a pinned FM20 image."""


@dataclass(frozen=True)
class Function:
    """One function's bounds, plus the chunk the queried address sits in."""

    start_rva: int
    end_rva: int
    chunk_start_rva: int
    chunk_end_rva: int

    def as_dict(self) -> dict[str, str]:
        return {
            "function": hex(self.start_rva),
            "function_end": hex(self.end_rva),
            "chunk": hex(self.chunk_start_rva),
            "chunk_end": hex(self.chunk_end_rva),
        }


@dataclass(frozen=True)
class ClassInfo:
    """An MSVC complete-object locator, resolved to a readable class name."""

    raw_name: str
    name: str
    vtable_rva: int
    object_offset: int

    def as_dict(self) -> dict[str, object]:
        return {
            "class": self.name,
            "raw_name": self.raw_name,
            "vtable": hex(self.vtable_rva),
            "object_offset": hex(self.object_offset),
        }


@dataclass(frozen=True)
class SlotOwner:
    """A vtable slot that holds a given function."""

    vtable_rva: int
    slot_offset: int
    owner: ClassInfo | None

    def as_dict(self) -> dict[str, object]:
        return {
            "vtable": hex(self.vtable_rva),
            "slot": hex(self.slot_offset),
            "class": self.owner.name if self.owner else None,
            "object_offset": hex(self.owner.object_offset) if self.owner else None,
        }


def readable_class_name(raw_name: str) -> str:
    """Turn ``.?AVACTUAL_PLAYER@db@@`` into ``db::ACTUAL_PLAYER``."""
    name = raw_name
    for prefix in (".?AV", ".?AU", ".?AW"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = name.rstrip("@")
    parts = [part for part in name.split("@") if part]
    return "::".join(reversed(parts)) if parts else raw_name


class Fm20Image:
    """Read-only accessor for the pinned executable's static structures."""

    def __init__(self, data: bytes | mmap.mmap) -> None:
        self.data = data
        self.image = PeImage.parse(data)
        self.base = self.image.image_base
        self._functions: tuple[list[int], list[int], list[int]] | None = None

    # -- primitive reads -------------------------------------------------
    def offset(self, rva: int) -> int | None:
        return self.image.rva_to_offset(rva)

    def read_u32(self, rva: int) -> int | None:
        offset = self.offset(rva)
        return struct.unpack_from("<I", self.data, offset)[0] if offset is not None else None

    def read_u64(self, rva: int) -> int | None:
        offset = self.offset(rva)
        return struct.unpack_from("<Q", self.data, offset)[0] if offset is not None else None

    def contains_va(self, address: int) -> bool:
        return self.base <= address < self.base + 0x80000000

    def read_c_string(self, rva: int, limit: int = 256) -> str | None:
        offset = self.offset(rva)
        if offset is None:
            return None
        raw = bytes(self.data[offset:offset + limit]).split(b"\0", 1)[0]
        return raw.decode("ascii", "replace")

    # -- functions -------------------------------------------------------
    def _runtime_functions(self) -> tuple[list[int], list[int], list[int]]:
        if self._functions is not None:
            return self._functions
        pe_offset = struct.unpack_from("<I", self.data, 0x3C)[0]
        directory = pe_offset + 24 + DATA_DIRECTORY_OFFSET + EXCEPTION_DIRECTORY_INDEX * 8
        table_rva, table_size = struct.unpack_from("<II", self.data, directory)
        table_offset = self.offset(table_rva)
        if table_offset is None or table_size < RUNTIME_FUNCTION_SIZE:
            raise SymbolError("executable has no usable exception directory")
        starts: list[int] = []
        ends: list[int] = []
        unwind: list[int] = []
        for index in range(table_size // RUNTIME_FUNCTION_SIZE):
            start, end, info = struct.unpack_from("<III", self.data, table_offset + index * RUNTIME_FUNCTION_SIZE)
            starts.append(start)
            ends.append(end)
            unwind.append(info)
        self._functions = (starts, ends, unwind)
        return self._functions

    @property
    def function_count(self) -> int:
        return len(self._runtime_functions()[0])

    def _primary_index(self, index: int) -> int:
        starts, _ends, unwind = self._runtime_functions()
        for _ in range(MAX_CHAIN_DEPTH):
            info_rva = unwind[index]
            if info_rva & 1:
                break
            offset = self.offset(info_rva & ~1)
            if offset is None:
                break
            version_flags, _prolog, code_count, _frame = struct.unpack_from("<BBBB", self.data, offset)
            if not (version_flags >> 3) & UNWIND_CHAIN_FLAG:
                break
            chained = offset + 4 + ((code_count + 1) & ~1) * 2
            chain_start = struct.unpack_from("<I", self.data, chained)[0]
            candidate = bisect.bisect_right(starts, chain_start) - 1
            if candidate < 0 or starts[candidate] != chain_start:
                break
            index = candidate
        return index

    def function_at(self, rva: int) -> Function | None:
        starts, ends, _unwind = self._runtime_functions()
        index = bisect.bisect_right(starts, rva) - 1
        if index < 0 or not starts[index] <= rva < ends[index]:
            return None
        primary = self._primary_index(index)
        return Function(starts[primary], ends[primary], starts[index], ends[index])

    # -- RTTI ------------------------------------------------------------
    def class_at_vtable(self, vtable_rva: int) -> ClassInfo | None:
        locator = self.read_u64(vtable_rva - 8)
        if not locator or not self.contains_va(locator):
            return None
        offset = self.offset(locator - self.base)
        if offset is None:
            return None
        signature, object_offset, _cd_offset, descriptor_rva = struct.unpack_from("<IIII", self.data, offset)
        if signature != 1:
            return None
        raw_name = self.read_c_string(descriptor_rva + 16)
        if not raw_name or not raw_name.startswith(".?A"):
            return None
        return ClassInfo(raw_name, readable_class_name(raw_name), vtable_rva, object_offset)

    def vtable_start(self, slot_rva: int) -> int | None:
        """Walk back over code pointers to the first slot of the vtable."""
        current = slot_rva
        for _ in range(MAX_VTABLE_SLOTS):
            previous = self.read_u64(current - 8)
            if previous is None:
                return None
            if not self.contains_va(previous) or not self.image.is_executable_rva(previous - self.base):
                return current
            current -= 8
        return None

    def slot_owners(self, function_rva: int, *, limit: int = 16) -> list[SlotOwner]:
        """Find vtable slots holding this function, with the owning class."""
        needle = struct.pack("<Q", self.base + function_rva)
        owners: list[SlotOwner] = []
        for section in self.image.sections:
            if section.characteristics & 0x20000000:
                continue
            start = section.raw_offset
            end = section.raw_offset + section.raw_size
            position = self.data.find(needle, start, end)
            while position >= 0 and len(owners) < limit:
                slot_rva = self.image.offset_to_rva(position)
                if slot_rva is not None:
                    table = self.vtable_start(slot_rva)
                    if table is not None:
                        owners.append(SlotOwner(table, slot_rva - table, self.class_at_vtable(table)))
                position = self.data.find(needle, position + 1, end)
        return owners

    # -- property keys ---------------------------------------------------
    def find_property_key(self, key: str, *, limit: int = 64) -> list[int]:
        """Locate a four-character FM property key, as compared in code."""
        if len(key) != 4 or not key.isascii():
            raise SymbolError("an FM property key is four ASCII characters, such as 'tofP'")
        needle = key.encode("ascii")
        hits: list[int] = []
        position = self.data.find(needle)
        while position >= 0 and len(hits) < limit:
            rva = self.image.offset_to_rva(position)
            if rva is not None and self.image.is_executable_rva(rva):
                hits.append(rva)
            position = self.data.find(needle, position + 1)
        return hits


@contextmanager
def open_image(executable: Path, *, validate: bool = True) -> Iterator[Fm20Image]:
    """Map the executable read-only for the duration of the block."""
    if validate:
        validate_executable(str(executable))
    stream = executable.open("rb")
    try:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    except ValueError as error:
        stream.close()
        raise SymbolError(f"cannot map {executable}: {error}") from error
    try:
        yield Fm20Image(mapped)
    finally:
        mapped.close()
        stream.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--no-validate", action="store_true", help="skip the pinned-build path and size check")
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    function = subparsers.add_parser("function", help="which function contains each address")
    function.add_argument("rva", nargs="+")
    owner = subparsers.add_parser("owner", help="which vtable slot and class hold each function")
    owner.add_argument("rva", nargs="+")
    klass = subparsers.add_parser("class", help="which class owns each vtable")
    klass.add_argument("rva", nargs="+")
    key = subparsers.add_parser("key", help="where a four-character property key appears")
    key.add_argument("key", nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    results: dict[str, object] = {}
    try:
        with open_image(args.executable, validate=not args.no_validate) as image:
            if args.command == "function":
                for value in args.rva:
                    found = image.function_at(int(value, 0))
                    results[value] = found.as_dict() if found else None
            elif args.command == "owner":
                for value in args.rva:
                    results[value] = [owner.as_dict() for owner in image.slot_owners(int(value, 0))]
            elif args.command == "class":
                for value in args.rva:
                    found = image.class_at_vtable(int(value, 0))
                    results[value] = found.as_dict() if found else None
            else:
                for value in args.key:
                    results[value] = [hex(rva) for rva in image.find_property_key(value)]
    except (SymbolError, OSError, ValueError) as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for query, value in results.items():
            print(f"{query}: {json.dumps(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
