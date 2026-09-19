"""Explainable, attribute-led set-piece assignments for the current squad.

FM's dedicated ``freeKickTaking``, ``penaltyTaking`` and ``longThrows``
attributes are not yet available in the owned-player feed. This module does
not fabricate them: it offers labelled proxies where captured attributes make
a useful comparison, and leaves long throws unranked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fm_analytics.analytics.role_scoring import RoleAttribute, RoleDefinition, RoleScore, score_role
from fm_analytics.domain import Player, Squad, Visibility


SET_PIECE_SCORING_VERSION = "set-piece-v1"


@dataclass(frozen=True)
class SetPieceTask:
    """One assignment in FM's set-piece screen and its visible inputs."""

    key: str
    name: str
    explanation: str
    attributes: tuple[RoleAttribute, ...]
    proxy_for_unread_attribute: str | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.name or not self.explanation:
            raise ValueError("set-piece key, name, and explanation are required")
        if not self.attributes:
            raise ValueError("a set-piece task requires at least one attribute")

    def score(self, player: Player) -> RoleScore:
        # The existing scorer retains uncertainty: an unobserved attribute
        # cannot improve a current rank, while the bounds show what new data
        # could change. Position eligibility is irrelevant to an assignment.
        profile = RoleDefinition(
            key=f"set_piece_{self.key}",
            name=self.name,
            eligible_positions=("set-piece",),
            attributes=self.attributes,
            catalogue_version=SET_PIECE_SCORING_VERSION,
        )
        return score_role(profile, player.attributes)


@dataclass(frozen=True)
class SetPieceCandidate:
    player: Player
    score: RoleScore


@dataclass(frozen=True)
class SetPieceRecommendation:
    task: SetPieceTask
    candidates: tuple[SetPieceCandidate, ...]

    @property
    def suggested(self) -> SetPieceCandidate | None:
        # Alphabetical tie-breaking is useful for a stable full ranking, but
        # it must never masquerade as a football recommendation when none of
        # this task's inputs has been observed for anyone.
        if not self.candidates or not any(
            contribution.observation.visibility is not Visibility.UNKNOWN
            for contribution in self.candidates[0].score.contributions
        ):
            return None
        return self.candidates[0]


@dataclass(frozen=True)
class SetPieceReport:
    recommendations: tuple[SetPieceRecommendation, ...]
    unavailable_players: tuple[Player, ...]


# These are explicit football hypotheses, not claims about FM's internal
# set-piece engine. The UI shows every input and its weight for review.
SET_PIECE_TASKS: tuple[SetPieceTask, ...] = (
    SetPieceTask(
        "corners", "Corners",
        "Delivery quality: corners first, supported by crossing and technique.",
        (RoleAttribute("corners", 60), RoleAttribute("crossing", 25), RoleAttribute("technique", 15)),
    ),
    SetPieceTask(
        "direct_free_kicks", "Direct free kicks",
        "Proxy from long shots, technique, composure and flair; the dedicated Free Kick Taking rating is not read yet.",
        (RoleAttribute("longShots", 35), RoleAttribute("technique", 35), RoleAttribute("composure", 15), RoleAttribute("flair", 15)),
        proxy_for_unread_attribute="Free Kick Taking",
    ),
    SetPieceTask(
        "indirect_free_kicks", "Indirect free kicks",
        "Delivery quality: corners, crossing and technique.",
        (RoleAttribute("corners", 45), RoleAttribute("crossing", 35), RoleAttribute("technique", 20)),
    ),
    SetPieceTask(
        "penalties", "Penalties",
        "Proxy from finishing, composure and technique; the dedicated Penalty Taking rating is not read yet.",
        (RoleAttribute("finishing", 45), RoleAttribute("composure", 35), RoleAttribute("technique", 20)),
        proxy_for_unread_attribute="Penalty Taking",
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
) -> SetPieceReport:
    """Rank currently available senior players for every set-piece task."""

    available = tuple(player for player in squad.players if is_set_piece_available(player))
    unavailable = tuple(player for player in squad.players if not is_set_piece_available(player))
    recommendations = []
    for task in tasks:
        candidates = tuple(sorted(
            (SetPieceCandidate(player=player, score=task.score(player)) for player in available),
            key=lambda item: (
                -item.score.score.central, -item.score.score.lower, -item.score.score.upper,
                item.player.name.casefold(), item.player.id,
            ),
        ))
        recommendations.append(SetPieceRecommendation(task=task, candidates=candidates))
    return SetPieceReport(tuple(recommendations), unavailable)
