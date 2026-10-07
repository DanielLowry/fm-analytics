"""Full stats for past matches, from the archive FM writes to its Temporary folder.

FM keeps full stats in memory only for the latest match and any match report
opened since. It keeps every match's stats in its archive files,
``Temporary/pks_<n>.obs``: a nine-byte header, then one zlib-compressed chunk
per match. Reading a file FM has already written is as safe as reading its
memory: nothing is attached to FM, no FM code runs, nothing is written. See
``docs/match-analysis-plan.md``.

A chunk packs the same player records that live memory holds, field by field
(checked field by field against the live records of all 32 players of the
Concord Rangers match). Each player record starts ``01``, the player's short
ID, four zero bytes, shirt, side and ``02``. Its fixed part is 129 bytes,
followed by one entry per shot. Team totals are the players' sums, apart from
possession, found beside the team's own passing figures (see
``TEAM_RUN``). Every decoded match is checked
(``fm20_match_layout.detail_problems``) before it is kept.
"""

from __future__ import annotations

import re
import struct
import zlib
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator

from tools import fm20_match_layout as layout

# (key, date, home club, away club, home goals, away goals)
Fixture = tuple[Any, date, int, int, int, int]
FILE_HEADER = 9
ARCHIVE_GLOB = "pks_*.obs"
# Packed player record, relative to the short ID.
RECORD = re.compile(rb"\x01(.{4})\x00\x00\x00\x00([\x01-\x63])([\x00\x01])\x02", re.S)
RECORD_FIELDS: tuple[tuple[str, int], ...] = (
    ("goals", 23),
    ("goals_conceded", 24),
    ("shots", 28),
    ("shots_on_target", 29),
    ("shots_blocked", 30),
    ("clear_cut_chances", 32),
    ("assists", 43),
    ("chances_created", 44),
    ("dribbles", 45),
    ("fouls", 47),
    ("passes_attempted", 73),
    ("passes_completed", 74),
    ("key_passes", 75),
    ("tackles_attempted", 78),
    ("tackles_won", 79),
    ("headers_attempted", 81),
    ("headers_won", 82),
    ("corners_taken", 123),
)
SHIRT, SIDE, WENT_OFF, CAME_ON, ROLE_CODE, RATING, DISTANCE = 8, 9, 54, 58, 100, 109, 113
# The live record's starting position (u16, then its centre side) and position
# played (u16); see fm20_match_layout.PLAYER_START_POSITION.
START_POSITION, START_CENTRE_SIDE, POSITION = 11, 13, 96
RECORD_LENGTH = 129
# Team figures summed from the players: shots and chances are not in the
# team's record next to its passing figures; the rest are read from it.
SUMMED = ("goals", "shots", "shots_on_target", "clear_cut_chances", "fouls",
          "passes_attempted", "passes_completed", "tackles_attempted", "tackles_won",
          "headers_attempted", "headers_won")
HEADER_SEARCH = 0x400


def archive_files(temporary: Path) -> list[Path]:
    return sorted(temporary.glob(ARCHIVE_GLOB))


def chunks(path: Path) -> Iterator[bytes]:
    """Each match's decompressed chunk in one archive file."""
    data = path.read_bytes()[FILE_HEADER:]
    while data:
        inflater = zlib.decompressobj()
        try:
            chunk = inflater.decompress(data)
        except zlib.error:
            return  # trailing bytes that are not a chunk
        if not inflater.eof:
            return
        yield chunk
        data = inflater.unused_data


def decode_player(chunk: bytes, at: int) -> dict[str, Any]:
    """One packed player record whose short ID starts at `at`."""
    short_id = struct.unpack_from("<I", chunk, at)[0]
    role_code = struct.unpack_from("<I", chunk, at + ROLE_CODE)[0]
    distance = struct.unpack_from("<f", chunk, at + DISTANCE)[0]
    played = role_code != 0 or distance > 0
    came_on = chunk[at + CAME_ON] or None
    went_off = chunk[at + WENT_OFF] or None
    minutes = max((went_off or layout.MATCH_MINUTES) - (came_on or 0), 0) if played else 0
    rated = played and minutes >= layout.RATED_MINIMUM_MINUTES
    return {
        "at": at,
        "short_id": short_id,
        "role_code": role_code,
        "shirt": chunk[at + SHIRT],
        "side": "home" if chunk[at + SIDE] == 0 else "away",
        "played": played,
        "came_on": came_on if played else None,
        "went_off": went_off if played else None,
        "rating": struct.unpack_from("<H", chunk, at + RATING)[0] / 100 if rated else None,
        "distance_m": round(distance) if played else 0,
        "stats": {name: chunk[at + offset] for name, offset in RECORD_FIELDS},
        **layout.decode_positions(
            struct.unpack_from("<H", chunk, at + START_POSITION)[0],
            chunk[at + START_CENTRE_SIDE],
            struct.unpack_from("<H", chunk, at + POSITION)[0],
            played,
        ),
    }


def players(chunk: bytes) -> list[dict[str, Any]]:
    """Every player record in a chunk, in line-up order per side."""
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for match in RECORD.finditer(chunk):
        at = match.start() + 1
        if at + RECORD_LENGTH > len(chunk):
            continue
        player = decode_player(chunk, at)
        rating = struct.unpack_from("<H", chunk, at + RATING)[0]
        if not 0 < player["short_id"] < 1 << 24 or not (rating == 0 or 100 <= rating <= 1000):
            continue
        key = (player["side"], player["short_id"])
        if key in seen:
            continue
        seen.add(key)
        found.append(player)
    for side in ("home", "away"):
        for order, player in enumerate(p for p in found if p["side"] == side):
            player["order"] = order
            player["started"] = order < layout.STARTERS
    return found


# The team's own panel figures, relative to its passes-attempted field. Found
# by the players' passing and tackling sums, which always equal the team's;
# the team's headers attempted can be one fewer than its players' sum, so the
# team's own figures are read rather than the sums (checked on 26 matches).
TEAM_RUN: tuple[tuple[str, int, str], ...] = (
    ("corners", -7, "<B"),  # the panel's name, as the live layout reads it
    ("fouls", -4, "<B"),
    ("passes_attempted", 0, "<H"),
    ("passes_completed", 2, "<H"),
    ("tackles_attempted", 6, "<H"),
    ("tackles_won", 8, "<H"),
    ("headers_attempted", 10, "<H"),
    ("headers_won", 12, "<H"),
    ("possession_time", 16, "<I"),
)


def team_figures(chunk: bytes, side_players: list[dict[str, Any]]) -> dict[str, int] | None:
    """A side's panel figures: its own team record, plus shots and chances from its players.

    A side's record comes before its players, so the nearest match before the
    first player is taken; the other side's record could have the same totals.
    """
    if not side_players:
        return None
    totals = {key: sum(player["stats"].get(key, 0) for player in side_players) for key in SUMMED}
    anchor = struct.pack("<HH", totals["passes_attempted"], totals["passes_completed"])
    tackles = (totals["tackles_attempted"], totals["tackles_won"])
    first_player = min(player["at"] for player in side_players)
    found = None
    position = chunk.find(anchor)
    while position != -1 and position < first_player:
        if position >= 7 and struct.unpack_from("<2H", chunk, position + 6) == tackles:
            found = position
        position = chunk.find(anchor, position + 1)
    if found is None:
        return None
    for name, offset, fmt in TEAM_RUN:
        totals[name] = struct.unpack_from(fmt, chunk, found + offset)[0]
    return totals


def involves(chunk: bytes, home_club: int, away_club: int) -> bool:
    """Whether the chunk's header names these two clubs, home first."""
    head = chunk[:HEADER_SEARCH]
    home = head.find(b"\x01" + struct.pack("<I", home_club))
    away = head.find(b"\x01" + struct.pack("<I", away_club))
    return home != -1 and away != -1 and home < away


def decode_match(chunk: bytes, home_goals: int, away_goals: int) -> tuple[dict[str, Any] | None, list[str]]:
    """A chunk as the capture's match detail, or None with the reasons it did not add up."""
    found = players(chunk)
    detail: dict[str, Any] = {"players": found, "events": []}
    for side, goals in (("home", home_goals), ("away", away_goals)):
        figures = team_figures(chunk, [p for p in found if p["side"] == side])
        if figures is None:
            return None, [f"{side} possession could not be found beside its passing figures"]
        # Own goals are in the score but credited to no player of that side.
        figures["goals"] = goals
        detail[side] = figures
    problems = layout.detail_problems(detail, home_goals, away_goals)
    return (None, problems) if problems else (detail, [])


def find_chunks(
    temporary: Path, fixtures: Iterable[Fixture]
) -> dict[Any, tuple[bytes, dict[str, Any]]]:
    """(chunk, decoded detail) for each fixture (key, date, home club, away club, home goals, away goals) found.

    A chunk names its two clubs but not its date, and a chunk that adds up to
    one score can add up to another (goals its players did not score read as
    own goals). So when the same clubs met more than once with the same club
    at home, their chunks are told apart by order: one archive file keeps a
    club's matches in the order they were played (all 67 archived matches of
    a season and a half, checked 7 October 2026). That is trusted only when
    one file holds exactly one chunk per meeting and each adds up to its own
    meeting's score. Otherwise a fixture is kept only when exactly one chunk
    names both clubs, home first, and adds up to its score, and that chunk
    fits no other meeting.
    """
    meetings: dict[tuple[int, int], list[Fixture]] = {}
    for fixture in sorted(fixtures, key=lambda fixture: fixture[1]):
        meetings.setdefault((fixture[2], fixture[3]), []).append(fixture)
    named: dict[tuple[int, int], list[tuple[Path, bytes]]] = {pair: [] for pair in meetings}
    for path in archive_files(temporary):
        for chunk in chunks(path):
            for pair, found in named.items():
                if involves(chunk, *pair):
                    found.append((path, chunk))
    kept: dict[Any, tuple[bytes, dict[str, Any]]] = {}
    for pair, games in meetings.items():
        kept.update(_in_order(games, named[pair]) or _unambiguous(games, named[pair]))
    return kept


def _in_order(games: list[Fixture], found: list[tuple[Path, bytes]]) -> dict[Any, tuple[bytes, dict[str, Any]]]:
    """Each meeting paired with the chunk at its place in the order played, or nothing unless all of them add up."""
    if len(games) != len(found) or len({path for path, _chunk in found}) != 1:
        return {}
    paired = {}
    for (key, _date, _home, _away, home_goals, away_goals), (_path, chunk) in zip(games, found):
        detail, _problems = decode_match(chunk, home_goals, away_goals)
        if detail is None:
            return {}
        paired[key] = (chunk, detail)
    return paired


def _unambiguous(games: list[Fixture], found: list[tuple[Path, bytes]]) -> dict[Any, tuple[bytes, dict[str, Any]]]:
    """Each meeting that exactly one chunk fits, when that chunk fits no other meeting."""
    fits: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    for key, _date, _home, _away, home_goals, away_goals in games:
        fits[key] = []
        for index, (_path, chunk) in enumerate(found):
            detail, _problems = decode_match(chunk, home_goals, away_goals)
            if detail is not None:
                fits[key].append((index, detail))
    claims = Counter(index for candidates in fits.values() for index, _detail in candidates)
    return {
        key: (found[candidates[0][0]][1], candidates[0][1])
        for key, candidates in fits.items()
        if len(candidates) == 1 and claims[candidates[0][0]] == 1
    }


def find_matches(
    temporary: Path, fixtures: Iterable[Fixture]
) -> dict[Any, dict[str, Any]]:
    """Full stats for each fixture found, as `find_chunks` finds it."""
    return {key: detail for key, (_chunk, detail) in find_chunks(temporary, fixtures).items()}
