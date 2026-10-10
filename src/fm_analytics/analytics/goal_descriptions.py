"""How a goal was scored, from the eight descriptor bytes FM keeps with it.

FM shows this on its match replays and goal descriptions; the bytes are
stored with each goal (`MatchEvent.descriptor`). Decoded 10 October 2026 from
the manager's reading of eight goals off FM's replays, checked against all
226 goals of the save's history:

- byte 0, bits 1-2, how it was struck: 0 a shot with the foot (Neufville 3′,
  Sharpe 6′ and Chambers 53′ v Chippenham, all right foot; every one of the
  19 penalties too, so which foot is not recorded here), 1 a header (Holden 2′
  at Hayes, Okosieme 60′ v Chippenham), 2 most likely a volley: Ekongo's at
  Hayes was right-footed, so it is not the left foot, and 25 of its 34 goals
  came from crosses, against 24 of 120 shots. No header is from outside the area.
- byte 4, where it was scored from: 2 in the area (all 19 penalties and the
  goals read off FM), 8 on its edge (Chambers's "just inside"), 1 the
  six-yard box (Okosieme's header), 0 outside the area (Ashby's free kick;
  45 goals, never a header, mostly midfielders'). 4 is not known (7 goals)
  and is left out.
- byte 1, flags for how: 0x20 a penalty (all 19, nothing else), 0x40 a cross
  (four read off FM; 55 of its 120 goals are headers), 0x08 a direct free
  kick (Ashby 72′; all 9 from outside the area and without an assist), 0x80
  a shot from distance (27 of 28 from outside the area, so the area says it).
  0x10 is not a set piece, as first thought: Zebroski's header from a cross
  near the corner flag (73′ v Chippenham) was open play. It is not read.

Corners are not told apart from other crosses by anything known here. The
other bytes and bits are not known, and are not read.
"""

from __future__ import annotations

from dataclasses import dataclass

STRIKES = {0: "shot", 1: "header", 2: "volley"}
AREAS = {
    1: "in the six-yard box",
    2: "in the area",
    8: "on the edge of the area",
    0: "from outside the area",
}
PENALTY, CROSS, DIRECT_FREE_KICK = 0x20, 0x40, 0x08


@dataclass(frozen=True)
class GoalDescription:
    strike: str | None  # a STRIKES value
    area: str | None  # an AREAS value
    how: str | None  # "penalty", "direct free kick" or "cross"

    @property
    def text(self) -> str:
        """In words: "Header in the area, from a cross" or "Direct free kick from outside the area"."""
        if self.how in ("penalty", "direct free kick"):
            words = " ".join(part for part in (self.how, self.area) if part)
        else:
            words = " ".join(part for part in (self.strike, self.area) if part)
            if self.how:
                words += f", from a {self.how}" if words else f"from a {self.how}"
        return words[:1].upper() + words[1:]


def describe_goal(descriptor: str | None) -> GoalDescription | None:
    """What FM's descriptor says about how a goal was scored, or None without one."""
    if descriptor is None:
        return None
    raw = bytes.fromhex(descriptor)
    flags = raw[1]
    how = (
        "penalty" if flags & PENALTY
        else "direct free kick" if flags & DIRECT_FREE_KICK
        else "cross" if flags & CROSS
        else None
    )
    return GoalDescription(STRIKES.get((raw[0] >> 1) & 3), AREAS.get(raw[4]), how)
