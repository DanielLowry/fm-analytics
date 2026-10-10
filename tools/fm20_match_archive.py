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
followed by his shots (``decode_shots``). Team totals are the players' sums, apart from
possession, found beside the team's own passing figures (see
``TEAM_RUN``). Every decoded match is checked
(``fm20_match_layout.detail_problems``) before it is kept.

A chunk also holds the match's timeline (``decode_events``): goals, assists,
clear-cut chances, cards and sendings-off, each with its player and minute.

Not read, on purpose: a later list of the match's highlights, which keeps
beside each shot a value between 0 and 1 that FM20 never shows (most likely
its own chance-quality figure), and blocks inside each person's record that
look like internal attribute values. Neither is something a manager can see.
"""

from __future__ import annotations

import math
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


# A player's shots follow his fixed record and end where the next record's
# leading byte is. They are grouped by the zone of the goal mouth they went
# to: per group the zone, a count, that many shots, then a byte not yet known.
# Per shot: where it crossed the goal line, or would have without a save or a
# block, in metres from the middle of the goal (across, then up: inside 3.66
# and under 2.44 is on goal); then the match clock's minute (0 is FM's 1st
# minute) and second; then two bytes not yet known, which are not read.
# Checked 10 October 2026 on 80 matches: of 477 single shots off target 474
# end outside the goal, of 151 goals 150 inside it.
SHOTS_START = RECORD_LENGTH - 1
SHOT_LENGTH = 12
MAX_CLOCK_MINUTE = 130  # after extra time and its added time
MAX_METRES = 100.0


def decode_shots(chunk: bytes, player: dict[str, Any], end: int | None) -> list[dict[str, Any]] | None:
    """A player's shots in the order FM keeps them, or None unless every one decodes.

    `end` is where the next record starts, when the next record is his
    team-mate's; the shots must end exactly there.
    """
    wanted = player["stats"]["shots"]
    at = player["at"] + SHOTS_START
    shots: list[dict[str, Any]] = []
    while len(shots) < wanted:
        if at + 2 > len(chunk):
            return None
        count = chunk[at + 1]
        if not 1 <= count <= wanted - len(shots):
            return None
        at += 2
        for _ in range(count):
            if at + SHOT_LENGTH > len(chunk):
                return None
            across, up = struct.unpack_from("<ff", chunk, at)
            minute, second = chunk[at + 8], chunk[at + 9]
            if not (math.isfinite(across) and math.isfinite(up) and abs(across) < MAX_METRES
                    and -1 < up < MAX_METRES and minute <= MAX_CLOCK_MINUTE and second < 60):
                return None
            shots.append({"minute": minute, "second": second, "across": round(across, 2), "up": round(up, 2)})
            at += SHOT_LENGTH
        at += 1
    if end is not None and at != end:
        return None
    return shots


def match_shots(chunk: bytes, found: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Every shot in the match by the match clock, or None unless every player's decodes.

    One player's shots that do not decode leave the whole match without
    shots, rather than a list that silently misses some.
    """
    ordered = sorted(found, key=lambda player: player["at"])
    shots = []
    for index, player in enumerate(ordered):
        if not player["stats"]["shots"]:
            continue
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        end = following["at"] - 1 if following and following["side"] == player["side"] else None
        decoded = decode_shots(chunk, player, end)
        if decoded is None:
            return None
        shots.extend({"side": player["side"], "playerShortId": player["short_id"], **shot} for shot in decoded)
    return sorted(shots, key=lambda shot: (shot["minute"], shot["second"]))


# The match timeline: a run of 48-byte records, one per event, in match order.
# Each holds 01, the side (0 home), the player's place in his side's line-up
# list, FM's code for the event, a running time (about 243 a minute), FM's
# minute and its added time; a goal's record then carries an unknown u32 and
# the same eight descriptor bytes as db::GOAL_DESCRIPTION (not decoded yet).
# A team's own events (no player) have place 0xff. The run is told from other
# data by those fields agreeing with each other, and FM's count of events (a
# u16 just before the run) must equal its length.
EVENT_LENGTH = 48
EVENT_TICKS_PER_MINUTE = (225, 262)
DESCRIPTOR_AT = 14
NO_PLAYER = 0xFF
# Codes checked against FM's own figures on 80 matches (10 October 2026):
# goals, own goals and penalties add up to every result's score with the
# right scorers; clear-cut chances to the panel's (160 of 160 sides); both
# assist codes, beside a goal, to the players' assists (160); a sending-off (0x05)
# follows each red card in each result's incidents, after a second booking
# (0x0e) only for a player booked (0x26) earlier in the match, otherwise after
# a straight red (0x0f). Bookings run at 2.6 a match. Every other code is kept
# as "other" with its code until it is checked.
EVENT_KINDS = {
    0x01: "goal", 0x02: "own_goal", 0x03: "penalty", 0x05: "sent_off",
    0x0E: "second_yellow", 0x0F: "straight_red", 0x24: "assist", 0x25: "assist",
    0x26: "yellow_card", 0x2F: "clear_cut_chance",
}
GOAL_EVENT_KINDS = {"goal", "penalty"}


def _event_at(chunk: bytes, at: int) -> bool:
    if at < 0 or at + EVENT_LENGTH > len(chunk) or chunk[at] != 1 or chunk[at + 1] > 1:
        return False
    if chunk[at + 2] > 40 and chunk[at + 2] != NO_PLAYER or chunk[at + 3] == 0:
        return False
    ticks = struct.unpack_from("<I", chunk, at + 4)[0]
    minute, added = chunk[at + 8], chunk[at + 9]
    if not 1 <= minute <= MAX_CLOCK_MINUTE or added > 30:
        return False
    low, high = EVENT_TICKS_PER_MINUTE
    return low * (minute - 1) <= ticks <= high * (minute + added) + 600


def _event_run(chunk: bytes) -> list[int]:
    """The longest run of consecutive event records in a chunk."""
    best: list[int] = []
    seen: set[int] = set()
    for at in range(len(chunk) - EVENT_LENGTH):
        if at in seen or not _event_at(chunk, at):
            continue
        start = at
        while _event_at(chunk, start - EVENT_LENGTH):
            start -= EVENT_LENGTH
        run = []
        while _event_at(chunk, start):
            run.append(start)
            seen.add(start)
            start += EVENT_LENGTH
        if len(run) > len(best):
            best = run
    if best and (best[0] < 2 or struct.unpack_from("<H", chunk, best[0] - 2)[0] != len(best)):
        return []
    return best


def decode_events(
    chunk: bytes, found: list[dict[str, Any]], home_goals: int, away_goals: int
) -> list[dict[str, Any]] | None:
    """The match timeline, or None unless its goals give the score and every player event names one.

    An own goal is recorded for the scorer's side and counts for the other.
    """
    line_ups = {
        (0 if player["side"] == "home" else 1, player["order"]): player for player in found
    }
    events = []
    for at in _event_run(chunk):
        code = chunk[at + 3]
        kind = EVENT_KINDS.get(code, "other")
        player = line_ups.get((chunk[at + 1], chunk[at + 2]))
        if player is None and (chunk[at + 2] != NO_PLAYER or kind != "other"):
            return None
        event = {
            "minute": chunk[at + 8],
            "addedTime": chunk[at + 9],
            "side": "home" if chunk[at + 1] == 0 else "away",
            "kind": kind,
            "code": code,
        }
        if player is not None:
            event["playerShortId"] = player["short_id"]
        if kind in GOAL_EVENT_KINDS:
            event["descriptor"] = chunk[at + DESCRIPTOR_AT:at + DESCRIPTOR_AT + 8].hex()
        events.append(event)
    # An assist code with no goal by its side in the same minute (3 in 80
    # matches, one before a penalty) is not an assist FM counts.
    scored = {(event["side"], event["minute"], event["addedTime"]) for event in events if event["kind"] in GOAL_EVENT_KINDS}
    for event in events:
        if event["kind"] == "assist" and (event["side"], event["minute"], event["addedTime"]) not in scored:
            event["kind"] = "other"
    goals = Counter(
        event["side"] if event["kind"] in GOAL_EVENT_KINDS else ("away" if event["side"] == "home" else "home")
        for event in events if event["kind"] in GOAL_EVENT_KINDS or event["kind"] == "own_goal"
    )
    if (goals["home"], goals["away"]) != (home_goals, away_goals):
        return None
    return events


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
    detail: dict[str, Any] = {
        "players": found,
        "events": decode_events(chunk, found, home_goals, away_goals) or [],
        "shots": match_shots(chunk, found) or [],
    }
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
