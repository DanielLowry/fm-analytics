"""The mentality a match was played in, as the manager records it: where it started and each change.

FM20 does not keep a match's mentality anywhere our reader finds, so this is
the manager's own record (`MatchHistoryStore.record_mentality`, or a stored
experiment match's label), kept apart from everything read from FM so that
reading FM again never touches it.

A change "from 65" takes effect at 65:00 on the match clock. A shot is placed
by its clock time; a goal or clear-cut chance in FM's minute m by the middle
of that minute (m - 0.5). FM's clock runs on through first-half added time,
so a change at half-time ("from 46") is approximate for shots in first-half
added time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

# FM20's tactics screen, most defensive first.
MENTALITIES = ("Very Defensive", "Defensive", "Cautious", "Balanced", "Positive", "Attacking", "Very Attacking")
MAX_CHANGES = 8
LAST_MINUTE = 120  # extra time

_BY_NAME = {name.lower(): name for name in MENTALITIES}


def mentality_name(text: str) -> str:
    """FM's name for a mentality, whatever its case."""
    name = _BY_NAME.get(" ".join(text.split()).lower())
    if name is None:
        raise ValueError(f"{text.strip()!r} is not one of FM's mentalities ({', '.join(MENTALITIES)})")
    return name


@dataclass(frozen=True)
class MentalityPlan:
    """(minute, mentality) pairs: the first from kickoff (0), each later change from its minute."""

    changes: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        if not self.changes or self.changes[0][0] != 0:
            raise ValueError("a mentality record starts with the mentality at kickoff")
        if len(self.changes) > MAX_CHANGES + 1:
            raise ValueError(f"a match can record up to {MAX_CHANGES} mentality changes")
        for (minute, name), (next_minute, next_name) in zip(self.changes, self.changes[1:]):
            if not minute < next_minute <= LAST_MINUTE:
                raise ValueError(f"each change needs a later minute, up to {LAST_MINUTE}")
            if name == next_name:
                raise ValueError(f"the change at {next_minute}′ is to {name}, the mentality already in use")
        for _minute, name in self.changes:
            if name not in MENTALITIES:
                raise ValueError(f"{name!r} is not one of FM's mentalities")

    @classmethod
    def build(cls, start: str, changes: Iterable[tuple[int, str]] = ()) -> MentalityPlan:
        """From the mentality at kickoff and later (minute, mentality) changes, in any order."""
        ordered = sorted(changes)
        if len({minute for minute, _name in ordered}) != len(ordered):
            raise ValueError("two changes are at the same minute")
        return cls(((0, mentality_name(start)), *((minute, mentality_name(name)) for minute, name in ordered)))

    @classmethod
    def parse(cls, text: str) -> MentalityPlan:
        """From text such as "Balanced, 65 Cautious, 80 Positive" (a minute may carry ′ or ')."""
        parts = [part.strip() for part in re.split(r"[,;]", text) if part.strip()]
        if not parts:
            raise ValueError("give the mentality at kickoff, e.g. 'Balanced, 65 Cautious'")
        start, changes = parts[0], []
        if re.match(r"0\s*['′]?\s+\D", start):
            start = re.sub(r"^0\s*['′]?\s+", "", start)
        for part in parts[1:]:
            found = re.fullmatch(r"(\d{1,3})\s*['′]?\s+(.+)", part)
            if found is None:
                raise ValueError(f"a change is a minute then a mentality, e.g. '65 Cautious', not {part!r}")
            changes.append((int(found.group(1)), found.group(2)))
        return cls.build(start, changes)

    @classmethod
    def from_document(cls, document: Sequence[dict[str, Any]]) -> MentalityPlan:
        return cls(tuple((int(item["from"]), str(item["mentality"])) for item in document))

    def to_document(self) -> list[dict[str, Any]]:
        return [{"from": minute, "mentality": name} for minute, name in self.changes]

    @property
    def start(self) -> str:
        return self.changes[0][1]

    def at(self, clock: float) -> str:
        """The mentality in use at `clock` minutes into the match."""
        current = self.start
        for minute, name in self.changes:
            if clock >= minute:
                current = name
        return current

    @property
    def text(self) -> str:
        """"Balanced; Cautious from 65′"."""
        return "; ".join([self.start, *(f"{name} from {minute}′" for minute, name in self.changes[1:])])
