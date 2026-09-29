"""Where FM20 (the pinned build) keeps match data, as byte layouts.

Every offset here was checked against FM's own match screens on two matches
(Concord Rangers 2-2 Hungerford Town, 2 November 2019, and Hampton & Richmond
Borough 1-3 Hungerford Town, 31 August 2019) -- see
``docs/match-analysis-plan.md``. Decoders take bytes already read from FM and
never touch a process, so they can be tested with made-up records.

Only what FM shows the manager is decoded: results, the match stats panel and
each player's match stats. Nothing here reads a hidden attribute.
"""

from __future__ import annotations

import struct
from datetime import date, timedelta
from typing import Any

# Class-table addresses (RVAs) in the pinned build.
GAME_MATCH_STATS = 0x655CA60
FIXTURE_RESULT = 0x6573620

FIXTURE_RESULT_SIZE = 0x80
MATCH_STATS_SIZE = 0xD0
TEAM_BLOCK_SIZE = 0x1D0
PLAYER_RECORD_SIZE = 0xB0
EVENT_SIZE = 0x30
NO_PLAYER = 0xFFFFFFFF
NO_SHIRT = 0xFF
STARTERS = 11

# FIXTURE_RESULT: one per played (or scheduled) match.
RESULT_HOME_TEAM = 0x08
RESULT_AWAY_TEAM = 0x10
RESULT_FIXTURE_NAME = 0x20  # db::FIXTURE_NAME: which competition
RESULT_DATE = 0x4C
RESULT_ATTENDANCE = 0x5C
RESULT_HOME_GOALS = 0x64
RESULT_AWAY_GOALS = 0x69
RESULT_OUTCOME = 0x78  # two bytes; both zero until the match is played

# db::FIXTURE_NAME -> db::COMP, whose names are plain FM strings.
FIXTURE_NAME_ID = 0x08
FIXTURE_NAME_COMP = 0x18
COMP_NAME = 0x58
COMP_SHORT_NAME = 0x60

# GAME_MATCH_STATS: the detail FM keeps for the latest match and any match
# report opened since.
STATS_RESULT = 0x08
STATS_EVENTS = 0x28  # vector of pointers to EVENT_SIZE records
STATS_HOME_BLOCK = 0x58
STATS_AWAY_BLOCK = 0x60

# Team block: FM's match stats panel for one side.
TEAM_FIELDS: tuple[tuple[str, int, str], ...] = (
    ("possession_time", 0x68, "<I"),
    ("goals", 0x122, "<H"),
    ("shots", 0x12C, "<B"),
    ("shots_on_target", 0x12D, "<B"),
    ("clear_cut_chances", 0x165, "<B"),
    ("corners", 0x180, "<B"),
    ("fouls", 0x183, "<B"),
    ("passes_attempted", 0xDA, "<H"),
    ("passes_completed", 0xDC, "<H"),
    ("tackles_attempted", 0xE0, "<H"),
    ("tackles_won", 0xE2, "<H"),
    ("headers_attempted", 0xE4, "<H"),
    ("headers_won", 0xE6, "<H"),
)
TEAM_PLAYERS = 0x198  # vector of pointers to PLAYER_RECORD_SIZE records

# Player record: one player's match stats. `chances_created` sums to the
# team's clear-cut chances in one match and not the other; it is kept, and
# labelled unconfirmed, until an FM screen names it.
PLAYER_ROLE_CODE = 0x08  # FM's role for the position played (one bit per role)
PLAYER_SHORT_ID = 0x10  # person +0x08 in FM's database
PLAYER_DISTANCE = 0x44  # float, metres
PLAYER_RATING = 0x5C  # u16, rating x 100
PLAYER_SHIRT = 0x60
PLAYER_SIDE = 0x61  # 0 home, 1 away
PLAYER_FIELDS: tuple[tuple[str, int], ...] = (
    ("goals", 0x65),
    ("goals_conceded", 0x66),
    ("shots", 0x6A),
    ("shots_on_target", 0x6B),
    ("clear_cut_chances", 0x6E),
    ("chances_created", 0x76),
    ("assists", 0x79),
    ("fouls", 0x7D),
    ("passes_attempted", 0x91),
    ("passes_completed", 0x92),
    ("tackles_attempted", 0x94),
    ("tackles_won", 0x95),
    ("headers_attempted", 0x97),
    ("headers_won", 0x98),
    ("corners_taken", 0x9F),
)

# Timeline event record.
EVENT_MINUTE = 0x28
EVENT_SIDE = 0x29
EVENT_CODE = 0x2B
EVENT_KINDS = {0x01: "goal", 0x24: "assist", 0x2F: "clear_cut_chance"}


def decode_fm_date(raw: bytes) -> date | None:
    """FM's four-byte date: day of year in the low nine bits, then the year."""
    encoded_day, year = struct.unpack("<HH", raw)
    day = encoded_day & 0x01FF
    if not 1 <= day <= 366 or not 1900 <= year <= 2300:
        return None
    return date(year, 1, 1) + timedelta(days=day - 1)


def pointer(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def vector_bounds(data: bytes, offset: int) -> tuple[int, int]:
    """(begin, end) of an MSVC vector stored at `offset`."""
    return struct.unpack_from("<QQ", data, offset)


def decode_fixture_result(record: bytes) -> dict[str, Any]:
    return {
        "home_team": pointer(record, RESULT_HOME_TEAM),
        "away_team": pointer(record, RESULT_AWAY_TEAM),
        "fixture_name": pointer(record, RESULT_FIXTURE_NAME),
        "date": decode_fm_date(record[RESULT_DATE:RESULT_DATE + 4]),
        "attendance": struct.unpack_from("<I", record, RESULT_ATTENDANCE)[0],
        "home_goals": record[RESULT_HOME_GOALS],
        "away_goals": record[RESULT_AWAY_GOALS],
        # Scheduled copies of a fixture carry 0-0 and no outcome.
        "played": record[RESULT_OUTCOME] != 0 or record[RESULT_OUTCOME + 1] != 0,
    }


def decode_team_block(block: bytes) -> dict[str, int]:
    return {name: struct.unpack_from(fmt, block, offset)[0] for name, offset, fmt in TEAM_FIELDS}


def team_block_is_empty(stats: dict[str, int]) -> bool:
    """FM keeps blank copies of a match's stats; they have no possession at all."""
    return stats["possession_time"] == 0


def decode_player_record(record: bytes) -> dict[str, Any] | None:
    """One player's match stats, or None for an empty squad place."""
    short_id = struct.unpack_from("<I", record, PLAYER_SHORT_ID)[0]
    shirt = record[PLAYER_SHIRT]
    if short_id == NO_PLAYER or shirt == NO_SHIRT:
        return None
    distance = struct.unpack_from("<f", record, PLAYER_DISTANCE)[0]
    role_code = struct.unpack_from("<I", record, PLAYER_ROLE_CODE)[0]
    # An unused substitute has no role, has run nowhere and is given FM's
    # default 6.40, which is not a rating he earned.
    played = role_code != 0 or distance > 0
    return {
        "short_id": short_id,
        "role_code": role_code,
        "shirt": shirt,
        "side": "home" if record[PLAYER_SIDE] == 0 else "away",
        "played": played,
        "rating": struct.unpack_from("<H", record, PLAYER_RATING)[0] / 100 if played else None,
        "distance_m": round(distance) if played else 0,
        "stats": {name: record[offset] for name, offset in PLAYER_FIELDS},
    }


def decode_event(record: bytes) -> dict[str, Any]:
    code = record[EVENT_CODE]
    return {
        "minute": record[EVENT_MINUTE],
        "side": "home" if record[EVENT_SIDE] == 0 else "away",
        "kind": EVENT_KINDS.get(code, "other"),
        "code": code,
    }
