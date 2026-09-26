"""Declarative rule types and categorical opponent-formation hypotheses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class EmphasisRule:
    sign: int
    attributes: tuple[str, ...]
    positions: tuple[str, ...]
    per_step: int = 1
    why: str = ""

    def __post_init__(self) -> None:
        if self.sign not in (-1, 1):
            raise ValueError("an emphasis rule's sign must be -1 or +1")
        if not self.attributes or not self.positions:
            raise ValueError("an emphasis rule needs attributes and positions")
        if not self.why:
            raise ValueError("an emphasis rule must say why")


@dataclass(frozen=True)
class FloorRule:
    sign: int
    floors: tuple[Mapping[str, float], Mapping[str, float]]
    why: str = ""

    def __post_init__(self) -> None:
        if self.sign not in (-1, 1):
            raise ValueError("a floor rule's sign must be -1 or +1")
        if len(self.floors) != 2 or not all(self.floors):
            raise ValueError("a floor rule needs both a one-step and a two-step minimum")
        one, two = self.floors
        if set(one) != set(two):
            raise ValueError("a floor rule's one-step and two-step minimums must cover the same dimensions")
        if any(two[dimension] < value for dimension, value in one.items()):
            raise ValueError("a floor rule's two-step minimum must not ask for less than its one-step")
        if not self.why:
            raise ValueError("a floor rule must say why")


@dataclass(frozen=True)
class OpponentFormation:
    key: str
    label: str
    emphasis: tuple[EmphasisRule, ...] = ()
    floors: tuple[FloorRule, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.label:
            raise ValueError("an opponent formation needs a key and label")


BACK_LINE = ("DL", "DC", "DR", "WBL", "WBR")
DEFENCE_AND_MIDFIELD = ("DC", "DL", "DR", "WBL", "WBR", "DM", "MC")


FORMATION_DEFINITIONS: tuple[OpponentFormation, ...] = (
    OpponentFormation("unknown", "Unknown / other"),
    OpponentFormation(
        "442", "4-4-2",
        emphasis=(
            EmphasisRule(+1, ("marking", "positioning", "anticipation"), ("DC",), why="Two forwards keep both centre-backs occupied."),
            EmphasisRule(+1, ("marking", "tackling", "positioning"), ("DL", "DR", "WBL", "WBR"), why="Wide midfielders make the flanks a standing defensive problem."),
        ),
        floors=(FloorRule(+1, ({"defensiveCover": 5.0, "restDefence": 5.0},) * 2, why="A two-forward, two-wing shape needs central cover and protection behind the flanks."),),
    ),
    OpponentFormation(
        "4231", "4-2-3-1",
        emphasis=(EmphasisRule(+1, ("positioning", "anticipation", "tackling"), ("DC", "DM", "MC"), why="The number ten and lone striker threaten the space between midfield and defence."),),
        floors=(FloorRule(+1, ({"defensiveCover": 5.0},) * 2, why="The central attacking midfielder needs a protected central defensive lane."),),
    ),
    OpponentFormation(
        "433dm", "4-3-3 DM",
        emphasis=(EmphasisRule(+1, ("pace", "anticipation", "positioning"), BACK_LINE, why="Three high forwards stretch and run at the whole back line."),),
        floors=(FloorRule(+1, ({"restDefence": 5.0},) * 2, why="Three high forwards punish attacks that leave no rest defence."),),
    ),
    OpponentFormation(
        "4141", "4-1-4-1",
        emphasis=(EmphasisRule(+1, ("marking", "tackling", "positioning"), ("DL", "DR", "WBL", "WBR"), why="The midfield line naturally supplies threats on both flanks."),),
        floors=(FloorRule(+1, ({"restDefence": 4.5},) * 2, why="Wide midfield transitions require protection behind advancing players."),),
    ),
    OpponentFormation(
        "4312", "4-3-1-2 / diamond",
        emphasis=(EmphasisRule(+1, ("marking", "positioning", "anticipation"), ("DC", "DM", "MC"), why="A number ten behind two forwards concentrates the threat centrally."),),
        floors=(FloorRule(+1, ({"defensiveCover": 5.5},) * 2, why="The central overload needs reliable cover through the middle."),),
    ),
    OpponentFormation(
        "352", "3-5-2",
        emphasis=(EmphasisRule(+1, ("marking", "positioning", "anticipation"), ("DC", "DM"), why="Two forwards occupy the centre while wing-backs stretch the defensive block."),),
        floors=(FloorRule(+1, ({"defensiveCover": 5.0, "width": 2.5},) * 2, why="The system must cover two forwards without conceding the wing-back lanes."),),
    ),
    OpponentFormation(
        "3421", "3-4-2-1",
        emphasis=(EmphasisRule(+1, ("positioning", "anticipation", "tackling"), ("DC", "DM", "MC"), why="Two inside attacking midfielders target the channels around the holding players."),),
        floors=(FloorRule(+1, ({"defensiveCover": 5.0, "restDefence": 5.0},) * 2, why="The two inside creators require both central cover and secure rest defence."),),
    ),
    OpponentFormation(
        "532", "5-3-2",
        emphasis=(EmphasisRule(+1, ("marking", "positioning", "anticipation"), ("DC",), why="Even from a defensive block, two forwards remain available for direct transitions."),),
        floors=(FloorRule(+1, ({"defensiveCover": 5.0},) * 2, why="Attacks still need cover against two forwards left up for transitions."),),
    ),
)
FORMATIONS_BY_KEY = {formation.key: formation for formation in FORMATION_DEFINITIONS}
