"""How scores went: leads held or let slip, and late goals, against what is usual in your matches.

A share of leads not won means little on its own: a side that leads goes on
to win about seven times in ten in most football, so some leads are always
lost. The usual here is your own matches, both sides counted, as the chance
values count both sides' shots: how often a side that led at any point went
on to win, and what share of all the goals came from the 76th minute on.
Your record is then set against it with how often luck alone leaves a gap
that large. Matches with a red card are left out (a sending-off changes the
game more than any instruction), as are extra-time matches and matches whose
goal times are not all known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fm_analytics.analytics.chance_value import at_least
from fm_analytics.analytics.match_analysis import MatchSummary

LATE_MINUTE = 76


def complete_goal_sequence(summary: MatchSummary) -> tuple[tuple[int, str], ...] | None:
    """Every goal's (minute, side it counts for), in order; None unless every goal is timed."""
    match = summary.match
    goals = [incident for incident in match.incidents if incident.is_goal]
    total = summary.goals_for + summary.goals_against
    if len(goals) == total:
        return tuple((goal.minute, goal.side) for goal in goals)
    if match.detail is not None:
        events = [event for event in match.detail.events if event.kind == "goal"]
        if len(events) == total:
            return tuple((event.minute, event.side) for event in events)
    return None


@dataclass(frozen=True)
class GameState:
    matches: int  # with every goal timed, no red card and no extra time
    led: int  # matches you led at some point
    led_won: int
    trailed: int  # matches they led at some point
    trailed_lost: int  # ...and went on to win
    scored: int
    conceded: int
    late_scored: int
    late_conceded: int
    red_card_matches_excluded: int

    @property
    def led_not_won(self) -> int:
        return self.led - self.led_won

    @property
    def usual_hold(self) -> float | None:
        """How often a side that led went on to win in these matches, both sides counted."""
        leads = self.led + self.trailed
        return (self.led_won + self.trailed_lost) / leads if leads else None

    @property
    def usual_late_share(self) -> float | None:
        """The share of all goals in these matches, both sides', from the 76th minute on."""
        goals = self.scored + self.conceded
        return (self.late_scored + self.late_conceded) / goals if goals else None

    @property
    def lead_odds(self) -> float:
        """How often luck alone lets at least this many of your leads go unwon, at the usual rate."""
        hold = self.usual_hold
        return 1.0 if hold is None else at_least(self.led_not_won, self.led, 1.0 - hold)

    @property
    def late_odds(self) -> float:
        """How often luck alone puts at least this many of the goals you concede late, at the usual share."""
        share = self.usual_late_share
        return 1.0 if share is None else at_least(self.late_conceded, self.conceded, share)


def game_state(rows: Sequence[MatchSummary]) -> GameState:
    covered = led = led_won = trailed = trailed_lost = 0
    scored = conceded = late_scored = late_conceded = excluded = 0
    for row in rows:
        if row.match.after_extra_time:
            continue
        if any(incident.kind == "sent_off" for incident in row.match.incidents):
            excluded += 1
            continue
        sequence = complete_goal_sequence(row)
        if sequence is None:
            continue
        covered += 1
        ours = theirs = 0
        we_led = they_led = False
        for minute, side in sequence:
            if side == row.side:
                ours += 1
                late_scored += int(minute >= LATE_MINUTE)
            else:
                theirs += 1
                late_conceded += int(minute >= LATE_MINUTE)
            we_led = we_led or ours > theirs
            they_led = they_led or theirs > ours
        scored += ours
        conceded += theirs
        led += int(we_led)
        led_won += int(we_led and row.result == "W")
        trailed += int(they_led)
        trailed_lost += int(they_led and row.result == "L")
    return GameState(
        covered, led, led_won, trailed, trailed_lost, scored, conceded, late_scored, late_conceded, excluded
    )
