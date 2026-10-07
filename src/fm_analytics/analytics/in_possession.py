"""A tactic's "In Possession" phase settings, as set on the FM tactics screen.

Distinct from `TacticDefinition.instructions` (the pressing/tempo/passing
style strings scored by `assess_instruction_suitability` in
`tactical_system.py`): these are the concrete toggles and sliders a manager
actually sets on the tactics screen's In Possession tab. The **fixed** half
feeds scoring too, via `in_possession_instruction_strings` below; nothing
else here does -- see `analytics/CLAUDE.md`'s "In-possession settings"
section for the full picture.

The JSON is authored in two nested objects, one per kind, so the split is
visible in the file itself rather than only in this dataclass:

    "inPossession": {
        "fixed": {"attackingWidth": "Fairly Wide", ..., "selected": ["Play Out Of Defence"]},
        "dependsOnPlayers": {"crossingType": "Low", "selected": ["Overlap Left"]},
        "timeWasting": "Sometimes"
    }

Each instruction is one of the kinds FM's screen has (confirmed against FM20,
7 October 2026; see docs/tactical-system-roadmap.md item 4c):

- **Scales** (attacking width, passing directness, tempo, time wasting): one
  value, with a "Standard" or middle default.
- **A dropdown** (crossing type): one value, independent of everything else;
  "Mixed" is FM's default.
- **Toggles**, listed by FM name under `selected`: selected or not, where not
  selected is FM's own default, never a deliberate "No". Selecting some makes
  others unavailable (`IN_POSSESSION_CLASHES`), so no tactic may select both
  of a clashing pair, even across the fixed/player-dependent split.

Fields are split in three, per product decision:

- **Fixed** (the three scales and the fixed toggles): part of what makes this
  tactic *this* tactic, always hand-authored, `None` when the catalogue entry
  has not set it yet. `InPossessionSettings.missing_fixed_fields` (and
  `TacticDefinition.in_possession_missing_fields`, for a tactic with no block
  at all) is what the tactic page reads to flag a gap. A fixed value that also
  has a scored legacy instruction-string equivalent must not also appear
  literally in `instructions` -- `TacticDefinition.__post_init__` refuses
  that, so scoring can never double-count it.
- **Player-dependent** (crossing type and the player-dependent toggles): a
  real manager sets these by looking at which players are out there, not at
  the formation. Nothing computes them from a squad's attributes yet (roadmap
  item 4b); each is only a fallback until that lands, so none of these are
  ever required or flagged as missing, and none of them reach scoring.
- **Situational** (`time_wasting`): depends on the scoreline and the clock,
  not on the squad or the tactic, so it carries a default and is likewise
  never flagged as missing, and does not reach scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fm_analytics.analytics.instruction_toggles import check_clashes, check_names, unavailable

ATTACKING_WIDTH_OPTIONS = ("Very Narrow", "Fairly Narrow", "Standard", "Fairly Wide", "Very Wide")
PASSING_DIRECTNESS_OPTIONS = (
    "Much Shorter Passing", "Shorter Passing", "Slightly Shorter Passing", "Standard",
    "Slightly More Direct Passing", "More Direct Passing", "Much More Direct Passing",
)
TEMPO_OPTIONS = ("Much Lower Tempo", "Lower Tempo", "Standard", "Higher Tempo", "Much Higher Tempo")
TIME_WASTING_OPTIONS = ("Never", "Sometimes", "Frequently")
CROSSING_TYPE_OPTIONS = ("Mixed", "Floated", "Whipped", "Low")

# Toggles, by FM name, in the order the tactic page shows them.
FIXED_TOGGLES = (
    "Pass Into Space", "Play Out Of Defence", "Focus Play Through The Middle",
    "Focus Play Down The Left", "Focus Play Down The Right", "Work Ball Into Box",
)
PLAYER_DEPENDENT_TOGGLES = (
    "Overlap Left", "Underlap Left", "Overlap Right", "Underlap Right", "Shoot On Sight",
    "Hit Early Crosses", "Play For Set Pieces", "Dribble Less", "Run At Defence",
    "Be More Expressive", "Be More Disciplined",
)
# Selecting either makes the other unavailable on FM20's screen. Left and right
# focus may be selected together; Shoot On Sight and Hit Early Crosses too.
IN_POSSESSION_CLASHES = (
    ("Focus Play Through The Middle", "Focus Play Down The Left"),
    ("Focus Play Through The Middle", "Focus Play Down The Right"),
    ("Overlap Left", "Underlap Left"),
    ("Overlap Right", "Underlap Right"),
    ("Work Ball Into Box", "Hit Early Crosses"),
    ("Work Ball Into Box", "Shoot On Sight"),
    ("Dribble Less", "Run At Defence"),
    ("Be More Expressive", "Be More Disciplined"),
)
# Fixed toggles with an instruction-fit rule; focus play has none.
_SCORED_FIXED_TOGGLES = ("Pass Into Space", "Play Out Of Defence", "Work Ball Into Box")

_FIXED_FIELD_LABELS = (
    ("attacking_width", "attacking width"),
    ("passing_directness", "passing directness"),
    ("tempo", "tempo"),
    ("fixed_selected", "which instructions are selected"),
)

# The `inPossession` object's own two (plus one) keys, and each nested
# object's own keys. A key outside these is an error, not a silent no-op,
# per the catalogue's "no ignored config" rule (analytics/CLAUDE.md).
IN_POSSESSION_TOP_KEYS = frozenset({"fixed", "dependsOnPlayers", "timeWasting"})
IN_POSSESSION_FIXED_KEYS = frozenset({"attackingWidth", "passingDirectness", "tempo", "selected"})
IN_POSSESSION_DEPENDENT_KEYS = frozenset({"crossingType", "selected"})

# Every fixed field name, in display order, for a tactic with no `inPossession`
# block at all (see `TacticDefinition.in_possession_missing_fields`).
ALL_FIXED_FIELD_LABELS = tuple(label for _attribute, label in _FIXED_FIELD_LABELS)


@dataclass(frozen=True)
class InPossessionSettings:
    attacking_width: str | None = None
    passing_directness: str | None = None
    tempo: str | None = None
    # Fixed toggles this tactic selects; None until authored, () for none.
    fixed_selected: tuple[str, ...] | None = None
    time_wasting: str = "Sometimes"
    crossing_type: str = "Mixed"
    player_selected: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.attacking_width is not None and self.attacking_width not in ATTACKING_WIDTH_OPTIONS:
            raise ValueError(f"attackingWidth must be one of {ATTACKING_WIDTH_OPTIONS!r}")
        if (
            self.passing_directness is not None
            and self.passing_directness not in PASSING_DIRECTNESS_OPTIONS
        ):
            raise ValueError(f"passingDirectness must be one of {PASSING_DIRECTNESS_OPTIONS!r}")
        if self.tempo is not None and self.tempo not in TEMPO_OPTIONS:
            raise ValueError(f"tempo must be one of {TEMPO_OPTIONS!r}")
        if self.time_wasting not in TIME_WASTING_OPTIONS:
            raise ValueError(f"timeWasting must be one of {TIME_WASTING_OPTIONS!r}")
        if self.crossing_type not in CROSSING_TYPE_OPTIONS:
            raise ValueError(f"crossingType must be one of {CROSSING_TYPE_OPTIONS!r}")
        for name, selected, allowed in (
            ("fixed.selected", self.fixed_selected, FIXED_TOGGLES),
            ("dependsOnPlayers.selected", self.player_selected, PLAYER_DEPENDENT_TOGGLES),
        ):
            if selected is not None and not isinstance(selected, tuple):
                raise ValueError(f"{name} must be a tuple of instruction names")
            check_names(selected or (), allowed, name)
        check_clashes(self.selected, IN_POSSESSION_CLASHES, "inPossession")

    @property
    def selected(self) -> tuple[str, ...]:
        """Every selected toggle, fixed first, in screen order."""
        return (self.fixed_selected or ()) + self.player_selected

    @property
    def unavailable(self) -> dict[str, tuple[str, ...]]:
        """Each toggle a selection makes unavailable, with what locks it."""
        return unavailable(self.selected, IN_POSSESSION_CLASHES)

    @property
    def missing_fixed_fields(self) -> tuple[str, ...]:
        return tuple(
            label for attribute, label in _FIXED_FIELD_LABELS if getattr(self, attribute) is None
        )

    @property
    def is_complete(self) -> bool:
        return not self.missing_fixed_fields


def in_possession_instruction_strings(settings: InPossessionSettings | None) -> tuple[str, ...]:
    """The fixed settings that double as legacy `instructions` strings.

    Only the fixed half ever reaches scoring, and only where the value has a
    real FM-instruction-screen name that `tactical_system._INSTRUCTION_REQUIREMENTS`
    can key on: "Standard" is the enum's explicit "no instruction, this is the
    default" value (there is no such instruction to pick in FM), so it is
    skipped, the same as the field being unset. Focus play has no rule and is
    left out. Anything else -- including a fixed value with no requirements
    entry yet -- is passed through unfiltered, so
    `tests/test_tactical_calibration.py` catches a genuine gap rather than this
    function quietly hiding it.
    """
    if settings is None:
        return ()
    strings = [
        value
        for value in (settings.attacking_width, settings.passing_directness, settings.tempo)
        if value is not None and value != "Standard"
    ]
    strings.extend(name for name in settings.fixed_selected or () if name in _SCORED_FIXED_TOGGLES)
    return tuple(strings)


def in_possession_selected_instructions(settings: InPossessionSettings | None) -> tuple[str, ...]:
    """Selected instructions for presentation, including unscored ones.

    What an `instructionRationale` key may explain. Only the fixed half
    (`in_possession_instruction_strings`) ever reaches scoring; every other
    selected toggle appears here under its FM name, a non-Mixed crossing type
    as e.g. "Floated Crosses", and time wasting, which always has a value, as
    e.g. "Sometimes Time Wasting".
    """
    if settings is None:
        return ()
    strings = list(in_possession_instruction_strings(settings))
    strings.extend(name for name in settings.fixed_selected or () if name not in strings)
    if settings.crossing_type != "Mixed":
        strings.append(f"{settings.crossing_type} Crosses")
    strings.extend(settings.player_selected)
    strings.append(f"{settings.time_wasting} Time Wasting")
    return tuple(strings)


def in_possession_from_json(value: Any, tactic_key: str, *, only_known_keys) -> InPossessionSettings | None:
    """Parse a tactic's `inPossession` block.

    `only_known_keys` is the catalogue loader's own key-validator, passed in
    rather than imported, so this module stays a leaf the loader depends on
    (matching `attribute_taper.py`) instead of importing back from it.
    """
    if value is None:
        return None
    where = f"tactic {tactic_key!r} inPossession"
    if not isinstance(value, dict):
        raise ValueError(f"tactic {tactic_key!r}: inPossession must be an object")
    only_known_keys(value, IN_POSSESSION_TOP_KEYS, where)

    fixed = value.get("fixed", {})
    if not isinstance(fixed, dict):
        raise ValueError(f"tactic {tactic_key!r}: inPossession.fixed must be an object")
    only_known_keys(fixed, IN_POSSESSION_FIXED_KEYS, f"{where}.fixed")

    depends = value.get("dependsOnPlayers", {})
    if not isinstance(depends, dict):
        raise ValueError(f"tactic {tactic_key!r}: inPossession.dependsOnPlayers must be an object")
    only_known_keys(depends, IN_POSSESSION_DEPENDENT_KEYS, f"{where}.dependsOnPlayers")

    def _opt_str(source: dict, name: str, part: str) -> str | None:
        setting = source.get(name)
        if setting is not None and not isinstance(setting, str):
            raise ValueError(f"tactic {tactic_key!r}: inPossession.{part}.{name} must be a string")
        return setting

    def _selected(source: dict, part: str, elsewhere: tuple[str, ...], other: str) -> tuple[str, ...] | None:
        names = source.get("selected")
        if names is None:
            return None
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError(
                f"tactic {tactic_key!r}: inPossession.{part}.selected must be an array of "
                "instruction names (list only what is selected)"
            )
        misplaced = [name for name in names if name in elsewhere]
        if misplaced:
            raise ValueError(f"tactic {tactic_key!r}: {misplaced!r} belong in inPossession.{other}.selected")
        return tuple(names)

    time_wasting = value.get("timeWasting", "Sometimes")
    if not isinstance(time_wasting, str):
        raise ValueError(f"tactic {tactic_key!r}: inPossession.timeWasting must be a string")
    crossing_type = _opt_str(depends, "crossingType", "dependsOnPlayers")

    try:
        return InPossessionSettings(
            attacking_width=_opt_str(fixed, "attackingWidth", "fixed"),
            passing_directness=_opt_str(fixed, "passingDirectness", "fixed"),
            tempo=_opt_str(fixed, "tempo", "fixed"),
            fixed_selected=_selected(fixed, "fixed", PLAYER_DEPENDENT_TOGGLES, "dependsOnPlayers"),
            time_wasting=time_wasting,
            crossing_type="Mixed" if crossing_type is None else crossing_type,
            player_selected=_selected(depends, "dependsOnPlayers", FIXED_TOGGLES, "fixed") or (),
        )
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from error
