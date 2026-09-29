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


SET_PIECE_SCORING_VERSION = "set-piece-v4"

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


def attacking_roles(kind: str, risk: str) -> tuple[RoutineRole, ...]:
    """Return ten outfield jobs for one attacking corner/free-kick routine."""

    if kind == "corner":
        return _attacking_corner_roles(risk)

    task_key = "indirect_free_kicks"
    delivery_name = "Free-kick taker"
    roles = [
        _role(
            f"{kind}_taker", delivery_name, "Delivery", "Ball",
            "Take the set piece", "Best delivery score for this side and curve.",
            (RoleAttribute("corners", 50), RoleAttribute("crossing", 30), RoleAttribute("technique", 20)),
            priority=100, taker_task_key=task_key,
        ),
        _role(
            f"{kind}_near", "Near-post runner", "Box attack", "Near post",
            "Attack near post", "Explosive first contact at the near post.",
            _AERIAL_ATTACK, priority=96,
        ),
        _role(
            f"{kind}_far", "Far-post target", "Box attack", "Far post",
            "Attack far post", "Aerial target for deeper delivery and second contact.",
            _AERIAL_ATTACK, priority=94,
        ),
        _role(
            f"{kind}_central", "Central target", "Box attack", "Six-yard centre",
            "Attack ball from centre", "Strong central contact and loose-ball threat.",
            _AERIAL_ATTACK, priority=92,
        ),
        _role(
            f"{kind}_edge", "Edge-of-box shooter", "Second ball", "Penalty-area edge",
            "Lurk outside area", "Collect clearances and threaten from range.",
            (RoleAttribute("longShots", 30), RoleAttribute("technique", 20), RoleAttribute("anticipation", 18), RoleAttribute("firstTouch", 12), RoleAttribute("decisions", 10), RoleAttribute("passing", 10)),
            priority=88,
        ),
        _role(
            f"{kind}_short", "Short option", "Support", "Short channel",
            "Come short", "Protects against a blocked delivery and enables a two-player routine.",
            (RoleAttribute("firstTouch", 22), RoleAttribute("technique", 20), RoleAttribute("passing", 18), RoleAttribute("decisions", 15), RoleAttribute("crossing", 15), RoleAttribute("acceleration", 10)),
            priority=86,
        ),
        _role(
            f"{kind}_stay", "Primary cover", "Rest defence", "Halfway line",
            "Stay back", "Best transition defender protects the first counter lane.",
            _REST_DEFENCE, priority=99,
        ),
    ]
    if risk != "aggressive":
        roles.append(_role(
            f"{kind}_cover", "Secondary cover", "Rest defence", "Halfway support",
            "Stay back if needed", "Second defender balances the opposite counter lane.",
            _REST_DEFENCE, priority=98,
        ))
    if risk == "secure":
        roles.extend((
            _role(
                f"{kind}_wide_recycle", "Wide recycler", "Rest defence", "Wide outlet",
                "Stay back if needed", "Keeps possession and prevents an exposed flank.",
                (RoleAttribute("decisions", 24), RoleAttribute("passing", 22), RoleAttribute("positioning", 18), RoleAttribute("anticipation", 14), RoleAttribute("pace", 12), RoleAttribute("firstTouch", 10)),
                priority=84,
            ),
            _role(
                f"{kind}_late", "Late box runner", "Second ball", "Penalty spot",
                "Go forward", "Arrives after the first contact rather than crowding it.",
                (RoleAttribute("anticipation", 24), RoleAttribute("offTheBall", 24), RoleAttribute("finishing", 18), RoleAttribute("composure", 12), RoleAttribute("firstTouch", 12), RoleAttribute("acceleration", 10)),
                priority=72,
            ),
        ))
    else:
        roles.extend((
            _role(
                f"{kind}_screen", "Goalkeeper screen", "Box attack", "Goalkeeper zone",
                "Mark keeper", "Occupies the goalkeeper without using the primary aerial target.",
                (RoleAttribute("strength", 28), RoleAttribute("bravery", 22), RoleAttribute("balance", 18), RoleAttribute("aggression", 14), RoleAttribute("offTheBall", 10), RoleAttribute("anticipation", 8)),
                priority=76,
            ),
            _role(
                f"{kind}_late", "Late box runner", "Second ball", "Penalty spot",
                "Go forward", "Arrives after the first contact rather than crowding it.",
                (RoleAttribute("anticipation", 24), RoleAttribute("offTheBall", 24), RoleAttribute("finishing", 18), RoleAttribute("composure", 12), RoleAttribute("firstTouch", 12), RoleAttribute("acceleration", 10)),
                priority=74,
            ),
        ))
    if risk == "aggressive":
        roles.append(_role(
            f"{kind}_rebound", "Rebound attacker", "Box attack", "Far-side six-yard box",
            "Go forward", "Attacks knock-downs and goalkeeper spills.",
            (RoleAttribute("anticipation", 28), RoleAttribute("finishing", 24), RoleAttribute("offTheBall", 20), RoleAttribute("composure", 14), RoleAttribute("acceleration", 8), RoleAttribute("bravery", 6)),
            priority=70,
        ))
    return tuple(roles)


def defensive_roles(kind: str) -> tuple[RoutineRole, ...]:
    """Return the goalkeeper and ten outfield defensive jobs."""

    keeper = _role(
        f"def_{kind}_keeper", "Goalkeeper", "Goalkeeper", "Goal line / six-yard box",
        "Defend area", "Claim or clear deliveries and organise the six-yard box.",
        (RoleAttribute("aerialReach", 28), RoleAttribute("commandOfArea", 26), RoleAttribute("handling", 16), RoleAttribute("communication", 12), RoleAttribute("anticipation", 10), RoleAttribute("decisions", 8)),
        priority=100, goalkeeper=True,
    )
    return (
        keeper,
        _role(f"def_{kind}_near", "Near-post guard", "Box defence", "Near post", "Mark near post", "Protects the fastest delivery route.", _AERIAL_DEFENCE, priority=99),
        _role(f"def_{kind}_far", "Far-post guard", "Box defence", "Far post", "Mark far post", "Protects deep deliveries and recycled crosses.", _AERIAL_DEFENCE, priority=98),
        _role(f"def_{kind}_aerial_1", "Primary aerial marker", "Box defence", "Central danger", "Mark tall player", "Takes the opponent's strongest aerial threat.", _AERIAL_DEFENCE, priority=97),
        _role(f"def_{kind}_aerial_2", "Secondary aerial marker", "Box defence", "Central danger", "Man mark", "Tracks the second aerial threat.", _AERIAL_DEFENCE, priority=94),
        _role(f"def_{kind}_zone", "Six-yard zonal defender", "Box defence", "Six-yard centre", "Go back", "Attacks deliveries entering the central six-yard area.", _AERIAL_DEFENCE, priority=92),
        _role(
            f"def_{kind}_short", "Short-routine closer", "Wide defence", "Short corner / wide ball",
            "Close down short", "Prevents an uncontested second angle.",
            (RoleAttribute("acceleration", 25), RoleAttribute("agility", 18), RoleAttribute("anticipation", 17), RoleAttribute("workRate", 15), RoleAttribute("tackling", 13), RoleAttribute("decisions", 12)),
            priority=91,
        ),
        _role(f"def_{kind}_spare", "Spare box defender", "Box defence", "Penalty spot", "Go back", "Reads loose balls and covers a lost marker.", _AERIAL_DEFENCE, priority=88),
        _role(
            f"def_{kind}_edge", "Edge-of-box guard", "Second ball", "Penalty-area edge",
            "Mark edge of area", "Closes down clearances and late shooters.",
            (RoleAttribute("anticipation", 24), RoleAttribute("positioning", 22), RoleAttribute("concentration", 16), RoleAttribute("acceleration", 14), RoleAttribute("tackling", 12), RoleAttribute("decisions", 12)),
            priority=86,
        ),
        _role(
            f"def_{kind}_outlet", "Counter outlet", "Outlet", "Halfway line",
            "Stay forward", "Pins back defenders and gives the clearance a target.",
            (RoleAttribute("pace", 24), RoleAttribute("acceleration", 20), RoleAttribute("firstTouch", 16), RoleAttribute("offTheBall", 14), RoleAttribute("strength", 12), RoleAttribute("dribbling", 8), RoleAttribute("passing", 6)),
            priority=82,
        ),
        _role(
            f"def_{kind}_recovery", "Recovery defender", "Wide defence", "Top of box",
            "Go back", "Covers a second phase while retaining speed for transition.",
            _REST_DEFENCE, priority=80,
        ),
    )
