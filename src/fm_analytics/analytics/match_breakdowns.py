"""A run of matches broken down by what FM's timeline and shots record.

- **By the score:** each side's shots, shots on goal, clear-cut chances and
  goals while level, ahead and behind, with the minutes spent in each. A side
  that leads usually sits deeper and faces more shots, so a match where the
  other side scored early is mostly played behind; this is what keeps that
  apart from how a tactic plays.
- **By period:** the same in 15-minute periods.
- **How the goals came:** shot, header or volley; where from; from a cross,
  a direct free kick or a penalty (`goal_descriptions`), for and against.
- **By the formation faced:** results and chances against each formation
  FM names for the opposition.
- **Per player:** bookings and sendings-off, where each player's shots went,
  his clear-cut chances and how many he scored, and his goals by type.

Times: a goal or clear-cut chance is at FM's minute plus its added time, and
changes the score at the end of that minute, so the goal's own shot counts in
the score before it. A shot is at the match clock, which runs on through
first-half added time, so minutes are approximate around half-time. Matches
with a sending-off or extra time are left out of the score and period figures
(numbers on the pitch and the clock change the game); one match's own split
(`score_split`) still shows them. Everything here is on FM's own match screens.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from fm_analytics.analytics.goal_descriptions import describe_goal
from fm_analytics.domain.matches import MATCH_MINUTES, MatchRecord

STATES = ("level", "ahead", "behind")
PERIODS = (
    ("1–15", 0, 15), ("16–30", 15, 30), ("31–45+", 30, 45),
    ("46–60", 45, 60), ("61–75", 60, 75), ("76–90+", 75, 10_000),
)
GOAL_KINDS = frozenset({"goal", "penalty"})


@dataclass
class Tally:
    """Ours and theirs: (shots, on goal, clear-cut chances, goals), and the minutes counted."""

    minutes: float = 0.0
    shots: list[int] = field(default_factory=lambda: [0, 0])
    on_goal: list[int] = field(default_factory=lambda: [0, 0])
    clear_cut_chances: list[int] = field(default_factory=lambda: [0, 0])
    goals: list[int] = field(default_factory=lambda: [0, 0])

    def per_90(self, pair: list[int]) -> tuple[float | None, float | None]:
        if self.minutes < 1:
            return (None, None)
        return tuple(round(90 * value / self.minutes, 2) for value in pair)  # type: ignore[return-value]

    def add(self, other: Tally) -> None:
        self.minutes += other.minutes
        for mine, theirs in ((self.shots, other.shots), (self.on_goal, other.on_goal),
                             (self.clear_cut_chances, other.clear_cut_chances), (self.goals, other.goals)):
            mine[0] += theirs[0]
            mine[1] += theirs[1]


@dataclass(frozen=True)
class ScoreSplit:
    """One match from one side's point of view: tallies by score and by period."""

    by_state: Mapping[str, Tally]
    by_period: Mapping[str, Tally]


def _period(minute: int) -> str:
    """FM's minute (1-based, added time not counted) to its period label."""
    minute = max(minute, 1)
    return next(label for label, start, end in PERIODS if start < minute <= end)


def score_split(match: MatchRecord, side: str) -> ScoreSplit | None:
    """The match by score and by period, or None without its shots or with goal times missing."""
    detail = match.detail
    goals = [incident for incident in match.incidents if incident.is_goal]
    if detail is None or not detail.shots or len(goals) != match.home_goals + match.away_goals:
        return None
    # Time is in minutes played: FM's minute m runs from m - 1 to m, its added
    # time on from there, and a goal changes the score at the end of its minute.
    changes = sorted((incident.minute + incident.added_time, 1 if incident.side == side else -1) for incident in goals)

    def state(at: float) -> str:
        score = sum(change for minute, change in changes if minute <= at)
        return "ahead" if score > 0 else "behind" if score < 0 else "level"

    by_state = {name: Tally() for name in STATES}
    by_period = {label: Tally() for label, _start, _end in PERIODS}
    end = max([MATCH_MINUTES + 3.0, *(shot.minute + 1 + shot.second / 60 for shot in detail.shots),
               *(event.minute + event.added_time + 1.0 for event in detail.events)])
    bounds = [0.0, *(minute for minute, _change in changes), end]
    for start, stop in zip(bounds, bounds[1:]):
        if stop > start:
            by_state[state((start + stop) / 2)].minutes += stop - start
    for label, start, stop in PERIODS:
        by_period[label].minutes = max(0.0, min(stop, end) - start)

    def count(tallies: tuple[Tally, ...], name: str, ours: bool) -> None:
        for tally in tallies:
            getattr(tally, name)[0 if ours else 1] += 1

    for shot in detail.shots:
        where = (by_state[state(shot.minute + shot.second / 60)], by_period[_period(shot.minute + 1)])
        count(where, "shots", shot.side == side)
        if shot.heading == "on_goal":
            count(where, "on_goal", shot.side == side)
    for event in detail.events:
        if event.kind != "clear_cut_chance":
            continue
        minute = event.minute + event.added_time
        count((by_state[state(minute - 0.5)], by_period[_period(event.minute)]), "clear_cut_chances", event.side == side)
    for incident in goals:
        minute = incident.minute + incident.added_time
        count((by_state[state(minute - 0.5)], by_period[_period(incident.minute)]), "goals", incident.side == side)
    return ScoreSplit(by_state, by_period)


@dataclass(frozen=True)
class FormationRecord:
    formation: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    shots: tuple[int, int]
    clear_cut_chances: tuple[int, int]
    with_stats: int  # matches whose shots and chances are counted


@dataclass(frozen=True)
class PlayerEvents:
    """One of our players over the run: what FM's timeline and shots add to his match stats."""

    key: str  # as `match_players.summarise_players` keys him: his FM ID, or his name
    yellow_cards: int = 0
    sent_off: int = 0
    shots_on_goal: int = 0
    shots_wide: int = 0
    shots_over: int = 0
    clear_cut_chances: int = 0
    clear_cut_chances_scored: int = 0
    headers: int = 0  # goals
    volleys: int = 0
    penalties: int = 0
    from_outside_the_area: int = 0


@dataclass(frozen=True)
class Breakdowns:
    by_state: Mapping[str, Tally]
    by_period: Mapping[str, Tally]
    split_matches: int  # matches in the score and period figures
    left_out: Mapping[str, int]  # reason -> matches left out of them
    goals_for: Mapping[str, Counter]  # "how" / "strike" / "area" -> counts
    goals_against: Mapping[str, Counter]
    formations: tuple[FormationRecord, ...]
    players: Mapping[str, PlayerEvents]


def _goal_types(found: dict[str, Counter], kind: str, descriptor: str | None) -> None:
    if kind == "penalty":
        found["how"]["penalty"] += 1
        return
    if kind == "own_goal":
        found["how"]["own goal"] += 1
        return
    how = describe_goal(descriptor)
    if how is None:
        found["how"]["not known"] += 1
        return
    found["how"][how.how or ("from outside the area" if how.area == "from outside the area" else "other open play")] += 1
    found["strike"][how.strike or "not known"] += 1
    found["area"][how.area or "not known"] += 1


def _player_key(match: MatchRecord, side: str, short_id: int | None) -> str | None:
    for player in match.detail.players_for(side) if match.detail else ():
        if player.short_id == short_id:
            return player.player_id or player.label
    return None


def breakdowns(matches: Iterable[MatchRecord], club_id: str) -> Breakdowns:
    matches = tuple(matches)
    by_state = {name: Tally() for name in STATES}
    by_period = {label: Tally() for label, _start, _end in PERIODS}
    split_matches = 0
    left_out: Counter = Counter()
    goals = {"for": defaultdict(Counter), "against": defaultdict(Counter)}
    formations: dict[str, list] = defaultdict(list)
    players: dict[str, Counter] = defaultdict(Counter)
    for match in matches:
        side = match.side_of(club_id)
        other = "away" if side == "home" else "home"
        detail = match.detail
        if any(incident.kind == "sent_off" for incident in match.incidents):
            left_out["a sending-off"] += 1
        elif match.after_extra_time:
            left_out["extra time"] += 1
        else:
            split = score_split(match, side)
            if split is None:
                left_out["no shots or goal times"] += 1
            else:
                split_matches += 1
                for name in STATES:
                    by_state[name].add(split.by_state[name])
                for label in by_period:
                    by_period[label].add(split.by_period[label])
        descriptors = {
            (event.side, event.minute, event.added_time, event.player_short_id): event.descriptor
            for event in (detail.events if detail else ()) if event.kind in GOAL_KINDS
        }
        for incident in match.incidents:
            if incident.is_goal:
                counts_for = incident.side == side
                descriptor = descriptors.get(
                    (incident.side, incident.minute, incident.added_time, incident.player_short_id)
                )
                _goal_types(goals["for" if counts_for else "against"], incident.kind, descriptor)
        formation = detail.formations.get(other) if detail else None
        if formation:
            formations[formation].append(match)
        if detail is None:
            continue
        for shot in detail.shots:
            key = _player_key(match, side, shot.player_short_id) if shot.side == side else None
            if key:
                players[key][f"shots_{'on_goal' if shot.heading == 'on_goal' else shot.heading}"] += 1
        for index, event in enumerate(detail.events):
            if event.side != side:
                continue
            key = _player_key(match, side, event.player_short_id)
            if key is None:
                continue
            if event.kind == "yellow_card":
                players[key]["yellow_cards"] += 1
            elif event.kind == "sent_off":
                players[key]["sent_off"] += 1
            elif event.kind == "clear_cut_chance":
                players[key]["clear_cut_chances"] += 1
                if any(
                    other_event.kind in GOAL_KINDS and other_event.player_short_id == event.player_short_id
                    and (other_event.minute, other_event.added_time) == (event.minute, event.added_time)
                    for other_event in detail.events[index:index + 3]
                ):
                    players[key]["clear_cut_chances_scored"] += 1
            elif event.kind == "penalty":
                players[key]["penalties"] += 1
            elif event.kind == "goal":
                how = describe_goal(event.descriptor)
                if how and how.strike == "header":
                    players[key]["headers"] += 1
                elif how and how.strike == "volley":
                    players[key]["volleys"] += 1
                if how and how.area == "from outside the area":
                    players[key]["from_outside_the_area"] += 1
    return Breakdowns(
        by_state=by_state,
        by_period=by_period,
        split_matches=split_matches,
        left_out=dict(left_out),
        goals_for=dict(goals["for"]),
        goals_against=dict(goals["against"]),
        formations=tuple(sorted(
            (_formation_record(name, games, club_id) for name, games in formations.items()),
            key=lambda record: (-record.played, record.formation),
        )),
        players={key: PlayerEvents(key, **counts) for key, counts in players.items()},
    )


def _formation_record(name: str, games: list[MatchRecord], club_id: str) -> FormationRecord:
    results = Counter()
    goals = [0, 0]
    shots = [0, 0]
    chances = [0, 0]
    with_stats = 0
    for match in games:
        side = match.side_of(club_id)
        other = "away" if side == "home" else "home"
        ours, theirs = match.goals(side), match.goals(other)
        results["won" if ours > theirs else "lost" if ours < theirs else "drawn"] += 1
        goals[0] += ours
        goals[1] += theirs
        if match.detail is not None:
            with_stats += 1
            for index, which in enumerate((side, other)):
                team = match.detail.team(which)
                shots[index] += team.get("shots", 0)
                chances[index] += team.get("clear_cut_chances", 0)
    return FormationRecord(
        name, len(games), results["won"], results["drawn"], results["lost"], goals[0], goals[1],
        tuple(shots), tuple(chances), with_stats,
    )
