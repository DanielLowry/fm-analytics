"""A tactic's "In Possession" phase settings, as set on the FM tactics screen.

Distinct from `TacticDefinition.instructions` (the pressing/tempo/passing
style strings scored by `assess_instruction_suitability`): these are the
concrete toggles and sliders a manager actually sets on the tactics screen's
In Possession tab. None of it is scoring input -- see `analytics/CLAUDE.md`
on the manager-visible boundary and per-tactic attribute emphasis, which are
the only things that change a score.

Fields are split in three, per product decision:

- **Fixed** (`attacking_width` through `work_ball_into_box`): part of what
  makes this tactic *this* tactic, always hand-authored, `None` when the
  catalogue entry has not set it yet. `InPossessionSettings.missing_fixed_fields`
  (and `TacticDefinition.in_possession_missing_fields`, for a tactic with no
  block at all) is what the tactic page reads to flag a gap, since the
  product decision was to ship a few tactics fully rather than every field
  on every tactic at once.
- **Player-dependent** (`overlap_left` through `be_more_disciplined`): a real
  manager sets these by looking at which players are out there, not at the
  formation. The app does not yet compute them from a squad's attributes
  (see docs/tactical-system-roadmap.md); each field is only a fallback used
  until that lands, so none of these are ever required or flagged as missing.
- **Situational** (`time_wasting`): depends on the scoreline and the clock,
  not on the squad or the tactic, so it carries a default and is likewise
  never flagged as missing.
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

# Every JSON key the loader reads for an `inPossession` block. A key outside
# this is an error, not a silent no-op, per the catalogue's "no ignored
# config" rule (analytics/CLAUDE.md).
IN_POSSESSION_KEYS = frozenset({
    "attackingWidth", "passingDirectness", "tempo", "passIntoSpace", "playOutOfDefence",
    "focusPlay", "workBallIntoBox", "timeWasting", "overlapLeft", "overlapRight",
    "underlapLeft", "underlapRight", "crossingType", "shootOnSight", "hitEarlyCrosses",
    "playForSetPieces", "dribbleLess", "runAtDefence", "beMoreExpressive", "beMoreDisciplined",
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
    only_known_keys(value, IN_POSSESSION_KEYS, f"tactic {tactic_key!r} inPossession")

    def _opt_bool(name: str) -> bool | None:
        if name not in value:
            return None
        setting = value[name]
        if not isinstance(setting, bool):
            raise ValueError(f"tactic {tactic_key!r}: inPossession.{name} must be true/false")
        return setting

    def _bool(name: str, default: bool) -> bool:
        setting = _opt_bool(name)
        return default if setting is None else setting

    def _opt_str(name: str) -> str | None:
        setting = value.get(name)
        if setting is not None and not isinstance(setting, str):
            raise ValueError(f"tactic {tactic_key!r}: inPossession.{name} must be a string")
        return setting

    def _str_default(name: str, default: str) -> str:
        setting = _opt_str(name)
        return default if setting is None else setting

    return InPossessionSettings(
        attacking_width=_opt_str("attackingWidth"),
        passing_directness=_opt_str("passingDirectness"),
        tempo=_opt_str("tempo"),
        pass_into_space=_opt_bool("passIntoSpace"),
        play_out_of_defence=_opt_bool("playOutOfDefence"),
        focus_play=_opt_str("focusPlay"),
        work_ball_into_box=_opt_bool("workBallIntoBox"),
        time_wasting=_str_default("timeWasting", "Sometimes"),
        overlap_left=_bool("overlapLeft", False),
        overlap_right=_bool("overlapRight", False),
        underlap_left=_bool("underlapLeft", False),
        underlap_right=_bool("underlapRight", False),
        crossing_type=_str_default("crossingType", "Mixed"),
        shoot_on_sight=_bool("shootOnSight", False),
        hit_early_crosses=_bool("hitEarlyCrosses", False),
        play_for_set_pieces=_bool("playForSetPieces", False),
        dribble_less=_bool("dribbleLess", False),
        run_at_defence=_bool("runAtDefence", False),
        be_more_expressive=_bool("beMoreExpressive", False),
        be_more_disciplined=_bool("beMoreDisciplined", False),
    )
