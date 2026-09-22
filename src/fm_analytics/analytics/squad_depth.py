from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticDefinition
from fm_analytics.analytics.opponent import OpponentProfile
from fm_analytics.analytics.weaknesses import (
    Weakness,
    WeaknessPolicy,
    WeaknessReport,
    assess_weaknesses,
)
from fm_analytics.analytics.xi_selection import (
    PlayerSelectionInput,
    ReadinessPolicy,
    TacticEvaluation,
)


@dataclass(frozen=True)
class TaggedWeakness:
    """A weakness found for one tactic, kept alongside which tactic it came from."""

    tactic_key: str
    tactic_name: str
    weakness: Weakness


@dataclass(frozen=True)
class PositionDepth:
    """One position's weakness record across every tactic that fields it.

    `assess_weaknesses` answers "where is this XI thin" for a single tactic.
    This groups that same output by *position* across several tactics, since
    a slot key is tactic-specific (a tactic's "DCL" is not another tactic's
    "DCC") while the position it represents is comparable. A position a
    tactic never fields (no DM slot in a back-four-no-DM shape) does not
    count against or for that position here.
    """

    position: str
    tactics_with_this_position: tuple[str, ...]
    tactics_with_a_weakness: tuple[str, ...]
    weaknesses: tuple[TaggedWeakness, ...]

    @property
    def is_persistent(self) -> bool:
        """Weak in every evaluated tactic that actually fields this position."""
        return bool(self.tactics_with_this_position) and set(
            self.tactics_with_a_weakness
        ) == set(self.tactics_with_this_position)

    @property
    def is_occasional(self) -> bool:
        """Weak in some, but not all, of the tactics that field this position."""
        return bool(self.tactics_with_a_weakness) and not self.is_persistent


@dataclass(frozen=True)
class SquadDepthReport:
    """Depth across the evaluated tactic set, not just the single selected one.

    A slot that is thin in every tactic the manager would realistically play
    is a real squad weakness; one thin only in a shape they will not play is
    noise. `persistent_weaknesses` is the former, `occasional_weaknesses` the
    latter -- pass in the tactic shortlist that reflects real intent, not
    necessarily every tactic in the catalogue.
    """

    policy_version: str
    tactic_keys: tuple[str, ...]
    per_tactic: Mapping[str, WeaknessReport]
    positions: Mapping[str, PositionDepth]

    @property
    def persistent_weaknesses(self) -> tuple[PositionDepth, ...]:
        return tuple(
            sorted(
                (position for position in self.positions.values() if position.is_persistent),
                key=lambda item: item.position,
            )
        )

    @property
    def occasional_weaknesses(self) -> tuple[PositionDepth, ...]:
        return tuple(
            sorted(
                (position for position in self.positions.values() if position.is_occasional),
                key=lambda item: item.position,
            )
        )


def assess_squad_depth(
    evaluations: Sequence[TacticEvaluation],
    players: Sequence[PlayerSelectionInput],
    catalogue: FootballCatalogue,
    *,
    weakness_policy: WeaknessPolicy = WeaknessPolicy(),
    readiness_policy: ReadinessPolicy = ReadinessPolicy(),
    opponent: OpponentProfile = OpponentProfile.neutral(),
) -> SquadDepthReport:
    if not evaluations:
        raise ValueError("squad depth assessment requires at least one tactic evaluation")
    tactic_keys = tuple(evaluation.tactic.key for evaluation in evaluations)
    if len(tactic_keys) != len(set(tactic_keys)):
        raise ValueError("squad depth assessment requires distinct tactics")

    per_tactic: dict[str, WeaknessReport] = {}
    positions_with_tactic: dict[str, set[str]] = {}
    positions_with_weakness: dict[str, set[str]] = {}
    tagged: dict[str, list[TaggedWeakness]] = {}

    for evaluation in evaluations:
        report = assess_weaknesses(
            evaluation,
            players,
            catalogue,
            policy=weakness_policy,
            readiness_policy=readiness_policy,
            opponent=opponent,
        )
        per_tactic[evaluation.tactic.key] = report
        slot_positions = _slot_positions(evaluation.tactic)
        for position in _tactic_positions(evaluation.tactic):
            positions_with_tactic.setdefault(position, set()).add(evaluation.tactic.key)
        for weakness in report.weaknesses:
            touched_positions = {
                slot_positions[key] for key in weakness.slot_keys if key in slot_positions
            }
            for position in touched_positions:
                positions_with_weakness.setdefault(position, set()).add(evaluation.tactic.key)
                tagged.setdefault(position, []).append(
                    TaggedWeakness(
                        tactic_key=evaluation.tactic.key,
                        tactic_name=evaluation.tactic.name,
                        weakness=weakness,
                    )
                )

    positions = {
        position: PositionDepth(
            position=position,
            tactics_with_this_position=tuple(sorted(tactics)),
            tactics_with_a_weakness=tuple(sorted(positions_with_weakness.get(position, ()))),
            weaknesses=tuple(tagged.get(position, ())),
        )
        for position, tactics in positions_with_tactic.items()
    }

    return SquadDepthReport(
        policy_version=weakness_policy.version,
        tactic_keys=tactic_keys,
        per_tactic=per_tactic,
        positions=positions,
    )


def _slot_positions(tactic: TacticDefinition) -> dict[str, str]:
    return {slot.key: slot.position for slot in tactic.slots}


def _tactic_positions(tactic: TacticDefinition) -> frozenset[str]:
    return frozenset(slot.position for slot in tactic.slots)
