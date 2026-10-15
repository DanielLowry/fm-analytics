"""Reviewable player-job profiles for complete set-piece routines.

The routine builders name the legal FM instructions, zones, purposes and
inclusion priorities. Attribute weights and responsibility importance come
from the validated JSON catalogue in ``data/set_pieces``. Assignment and
uncertainty mechanics live in ``set_pieces.py``.
"""

from __future__ import annotations

from fm_analytics.analytics.set_piece_config import (
    DefensiveTemplate, FLEXIBLE_DEFENSIVE_FREE_KICKS, JobWeights, SET_PIECE_WEIGHTS,
)
from fm_analytics.analytics.set_piece_defence import DEFENSIVE_FREE_KICK_JOBS, responsibility_importances
from fm_analytics.analytics.set_piece_roles import RoutineRole, _role


SET_PIECE_SCORING_VERSION = SET_PIECE_WEIGHTS.version

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

DEFENDING_FREE_KICK_INSTRUCTIONS_BY_VARIANT = {
    kind: frozenset(jobs.values()) for kind, jobs in DEFENSIVE_FREE_KICK_JOBS.items()
}
DEFENDING_FREE_KICK_INSTRUCTIONS = tuple(sorted(set().union(*DEFENDING_FREE_KICK_INSTRUCTIONS_BY_VARIANT.values())))




def _attacking_corner_roles(risk: str) -> tuple[RoutineRole, ...]:
    """Use only the player instructions available in FM's attacking-corner UI."""
    weights = SET_PIECE_WEIGHTS.routine("attacking_corners")

    taker = _role(
        "corner_taker", "Corner taker", "Delivery", "Ball",
        "Take the set piece", "Delivers the corner while balancing box attack and counter cover.",
        weights["corner_taker"],
        priority=100, taker_task_key="corners",
    )
    attack_near = _role(
        "corner_attack_near", "Near-post runner", "Box attack", "Near post",
        "Attack near post", "Explosive first contact at the near post.",
        weights["corner_attack_near"], priority=96,
    )
    lurk_near = _role(
        "corner_lurk_near", "Near-post lurker", "Box attack", "Near post",
        "Lurk near post", "Finds space for rebounds and loose balls at the near post.",
        weights["corner_lurk_near"], priority=82,
    )
    attack_far = _role(
        "corner_attack_far", "Far-post target", "Box attack", "Far post",
        "Attack far post", "Aerial target for deeper delivery and second contact.",
        weights["corner_attack_far"], priority=94,
    )
    lurk_far = _role(
        "corner_lurk_far", "Far-post lurker", "Box attack", "Far post",
        "Lurk far post", "Finds space for deep knock-downs and loose balls.",
        weights["corner_lurk_far"], priority=80,
    )
    mark_keeper = _role(
        "corner_mark_keeper", "Goalkeeper challenger", "Box attack", "Goalkeeper zone",
        "Mark keeper", "Challenges the goalkeeper for deliveries and reacts to rebounds.",
        weights["corner_mark_keeper"],
        priority=76,
    )
    come_short = _role(
        "corner_come_short", "Short option", "Support", "Short corner channel",
        "Come short", "Offers a short passing option and a second delivery angle.",
        weights["corner_come_short"],
        priority=86,
    )
    go_left = _role(
        "corner_go_left", "Left box runner", "Box attack", "Left side of box",
        "Go forward", "Attacks loose balls and second contacts from the left side.",
        weights["corner_go_left"], priority=74,
    )
    go_right = _role(
        "corner_go_right", "Right box runner", "Box attack", "Right side of box",
        "Go forward", "Attacks loose balls and second contacts from the right side.",
        weights["corner_go_right"], priority=73,
    )
    attack_edge = _role(
        "corner_attack_edge", "Edge runner", "Box attack", "Edge of area",
        "Attack ball from edge of area", "Runs into the box to contest the delivery and attack second balls.",
        weights["corner_attack_edge"], priority=90,
    )
    lurk_outside = _role(
        "corner_lurk_outside", "Outside-area option", "Second ball", "Outside edge of area",
        "Lurk outside edge of area", "Collects clearances and threatens from range.",
        weights["corner_lurk_outside"], priority=88,
    )
    stay = _role(
        "corner_stay", "Primary cover", "Rest defence", "Halfway line",
        "Stay back", "Best transition defender protects the first counter lane.",
        weights["corner_stay"], priority=99,
    )
    cover = _role(
        "corner_cover", "Secondary cover", "Rest defence", "Halfway support",
        "Stay back", "Stays back throughout the corner, reads clearances and covers the second counter lane.",
        weights["corner_cover"], priority=98,
    )
    wide_cover = _role(
        "corner_wide_cover", "Wide cover", "Rest defence", "Wide outlet",
        "Stay back if needed", "Keeps possession and prevents an exposed flank.",
        weights["corner_wide_cover"],
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


def _attacking_free_kick_roles(kind: str, risk: str) -> tuple[RoutineRole, ...]:
    """Use only the player instructions available in FM's attacking-free-kick UI."""

    kind = {"wide_free_kick": "indirect_wide"}.get(kind, kind)
    weights = SET_PIECE_WEIGHTS.routine("attacking_free_kicks", kind)
    task_key = (
        "direct_free_kicks" if kind.startswith("direct")
        else "indirect_free_kicks"
    )
    taker = _role(
        f"{kind}_taker", "Free-kick taker", "Delivery", "Ball",
        "Take the set piece", "Best free-kick taker for this situation and side.",
        weights["taker"],
        priority=100, taker_task_key=task_key,
    )
    near = _role(
        f"{kind}_near", "Near-post runner", "Box attack", "Near post",
        "Attack near post", "Attacks the quickest delivery lane for first contact.",
        weights["near"], priority=96,
    )
    far = _role(
        f"{kind}_far", "Far-post target", "Box attack", "Far post",
        "Attack far post", "Attacks deeper deliveries and far-side knock-downs.",
        weights["far"], priority=95,
    )
    edge_left = _role(
        f"{kind}_edge_left", "Left edge runner", "Box attack", "Left edge of area",
        "Attack ball from edge", "Arrives from the edge onto a dropping delivery.",
        weights["edge_left"], priority=91,
    )
    edge_right = _role(
        f"{kind}_edge_right", "Right edge runner", "Box attack", "Right edge of area",
        "Attack ball from edge", "Attacks a dropping delivery from the opposite edge lane.",
        weights["edge_right"], priority=89,
    )
    partner = _role(
        f"{kind}_partner", "Taker support", "Support", "With taker",
        "Stand with taker", "Offers a disguised short option and a second delivery angle.",
        weights["partner"],
        priority=87,
    )
    go_left = _role(
        f"{kind}_go_left", "Left box runner", "Box attack", "Left side of box",
        "Go forward", "Attacks loose balls and second contacts from the left side.",
        weights["go_left"], priority=78,
    )
    go_centre = _role(
        f"{kind}_go_centre", "Central box runner", "Box attack", "Central box",
        "Go forward", "Attacks central knock-downs after the first contact.",
        weights["go_centre"], priority=77,
    )
    go_right = _role(
        f"{kind}_go_right", "Right box runner", "Box attack", "Right side of box",
        "Go forward", "Attacks loose balls and second contacts from the right side.",
        weights["go_right"], priority=76,
    )
    stay = _role(
        f"{kind}_stay", "Primary cover", "Rest defence", "Halfway line",
        "Stay back", "Best transition defender protects the first counter lane.",
        weights["stay"], priority=99,
    )
    cover = _role(
        f"{kind}_cover", "Secondary cover", "Rest defence", "Halfway support",
        "Stay back", "Second defender balances the opposite counter lane.",
        weights["cover"], priority=98,
    )
    wide_cover = _role(
        f"{kind}_wide_cover", "Wide cover", "Rest defence", "Wide outlet",
        "Stay back", "Keeps possession and prevents an exposed flank.",
        weights["wide_cover"],
        priority=85,
    )

    active_roles = {
        "direct_free_kick": (
            partner, edge_left, edge_right, go_centre,
            go_left, go_right, near, far,
        ),
        "direct_small_chance": (
            partner, near, far, edge_left,
            go_left, go_right, go_centre, edge_right,
        ),
        "indirect_wide": (
            near, far, edge_left, partner,
            go_left, go_right, go_centre, edge_right,
        ),
        "indirect_deep": (
            near, far, go_left, go_right,
            go_centre, edge_left, edge_right, partner,
        ),
    }[kind]
    committed = {"secure": 6, "balanced": 7, "aggressive": 8}[risk]
    cover_roles = {"secure": (stay, cover, wide_cover),
                   "balanced": (stay, cover), "aggressive": (stay,)}[risk]
    return (taker, *active_roles[:committed], *cover_roles)


def attacking_roles(kind: str, risk: str) -> tuple[RoutineRole, ...]:
    """Return ten outfield jobs for one attacking corner/free-kick routine."""

    if kind == "corner":
        return _attacking_corner_roles(risk)
    return _attacking_free_kick_roles(kind, risk)


def _defending_corner_roles() -> tuple[RoutineRole, ...]:
    """Use the ten outfield instructions available in FM's defending-corner UI."""
    weights = SET_PIECE_WEIGHTS.routine("defending_corners")

    keeper = _role(
        "def_corner_keeper", "Goalkeeper", "Goalkeeper", "Goal line / six-yard box",
        "Defend area", "Claim or clear deliveries and organise the six-yard box.",
        weights["def_corner_keeper"],
        priority=100, goalkeeper=True,
    )
    post_near = _role(
        "def_corner_post_near", "Near-post guard", "Box defence", "Near post",
        "Mark near post", "Guards the near-post goal line and reacts to shots and flick-ons.",
        weights["def_corner_post_near"], priority=85,
    )
    post_far = _role(
        "def_corner_post_far", "Far-post guard", "Box defence", "Far post",
        "Mark far post", "Guards the far-post goal line and reacts to shots and knock-downs.",
        weights["def_corner_post_far"], priority=84,
    )
    zonal_near = _role(
        "def_corner_zonal_near", "Near-post zonal defender", "Box defence",
        "Six-yard box near post", "Zonally mark 6 yard box near post",
        "Attacks deliveries entering the near side of the six-yard box.",
        weights["def_corner_zonal_near"], priority=97,
    )
    zonal_centre = _role(
        "def_corner_zonal_centre", "Central zonal defender", "Box defence",
        "Six-yard box centre", "Zonally mark 6 yard box centre",
        "Anchors the central six-yard zone and attacks the main delivery.",
        weights["def_corner_zonal_centre"], priority=99,
    )
    zonal_far = _role(
        "def_corner_zonal_far", "Far-post zonal defender", "Box defence",
        "Six-yard box far post", "Zonally mark 6 yard box far post",
        "Attacks deliveries entering the far side of the six-yard box.",
        weights["def_corner_zonal_far"], priority=96,
    )
    go_back = _role(
        "def_corner_go_back", "Spare box defender", "Box defence", "Penalty spot",
        "Go back", "Reads loose balls and covers a lost marker.",
        weights["def_corner_go_back"], priority=90,
    )
    man_mark = _role(
        "def_corner_man_mark", "Man marker", "Box defence", "Central danger",
        "Man mark", "Tracks a designated opposition runner.",
        weights["def_corner_man_mark"], priority=95,
    )
    mark_tall = _role(
        "def_corner_mark_tall", "Primary aerial marker", "Box defence", "Central danger",
        "Mark tall player", "Takes the opponent's strongest aerial threat.",
        weights["def_corner_mark_tall"], priority=98,
    )
    edge = _role(
        "def_corner_edge", "Edge-of-area guard", "Second ball", "Edge of area",
        "Edge of area", "Closes down clearances and late shooters.",
        weights["def_corner_edge"], priority=94,
    )
    forward = _role(
        "def_corner_forward", "Counter outlet", "Outlet", "Halfway line",
        "Stay forward", "Pins back defenders and gives the clearance a target.",
        weights["def_corner_forward"], priority=82,
    )
    return (
        keeper, post_near, post_far, zonal_near, zonal_centre, zonal_far,
        go_back, man_mark, mark_tall, edge, forward,
    )


def _defending_free_kick_roles(kind: str, template: DefensiveTemplate | None = None) -> tuple[RoutineRole, ...]:
    """Build only jobs supported by this variant's verified FM20 menu."""
    kind = {"free_kick": "indirect_wide"}.get(kind, kind)
    weights = SET_PIECE_WEIGHTS.routine("defending_free_kicks", kind)
    if kind in FLEXIBLE_DEFENSIVE_FREE_KICKS:
        template = template or SET_PIECE_WEIGHTS.defensive_templates[kind][0]
        if template.variant != kind:
            raise ValueError("defensive template belongs to a different free-kick variant")
        counts = {**template.jobs, "keeper": 1}
        importance = responsibility_importances(
            counts, {job: weight.importance for job, weight in weights.items()},
            SET_PIECE_WEIGHTS.defensive_budgets[kind],
        )
    else:
        if template is not None:
            raise ValueError("direct defensive free kicks retain their fixed structure")
        counts = dict(keeper=1, wall=5, mark=1, back=2, edge=1, forward=1)
        importance = {job: weight.importance for job, weight in weights.items()}

    def job_weights(job):
        return JobWeights(weights[job].attributes, importance[job])

    keeper = _role(
        f"def_{kind}_keeper", "Goalkeeper", "Goalkeeper", "Goal line / six-yard box",
        "Defend area", "Sets the wall, claims deliveries and protects the goal.",
        job_weights("keeper"), priority=100, goalkeeper=True,
    )
    wall_zones = {
        5: ("Left edge", "Inner left", "Centre", "Inner right", "Right edge"),
        4: ("Left edge", "Inner left", "Inner right", "Right edge"),
        3: ("Left", "Centre", "Right"), 2: ("Left", "Right"),
        1: ("Delivery angle",), 0: (),
    }[counts["wall"]]
    roles = [keeper]
    roles.extend(
        _role(
            f"def_{kind}_wall_{i}", f"Wall player {i}", "Wall", zone,
            "Wall", "Blocks the direct shooting route and holds the wall's shape.",
            job_weights("wall"), priority=(80 if template else 99) - i,
        ) for i, zone in enumerate(wall_zones, start=1)
    )
    roles.extend(
        _role(
            f"def_{kind}_mark_{i}", f"Man marker {i}", "Box defence", f"Runner {i}",
            "Man mark", "Tracks an opposition runner through the delivery phase.",
            job_weights("mark"), priority=(92 if template else 94) - i,
        ) for i in range(1, counts["mark"] + 1)
    )
    roles.extend(
        _role(
            f"def_{kind}_tall_{i}", f"Tall-player marker {i}", "Box defence", "Tall opposition player",
            "Man mark tall player", "Tracks a tall opposition attacker and contests their aerial delivery.",
            job_weights("tall"), priority=99 - i,
        ) for i in range(1, counts.get("tall", 0) + 1)
    )
    for job, name, zone, priority in (
        ("zonal_near", "Near-post zonal defender", "Six-yard box near post", 97),
        ("zonal_centre", "Central zonal defender", "Six-yard box centre", 99),
        ("zonal_far", "Far-post zonal defender", "Six-yard box far post", 96),
    ):
        if counts.get(job, 0):
            roles.append(_role(
                f"def_{kind}_{job}", name, "Box defence", zone,
                DEFENSIVE_FREE_KICK_JOBS[kind][job],
                "Holds the named six-yard zone and attacks deliveries entering it.",
                job_weights(job), priority=priority,
            ))
    roles.extend(
        _role(
            f"def_{kind}_back_{i}", f"Covering defender {i}", "Box defence",
            "General box cover" if template else ("Central box", "Deep box")[i - 1],
            "Go back",
            "Provides spare cover for loose balls and runners who escape their markers; no fixed six-yard zone."
            if template else "Attacks the delivery and covers a runner who escapes their marker.",
            job_weights("back"), priority=90 - i,
        ) for i in range(1, counts["back"] + 1)
    )
    roles.extend(
        _role(
            f"def_{kind}_edge" + (f"_{i}" if i > 1 else ""),
            "Edge-of-area guard" + (f" {i}" if i > 1 else ""), "Second ball", "Edge of area",
            "Edge of area", "Closes down clearances and late shooters.",
            job_weights("edge"), priority=85 - i,
        ) for i in range(1, counts["edge"] + 1)
    )
    roles.extend(
        _role(
            f"def_{kind}_forward" + (f"_{i}" if i > 1 else ""),
            "Counter outlet" + (f" {i}" if i > 1 else ""), "Outlet", "Halfway line",
            "Stay forward", "Pins back defenders and gives the clearance a target.",
            job_weights("forward"), priority=(70 if template else 83) - i,
        ) for i in range(1, counts["forward"] + 1)
    )
    return tuple(roles)


def defensive_roles(kind: str, template: DefensiveTemplate | None = None) -> tuple[RoutineRole, ...]:
    """Return the goalkeeper and ten outfield defensive jobs."""

    if kind == "corner":
        if template is not None:
            raise ValueError("defensive corners retain their existing routine")
        return _defending_corner_roles()
    return _defending_free_kick_roles(kind, template)
