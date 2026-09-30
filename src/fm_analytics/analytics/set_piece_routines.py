"""Reviewable player-job profiles for complete set-piece routines.

This module is deliberately data-like: it names the FM instruction, field
zone, purpose, priority, and visible-attribute weights for each mutually
exclusive job. The assignment and uncertainty mechanics live in
``set_pieces.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from fm_analytics.analytics.role_scoring import (
    RoleAttribute,
    RoleDefinition,
    RoleScore,
    score_role,
)
from fm_analytics.domain import Player


SET_PIECE_SCORING_VERSION = "set-piece-v6"

ATTACKING_CORNER_INSTRUCTIONS = (
    "Attack near post",
    "Lurk near post",
    "Attack far post",
    "Lurk far post",
    "Mark keeper",
    "Come short",
    "Go forward",
    "Attack ball from edge of area",
    "Lurk outside edge of area",
    "Stay back if needed",
    "Stay back",
)

DEFENDING_CORNER_INSTRUCTIONS = (
    "Mark near post",
    "Mark far post",
    "Zonally mark 6 yard box near post",
    "Zonally mark 6 yard box centre",
    "Zonally mark 6 yard box far post",
    "Go back",
    "Man mark",
    "Mark tall player",
    "Edge of area",
    "Stay forward",
)

ATTACKING_FREE_KICK_INSTRUCTIONS = (
    "Stay back",
    "Attack ball from edge",
    "Stand with taker",
    "Go forward",
    "Attack near post",
    "Attack far post",
)

DEFENDING_FREE_KICK_INSTRUCTIONS = (
    "Man mark",
    "Go back",
    "Edge of area",
    "Wall",
    "Stay forward",
)


@dataclass(frozen=True)
class RoutineRole:
    """One mutually exclusive player job inside a set-piece routine."""

    key: str
    name: str
    unit: str
    zone: str
    instruction: str
    explanation: str
    attributes: tuple[RoleAttribute, ...]
    priority: int = 50
    goalkeeper: bool = False
    taker_task_key: str | None = None

    def score(self, player: Player) -> RoleScore:
        profile = RoleDefinition(
            key=f"set_piece_routine_{self.key}",
            name=self.name,
            eligible_positions=("set-piece",),
            attributes=self.attributes,
            catalogue_version=SET_PIECE_SCORING_VERSION,
        )
        return score_role(profile, player.attributes)


_AERIAL_ATTACK = (
    RoleAttribute("jumpingReach", 30), RoleAttribute("heading", 25),
    RoleAttribute("anticipation", 15), RoleAttribute("offTheBall", 12),
    RoleAttribute("bravery", 10), RoleAttribute("strength", 8),
)
_AERIAL_DEFENCE = (
    RoleAttribute("jumpingReach", 25), RoleAttribute("heading", 22),
    RoleAttribute("marking", 18), RoleAttribute("positioning", 12),
    RoleAttribute("anticipation", 10), RoleAttribute("strength", 8),
    RoleAttribute("bravery", 5),
)
_REST_DEFENCE = (
    RoleAttribute("positioning", 22), RoleAttribute("anticipation", 18),
    RoleAttribute("pace", 16), RoleAttribute("marking", 15),
    RoleAttribute("tackling", 14), RoleAttribute("decisions", 10),
    RoleAttribute("concentration", 5),
)
_LURK_POST = (
    RoleAttribute("offTheBall", 25), RoleAttribute("anticipation", 22),
    RoleAttribute("finishing", 18), RoleAttribute("firstTouch", 12),
    RoleAttribute("composure", 10), RoleAttribute("agility", 8),
    RoleAttribute("balance", 5),
)
_GO_FORWARD = (
    RoleAttribute("anticipation", 24), RoleAttribute("offTheBall", 24),
    RoleAttribute("finishing", 18), RoleAttribute("composure", 12),
    RoleAttribute("firstTouch", 12), RoleAttribute("acceleration", 10),
)
_ATTACK_EDGE = (
    RoleAttribute("anticipation", 25), RoleAttribute("offTheBall", 22),
    RoleAttribute("acceleration", 18), RoleAttribute("finishing", 15),
    RoleAttribute("firstTouch", 10), RoleAttribute("technique", 10),
)
_LURK_OUTSIDE = (
    RoleAttribute("longShots", 30), RoleAttribute("technique", 20),
    RoleAttribute("anticipation", 18), RoleAttribute("firstTouch", 12),
    RoleAttribute("decisions", 10), RoleAttribute("passing", 10),
)


def _role(
    key: str, name: str, unit: str, zone: str, instruction: str,
    explanation: str, attributes: tuple[RoleAttribute, ...], *,
    priority: int = 50, goalkeeper: bool = False,
    taker_task_key: str | None = None,
) -> RoutineRole:
    return RoutineRole(
        key, name, unit, zone, instruction, explanation, attributes,
        priority, goalkeeper, taker_task_key,
    )


def _attacking_corner_roles(risk: str) -> tuple[RoutineRole, ...]:
    """Use only the player instructions available in FM's attacking-corner UI."""

    taker = _role(
        "corner_taker", "Corner taker", "Delivery", "Ball",
        "Take the set piece", "Best delivery score for this side and curve.",
        (RoleAttribute("corners", 50), RoleAttribute("crossing", 30),
         RoleAttribute("technique", 20)),
        priority=100, taker_task_key="corners",
    )
    attack_near = _role(
        "corner_attack_near", "Near-post runner", "Box attack", "Near post",
        "Attack near post", "Explosive first contact at the near post.",
        _AERIAL_ATTACK, priority=96,
    )
    lurk_near = _role(
        "corner_lurk_near", "Near-post lurker", "Box attack", "Near post",
        "Lurk near post", "Finds space for rebounds and loose balls at the near post.",
        _LURK_POST, priority=82,
    )
    attack_far = _role(
        "corner_attack_far", "Far-post target", "Box attack", "Far post",
        "Attack far post", "Aerial target for deeper delivery and second contact.",
        _AERIAL_ATTACK, priority=94,
    )
    lurk_far = _role(
        "corner_lurk_far", "Far-post lurker", "Box attack", "Far post",
        "Lurk far post", "Finds space for deep knock-downs and loose balls.",
        _LURK_POST, priority=80,
    )
    mark_keeper = _role(
        "corner_mark_keeper", "Goalkeeper screen", "Box attack", "Goalkeeper zone",
        "Mark keeper", "Occupies the goalkeeper without using the primary aerial target.",
        (RoleAttribute("strength", 28), RoleAttribute("bravery", 22),
         RoleAttribute("balance", 18), RoleAttribute("aggression", 14),
         RoleAttribute("offTheBall", 10), RoleAttribute("anticipation", 8)),
        priority=76,
    )
    come_short = _role(
        "corner_come_short", "Short option", "Support", "Short corner channel",
        "Come short", "Offers a short passing option and a second delivery angle.",
        (RoleAttribute("firstTouch", 22), RoleAttribute("technique", 20),
         RoleAttribute("passing", 18), RoleAttribute("decisions", 15),
         RoleAttribute("crossing", 15), RoleAttribute("acceleration", 10)),
        priority=86,
    )
    go_left = _role(
        "corner_go_left", "Left box runner", "Box attack", "Left side of box",
        "Go forward", "Attacks loose balls and second contacts from the left side.",
        _GO_FORWARD, priority=74,
    )
    go_right = _role(
        "corner_go_right", "Right box runner", "Box attack", "Right side of box",
        "Go forward", "Attacks loose balls and second contacts from the right side.",
        _GO_FORWARD, priority=73,
    )
    attack_edge = _role(
        "corner_attack_edge", "Edge runner", "Box attack", "Edge of area",
        "Attack ball from edge of area", "Arrives onto a dropping or cleared ball.",
        _ATTACK_EDGE, priority=90,
    )
    lurk_outside = _role(
        "corner_lurk_outside", "Outside-area option", "Second ball", "Outside edge of area",
        "Lurk outside edge of area", "Collects clearances and threatens from range.",
        _LURK_OUTSIDE, priority=88,
    )
    stay = _role(
        "corner_stay", "Primary cover", "Rest defence", "Halfway line",
        "Stay back", "Best transition defender protects the first counter lane.",
        _REST_DEFENCE, priority=99,
    )
    cover = _role(
        "corner_cover", "Secondary cover", "Rest defence", "Halfway support",
        "Stay back if needed", "Second defender balances the opposite counter lane.",
        _REST_DEFENCE, priority=98,
    )
    wide_cover = _role(
        "corner_wide_cover", "Wide cover", "Rest defence", "Wide outlet",
        "Stay back if needed", "Keeps possession and prevents an exposed flank.",
        (RoleAttribute("decisions", 24), RoleAttribute("passing", 22),
         RoleAttribute("positioning", 18), RoleAttribute("anticipation", 14),
         RoleAttribute("pace", 12), RoleAttribute("firstTouch", 10)),
        priority=84,
    )

    if risk == "secure":
        return (
            taker, attack_near, lurk_near, attack_far, come_short,
            attack_edge, lurk_outside, stay, cover, wide_cover,
        )
    if risk == "balanced":
        return (
            taker, attack_near, attack_far, lurk_far, come_short,
            mark_keeper, attack_edge, lurk_outside, stay, cover,
        )
    return (
        taker, attack_near, lurk_near, attack_far, lurk_far,
        mark_keeper, go_left, go_right, attack_edge, stay,
    )


def _attacking_free_kick_roles(risk: str) -> tuple[RoutineRole, ...]:
    """Use only the player instructions available in FM's attacking-free-kick UI."""

    taker = _role(
        "free_kick_taker", "Free-kick taker", "Delivery", "Ball",
        "Take the set piece", "Best indirect free-kick delivery score for this side and curve.",
        (RoleAttribute("freeKickTaking", 50), RoleAttribute("crossing", 30),
         RoleAttribute("technique", 20)),
        priority=100, taker_task_key="indirect_free_kicks",
    )
    near = _role(
        "free_kick_near", "Near-post runner", "Box attack", "Near post",
        "Attack near post", "Attacks the quickest delivery lane for first contact.",
        _AERIAL_ATTACK, priority=96,
    )
    far = _role(
        "free_kick_far", "Far-post target", "Box attack", "Far post",
        "Attack far post", "Attacks deeper deliveries and far-side knock-downs.",
        _AERIAL_ATTACK, priority=95,
    )
    edge_left = _role(
        "free_kick_edge_left", "Left edge runner", "Box attack", "Left edge of area",
        "Attack ball from edge", "Arrives from the edge onto a dropping delivery.",
        _ATTACK_EDGE, priority=91,
    )
    edge_right = _role(
        "free_kick_edge_right", "Right edge runner", "Box attack", "Right edge of area",
        "Attack ball from edge", "Attacks a dropping delivery from the opposite edge lane.",
        _ATTACK_EDGE, priority=89,
    )
    partner = _role(
        "free_kick_partner", "Taker support", "Support", "With taker",
        "Stand with taker", "Offers a disguised short option and a second delivery angle.",
        (RoleAttribute("firstTouch", 22), RoleAttribute("technique", 20),
         RoleAttribute("passing", 18), RoleAttribute("decisions", 15),
         RoleAttribute("crossing", 15), RoleAttribute("acceleration", 10)),
        priority=87,
    )
    go_left = _role(
        "free_kick_go_left", "Left box runner", "Box attack", "Left side of box",
        "Go forward", "Attacks loose balls and second contacts from the left side.",
        _GO_FORWARD, priority=78,
    )
    go_centre = _role(
        "free_kick_go_centre", "Central box runner", "Box attack", "Central box",
        "Go forward", "Attacks central knock-downs after the first contact.",
        _GO_FORWARD, priority=77,
    )
    go_right = _role(
        "free_kick_go_right", "Right box runner", "Box attack", "Right side of box",
        "Go forward", "Attacks loose balls and second contacts from the right side.",
        _GO_FORWARD, priority=76,
    )
    stay = _role(
        "free_kick_stay", "Primary cover", "Rest defence", "Halfway line",
        "Stay back", "Best transition defender protects the first counter lane.",
        _REST_DEFENCE, priority=99,
    )
    cover = _role(
        "free_kick_cover", "Secondary cover", "Rest defence", "Halfway support",
        "Stay back", "Second defender balances the opposite counter lane.",
        _REST_DEFENCE, priority=98,
    )
    wide_cover = _role(
        "free_kick_wide_cover", "Wide cover", "Rest defence", "Wide outlet",
        "Stay back", "Keeps possession and prevents an exposed flank.",
        (RoleAttribute("decisions", 24), RoleAttribute("passing", 22),
         RoleAttribute("positioning", 18), RoleAttribute("anticipation", 14),
         RoleAttribute("pace", 12), RoleAttribute("firstTouch", 10)),
        priority=85,
    )

    if risk == "secure":
        return (
            taker, near, far, edge_left, partner, go_left, go_right,
            stay, cover, wide_cover,
        )
    if risk == "balanced":
        return (
            taker, near, far, edge_left, partner, go_left, go_centre,
            go_right, stay, cover,
        )
    return (
        taker, near, far, edge_left, edge_right, partner, go_left,
        go_centre, go_right, stay,
    )


def attacking_roles(kind: str, risk: str) -> tuple[RoutineRole, ...]:
    """Return ten outfield jobs for one attacking corner/free-kick routine."""

    if kind == "corner":
        return _attacking_corner_roles(risk)
    return _attacking_free_kick_roles(risk)


def _defending_corner_roles() -> tuple[RoutineRole, ...]:
    """Use the ten outfield instructions available in FM's defending-corner UI."""

    keeper = _role(
        "def_corner_keeper", "Goalkeeper", "Goalkeeper", "Goal line / six-yard box",
        "Defend area", "Claim or clear deliveries and organise the six-yard box.",
        (RoleAttribute("aerialReach", 28), RoleAttribute("commandOfArea", 26),
         RoleAttribute("handling", 16), RoleAttribute("communication", 12),
         RoleAttribute("anticipation", 10), RoleAttribute("decisions", 8)),
        priority=100, goalkeeper=True,
    )
    post_near = _role(
        "def_corner_post_near", "Near-post guard", "Box defence", "Near post",
        "Mark near post", "Protects the fastest delivery route.",
        _AERIAL_DEFENCE, priority=99,
    )
    post_far = _role(
        "def_corner_post_far", "Far-post guard", "Box defence", "Far post",
        "Mark far post", "Protects deep deliveries and recycled crosses.",
        _AERIAL_DEFENCE, priority=98,
    )
    zonal_near = _role(
        "def_corner_zonal_near", "Near-post zonal defender", "Box defence",
        "Six-yard box near post", "Zonally mark 6 yard box near post",
        "Attacks deliveries entering the near side of the six-yard box.",
        _AERIAL_DEFENCE, priority=95,
    )
    zonal_centre = _role(
        "def_corner_zonal_centre", "Central zonal defender", "Box defence",
        "Six-yard box centre", "Zonally mark 6 yard box centre",
        "Attacks deliveries entering the centre of the six-yard box.",
        _AERIAL_DEFENCE, priority=97,
    )
    zonal_far = _role(
        "def_corner_zonal_far", "Far-post zonal defender", "Box defence",
        "Six-yard box far post", "Zonally mark 6 yard box far post",
        "Attacks deliveries entering the far side of the six-yard box.",
        _AERIAL_DEFENCE, priority=94,
    )
    go_back = _role(
        "def_corner_go_back", "Spare box defender", "Box defence", "Penalty spot",
        "Go back", "Reads loose balls and covers a lost marker.",
        _AERIAL_DEFENCE, priority=88,
    )
    man_mark = _role(
        "def_corner_man_mark", "Man marker", "Box defence", "Central danger",
        "Man mark", "Tracks a designated opposition runner.",
        (RoleAttribute("marking", 28), RoleAttribute("anticipation", 20),
         RoleAttribute("positioning", 18), RoleAttribute("concentration", 14),
         RoleAttribute("strength", 10), RoleAttribute("tackling", 10)),
        priority=93,
    )
    mark_tall = _role(
        "def_corner_mark_tall", "Primary aerial marker", "Box defence", "Central danger",
        "Mark tall player", "Takes the opponent's strongest aerial threat.",
        _AERIAL_DEFENCE, priority=96,
    )
    edge = _role(
        "def_corner_edge", "Edge-of-area guard", "Second ball", "Edge of area",
        "Edge of area", "Closes down clearances and late shooters.",
        (RoleAttribute("anticipation", 24), RoleAttribute("positioning", 22),
         RoleAttribute("concentration", 16), RoleAttribute("acceleration", 14),
         RoleAttribute("tackling", 12), RoleAttribute("decisions", 12)),
        priority=86,
    )
    forward = _role(
        "def_corner_forward", "Counter outlet", "Outlet", "Halfway line",
        "Stay forward", "Pins back defenders and gives the clearance a target.",
        (RoleAttribute("pace", 24), RoleAttribute("acceleration", 20),
         RoleAttribute("firstTouch", 16), RoleAttribute("offTheBall", 14),
         RoleAttribute("strength", 12), RoleAttribute("dribbling", 8),
         RoleAttribute("passing", 6)),
        priority=82,
    )
    return (
        keeper, post_near, post_far, zonal_near, zonal_centre, zonal_far,
        go_back, man_mark, mark_tall, edge, forward,
    )


def _defending_free_kick_roles() -> tuple[RoutineRole, ...]:
    """Use only the player instructions available in FM's defending-free-kick UI."""

    keeper = _role(
        "def_free_kick_keeper", "Goalkeeper", "Goalkeeper", "Goal line / six-yard box",
        "Defend area", "Sets the wall, claims deliveries and protects the goal.",
        (RoleAttribute("aerialReach", 28), RoleAttribute("commandOfArea", 26),
         RoleAttribute("handling", 16), RoleAttribute("communication", 12),
         RoleAttribute("anticipation", 10), RoleAttribute("decisions", 8)),
        priority=100, goalkeeper=True,
    )
    wall_attributes = (
        RoleAttribute("bravery", 25), RoleAttribute("positioning", 20),
        RoleAttribute("anticipation", 18), RoleAttribute("jumpingReach", 12),
        RoleAttribute("balance", 10), RoleAttribute("concentration", 10),
        RoleAttribute("strength", 5),
    )
    marking_attributes = (
        RoleAttribute("marking", 28), RoleAttribute("anticipation", 20),
        RoleAttribute("positioning", 18), RoleAttribute("concentration", 14),
        RoleAttribute("strength", 10), RoleAttribute("tackling", 10),
    )
    edge_attributes = (
        RoleAttribute("anticipation", 24), RoleAttribute("positioning", 22),
        RoleAttribute("concentration", 16), RoleAttribute("acceleration", 14),
        RoleAttribute("tackling", 12), RoleAttribute("decisions", 12),
    )
    outlet_attributes = (
        RoleAttribute("pace", 24), RoleAttribute("acceleration", 20),
        RoleAttribute("firstTouch", 16), RoleAttribute("offTheBall", 14),
        RoleAttribute("strength", 12), RoleAttribute("dribbling", 8),
        RoleAttribute("passing", 6),
    )
    return (
        keeper,
        _role(
            "def_free_kick_wall_left", "Left wall player", "Wall", "Left of wall",
            "Wall", "Blocks the direct route to the near side of goal.",
            wall_attributes, priority=99,
        ),
        _role(
            "def_free_kick_wall_centre", "Central wall player", "Wall", "Centre of wall",
            "Wall", "Holds the centre of the wall against a direct shot.",
            wall_attributes, priority=98,
        ),
        _role(
            "def_free_kick_wall_right", "Right wall player", "Wall", "Right of wall",
            "Wall", "Blocks the direct route to the far side of goal.",
            wall_attributes, priority=97,
        ),
        _role(
            "def_free_kick_mark_1", "Primary man marker", "Box defence", "Primary runner",
            "Man mark", "Tracks the opposition's most dangerous runner.",
            marking_attributes, priority=96,
        ),
        _role(
            "def_free_kick_mark_2", "Secondary man marker", "Box defence", "Second runner",
            "Man mark", "Tracks the second attacking runner into the box.",
            marking_attributes, priority=94,
        ),
        _role(
            "def_free_kick_mark_3", "Third man marker", "Box defence", "Third runner",
            "Man mark", "Tracks another runner without weakening the wall.",
            marking_attributes, priority=92,
        ),
        _role(
            "def_free_kick_back_1", "Primary covering defender", "Box defence", "Central box",
            "Go back", "Attacks the first delivery and covers a lost marker.",
            _AERIAL_DEFENCE, priority=95,
        ),
        _role(
            "def_free_kick_back_2", "Secondary covering defender", "Box defence", "Deep box",
            "Go back", "Protects the deeper delivery and the second contact.",
            _AERIAL_DEFENCE, priority=90,
        ),
        _role(
            "def_free_kick_edge", "Edge-of-area guard", "Second ball", "Edge of area",
            "Edge of area", "Closes down clearances and late shooters.",
            edge_attributes, priority=88,
        ),
        _role(
            "def_free_kick_forward", "Counter outlet", "Outlet", "Halfway line",
            "Stay forward", "Pins back defenders and gives the clearance a target.",
            outlet_attributes, priority=84,
        ),
    )


def defensive_roles(kind: str) -> tuple[RoutineRole, ...]:
    """Return the goalkeeper and ten outfield defensive jobs."""

    if kind == "corner":
        return _defending_corner_roles()
    return _defending_free_kick_roles()
