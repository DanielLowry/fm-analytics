"""Goals and chances we conceded, one by one and broken down: who delivered, from where, where it was met, and who of ours was there.

From FM's own match record: each goal's scorer, its assist and FM's
description of it (header or shot, from a cross, which area), each clear-cut
chance and who had it, where each shot went, and where every player played,
with substitutions and sendings-off. Two things FM does not record are
guesses from positions, and always say so:

* **near or back post** (`POST_GUESS`), for a goal from a cross from a flank;
* **which of our players were in that zone** (`ZONE_GUESS`): those playing
  the positions facing the delivery and covering where it was finished, at
  that minute.

Set pieces are FM's own where it marks them (a penalty, a direct free kick);
a corner is the match page's guess (`match_timeline.CORNER_GUESS`), and no post
or zone is guessed for any of them: where a set piece is met depends on the
routine, not on positions. A penalty carries who you recorded giving it away.

Flanks are from our side of the pitch: their right winger attacks down our
left. A clear-cut chance FM records as the goal it became is told with the
goal, not again as a chance.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from fm_analytics.analytics.match_timeline import GOAL_SHOT_WINDOW, GoalMoment
from fm_analytics.analytics.opponent_goals import AREA_ROWS, AREA_WORDS, HOW_ROWS, PERIODS
from fm_analytics.analytics.opponent_players import FM_POSITION_ORDER, WIDE, timeline_goals, where
from fm_analytics.analytics.penalty_record import PenaltyKey
from fm_analytics.domain.matches import MatchEvent, MatchRecord, PlayerMatchStats

POST_GUESS = (
    "FM's record does not say where a goal was finished. A goal from a cross from a flank is counted as met "
    "at the near post when the scorer played on the crosser's side, at the back post when he played on the "
    "other side, and in the middle when he played centrally (a lone striker), so it is a guess from positions."
)
ZONE_GUESS = (
    "FM's record does not say where our players were. These are the players we had on the pitch at that minute "
    "in the positions facing the delivery (the full-back and wide midfielder on that flank) and covering where "
    "it was finished (that side's full-back and centre-back, both centre-backs for the middle, and the holding "
    "and central midfielders for a shot from the edge or outside the area), so it is a guess from positions."
)
MIRROR = {"left": "right", "right": "left"}
FULL_BACKS = {"left": ("DL", "WBL"), "right": ("DR", "WBR")}
WIDE_MIDFIELD = {"left": ("ML", "AML"), "right": ("MR", "AMR")}
CENTRE_BACKS = ("DC", "SW")
SCREEN = ("DM", "MC")
SET_PIECES = frozenset({"penalty", "direct_free_kick", "possibly_corner"})
FLANK_ROWS = (("left", "Down our left"), ("right", "Down our right"), ("middle", "From a central position"),
              ("unassisted", "No assist"))
FLANK_WORDS = {"left": "down our left", "right": "down our right", "middle": "from a central position"}
POST_ROWS = (("near", "Near post"), ("back", "Back post"), ("middle", "In the middle"))
CHANCE_OUTCOMES = {"on_goal": "Saved or blocked", "wide": "Wide", "over": "Over"}


@dataclass(frozen=True)
class ZonePlayer:
    """One of ours on the pitch in a position covering the zone."""

    short_id: int
    name: str
    position: str

    @property
    def label(self) -> str:
        return f"{self.name} ({self.position})"


@dataclass(frozen=True)
class ConcededMoment:
    """One goal or clear-cut chance against us."""

    match_key: str
    date: date
    opponent: str
    venue: str  # "H" or "A", ours
    minute: int
    added_time: int
    goal: bool
    kind: str  # "goal", "penalty", "own_goal" or "chance"
    outcome: str  # "Goal", "Penalty", "Own goal", or a chance's: "Saved or blocked", "Wide", "Over", "No shot found"
    score_before: tuple[int, int]  # (us, them) just before it
    taker: str | None  # their scorer or the player who had the chance; ours for an own goal
    taker_position: str | None
    taker_side: str  # where he played, from our side: "left", "right" or "centre"
    how: str | None = None  # FM's description in words: "Header in the six-yard box, from a cross"
    how_key: str | None = None  # an opponent_goals.HOW_ROWS key
    area_key: str | None = None  # an opponent_goals.AREA_ROWS key
    delivered_by: str | None = None  # the assist
    delivery_position: str | None = None
    delivery_flank: str | None = None  # "left", "right" or "middle", from our side
    post: str | None = None  # "near", "back" or "middle": POST_GUESS
    facing_delivery: tuple[ZonePlayer, ...] = ()  # ZONE_GUESS
    in_zone: tuple[ZonePlayer, ...] = ()  # ZONE_GUESS
    given_away_by: str | None = None  # a penalty: who you recorded giving it away
    from_clear_cut_chance: bool = False  # a goal FM also records as a clear-cut chance

    @property
    def clock(self) -> str:
        return f"{self.minute}+{self.added_time}" if self.added_time else str(self.minute)

    @property
    def around(self) -> tuple[ZonePlayer, ...]:
        """Everyone of ours the zone guess names, once each, the delivery's first."""
        seen: dict[int, ZonePlayer] = {}
        for player in (*self.facing_delivery, *self.in_zone):
            seen.setdefault(player.short_id, player)
        return tuple(seen.values())


@dataclass(frozen=True)
class Tally:
    key: str
    label: str
    goals: int
    chances: int = 0


@dataclass(frozen=True)
class ZoneRecord:
    """How often one of our players was in the zone of a goal or chance (ZONE_GUESS)."""

    name: str
    positions: str  # where he was when he was, most often first
    goals: int
    chances: int
    minutes: int  # all his minutes in the selected matches

    @property
    def per90(self) -> float | None:
        return round(90 * self.goals / self.minutes, 2) if self.minutes >= 270 else None


@dataclass(frozen=True)
class ConcededReview:
    matches: int  # with full stats
    without_stats: int  # selected matches whose stats FM's archive did not have
    goals: int
    chances: int  # clear-cut chances that did not become goals
    goals_from_chances: int  # goals FM records as clear-cut chances
    moments: tuple[ConcededMoment, ...]  # latest first
    how: tuple[Tally, ...]
    flanks: tuple[Tally, ...]
    delivered_by: tuple[Tally, ...]  # their position
    posts: tuple[Tally, ...]
    takers: tuple[Tally, ...]  # their position, goals and chances
    areas: tuple[Tally, ...]
    periods: tuple[Tally, ...]
    zone: tuple[ZoneRecord, ...]
    cross_goals_from_a_flank: int = 0  # the near/back post guess's denominator


# -- one match ------------------------------------------------------------


def _ours_on_pitch(match: MatchRecord, side: str, minute: int) -> list[tuple[PlayerMatchStats, str | None, str]]:
    """Our players on the pitch at `minute`, each with his position and side: a player sent off has gone."""
    gone = {
        event.player_short_id: event.minute for event in match.detail.events
        if event.side == side and event.kind == "sent_off" and event.player_short_id is not None
    }
    found = []
    for player in match.detail.players_for(side):
        if not player.played or (player.came_on or 0) > minute:
            continue
        if player.went_off is not None and player.went_off <= minute:
            continue
        if player.short_id in gone and gone[player.short_id] <= minute:
            continue
        position, pitch_side = where(player)
        found.append((player, position, pitch_side))
    return found


def _pick(on_pitch, positions: Iterable[str], sides: Iterable[str] | None = None) -> tuple[ZonePlayer, ...]:
    wanted = tuple(positions)
    picked = [
        (wanted.index(position), ZonePlayer(player.short_id, player.label, position))
        for player, position, pitch_side in on_pitch
        if position in wanted and (sides is None or pitch_side in sides)
    ]
    return tuple(player for _order, player in sorted(picked, key=lambda item: item[0]))


def _finish_zone(on_pitch, side: str, area_key: str | None) -> tuple[ZonePlayer, ...]:
    if side in ("left", "right"):
        zone = _pick(on_pitch, FULL_BACKS[side]) + _pick(on_pitch, CENTRE_BACKS, sides=(side, "centre"))
    else:
        zone = _pick(on_pitch, CENTRE_BACKS)
    if area_key in ("edge", "outside"):
        zone += _pick(on_pitch, SCREEN)
    return zone


def _their(match: MatchRecord, side: str, short_id: int | None) -> tuple[str | None, str | None, str]:
    """A player's name, position and side of the pitch from ours (their right is our left)."""
    player = next((item for item in match.detail.players_for(side) if item.short_id == short_id), None)
    if player is None:
        return None, None, "centre"
    position, pitch_side = where(player)
    return player.label, position, MIRROR.get(pitch_side, pitch_side)


def _how_key(moment: GoalMoment) -> str | None:
    kind = moment.event.kind
    if kind in ("penalty", "own_goal"):
        return kind
    how = moment.how
    if how is None or (how.strike is None and how.area is None and how.how is None):
        return None
    if how.how == "direct free kick":
        return "direct_free_kick"
    if how.how == "cross":
        if moment.possibly_from_a_corner:
            return "possibly_corner"
        return "header_from_cross" if how.strike == "header" else "foot_from_cross"
    return "open_play"


def _chance_outcome(match: MatchRecord, event: MatchEvent) -> str:
    minute = event.minute + event.added_time
    shots = [
        (abs(shot.fm_minute - minute), shot.heading)
        for shot in match.detail.shots
        if shot.side == event.side and shot.player_short_id == event.player_short_id
        and abs(shot.fm_minute - minute) <= GOAL_SHOT_WINDOW
    ]
    return CHANCE_OUTCOMES[min(shots)[1]] if shots else "No shot found"


def _same_moment(first: MatchEvent, second: MatchEvent) -> bool:
    return (first.side, first.minute, first.added_time) == (second.side, second.minute, second.added_time)


def conceded_moments(
    match: MatchRecord, club_id: str, given_away: Mapping[PenaltyKey, int] = {}
) -> tuple[ConcededMoment, ...]:
    """Every goal and clear-cut chance against `club_id` in one match, in match order; empty without full stats."""
    if match.detail is None or not match.detail.players:
        return ()
    ours = match.side_of(club_id)
    theirs = "away" if ours == "home" else "home"
    common = {
        "match_key": match.key, "date": match.date, "opponent": match.team(theirs).name,
        "venue": "H" if ours == "home" else "A",
    }
    moments = timeline_goals(match)
    if moments is None:
        # No timeline that names the goals: FM's result still names each scorer and minute.
        score = [0, 0]
        found = []
        for incident in match.incidents:
            if not incident.is_goal:
                continue
            if incident.side == theirs:
                kind = incident.kind
                found.append(ConcededMoment(
                    **common, minute=incident.minute, added_time=incident.added_time, goal=True, kind=kind,
                    outcome={"goal": "Goal", "penalty": "Penalty", "own_goal": "Own goal"}[kind],
                    score_before=(score[0], score[1]), taker=incident.player, taker_position=None, taker_side="centre",
                ))
            score[0 if incident.side == ours else 1] += 1
        return tuple(found)
    by_event = {id(moment.event): moment for moment in moments}
    events = match.detail.events
    score = [0, 0]
    found = []
    for index, event in enumerate(events):
        moment = by_event.get(id(event))
        if moment is not None:
            if moment.counts_for == theirs:
                found.append(_goal(match, moment, ours, theirs, tuple(score), common, given_away))
            score[0 if moment.counts_for == ours else 1] += 1
            continue
        if event.kind != "clear_cut_chance" or event.side != theirs:
            continue
        nearby = events[max(index - 2, 0):index + 3]
        if any(other.kind in ("goal", "penalty") and other.player_short_id == event.player_short_id
               and _same_moment(event, other) for other in nearby):
            continue  # the goal it became tells it
        name, position, side = _their(match, theirs, event.player_short_id)
        on_pitch = _ours_on_pitch(match, ours, event.minute)
        found.append(ConcededMoment(
            **common, minute=event.minute, added_time=event.added_time, goal=False, kind="chance",
            outcome=_chance_outcome(match, event), score_before=tuple(score), taker=name,
            taker_position=position, taker_side=side, in_zone=_finish_zone(on_pitch, side, None),
        ))
    return tuple(found)


def _goal(match, moment: GoalMoment, ours: str, theirs: str, score, common, given_away) -> ConcededMoment:
    event = moment.event
    kind = event.kind
    if kind == "own_goal":
        name, position, side = (None, None, "centre")
        player = next((item for item in match.detail.players_for(ours) if item.short_id == event.player_short_id), None)
        if player is not None:
            name, (position, side) = player.label, where(player)
    else:
        name, position, side = _their(match, theirs, event.player_short_id)
    how_key = _how_key(moment)
    area_key = next((key for key, words in AREA_WORDS.items() if moment.how and moment.how.area == words), None)
    delivered_by = delivery_position = flank = None
    if moment.assist is not None and kind != "own_goal":
        delivered_by, delivery_position, assist_side = _their(match, theirs, moment.assist.player_short_id)
        flank = assist_side if delivery_position in WIDE and assist_side in MIRROR else "middle"
    post = None
    if how_key in ("header_from_cross", "foot_from_cross") and flank in MIRROR:
        post = "near" if side == flank else "back" if side == MIRROR[flank] else "middle"
    facing = in_zone = ()
    if kind == "goal" and how_key not in SET_PIECES:
        on_pitch = _ours_on_pitch(match, ours, event.minute)
        if flank in MIRROR:
            facing = _pick(on_pitch, FULL_BACKS[flank] + WIDE_MIDFIELD[flank])
        zone_side = {"near": flank, "back": MIRROR.get(flank or "", ""), "middle": "centre"}.get(post or "", side)
        in_zone = _finish_zone(on_pitch, zone_side, area_key)
    given = None
    if kind == "penalty":
        recorded = given_away.get((match.key, event.minute, event.added_time))
        given = next((p.label for p in match.detail.players_for(ours) if p.short_id == recorded), None)
    return ConcededMoment(
        **common, minute=event.minute, added_time=event.added_time, goal=True, kind=kind,
        outcome={"goal": "Goal", "penalty": "Penalty", "own_goal": "Own goal"}[kind],
        score_before=score, taker=name, taker_position=position, taker_side=side,
        how=moment.how.text if moment.how else None, how_key=how_key, area_key=area_key,
        delivered_by=delivered_by, delivery_position=delivery_position, delivery_flank=flank, post=post,
        facing_delivery=facing, in_zone=in_zone, given_away_by=given,
        from_clear_cut_chance=moment.from_clear_cut_chance,
    )


# -- the selection ----------------------------------------------------------


def _period(minute: int) -> str | None:
    return next((f"{start}-{end}" for start, end in PERIODS if start <= minute <= end), None)


def _tallies(rows, goals: Counter, chances: Counter | None = None, *, keep_empty: bool = False) -> tuple[Tally, ...]:
    return tuple(
        Tally(key, label, goals.get(key, 0), (chances or Counter()).get(key, 0))
        for key, label, *_words in rows
        if keep_empty or goals.get(key, 0) or (chances or Counter()).get(key, 0)
    )


def review_conceded(
    matches: Iterable[MatchRecord], club_id: str, given_away: Mapping[PenaltyKey, int] = {}
) -> ConcededReview:
    """Every goal and clear-cut chance conceded in `matches`, and the breakdowns of them."""
    moments: list[ConcededMoment] = []
    minutes: Counter = Counter()
    names: dict[int, str] = {}
    detailed = without = 0
    for match in matches:
        if match.detail is None or not match.detail.players:
            without += 1
            continue
        detailed += 1
        moments.extend(conceded_moments(match, club_id, given_away))
        for player in match.detail.players_for(match.side_of(club_id)):
            minutes[player.short_id] += player.minutes
            names.setdefault(player.short_id, player.label)
    goals = [moment for moment in moments if moment.goal]
    chances = [moment for moment in moments if not moment.goal]
    how = Counter(moment.how_key or "not_described" for moment in goals)
    flanks = Counter(moment.delivery_flank or "unassisted" for moment in goals if moment.kind in ("goal",)
                     and moment.how_key not in SET_PIECES)
    delivered = Counter(moment.delivery_position for moment in goals if moment.delivery_position)
    posts = Counter(moment.post for moment in goals if moment.post)
    takers_goals = Counter(moment.taker_position for moment in goals if moment.taker_position and moment.kind != "own_goal")
    takers_chances = Counter(moment.taker_position for moment in chances if moment.taker_position)
    areas = Counter(moment.area_key for moment in goals if moment.area_key)
    periods_goals = Counter(_period(moment.minute) for moment in goals)
    periods_chances = Counter(_period(moment.minute) for moment in chances)
    zone_goals: Counter = Counter()
    zone_chances: Counter = Counter()
    zone_positions: dict[int, Counter] = defaultdict(Counter)
    for moment in moments:
        for player in moment.around:
            (zone_goals if moment.goal else zone_chances)[player.short_id] += 1
            zone_positions[player.short_id][player.position] += 1
    positions = [(position, position) for position in FM_POSITION_ORDER]
    return ConcededReview(
        matches=detailed,
        without_stats=without,
        goals=len(goals),
        chances=len(chances),
        goals_from_chances=sum(1 for moment in goals if moment.from_clear_cut_chance),
        moments=tuple(sorted(moments, key=lambda item: (item.date, item.minute, item.added_time), reverse=True)),
        how=_tallies(tuple(HOW_ROWS) + (("not_described", "Not described by FM", ""),), how),
        flanks=_tallies(FLANK_ROWS, flanks),
        delivered_by=_tallies(positions, delivered),
        posts=_tallies(POST_ROWS, posts),
        takers=_tallies(positions, takers_goals, takers_chances),
        areas=_tallies(AREA_ROWS, areas),
        periods=_tallies([(f"{start}-{end}", f"{start}-{end}′") for start, end in PERIODS],
                         periods_goals, periods_chances, keep_empty=True),
        zone=tuple(sorted(
            (
                ZoneRecord(
                    names[short_id],
                    ", ".join(position for position, _count in zone_positions[short_id].most_common()),
                    zone_goals[short_id], zone_chances[short_id], minutes[short_id],
                )
                for short_id in set(zone_goals) | set(zone_chances)
            ),
            key=lambda record: (-record.goals, -record.chances, record.name),
        )),
        cross_goals_from_a_flank=sum(posts.values()),
    )
