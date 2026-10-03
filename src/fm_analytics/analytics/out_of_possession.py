"""Hand-authored defensive settings and their existing scoring equivalents.

None is unauthored. Boolean fields accept True, False or "Neutral"; neutral
leaves the corresponding control unselected. New choices without an existing
scoring rule are presentation only.
"""

from dataclasses import dataclass
from typing import Any

LINE_OPTIONS = ("Standard", "Lower", "Much Lower", "Higher", "Much Higher")
PRESSING_INTENSITY_OPTIONS = (
    "Standard", "More Urgent", "Extremely Urgent", "Less Urgent", "Much Less Urgent",
)
FIELD_LABELS = (
    ("line_of_engagement", "line of engagement"),
    ("defensive_line", "defensive line"),
    ("use_tighter_marking", "use tighter marking"),
    ("pressing_intensity", "pressing intensity"),
    ("prevent_short_gk_distribution", "prevent short GK distribution"),
)
ALL_FIELD_LABELS = tuple(label for _, label in FIELD_LABELS)
OUT_OF_POSSESSION_KEYS = frozenset({
    "lineOfEngagement", "defensiveLine", "useTighterMarking", "pressingIntensity",
    "preventShortGKDistribution",
})

# Explicit mappings preserve the app's existing scoring vocabulary and demands.
_SCORED_ENGAGEMENT = {level: f"{level} Line of Engagement" for level in LINE_OPTIONS}
_SCORED_DEFENSIVE_LINE = {
    "Standard": "Standard Defensive Line", "Higher": "Higher Defensive Line",
    "Lower": "Drop Off More Defensive Line", "Much Lower": "Much Deeper Defensive Line",
}
_SCORED_PRESSING = {"Extremely Urgent": "Much More Urgent Pressing"}
LEGACY_INSTRUCTION_GROUPS = {
    "line_of_engagement": frozenset(_SCORED_ENGAGEMENT.values()) | {"Drop Deeper Line of Engagement"},
    "defensive_line": frozenset(f"{level} Defensive Line" for level in LINE_OPTIONS)
    | frozenset(_SCORED_DEFENSIVE_LINE.values()),
    "pressing_intensity": frozenset(f"{level} Pressing" for level in PRESSING_INTENSITY_OPTIONS)
    | frozenset(_SCORED_PRESSING.values()),
    "use_tighter_marking": frozenset({"Use Tighter Marking"}),
    "prevent_short_gk_distribution": frozenset({"Prevent Short GK Distribution"}),
}
LEGACY_INSTRUCTIONS = frozenset().union(*LEGACY_INSTRUCTION_GROUPS.values())


@dataclass(frozen=True)
class OutOfPossessionSettings:
    line_of_engagement: str | None = None
    defensive_line: str | None = None
    use_tighter_marking: bool | str | None = None
    pressing_intensity: str | None = None
    prevent_short_gk_distribution: bool | str | None = None

    def __post_init__(self) -> None:
        for name, options in (
            ("line_of_engagement", LINE_OPTIONS), ("defensive_line", LINE_OPTIONS),
            ("pressing_intensity", PRESSING_INTENSITY_OPTIONS),
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or value not in options):
                raise ValueError(f"{name} must be one of {options!r}")
        for name in ("use_tighter_marking", "prevent_short_gk_distribution"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool) and value != "Neutral":
                raise ValueError(f"{name} must be true/false or 'Neutral'")

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(label for name, label in FIELD_LABELS if getattr(self, name) is None)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


def out_of_possession_instruction_strings(settings: OutOfPossessionSettings | None) -> tuple[str, ...]:
    """Only choices with existing instruction-fit scoring rules."""
    if settings is None:
        return ()
    instructions = [
        mapping[value] for mapping, value in (
            (_SCORED_ENGAGEMENT, settings.line_of_engagement),
            (_SCORED_DEFENSIVE_LINE, settings.defensive_line),
            (_SCORED_PRESSING, settings.pressing_intensity),
        ) if value in mapping
    ]
    if settings.prevent_short_gk_distribution is True:
        instructions.append("Prevent Short GK Distribution")
    return tuple(instructions)


def out_of_possession_selected_instructions(settings: OutOfPossessionSettings | None) -> tuple[str, ...]:
    """Selected instructions for presentation, including unscored choices."""
    if settings is None:
        return ()
    instructions = []
    if settings.line_of_engagement is not None:
        instructions.append(_SCORED_ENGAGEMENT[settings.line_of_engagement])
    if settings.defensive_line is not None:
        instructions.append(_SCORED_DEFENSIVE_LINE.get(
            settings.defensive_line, f"{settings.defensive_line} Defensive Line"
        ))
    if settings.use_tighter_marking is True:
        instructions.append("Use Tighter Marking")
    if settings.pressing_intensity not in (None, "Standard"):
        instructions.append(_SCORED_PRESSING.get(
            settings.pressing_intensity, f"{settings.pressing_intensity} Pressing"
        ))
    if settings.prevent_short_gk_distribution is True:
        instructions.append("Prevent Short GK Distribution")
    return tuple(instructions)


def validate_legacy_instructions(settings: OutOfPossessionSettings | None, instructions: tuple[str, ...], tactic_key: str) -> None:
    if settings is None:
        return
    for attribute, choices in LEGACY_INSTRUCTION_GROUPS.items():
        duplicates = choices & set(instructions)
        if getattr(settings, attribute) is not None and duplicates:
            raise ValueError(
                f"tactic {tactic_key!r}: outOfPossession.{attribute} duplicates or conflicts with "
                f"legacy instructions {sorted(duplicates)!r}; remove the legacy strings"
            )


def out_of_possession_from_json(value: Any, tactic_key: str, *, only_known_keys) -> OutOfPossessionSettings | None:
    if value is None:
        return None
    where = f"tactic {tactic_key!r} outOfPossession"
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    only_known_keys(value, OUT_OF_POSSESSION_KEYS, where)
    if any(item is None for item in value.values()):
        raise ValueError(f"{where}: omit unauthored fields rather than setting null")
    try:
        return OutOfPossessionSettings(
            line_of_engagement=value.get("lineOfEngagement"),
            defensive_line=value.get("defensiveLine"),
            use_tighter_marking=value.get("useTighterMarking"),
            pressing_intensity=value.get("pressingIntensity"),
            prevent_short_gk_distribution=value.get("preventShortGKDistribution"),
        )
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from error
