"""Matchday replacement options for the recommended XI.

This deliberately answers the narrow, in-match question "who can replace
this starter from the named bench?"  It does not infer match ratings, fatigue
events, or a preferred substitution minute -- those observations are not part
of the current manager-visible snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fm_analytics.analytics.bench_selection import BenchSelection
from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.xi_selection import (
    FamiliarityPolicy,
    PlayerSelectionInput,
    ReadinessPolicy,
    SlotAssignment,
    TacticEvaluation,
    score_player_for_slot,
)


@dataclass(frozen=True)
class ReplacementOption:
    """One named substitute's suitability for one starter's exact slot."""

    player_id: str
    player_name: str
    assignment: SlotAssignment
    covered_slot_keys: tuple[str, ...]
    sole_cover_slot_keys: tuple[str, ...]


@dataclass(frozen=True)
class SubstitutionTarget:
    """The available named-bench replacements for a current starter."""

    starter: SlotAssignment
    options: tuple[ReplacementOption, ...]


@dataclass(frozen=True)
class SubstitutionBoard:
    """Replacement choices for every selected starter, in tactic-slot order."""

    targets: tuple[SubstitutionTarget, ...]


def build_substitution_board(
    evaluation: TacticEvaluation,
    bench: BenchSelection,
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    familiarity_policy: FamiliarityPolicy = FamiliarityPolicy(),
) -> SubstitutionBoard:
    """Rank named substitutes for each selected starter's actual role/slot.

    A sole-cover warning means that, after bringing this player on, no other
    named substitute can replace a starter in the listed slot.  The target
    being replaced is excluded because it will be occupied by the substitute.
    """
    if (
        evaluation.tactic.key not in catalogue.tactics
        or catalogue.tactics[evaluation.tactic.key] != evaluation.tactic
    ):
        raise ValueError("evaluated tactic must belong to the supplied catalogue")
    catalogue = catalogue.for_tactic(evaluation.tactic.key)

    players_by_id = {player.id: player for player in players}
    if len(players_by_id) != len(players):
        raise ValueError("selection player ids must be unique")
    bench_entries = tuple(bench.entries)
    missing = [entry.player_id for entry in bench_entries if entry.player_id not in players_by_id]
    if missing:
        raise ValueError("bench players must belong to the supplied selection players")

    targets = []
    for starter in evaluation.assignments:
        options = []
        for entry in bench_entries:
            assignment = score_player_for_slot(
                players_by_id[entry.player_id],
                starter.slot,
                catalogue,
                readiness_policy=readiness_policy,
                familiarity_policy=familiarity_policy,
            )
            if assignment is None:
                continue
            sole_cover = tuple(
                slot_key
                for slot_key in entry.covered_slots
                if slot_key != starter.slot.key
                and not any(
                    slot_key in other.covered_slots
                    for other in bench_entries
                    if other.player_id != entry.player_id
                )
            )
            options.append(
                ReplacementOption(
                    player_id=entry.player_id,
                    player_name=entry.player_name,
                    assignment=assignment,
                    covered_slot_keys=entry.covered_slots,
                    sole_cover_slot_keys=sole_cover,
                )
            )
        targets.append(
            SubstitutionTarget(
                starter=starter,
                options=tuple(
                    sorted(
                        options,
                        key=lambda option: (
                            -option.assignment.selection_score.central,
                            -option.assignment.selection_score.lower,
                            option.player_name.casefold(),
                            option.player_id,
                        ),
                    )
                ),
            )
        )
    return SubstitutionBoard(targets=tuple(targets))
