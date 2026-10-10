"""How a goal was scored, from the eight descriptor bytes FM keeps with it.

FM shows this on its match replays and goal descriptions; the bytes are
stored with each goal (`MatchEvent.descriptor`). Decoded 10 October 2026 from
the manager's reading of four goals off FM's replays (Neufville 3′ and Sharpe
6′, both right foot from crosses in the area; Chambers 53′, right foot just
inside the area, all v Chippenham; Holden's header from a cross in the area
at Hayes), checked against all 226 goals of the save's history:

- byte 0, bits 1-2, the body part: 0 right foot (120 goals, 3 read off FM),
  1 header (72, 1 read off FM), 2 left foot (34, by elimination). No header
  is from outside the area.
- byte 4, where it was scored from: 2 in the area (all 19 penalties and the
  three goals read off FM), 8 on its edge (Chambers's "just inside"), 1 the
  six-yard box (35, among them 18 headers and 11 centre-backs' goals), 0
  outside the area (45, never a header, mostly midfielders'). 4 is not known
  (7 goals) and is left out.
- byte 1, flags for how: 0x20 a penalty (all 19, nothing else), 0x40 a cross
  (the three read off FM; 55 of its 101 goals are headers), 0x08 a direct
  free kick (all 9 from outside the area and without an assist), 0x10 a set
  piece (with 0x40, mostly headers: a corner or free kick crossed in), 0x80 a
  shot from distance (27 of 28 from outside the area; the area says so).

The other bytes and bits are not known, and are not read.
"""

from __future__ import annotations

from dataclasses import dataclass

BODY_PARTS = {0: "right foot", 1: "header", 2: "left foot"}
AREAS = {
    1: "in the six-yard box",
    2: "in the area",
    8: "on the edge of the area",
    0: "from outside the area",
}
PENALTY, CROSS, DIRECT_FREE_KICK, SET_PIECE = 0x20, 0x40, 0x08, 0x10


@dataclass(frozen=True)
class GoalDescription:
    body: str | None  # a BODY_PARTS value
    area: str | None  # an AREAS value
    how: str | None  # "a penalty", "a direct free kick", "a set-piece cross", "a cross", "a set piece"

    @property
    def text(self) -> str:
        """In words: "Header in the area, from a cross"."""
        where = " ".join(part for part in (self.body, self.area) if part)
        return ", ".join(part for part in (where[:1].upper() + where[1:], f"from {self.how}" if self.how else "") if part)


def describe_goal(descriptor: str | None) -> GoalDescription | None:
    """What FM's descriptor says about how a goal was scored, or None without one."""
    if descriptor is None:
        return None
    raw = bytes.fromhex(descriptor)
    flags = raw[1]
    if flags & PENALTY:
        how = "a penalty"
    elif flags & DIRECT_FREE_KICK:
        how = "a direct free kick"
    elif flags & CROSS:
        how = "a set-piece cross" if flags & SET_PIECE else "a cross"
    elif flags & SET_PIECE:
        how = "a set piece"
    else:
        how = None
    return GoalDescription(BODY_PARTS.get((raw[0] >> 1) & 3), AREAS.get(raw[4]), how)
