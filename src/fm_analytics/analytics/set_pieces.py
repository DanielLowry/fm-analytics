"""Explainable set-piece takers and whole-routine player assignments.

The optimiser only uses manager-visible observations. Dedicated set-piece
attributes are preferred when a source supplies them; where the live FM20
reader cannot yet do so, a labelled proxy remains useful for free kicks and
penalties. Long throws deliberately remain unranked without their dedicated
attribute.

Routine jobs are solved together rather than ranked independently. A player
can therefore take exactly one job in a routine, the taker cannot also attack
the box, and the best aerial players are distributed across distinct zones.
The role profiles and instructions below are explicit football hypotheses,
not claims about FM's hidden match engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from fm_analytics.analytics.assignment_solver import _minimum_cost_full_assignment
from fm_analytics.analytics.set_piece_routines import (
    SET_PIECE_SCORING_VERSION,
    RoutineRole,
    attacking_roles,
    defensive_roles,
)
from fm_analytics.analytics.role_scoring import (
    RoleAttribute,
    RoleDefinition,
    RoleScore,
    ScoreBand,
    score_role,
)
from fm_analytics.domain import Player, Squad, Visibility


DELIVERY_STYLES = {
    "inswinging": "Inswingers",
    "outswinging": "Outswingers",
}
ATTACKING_RISKS = {
    "secure": "Secure",
    "balanced": "Balanced",
    "aggressive": "Aggressive",
}
_SIDE_DELIVERY_TASKS = frozenset(
    {"corners", "direct_free_kicks", "indirect_free_kicks"}
)
_SIDE_FOOT_BONUS = 4.0


@dataclass(frozen=True)
class SetPieceTask:
    """One taker assignment and the visible evidence used to rank it."""

    key: str
    name: str
    explanation: str
    attributes: tuple[RoleAttribute, ...]
    proxy_for_unread_attribute: str | None = None
    dedicated_attribute: str | None = None
    dedicated_label: str | None = None
    dedicated_attributes: tuple[RoleAttribute, ...] = ()
    proxy_allowed: bool = True

    def __post_init__(self) -> None:
        if not self.key or not self.name or not self.explanation:
            raise ValueError("set-piece key, name, and explanation are required")
        if not self.attributes:
            raise ValueError("a set-piece task requires at least one attribute")
        if bool(self.dedicated_attribute) != bool(self.dedicated_label):
            raise ValueError("dedicated attribute and label must be supplied together")
        if self.dedicated_attributes and not self.dedicated_attribute:
            raise ValueError("dedicated scoring attributes require a dedicated attribute")

    def scoring_attributes(self, player: Player) -> tuple[RoleAttribute, ...]:
        """Use the dedicated rating when it is present and manager-visible."""

        if self.dedicated_attribute is not None:
            observation = player.attributes.get(self.dedicated_attribute)
            if observation is not None and observation.visibility is not Visibility.UNKNOWN:
                return self.dedicated_attributes or self.attributes
        return self.attributes

    def evidence_mode(self, player: Player) -> str:
        if self.dedicated_attribute is None:
            return "standard"
        observation = player.attributes.get(self.dedicated_attribute)
        if observation is not None and observation.visibility is not Visibility.UNKNOWN:
            return "dedicated"
        return "proxy" if self.proxy_allowed else "unavailable"

    def score(self, player: Player) -> RoleScore:
        profile = RoleDefinition(
            key=f"set_piece_{self.key}",
            name=self.name,
            eligible_positions=("set-piece",),
            attributes=self.scoring_attributes(player),
            catalogue_version=SET_PIECE_SCORING_VERSION,
        )
        return score_role(profile, player.attributes)


@dataclass(frozen=True)
class SetPieceCandidate:
    player: Player
    score: RoleScore
    side_fit_bonus: float = 0.0
    side_fit_label: str = "Not applicable"
    evidence_mode: str = "standard"

    @property
    def ordering_score(self) -> float:
        """The side-specific ranking score, including the visible foot bonus."""

        return self.score.score.central + self.side_fit_bonus

    @property
    def evidence_label(self) -> str:
        return {
            "dedicated": "Dedicated rating",
            "proxy": "Attribute proxy",
            "unavailable": "Dedicated rating needed",
            "standard": "Visible attributes",
        }[self.evidence_mode]


@dataclass(frozen=True)
class SetPieceRecommendation:
    task: SetPieceTask
    candidates: tuple[SetPieceCandidate, ...]
    side: str | None = None
    preferred_foot: str | None = None

    @property
    def name(self) -> str:
        if self.side is None:
            return self.task.name
        assert self.preferred_foot is not None
        return f"{self.side.capitalize()}-side {self.task.name} (prefer {self.preferred_foot} foot)"

    @property
    def suggested(self) -> SetPieceCandidate | None:
        # Alphabetical tie-breaking is useful for a stable full ranking, but
        # it must never masquerade as evidence when every input is unknown.
        if not self.candidates or self.candidates[0].evidence_mode == "unavailable":
            return None
        if not any(
            contribution.observation.visibility is not Visibility.UNKNOWN
            for contribution in self.candidates[0].score.contributions
        ):
            return None
        return self.candidates[0]


@dataclass(frozen=True)
class RoutineAssignment:
    role: RoutineRole
    player: Player
    score: RoleScore
    side_fit_bonus: float = 0.0
    side_fit_label: str = "Not applicable"
    evidence_mode: str = "standard"

    @property
    def ordering_score(self) -> float:
        return self.score.score.central + self.side_fit_bonus

    @property
    def strongest_inputs(self) -> tuple[str, ...]:
        ordered = sorted(
            self.score.contributions,
            key=lambda item: (-item.weight, item.attribute),
        )
        return tuple(item.attribute for item in ordered[:3])


@dataclass(frozen=True)
class SetPieceRoutine:
    key: str
    name: str
    phase: str
    side: str | None
    objective: str
    assignments: tuple[RoutineAssignment, ...]
    unfilled_roles: tuple[RoutineRole, ...]
    notes: tuple[str, ...]
    score: ScoreBand
    evidence_coverage: float

    @property
    def players_in_box(self) -> int:
        box_unit = "Box attack" if self.phase == "attacking" else "Box defence"
        return sum(item.role.unit == box_unit for item in self.assignments)

    @property
    def players_held_back(self) -> int:
        safety_unit = "Rest defence" if self.phase == "attacking" else "Outlet"
        return sum(item.role.unit == safety_unit for item in self.assignments)


@dataclass(frozen=True)
class SetPieceReport:
    recommendations: tuple[SetPieceRecommendation, ...]
    unavailable_players: tuple[Player, ...]
    delivery_style: str
    attacking_risk: str = "balanced"
    routines: tuple[SetPieceRoutine, ...] = ()
    player_pool: tuple[Player, ...] = ()
    lineup_name: str = "Available senior squad"
    uses_match_xi: bool = False
    coverage_notes: tuple[str, ...] = ()


# Taker profiles. The dedicated form is selected player-by-player, so an HTML
# overlay that contains Fre/Pen/L Th immediately improves the result even when
# the live reader cannot supply those fields yet.
SET_PIECE_TASKS: tuple[SetPieceTask, ...] = (
    SetPieceTask(
        "corners", "Corners",
        "Delivery quality: Corners first, supported by crossing and technique.",
        (RoleAttribute("corners", 60), RoleAttribute("crossing", 25), RoleAttribute("technique", 15)),
    ),
    SetPieceTask(
        "direct_free_kicks", "Direct free kicks",
        "Uses Free Kick Taking when supplied; otherwise estimates striking quality from long shots, technique, composure and flair.",
        (RoleAttribute("longShots", 35), RoleAttribute("technique", 35), RoleAttribute("composure", 15), RoleAttribute("flair", 15)),
        proxy_for_unread_attribute="Free Kick Taking",
        dedicated_attribute="freeKickTaking", dedicated_label="Free Kick Taking",
        dedicated_attributes=(RoleAttribute("freeKickTaking", 70), RoleAttribute("technique", 15), RoleAttribute("longShots", 10), RoleAttribute("composure", 5)),
    ),
    SetPieceTask(
        "indirect_free_kicks", "Indirect free kicks",
        "Uses Free Kick Taking when supplied; otherwise compares crossing, corners and technique for delivery.",
        (RoleAttribute("corners", 40), RoleAttribute("crossing", 40), RoleAttribute("technique", 20)),
        proxy_for_unread_attribute="Free Kick Taking",
        dedicated_attribute="freeKickTaking", dedicated_label="Free Kick Taking",
        dedicated_attributes=(RoleAttribute("freeKickTaking", 60), RoleAttribute("crossing", 25), RoleAttribute("technique", 15)),
    ),
    SetPieceTask(
        "penalties", "Penalties",
        "Uses Penalty Taking when supplied; otherwise estimates conversion under pressure from finishing, composure and technique.",
        (RoleAttribute("finishing", 45), RoleAttribute("composure", 35), RoleAttribute("technique", 20)),
        proxy_for_unread_attribute="Penalty Taking",
        dedicated_attribute="penaltyTaking", dedicated_label="Penalty Taking",
        dedicated_attributes=(RoleAttribute("penaltyTaking", 75), RoleAttribute("composure", 20), RoleAttribute("finishing", 5)),
    ),
    SetPieceTask(
        "long_throws", "Long throws",
        "Long throws require the dedicated Long Throws rating; unrelated throwing or strength ratings are not substituted.",
        (RoleAttribute("longThrows", 100),),
        dedicated_attribute="longThrows", dedicated_label="Long Throws",
        proxy_allowed=False,
    ),
    SetPieceTask(
        "attacking_aerial_target", "Attacking aerial target",
        "Attack the delivery with jumping reach, heading, strength, anticipation and bravery.",
        (RoleAttribute("jumpingReach", 35), RoleAttribute("heading", 30), RoleAttribute("strength", 15), RoleAttribute("anticipation", 10), RoleAttribute("bravery", 10)),
    ),
    SetPieceTask(
        "defensive_aerial_target", "Defensive aerial target",
        "Defend the box with jumping reach, heading, marking, strength and bravery.",
        (RoleAttribute("jumpingReach", 30), RoleAttribute("heading", 25), RoleAttribute("marking", 20), RoleAttribute("strength", 15), RoleAttribute("bravery", 10)),
    ),
)


def is_set_piece_available(player: Player) -> bool:
    """Whether the player can be proposed for the next match's assignments."""

    return player.availability == "available" and not player.injured and not player.suspended


def recommend_set_pieces(
    squad: Squad,
    tasks: Sequence[SetPieceTask] = SET_PIECE_TASKS,
    *,
    delivery_style: str = "inswinging",
    attacking_risk: str = "balanced",
    selected_player_ids: Sequence[str] | None = None,
    lineup_positions: Mapping[str, str] | None = None,
    lineup_name: str | None = None,
) -> SetPieceReport:
    """Build taker orders and exact whole-routine assignments."""

    if delivery_style not in DELIVERY_STYLES:
        raise ValueError(f"delivery_style must be one of {sorted(DELIVERY_STYLES)}")
    if attacking_risk not in ATTACKING_RISKS:
        raise ValueError(f"attacking_risk must be one of {sorted(ATTACKING_RISKS)}")

    available = tuple(player for player in squad.players if is_set_piece_available(player))
    unavailable = tuple(player for player in squad.players if not is_set_piece_available(player))
    by_id = {player.id: player for player in available}
    if selected_player_ids is None:
        pool = available
        uses_match_xi = False
    else:
        selected_player_ids = tuple(selected_player_ids)
        if len(selected_player_ids) != len(set(selected_player_ids)):
            raise ValueError("selected set-piece player IDs must be unique")
        pool = tuple(by_id[player_id] for player_id in selected_player_ids if player_id in by_id)
        uses_match_xi = True

    recommendations: list[SetPieceRecommendation] = []
    for task in tasks:
        sides = ("left", "right") if task.key in _SIDE_DELIVERY_TASKS else (None,)
        for side in sides:
            preferred_foot = _preferred_foot_for_side(side, delivery_style) if side else None
            candidates = tuple(sorted(
                (_candidate_for(task, player, preferred_foot) for player in pool),
                key=lambda item: (
                    item.evidence_mode == "unavailable",
                    -item.ordering_score, -item.score.score.central,
                    -item.score.score.lower, -item.score.score.upper,
                    item.player.name.casefold(), item.player.id,
                ),
            ))
            recommendations.append(SetPieceRecommendation(
                task=task, candidates=candidates, side=side,
                preferred_foot=preferred_foot,
            ))

    routines = _build_routines(
        pool, tuple(recommendations), attacking_risk,
        lineup_positions or {},
    )
    dedicated_gaps = sorted({
        task.dedicated_label
        for task in tasks
        if task.dedicated_attribute
        and not any(
            player.attributes.get(task.dedicated_attribute) is not None
            and player.attributes[task.dedicated_attribute].visibility is not Visibility.UNKNOWN
            for player in pool
        )
    })
    coverage_notes = tuple(
        f"{label} is not captured by this source; "
        + ("a labelled proxy is used." if label != "Long Throws" else "that taker order is withheld.")
        for label in dedicated_gaps
    )
    return SetPieceReport(
        recommendations=tuple(recommendations),
        unavailable_players=unavailable,
        delivery_style=delivery_style,
        attacking_risk=attacking_risk,
        routines=routines,
        player_pool=pool,
        lineup_name=lineup_name or ("Available senior squad" if not uses_match_xi else "Match XI"),
        uses_match_xi=uses_match_xi,
        coverage_notes=coverage_notes,
    )


def _build_routines(
    players: tuple[Player, ...],
    recommendations: tuple[SetPieceRecommendation, ...],
    attacking_risk: str,
    lineup_positions: Mapping[str, str],
) -> tuple[SetPieceRoutine, ...]:
    routines = []
    for kind, title, objective in (
        ("corner", "Attacking corner", "Create separated first-contact, second-ball and transition responsibilities."),
        ("wide_free_kick", "Attacking wide free kick", "Attack three delivery lanes without sacrificing the edge or counter cover."),
    ):
        for side in ("left", "right"):
            routines.append(_optimise_routine(
                key=f"attacking_{kind}_{side}",
                name=f"{side.capitalize()} {title.lower()}",
                phase="attacking", side=side, objective=objective,
                roles=attacking_roles(kind, attacking_risk), players=players,
                recommendations=recommendations,
                lineup_positions=lineup_positions,
                notes=(
                    f"{ATTACKING_RISKS[attacking_risk]} template: reserve "
                    f"{'three players' if attacking_risk == 'secure' else 'two players' if attacking_risk == 'balanced' else 'one player'} in rest-defence jobs.",
                    "If the opponent leaves extra players forward, move the lowest-priority box runner into cover.",
                ),
            ))
    routines.extend((
        _optimise_routine(
            key="defending_corner", name="Defending corners", phase="defending", side=None,
            objective="Protect both posts and the central delivery while retaining one counter outlet.",
            roles=defensive_roles("corner"), players=players,
            recommendations=recommendations,
            lineup_positions=lineup_positions,
            notes=("Primary and secondary aerial markers are intentionally different players.", "Drop the counter outlet only when protecting a late lead or facing overwhelming aerial pressure."),
        ),
        _optimise_routine(
            key="defending_wide_free_kick", name="Defending wide free kicks", phase="defending", side=None,
            objective="Defend first contact, protect the second phase and keep a route out.",
            roles=defensive_roles("free_kick"), players=players,
            recommendations=recommendations,
            lineup_positions=lineup_positions,
            notes=("Use the same responsibilities from either side; mirror the near/far-post positions in FM.", "Do not use the quickest outlet as a post guard unless no credible aerial defender is available."),
        ),
    ))
    return tuple(routines)


def _optimise_routine(
    *, key: str, name: str, phase: str, side: str | None, objective: str,
    roles: tuple[RoutineRole, ...], players: tuple[Player, ...],
    recommendations: tuple[SetPieceRecommendation, ...],
    lineup_positions: Mapping[str, str], notes: tuple[str, ...],
) -> SetPieceRoutine:
    goalkeepers = tuple(player for player in players if _is_goalkeeper(player, lineup_positions))
    outfield = tuple(player for player in players if player not in goalkeepers)
    if phase == "attacking":
        eligible_players = outfield
        eligible_roles = tuple(role for role in roles if not role.goalkeeper)
    else:
        eligible_players = players
        eligible_roles = tuple(role for role in roles if not role.goalkeeper or goalkeepers)

    # On a partial feed keep the highest-priority responsibilities rather than
    # producing duplicates or pretending all eleven jobs can be filled.
    selected_roles = tuple(sorted(eligible_roles, key=lambda item: -item.priority)[:len(eligible_players)])
    role_candidates: list[list[RoutineAssignment | None]] = []
    for role in selected_roles:
        row = []
        for player in eligible_players:
            is_keeper = player in goalkeepers
            if role.goalkeeper != is_keeper:
                row.append(None)
                continue
            row.append(_routine_candidate(role, player, side, recommendations))
        role_candidates.append(row)

    assignments: tuple[RoutineAssignment, ...] = ()
    if role_candidates:
        maximum = max(
            (candidate.ordering_score for row in role_candidates for candidate in row if candidate is not None),
            default=0.0,
        )
        costs = [
            [round(maximum - candidate.ordering_score, 6) if candidate is not None else None for candidate in row]
            for row in role_candidates
        ]
        player_indexes = _minimum_cost_full_assignment(costs)
        if player_indexes is not None:
            assignments = tuple(
                role_candidates[index][player_index]  # type: ignore[misc]
                for index, player_index in enumerate(player_indexes)
            )

    assigned_role_keys = {item.role.key for item in assignments}
    unfilled = tuple(role for role in roles if role.key not in assigned_role_keys)
    ordered_assignments = tuple(sorted(
        assignments,
        key=lambda item: (_unit_order(item.role.unit), -item.role.priority, item.role.name),
    ))
    return SetPieceRoutine(
        key=key, name=name, phase=phase, side=side, objective=objective,
        assignments=ordered_assignments, unfilled_roles=unfilled, notes=notes,
        score=_mean_band(tuple(item.score.score for item in assignments)),
        evidence_coverage=_evidence_coverage(assignments),
    )


def _routine_candidate(
    role: RoutineRole, player: Player, side: str | None,
    recommendations: tuple[SetPieceRecommendation, ...],
) -> RoutineAssignment:
    if role.taker_task_key is not None:
        recommendation = next(
            item for item in recommendations
            if item.task.key == role.taker_task_key and item.side == side
        )
        candidate = next(item for item in recommendation.candidates if item.player.id == player.id)
        return RoutineAssignment(
            role=role, player=player, score=candidate.score,
            side_fit_bonus=candidate.side_fit_bonus,
            side_fit_label=candidate.side_fit_label,
            evidence_mode=candidate.evidence_mode,
        )
    return RoutineAssignment(role=role, player=player, score=role.score(player))


def _is_goalkeeper(player: Player, lineup_positions: Mapping[str, str]) -> bool:
    lineup_position = lineup_positions.get(player.id)
    if lineup_position is not None:
        return lineup_position == "GK"
    return "GK" in player.positions and not any(position != "GK" for position in player.positions)


def _unit_order(unit: str) -> int:
    return {
        "Delivery": 0, "Box attack": 1, "Support": 2, "Second ball": 3,
        "Rest defence": 4, "Goalkeeper": 0, "Box defence": 1,
        "Wide defence": 2, "Outlet": 4,
    }.get(unit, 9)


def _mean_band(bands: tuple[ScoreBand, ...]) -> ScoreBand:
    if not bands:
        return ScoreBand(0.0, 0.0, 0.0)
    count = len(bands)
    return ScoreBand(
        lower=round(sum(item.lower for item in bands) / count, 6),
        central=round(sum(item.central for item in bands) / count, 6),
        upper=round(sum(item.upper for item in bands) / count, 6),
    )


def _evidence_coverage(assignments: tuple[RoutineAssignment, ...]) -> float:
    observed = 0.0
    total = 0.0
    for assignment in assignments:
        for contribution in assignment.score.contributions:
            total += contribution.weight
            if contribution.observation.visibility is not Visibility.UNKNOWN:
                observed += contribution.weight
    return round(observed / total, 4) if total else 0.0


def _preferred_foot_for_side(side: str, delivery_style: str) -> str:
    if side not in {"left", "right"}:
        raise ValueError("side must be 'left' or 'right'")
    if delivery_style == "inswinging":
        return "Right" if side == "left" else "Left"
    return "Left" if side == "left" else "Right"


def _candidate_for(
    task: SetPieceTask, player: Player, preferred_foot: str | None,
) -> SetPieceCandidate:
    bonus, label = _side_fit(player.preferred_foot, preferred_foot)
    return SetPieceCandidate(
        player=player, score=task.score(player), side_fit_bonus=bonus,
        side_fit_label=label, evidence_mode=task.evidence_mode(player),
    )


def _side_fit(player_foot: str | None, preferred_foot: str | None) -> tuple[float, str]:
    if preferred_foot is None:
        return 0.0, "Not applicable"
    if player_foot is None:
        return 0.0, "Foot not captured"
    if player_foot == "Either":
        return _SIDE_FOOT_BONUS / 2, "Either foot"
    if player_foot.startswith(preferred_foot):
        return _SIDE_FOOT_BONUS, f"Preferred {preferred_foot.lower()} foot"
    return 0.0, f"Prefers {player_foot.lower()} foot"
