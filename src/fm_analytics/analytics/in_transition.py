"""Hand-authored transition settings, as FM's In Transition tab shows them.

Every choice here is a toggle (see `instruction_toggles.py`): each of FM's five
sections is a list of what the tactic selects, where an empty list is FM's
default of nothing selected and an absent section is unauthored. Selecting one
can make others unavailable (`IN_TRANSITION_CLASHES`, confirmed against FM20,
7 October 2026; roadmap item 4c). Only the possession-lost and possession-won
choices feed instruction-fit scoring; goalkeeper choices have no scoring
weights yet.
"""

from dataclasses import dataclass
from typing import Any

from fm_analytics.analytics.instruction_toggles import check_clashes, check_names, one_at_most, unavailable

POSSESSION_LOST_OPTIONS = ("Counter-Press", "Regroup")
POSSESSION_WON_OPTIONS = ("Counter", "Hold Shape")
GOALKEEPER_PACE_OPTIONS = ("Distribute Quickly", "Slow Pace Down")
DISTRIBUTION_TARGET_OPTIONS = (
    "Distribute To Centre Backs", "Distribute To Full Backs", "Distribute To Playmaker",
    "Distribute To Target Man", "Distribute To Flanks", "Distribute Over Opposition Defence",
)
DISTRIBUTION_TYPE_OPTIONS = (
    "Roll It Out", "Throw It Long", "Take Short Kicks", "Take Long Kicks",
)
# Each section is at most one choice, except that centre-backs and full-backs
# may be distribution targets together.
IN_TRANSITION_CLASHES = (
    one_at_most(POSSESSION_LOST_OPTIONS)
    + one_at_most(POSSESSION_WON_OPTIONS)
    + one_at_most(GOALKEEPER_PACE_OPTIONS)
    + one_at_most(
        DISTRIBUTION_TARGET_OPTIONS,
        combinable={frozenset({"Distribute To Centre Backs", "Distribute To Full Backs"})},
    )
    + one_at_most(DISTRIBUTION_TYPE_OPTIONS)
)
# (attribute, JSON key, label, options), in FM's screen order.
SECTIONS = (
    ("when_possession_lost", "whenPossessionLost", "when possession has been lost", POSSESSION_LOST_OPTIONS),
    ("when_possession_won", "whenPossessionWon", "when possession has been won", POSSESSION_WON_OPTIONS),
    ("goalkeeper_pace", "goalkeeperPace", "goalkeeper in possession", GOALKEEPER_PACE_OPTIONS),
    ("distribution_targets", "distributionTargets", "distribute to area/player", DISTRIBUTION_TARGET_OPTIONS),
    ("distribution_types", "distributionTypes", "distribution type", DISTRIBUTION_TYPE_OPTIONS),
)
ALL_FIELD_LABELS = tuple(label for _, _, label, _ in SECTIONS)
IN_TRANSITION_KEYS = frozenset(key for _, key, _, _ in SECTIONS)


@dataclass(frozen=True)
class InTransitionSettings:
    # What each section selects; None until authored, () for nothing selected.
    when_possession_lost: tuple[str, ...] | None = None
    when_possession_won: tuple[str, ...] | None = None
    goalkeeper_pace: tuple[str, ...] | None = None
    distribution_targets: tuple[str, ...] | None = None
    distribution_types: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        for attribute, key, _label, options in SECTIONS:
            values = getattr(self, attribute)
            if values is not None and not isinstance(values, tuple):
                raise ValueError(f"{key} must be a tuple of instruction names")
            check_names(values or (), options, key)
        check_clashes(self.selected, IN_TRANSITION_CLASHES, "inTransition")

    @property
    def selected(self) -> tuple[str, ...]:
        return tuple(name for attribute, _, _, _ in SECTIONS for name in getattr(self, attribute) or ())

    @property
    def unavailable(self) -> dict[str, tuple[str, ...]]:
        return unavailable(self.selected, IN_TRANSITION_CLASHES)

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(label for attribute, _, label, _ in SECTIONS if getattr(self, attribute) is None)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


def in_transition_instruction_strings(settings: InTransitionSettings | None) -> tuple[str, ...]:
    """Existing scored instructions; distribution settings are display-only."""
    if settings is None:
        return ()
    return (settings.when_possession_lost or ()) + (settings.when_possession_won or ())


def in_transition_selected_instructions(settings: InTransitionSettings | None) -> tuple[str, ...]:
    """All selected choices for CLI/export presentation, including distribution."""
    return () if settings is None else settings.selected


def in_transition_from_json(value: Any, tactic_key: str, *, only_known_keys) -> InTransitionSettings | None:
    if value is None:
        return None
    where = f"tactic {tactic_key!r} inTransition"
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    only_known_keys(value, IN_TRANSITION_KEYS, where)

    def selected(key: str) -> tuple[str, ...] | None:
        if key not in value:
            return None
        items = value[key]
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError(
                f"{where}.{key} must be an array of instruction names "
                "(list only what is selected; [] for none)"
            )
        return tuple(items)

    try:
        return InTransitionSettings(**{attribute: selected(key) for attribute, key, _, _ in SECTIONS})
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from error
