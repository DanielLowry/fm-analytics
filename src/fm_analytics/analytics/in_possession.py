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
        "fixed": {"attackingWidth": "Fairly Wide", ...},
        "dependsOnPlayers": {"overlapLeft": true, ...},
        "timeWasting": "Sometimes"
    }

Fields are split in three, per product decision:

- **Fixed** (`attacking_width` through `work_ball_into_box`): part of what
  makes this tactic *this* tactic, always hand-authored, `None` when the
  catalogue entry has not set it yet. `InPossessionSettings.missing_fixed_fields`
  (and `TacticDefinition.in_possession_missing_fields`, for a tactic with no
  block at all) is what the tactic page reads to flag a gap, since the
  product decision was to ship a few tactics fully rather than every field
  on every tactic at once. A fixed value that also has a scored legacy
  instruction-string equivalent (attacking width, passing directness, tempo,
  pass into space, play out of defence, work ball into box) must not also
  appear literally in `instructions` -- `TacticDefinition.__post_init__`
  refuses that, so scoring can never double-count it.
- **Player-dependent** (`overlap_left` through `be_more_disciplined`): a real
  manager sets these by looking at which players are out there, not at the
  formation. The app does not yet compute them from a squad's attributes
  (see docs/tactical-system-roadmap.md); each field is only a fallback used
  until that lands, so none of these are ever required or flagged as missing,
  and none of them reach scoring.
- **Situational** (`time_wasting`): depends on the scoreline and the clock,
  not on the squad or the tactic, so it carries a default and is likewise
  never flagged as missing, and does not reach scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ATTACKING_WIDTH_OPTIONS = ("Very Narrow", "Fairly Narrow", "Standard", "Fairly Wide", "Very Wide")
PASSING_DIRECTNESS_OPTIONS = (
    "Much Shorter Passing", "Shorter Passing", "Slightly Shorter Passing", "Standard",
    "Slightly More Direct Passing", "More Direct Passing", "Much More Direct Passing",
)
TEMPO_OPTIONS = ("Much Lower Tempo", "Lower Tempo", "Standard", "Higher Tempo", "Much Higher Tempo")
FOCUS_PLAY_OPTIONS = ("Balanced", "Through the Middle", "Down the Left", "Down the Right")
TIME_WASTING_OPTIONS = ("Never", "Sometimes", "Frequently")
CROSSING_TYPE_OPTIONS = ("Mixed", "Floated", "Whipped", "Low")

_FIXED_FIELD_LABELS = (
    ("attacking_width", "attacking width"),
    ("passing_directness", "passing directness"),
    ("tempo", "tempo"),
    ("pass_into_space", "pass into space"),
    ("play_out_of_defence", "play out of defence"),
    ("focus_play", "focus play"),
    ("work_ball_into_box", "work ball into box"),
)

# The `inPossession` object's own two (plus one) keys, and each nested
# object's own keys. A key outside these is an error, not a silent no-op,
# per the catalogue's "no ignored config" rule (analytics/CLAUDE.md).
IN_POSSESSION_TOP_KEYS = frozenset({"fixed", "dependsOnPlayers", "timeWasting"})
IN_POSSESSION_FIXED_KEYS = frozenset({
    "attackingWidth", "passingDirectness", "tempo", "passIntoSpace",
    "playOutOfDefence", "focusPlay", "workBallIntoBox",
})
IN_POSSESSION_DEPENDENT_KEYS = frozenset({
    "overlapLeft", "overlapRight", "underlapLeft", "underlapRight", "crossingType",
    "shootOnSight", "hitEarlyCrosses", "playForSetPieces", "dribbleLess", "runAtDefence",
    "beMoreExpressive", "beMoreDisciplined",
})

# Every fixed field name, in display order, for a tactic with no `inPossession`
# block at all (see `TacticDefinition.in_possession_missing_fields`).
ALL_FIXED_FIELD_LABELS = tuple(label for _attribute, label in _FIXED_FIELD_LABELS)


@dataclass(frozen=True)
class InPossessionSettings:
    attacking_width: str | None = None
    passing_directness: str | None = None
    tempo: str | None = None
    pass_into_space: bool | None = None
    play_out_of_defence: bool | None = None
    focus_play: str | None = None
    work_ball_into_box: bool | None = None
    time_wasting: str = "Sometimes"
    overlap_left: bool = False
    overlap_right: bool = False
    underlap_left: bool = False
    underlap_right: bool = False
    crossing_type: str = "Mixed"
    shoot_on_sight: bool = False
    hit_early_crosses: bool = False
    play_for_set_pieces: bool = False
    dribble_less: bool = False
    run_at_defence: bool = False
    be_more_expressive: bool = False
    be_more_disciplined: bool = False

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
        if self.focus_play is not None and self.focus_play not in FOCUS_PLAY_OPTIONS:
            raise ValueError(f"focusPlay must be one of {FOCUS_PLAY_OPTIONS!r}")
        if self.time_wasting not in TIME_WASTING_OPTIONS:
            raise ValueError(f"timeWasting must be one of {TIME_WASTING_OPTIONS!r}")
        if self.crossing_type not in CROSSING_TYPE_OPTIONS:
            raise ValueError(f"crossingType must be one of {CROSSING_TYPE_OPTIONS!r}")
        if self.overlap_left and self.underlap_left:
            raise ValueError("cannot set both overlapLeft and underlapLeft: same side, opposite runs")
        if self.overlap_right and self.underlap_right:
            raise ValueError("cannot set both overlapRight and underlapRight: same side, opposite runs")
        if self.dribble_less and self.run_at_defence:
            raise ValueError("dribbleLess and runAtDefence are opposite ends of one setting")
        if self.be_more_expressive and self.be_more_disciplined:
            raise ValueError("beMoreExpressive and beMoreDisciplined are opposite ends of one setting")

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
    skipped, the same as the field being unset. Anything else -- including a
    fixed value with no requirements entry yet -- is passed through
    unfiltered, so `tests/test_tactical_calibration.py` catches a genuine gap
    rather than this function quietly hiding it.
    """
    if settings is None:
        return ()
    strings = [
        value
        for value in (settings.attacking_width, settings.passing_directness, settings.tempo)
        if value is not None and value != "Standard"
    ]
    if settings.pass_into_space:
        strings.append("Pass Into Space")
    if settings.play_out_of_defence:
        strings.append("Play Out Of Defence")
    if settings.work_ball_into_box:
        strings.append("Work Ball Into Box")
    return tuple(strings)


_PLAYER_DEPENDENT_INSTRUCTIONS = (
    ("overlap_left", "Overlap Left"),
    ("overlap_right", "Overlap Right"),
    ("underlap_left", "Underlap Left"),
    ("underlap_right", "Underlap Right"),
    ("shoot_on_sight", "Shoot On Sight"),
    ("hit_early_crosses", "Hit Early Crosses"),
    ("play_for_set_pieces", "Play For Set Pieces"),
    ("dribble_less", "Dribble Less"),
    ("run_at_defence", "Run At Defence"),
    ("be_more_expressive", "Be More Expressive"),
    ("be_more_disciplined", "Be More Disciplined"),
)


def in_possession_selected_instructions(settings: InPossessionSettings | None) -> tuple[str, ...]:
    """Selected instructions for presentation, including unscored player-dependent ones.

    What an `instructionRationale` key may explain. Only the fixed half
    (`in_possession_instruction_strings`) ever reaches scoring; a
    player-dependent choice appears here under its FM instruction name, and a
    non-Mixed crossing type as e.g. "Floated Crosses".
    """
    if settings is None:
        return ()
    strings = list(in_possession_instruction_strings(settings))
    if settings.crossing_type != "Mixed":
        strings.append(f"{settings.crossing_type} Crosses")
    strings.extend(label for attribute, label in _PLAYER_DEPENDENT_INSTRUCTIONS if getattr(settings, attribute))
    return tuple(strings)


def in_possession_from_json(value: Any, tactic_key: str, *, only_known_keys) -> InPossessionSettings | None:
    """Parse a tactic's `inPossession` block.

    `only_known_keys` is the catalogue loader's own key-validator, passed in
    rather than imported, so this module stays a leaf the loader depends on
    (matching `attribute_taper.py`) instead of importing back from it.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"tactic {tactic_key!r}: inPossession must be an object")
    only_known_keys(value, IN_POSSESSION_TOP_KEYS, f"tactic {tactic_key!r} inPossession")

    fixed = value.get("fixed", {})
    if not isinstance(fixed, dict):
        raise ValueError(f"tactic {tactic_key!r}: inPossession.fixed must be an object")
    only_known_keys(fixed, IN_POSSESSION_FIXED_KEYS, f"tactic {tactic_key!r} inPossession.fixed")

    depends = value.get("dependsOnPlayers", {})
    if not isinstance(depends, dict):
        raise ValueError(f"tactic {tactic_key!r}: inPossession.dependsOnPlayers must be an object")
    only_known_keys(
        depends, IN_POSSESSION_DEPENDENT_KEYS, f"tactic {tactic_key!r} inPossession.dependsOnPlayers"
    )

    def _opt_bool(source: dict, name: str, where: str) -> bool | None:
        if name not in source:
            return None
        setting = source[name]
        if not isinstance(setting, bool):
            raise ValueError(f"tactic {tactic_key!r}: inPossession.{where}.{name} must be true/false")
        return setting

    def _bool(source: dict, name: str, where: str, default: bool) -> bool:
        setting = _opt_bool(source, name, where)
        return default if setting is None else setting

    def _opt_str(source: dict, name: str, where: str) -> str | None:
        setting = source.get(name)
        if setting is not None and not isinstance(setting, str):
            raise ValueError(f"tactic {tactic_key!r}: inPossession.{where}.{name} must be a string")
        return setting

    def _str_default(source: dict, name: str, where: str, default: str) -> str:
        setting = _opt_str(source, name, where)
        return default if setting is None else setting

    time_wasting = value.get("timeWasting", "Sometimes")
    if not isinstance(time_wasting, str):
        raise ValueError(f"tactic {tactic_key!r}: inPossession.timeWasting must be a string")

    return InPossessionSettings(
        attacking_width=_opt_str(fixed, "attackingWidth", "fixed"),
        passing_directness=_opt_str(fixed, "passingDirectness", "fixed"),
        tempo=_opt_str(fixed, "tempo", "fixed"),
        pass_into_space=_opt_bool(fixed, "passIntoSpace", "fixed"),
        play_out_of_defence=_opt_bool(fixed, "playOutOfDefence", "fixed"),
        focus_play=_opt_str(fixed, "focusPlay", "fixed"),
        work_ball_into_box=_opt_bool(fixed, "workBallIntoBox", "fixed"),
        time_wasting=time_wasting,
        overlap_left=_bool(depends, "overlapLeft", "dependsOnPlayers", False),
        overlap_right=_bool(depends, "overlapRight", "dependsOnPlayers", False),
        underlap_left=_bool(depends, "underlapLeft", "dependsOnPlayers", False),
        underlap_right=_bool(depends, "underlapRight", "dependsOnPlayers", False),
        crossing_type=_str_default(depends, "crossingType", "dependsOnPlayers", "Mixed"),
        shoot_on_sight=_bool(depends, "shootOnSight", "dependsOnPlayers", False),
        hit_early_crosses=_bool(depends, "hitEarlyCrosses", "dependsOnPlayers", False),
        play_for_set_pieces=_bool(depends, "playForSetPieces", "dependsOnPlayers", False),
        dribble_less=_bool(depends, "dribbleLess", "dependsOnPlayers", False),
        run_at_defence=_bool(depends, "runAtDefence", "dependsOnPlayers", False),
        be_more_expressive=_bool(depends, "beMoreExpressive", "dependsOnPlayers", False),
        be_more_disciplined=_bool(depends, "beMoreDisciplined", "dependsOnPlayers", False),
    )
