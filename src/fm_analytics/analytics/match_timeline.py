"""One match's timeline and shots, as the match page, `fm-matches show` and the exports present them.

Everything here is on FM's own match screens: who scored, how and with whose
assist, who had a clear-cut chance, was booked or had a goal ruled out, and
when; and for every shot, who took it, when, and whether it was going in,
wide or over. A goal's own shot is told from the scorer's other shots by
being on goal nearest the goal's minute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from fm_analytics.analytics.goal_descriptions import GoalDescription, describe_goal
from fm_analytics.analytics.match_breakdowns import ScoreSplit, score_split
from fm_analytics.domain.matches import MatchEvent, MatchRecord, MatchShot

# What the timeline lists, in FM's words. A sending-off always follows its
# second booking or straight red, which already say so; an assist is told
# with its goal; a clear-cut chance with the goal it became.
EVENT_LABELS = {
    "goal": "Goal",
    "penalty": "Penalty scored",
    "own_goal": "Own goal",
    "offside_goal": "Goal ruled out for offside",
    "clear_cut_chance": "Clear-cut chance",
    "yellow_card": "Booked",
    "second_yellow": "Sent off (second booking)",
    "straight_red": "Sent off",
    "sent_off": "Sent off",
}
SHOT_LABELS = {"goal": "Goal", "on_goal": "On goal", "wide": "Wide", "over": "Over"}
GOAL_KINDS = frozenset({"goal", "penalty"})
# A goal's shot is on the match clock within this many minutes of the goal.
GOAL_SHOT_WINDOW = 2
# Nothing FM keeps with a match says a goal came from a corner (see
# goal_descriptions), so this is a guess, and always shown as one: a goal from
# a cross whose assist came from a player who took corners in that match. It
# is wrong when a corner taker crosses in open play (Zebroski's 73′ header v
# Chippenham, 15 September 2020, read off FM's replay as open play), and
# misses a corner whose cross was not the assist. It flags 44 of 121 goals
# from crosses in the save's history (10 October 2026).
CORNER_GUESS = (
    "The cross came from a player who took corners in this match. A corner taker "
    "also crosses in open play, so some of these were not corners."
)


@dataclass(frozen=True)
class TimelineEntry:
    minute: int
    added_time: int
    ours: bool  # whether it counts for us (an own goal counts for the other side)
    kind: str
    label: str
    player: str | None  # None when FM's record names nobody
    assisted_by: str | None = None
    from_clear_cut_chance: bool = False
    how: GoalDescription | None = None  # how a goal (not a penalty) was scored
    possibly_from_a_corner: bool = False  # a guess, CORNER_GUESS
    given_away_by: str | None = None  # a penalty against us: the manager's record of who conceded it

    @property
    def clock(self) -> str:
        """The minute as FM shows it: 45, or 90+2."""
        return f"{self.minute}+{self.added_time}" if self.added_time else str(self.minute)


@dataclass(frozen=True)
class ShotEntry:
    clock: str
    ours: bool
    player: str | None
    outcome: str  # a SHOT_LABELS key
    second: int = 0  # the match clock's second within its minute
    across: float = 0.0  # where it crossed the goal line, metres from the middle of the goal
    up: float = 0.0

    @property
    def label(self) -> str:
        return SHOT_LABELS[self.outcome]


@dataclass(frozen=True)
class SideShots:
    shots: int
    on_goal: int  # goals included
    wide: int
    over: int
    first_half: int
    second_half: int


@dataclass(frozen=True)
class MatchTimeline:
    entries: tuple[TimelineEntry, ...]
    shots: tuple[ShotEntry, ...]
    opponent_formation: str | None
    ours: SideShots | None  # None when the match has no shots recorded
    theirs: SideShots | None
    # Whether these were read with each event's player: a timeline read from
    # the live match alone has goals and chances without names.
    named: bool
    # Shots, chances and goals by the score at the time and by period; None
    # without shots or with goal times missing.
    by_score: ScoreSplit | None = None
    # FM's timeline codes not yet identified, as (clock, ours, code): kept so
    # nothing FM recorded is hidden, though what they mean is not known.
    unidentified: tuple[tuple[str, bool, int], ...] = ()


def _name(match: MatchRecord, side: str, short_id: int | None) -> str | None:
    if short_id is None or match.detail is None:
        return None
    for player in match.detail.players_for(side):
        if player.short_id == short_id:
            return player.label
    return None


def _took_corners(match: MatchRecord, event: MatchEvent) -> bool:
    return any(
        player.short_id == event.player_short_id and player.stat("corners_taken")
        for player in match.detail.players_for(event.side)
    )


def _same_moment(first: MatchEvent, second: MatchEvent) -> bool:
    return (first.side, first.minute, first.added_time) == (second.side, second.minute, second.added_time)


def _entries(
    match: MatchRecord, side: str, given_away: Mapping[tuple[int, int], str]
) -> tuple[TimelineEntry, ...]:
    events = match.detail.events if match.detail else ()
    entries = []
    for index, event in enumerate(events):
        if event.kind not in EVENT_LABELS:
            continue
        nearby = events[max(index - 2, 0):index + 3]
        if event.kind == "clear_cut_chance" and any(
            other.kind in GOAL_KINDS and other.player_short_id == event.player_short_id and _same_moment(event, other)
            for other in nearby
        ):
            continue  # told with the goal it became
        if event.kind == "sent_off" and any(
            other.kind in ("second_yellow", "straight_red") and other.player_short_id == event.player_short_id
            and _same_moment(event, other)
            for other in nearby
        ):
            continue
        assist = None
        assisting = None
        chance = False
        if event.kind in GOAL_KINDS:
            assisting = next((other for other in nearby if other.kind == "assist" and _same_moment(event, other)), None)
            assist = _name(match, assisting.side, assisting.player_short_id) if assisting else None
            chance = any(
                other.kind == "clear_cut_chance" and other.player_short_id == event.player_short_id
                and _same_moment(event, other)
                for other in nearby
            )
        how = describe_goal(event.descriptor) if event.kind == "goal" else None
        counts_for = event.side if event.kind != "own_goal" else ("away" if event.side == "home" else "home")
        entries.append(TimelineEntry(
            minute=event.minute,
            added_time=event.added_time,
            ours=counts_for == side,
            kind=event.kind,
            label=EVENT_LABELS[event.kind],
            player=_name(match, event.side, event.player_short_id),
            assisted_by=assist,
            from_clear_cut_chance=chance,
            how=how,
            possibly_from_a_corner=bool(how and how.how == "cross" and assisting and _took_corners(match, assisting)),
            given_away_by=given_away.get((event.minute, event.added_time)) if event.kind == "penalty" else None,
        ))
    return tuple(entries)


def goal_shots(match: MatchRecord) -> dict[int, MatchEvent]:
    """Which shots (by index) were goals, each with its goal: the scorer's shot on goal nearest its minute."""
    shots = match.detail.shots
    used: dict[int, MatchEvent] = {}
    for event in match.detail.events:
        if event.kind not in GOAL_KINDS or event.player_short_id is None:
            continue
        minute = event.minute + event.added_time
        candidates = [
            (abs(shot.fm_minute - minute), index)
            for index, shot in enumerate(shots)
            if index not in used and shot.side == event.side and shot.player_short_id == event.player_short_id
            and shot.heading == "on_goal" and abs(shot.fm_minute - minute) <= GOAL_SHOT_WINDOW
        ]
        if candidates:
            used[min(candidates)[1]] = event
    return used


def _side_shots(shots: tuple[MatchShot, ...], side: str) -> SideShots:
    own = [shot for shot in shots if shot.side == side]
    return SideShots(
        shots=len(own),
        on_goal=sum(shot.heading == "on_goal" for shot in own),
        wide=sum(shot.heading == "wide" for shot in own),
        over=sum(shot.heading == "over" for shot in own),
        first_half=sum(shot.minute < 45 for shot in own),
        second_half=sum(shot.minute >= 45 for shot in own),
    )


def build_timeline(
    match: MatchRecord, side: str, *, given_away: Mapping[tuple[int, int], str] = {}
) -> MatchTimeline | None:
    """The match's timeline and shots from `side`'s point of view, or None without match detail.

    `given_away` is the manager's record of who conceded each penalty against
    `side`, by (minute, added time); see `analytics.penalty_record`.
    """
    detail = match.detail
    if detail is None:
        return None
    other = "away" if side == "home" else "home"
    goals = goal_shots(match)
    shots = tuple(
        ShotEntry(
            clock=shot.clock(extra_time=match.after_extra_time),
            ours=shot.side == side,
            player=_name(match, shot.side, shot.player_short_id),
            outcome="goal" if index in goals else shot.heading,
            second=shot.second,
            across=shot.across,
            up=shot.up,
        )
        for index, shot in enumerate(detail.shots)
    )
    return MatchTimeline(
        entries=_entries(match, side, given_away),
        shots=shots,
        opponent_formation=detail.formations.get(other),
        ours=_side_shots(detail.shots, side) if detail.shots else None,
        theirs=_side_shots(detail.shots, other) if detail.shots else None,
        named=any(event.player_short_id is not None for event in detail.events),
        by_score=score_split(match, side),
        unidentified=tuple(
            (event.clock, event.side == side, event.code) for event in detail.events if event.kind == "other"
        ),
    )
