"""Matches the manager chose to keep for experiments, and the groups they go in.

A stored match is a copy of one match exactly as FM recorded it, kept because
the manager asked for it (the match just played, often a replay of a fixture
with something changed, or a match from the history). It carries the
manager's label for it (the variant being tried), and any notes and tags.
Groups are the manager's own collections of stored matches; a match can be
in several. Stored by `persistence.experiments`, compared by
`analytics.experiments`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from fm_analytics.domain.matches import MatchRecord, TeamRef

MAX_NAME_LENGTH = 80
MAX_NOTE_LENGTH = 1000
MAX_TAGS = 20


@dataclass(frozen=True)
class MatchLabel:
    """How the manager labels a stored match: the variant it tried, and anything FM can't say."""

    variant: str
    tactic_key: str | None = None  # the catalogue tactic, when one fits
    note: str = ""
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredMatch:
    id: int
    stored_at: str
    club: TeamRef  # the managed club, whose point of view the match is read from
    match: MatchRecord
    label: MatchLabel
    withdrawn: bool = False  # left out of every comparison, but kept
    groups: tuple[str, ...] = ()

    @property
    def side(self) -> str:
        return self.match.side_of(self.club.id)

    @property
    def opponent(self) -> str:
        return self.match.team("away" if self.side == "home" else "home").name


@dataclass(frozen=True)
class MatchGroup:
    name: str
    note: str
    created_at: str
    matches: tuple[StoredMatch, ...] = ()  # oldest first, withdrawn ones included

    @property
    def active(self) -> tuple[StoredMatch, ...]:
        return tuple(match for match in self.matches if not match.withdrawn)


@dataclass(frozen=True)
class Stored:
    match_id: int
    added: bool  # False when this exact match was already stored


def validate_name(name: str, what: str) -> str:
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"{what} needs a name of up to {MAX_NAME_LENGTH} characters")
    return name


def validate_label(label: MatchLabel) -> MatchLabel:
    variant = validate_name(label.variant, "a stored match's label")
    note = (label.note or "").strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"a note is limited to {MAX_NOTE_LENGTH} characters")
    tags = {str(key).strip(): str(value).strip() for key, value in (label.tags or {}).items() if str(key).strip()}
    if len(tags) > MAX_TAGS or any(len(key) > MAX_NAME_LENGTH or len(value) > MAX_NAME_LENGTH for key, value in tags.items()):
        raise ValueError(f"a stored match has at most {MAX_TAGS} tags, each up to {MAX_NAME_LENGTH} characters")
    tactic = label.tactic_key.strip() if label.tactic_key else None
    return MatchLabel(variant, tactic or None, note, tags)
