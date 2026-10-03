"""Hand-authored transition settings, with explicit neutral choices.

None means unauthored; "Neither" and empty tuples mean deliberately
unselected. Only existing possession-loss/win choices feed
instruction-fit scoring. Goalkeeper choices have no scoring weights yet.
"""

from dataclasses import dataclass
from typing import Any

POSSESSION_LOST_OPTIONS = ("Counter-Press", "Regroup", "Neither")
POSSESSION_WON_OPTIONS = ("Counter", "Hold Shape", "Neither")
GOALKEEPER_PACE_OPTIONS = ("Distribute Quickly", "Slow Pace Down", "Neither")
DISTRIBUTION_TARGET_OPTIONS = (
    "Distribute Over Opposition Defence", "Distribute To Flanks",
    "Distribute To Target Man", "Distribute To Playmaker",
    "Distribute To Full Backs", "Distribute To Centre Backs",
)
DISTRIBUTION_TYPE_OPTIONS = (
    "Roll It Out", "Throw It Long", "Take Short Kicks", "Take Long Kicks",
)
FIELD_LABELS = (
    ("when_possession_lost", "when possession has been lost"),
    ("when_possession_won", "when possession has been won"),
    ("goalkeeper_pace", "goalkeeper in possession"),
    ("distribution_targets", "distribute to area/player"),
    ("distribution_types", "distribution type"),
)
ALL_FIELD_LABELS = tuple(label for _, label in FIELD_LABELS)
IN_TRANSITION_KEYS = frozenset({
    "whenPossessionLost", "whenPossessionWon", "goalkeeperPace", "distributionTargets", "distributionTypes",
})


@dataclass(frozen=True)
class InTransitionSettings:
    when_possession_lost: str | None = None
    when_possession_won: str | None = None
    goalkeeper_pace: str | None = None
    distribution_targets: tuple[str, ...] | None = None
    distribution_types: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        for name, options in (
            ("when_possession_lost", POSSESSION_LOST_OPTIONS),
            ("when_possession_won", POSSESSION_WON_OPTIONS),
            ("goalkeeper_pace", GOALKEEPER_PACE_OPTIONS),
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or value not in options):
                raise ValueError(f"{name} must be one of {options!r}")
        for name, options in (
            ("distribution_targets", DISTRIBUTION_TARGET_OPTIONS),
            ("distribution_types", DISTRIBUTION_TYPE_OPTIONS),
        ):
            values = getattr(self, name)
            if values is None:
                continue
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or value not in options for value in values
            ):
                raise ValueError(f"{name} must be a tuple of choices from {options!r}")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must not repeat a choice")

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(label for name, label in FIELD_LABELS if getattr(self, name) is None)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


def in_transition_instruction_strings(settings: InTransitionSettings | None) -> tuple[str, ...]:
    """Existing scored instructions; distribution settings are display-only."""
    if settings is None:
        return ()
    instructions = []
    if settings.when_possession_lost not in (None, "Neither"):
        instructions.append(settings.when_possession_lost)
    if settings.when_possession_won not in (None, "Neither"):
        instructions.append(settings.when_possession_won)
    return tuple(instructions)


def in_transition_selected_instructions(settings: InTransitionSettings | None) -> tuple[str, ...]:
    """All selected choices for CLI/export presentation, including distribution."""
    instructions = in_transition_instruction_strings(settings)
    if settings is None:
        return instructions
    if settings.goalkeeper_pace not in (None, "Neither"):
        instructions += (settings.goalkeeper_pace,)
    return instructions + (settings.distribution_targets or ()) + (settings.distribution_types or ())


def in_transition_from_json(value: Any, tactic_key: str, *, only_known_keys) -> InTransitionSettings | None:
    if value is None:
        return None
    where = f"tactic {tactic_key!r} inTransition"
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    only_known_keys(value, IN_TRANSITION_KEYS, where)

    def choices(name: str) -> tuple[str, ...] | None:
        if name not in value:
            return None
        items = value[name]
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError(f"{where}.{name} must be an array of strings")
        return tuple(items)

    for name in ("whenPossessionLost", "whenPossessionWon", "goalkeeperPace"):
        if name in value and not isinstance(value[name], str):
            raise ValueError(f"{where}.{name} must be a string")
    try:
        return InTransitionSettings(
            when_possession_lost=value.get("whenPossessionLost"),
            when_possession_won=value.get("whenPossessionWon"),
            goalkeeper_pace=value.get("goalkeeperPace"),
            distribution_targets=choices("distributionTargets"),
            distribution_types=choices("distributionTypes"),
        )
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from error
