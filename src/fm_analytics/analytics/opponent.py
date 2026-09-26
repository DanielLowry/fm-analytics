"""The opponent, as the manager estimates them, and what that changes.

An `OpponentProfile` is a handful of sliders, each -2..+2 and 0 by default. It
is the manager's own read of the opposition (league position, scouting
report, recent games), never derived from hidden Current/Potential Ability.
"Quality" in particular is relative to *us*, which is only knowable by the
manager.

An opponent changes tactic choice in two ways, and both feed the one ranking
rather than being scored separately:

* `attribute_emphasis` -- what each job asks of whoever plays it. Same
  mechanism as a tactic's own emphasis (deltas on a role's existing weights,
  summed, clamped 0-10), so it can change *who is picked*.
* `system_floors` -- what the eleven's roles must jointly supply against this
  side, as absolute minimums (not increments on a tactic's own, which would
  penalise a deliberately open tactic and a deliberately tight one alike).
  `assess_opponent_fit` scores that, reusing the instruction-fit machinery.

Everything below is declared football hypothesis, in the same spirit as
`_INSTRUCTION_REQUIREMENTS`: reviewable data, not fitted numbers. A neutral
profile produces no emphasis and no floors, so it changes nothing.

## Adding a slider

Each axis is one `OpponentAxis` entry in `AXIS_DEFINITIONS`, carrying its own
labels, its own emphasis rules and its own floors -- nothing about adding one
touches the scoring code below. Two steps, both required:

1. Add a field to `OpponentProfile` (the slider itself).
2. Add its `OpponentAxis` entry to `AXIS_DEFINITIONS` (its labels and effects).

Forgetting either half fails at import time (`_check_profile_matches_axes`),
not silently: a slider with nowhere to store its value, or a stored value
with no declared effect, is a bug the module refuses to load with.

This shape is for another *scalar* slider -- something that is more or less
true by degree. Likely formation is kept as a categorical choice alongside
the axes rather than being forced into a -2..+2 scale.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from collections.abc import Iterable, Mapping
from typing import Sequence

from fm_analytics.analytics.catalogue import AttributeEmphasis
from fm_analytics.analytics.opponent_rules import (
    BACK_LINE as _BACK_LINE,
    DEFENCE_AND_MIDFIELD as _DEFENCE_AND_MIDFIELD,
    FORMATION_DEFINITIONS,
    FORMATIONS_BY_KEY,
    EmphasisRule,
    FloorRule,
    OpponentFormation,
)
from fm_analytics.analytics.opponent_details import (
    ATTRIBUTES_BY_KEY,
    AXIS_DETAIL_OVERRIDES,
    POSITIONS_BY_KEY,
)
from fm_analytics.analytics.role_scoring import RoleDefinition
from fm_analytics.analytics.tactical_system import SystemAssessment, assess_demands

AXIS_MINIMUM = -2
AXIS_MAXIMUM = 2


def _normalise_observations(
    observations: Mapping[str, int] | Iterable[tuple[str, int]],
    definitions: Mapping[str, object],
    kind: str,
) -> tuple[tuple[str, int], ...]:
    """Validate and canonicalise sparse observations for hashing and URLs."""
    items = observations.items() if isinstance(observations, Mapping) else observations
    values: dict[str, int] = {}
    try:
        for key, value in items:
            if key not in definitions:
                raise ValueError(f"unknown opponent {kind} {key!r}")
            if key in values:
                raise ValueError(f"duplicate opponent {kind} {key!r}")
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"opponent {kind} {key!r} must be a whole number")
            if not AXIS_MINIMUM <= value <= AXIS_MAXIMUM:
                raise ValueError(
                    f"opponent {kind} {key!r} must be between "
                    f"{AXIS_MINIMUM} and {AXIS_MAXIMUM}"
                )
            values[key] = value
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"opponent {kind} observations must be key/value pairs") from exc
    return tuple((key, values[key]) for key in definitions if values.get(key))


@dataclass(frozen=True)
class OpponentProfile:
    """The manager's likely formation plus one value per scalar axis."""

    formation: str = "unknown"
    quality: int = 0
    defensive_line: int = 0
    pressing: int = 0
    attacking_width: int = 0
    aerial_threat: int = 0
    pace_in_behind: int = 0
    chance_creation: int = 0
    dribbling_quality: int = 0
    finishing_quality: int = 0
    attribute_levels: tuple[tuple[str, int], ...] = ()
    position_levels: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if self.formation not in FORMATIONS_BY_KEY:
            raise ValueError(f"unknown opponent formation {self.formation!r}")
        for axis in AXES:
            value = getattr(self, axis)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"opponent {axis} must be a whole number")
            if not AXIS_MINIMUM <= value <= AXIS_MAXIMUM:
                raise ValueError(
                    f"opponent {axis} must be between {AXIS_MINIMUM} and {AXIS_MAXIMUM}"
                )
        object.__setattr__(
            self,
            "attribute_levels",
            _normalise_observations(
                self.attribute_levels, ATTRIBUTES_BY_KEY, "attribute"
            ),
        )
        object.__setattr__(
            self,
            "position_levels",
            _normalise_observations(self.position_levels, POSITIONS_BY_KEY, "position"),
        )

    @classmethod
    def neutral(cls) -> "OpponentProfile":
        return cls()

    @property
    def is_neutral(self) -> bool:
        return (
            self.formation == "unknown"
            and not self.attribute_levels
            and not self.position_levels
            and not any(getattr(self, axis) for axis in AXES)
        )




@dataclass(frozen=True)
class OpponentAxis:
    """One slider: its labels, and everything it declares as a consequence.

    `low`/`high` are what -2 and +2 mean, in the manager's language, for the
    eventual CLI flag and web slider to show -- not scoring input themselves.
    """

    key: str
    label: str
    low: str
    high: str
    emphasis: tuple[EmphasisRule, ...] = ()
    floors: tuple[FloorRule, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.low or not self.high:
            raise ValueError("an opponent axis needs a key, a label, and both end labels")


# Declared football hypotheses, in the same spirit as `_INSTRUCTION_REQUIREMENTS`:
# reviewable data, not fitted numbers. Floors are set against what the catalogue
# can actually supply (tested): one step is reachable by essentially every
# tactic, two steps by most. A tactic that still falls short at two steps is
# structurally poor at that job (an all-out attacking 4-3-3 against a much
# stronger side), which is the point.
AXIS_DEFINITIONS: tuple[OpponentAxis, ...] = (
    OpponentAxis(
        key="quality",
        label="Quality",
        low="much weaker than us",
        high="much stronger than us",
        # Quality says nothing about who specifically to pick -- only about
        # how solid or how open the system as a whole must be.
        floors=(
            FloorRule(
                +1,
                ({"defensiveCover": 5.0, "restDefence": 5.0}, {"defensiveCover": 6.5, "restDefence": 6.5}),
                why="A better side punishes gaps; the system needs to be solid before it can be ambitious.",
            ),
            FloorRule(
                -1,
                ({"penetration": 1.5, "boxPresence": 1.5}, {"penetration": 2.0, "boxPresence": 2.0}),
                why="A weaker side should be made to work; a system with no penetration wastes the advantage.",
            ),
        ),
    ),
    OpponentAxis(
        key="defensive_line",
        label="Defensive line",
        low="deep block",
        high="high line",
        emphasis=(
            EmphasisRule(
                +1, ("pace", "acceleration", "offTheBall"), ("ST", "AML", "AMR"),
                why="A high line leaves space behind it for forwards who can get there.",
            ),
            EmphasisRule(
                -1, ("vision", "technique", "dribbling"), ("AMC", "MC", "AML", "AMR"),
                why="A deep block has to be opened up, not run in behind.",
            ),
        ),
        floors=(
            FloorRule(
                +1,
                ({"runners": 2.5, "penetration": 1.5}, {"runners": 3.0, "penetration": 2.0}),
                why="A high line is there to be exploited by runners in behind.",
            ),
            FloorRule(
                -1,
                ({"creativity": 1.0, "boxPresence": 1.5}, {"creativity": 1.5, "boxPresence": 2.0}),
                why="A deep block needs unlocking with creativity and bodies in the box, not pace in behind.",
            ),
        ),
    ),
    OpponentAxis(
        key="pressing",
        label="Pressing",
        low="passive",
        high="heavy press",
        emphasis=(
            EmphasisRule(
                +1, ("composure", "firstTouch", "passing"), _DEFENCE_AND_MIDFIELD,
                why="A heavy press is beaten by players who keep the ball under pressure.",
            ),
            EmphasisRule(
                -1, ("composure", "firstTouch"), _DEFENCE_AND_MIDFIELD,
                why="Against a passive press there is time on the ball.",
            ),
        ),
        floors=(
            FloorRule(
                +1,
                ({"ballProgression": 4.0}, {"ballProgression": 4.5}),
                why="Beating a press is a ball-progression problem for the whole system, not one player's.",
            ),
        ),
    ),
    OpponentAxis(
        key="attacking_width",
        label="Attacking width",
        low="central threat",
        high="wide threat",
        emphasis=(
            EmphasisRule(
                +1, ("marking", "tackling", "positioning"), ("DL", "DR", "WBL", "WBR"),
                why="Wide threats are the full-backs' problem first.",
            ),
            EmphasisRule(
                -1, ("marking", "tackling", "positioning"), ("DC", "DM"),
                why="A central threat is the centre-backs' and holding midfielder's problem.",
            ),
        ),
        floors=(
            FloorRule(
                +1,
                ({"restDefence": 5.0}, {"restDefence": 6.0}),
                why="A wide threat is countered by cover behind advancing full-backs, not by the full-backs alone.",
            ),
            FloorRule(
                -1,
                ({"defensiveCover": 5.0}, {"defensiveCover": 6.0}),
                why="A central threat is countered by cover through the middle.",
            ),
        ),
    ),
    OpponentAxis(
        key="aerial_threat",
        label="Aerial threat",
        low="negligible",
        high="dominant",
        # No system floor: the system model has no aerial-defence dimension,
        # so aerial threat acts entirely through who is picked.
        emphasis=(
            EmphasisRule(
                +1, ("heading", "jumpingReach", "strength"), ("DC",),
                why="Someone has to win the ball in the air against them.",
            ),
            EmphasisRule(
                +1, ("aerialReach", "commandOfArea"), ("GK",),
                why="Crosses and long balls come to the keeper too.",
            ),
            EmphasisRule(
                -1, ("heading", "jumpingReach"), ("DC",),
                why="With no aerial threat, aerial ability is worth less at the back.",
            ),
        ),
    ),
    OpponentAxis(
        key="pace_in_behind",
        label="Pace in behind",
        low="slow",
        high="very fast",
        emphasis=(
            EmphasisRule(
                +1, ("pace", "acceleration", "anticipation"), _BACK_LINE,
                why="Quick forwards punish a back line that cannot turn or recover.",
            ),
            EmphasisRule(
                -1, ("pace", "acceleration"), _BACK_LINE,
                why="Against slow forwards, recovery pace is worth less.",
            ),
        ),
        floors=(
            FloorRule(
                +1,
                ({"defensiveCover": 5.0, "restDefence": 5.0}, {"defensiveCover": 6.5, "restDefence": 6.5}),
                why="Pace in behind is a defensive-cover problem for the whole system, not one defender's.",
            ),
        ),
    ),
    OpponentAxis(
        key="chance_creation",
        label="Chance creation",
        low="creates very little",
        high="creates many chances",
        emphasis=(
            EmphasisRule(
                +1,
                ("anticipation", "concentration", "decisions", "positioning"),
                _DEFENCE_AND_MIDFIELD,
                why="Frequent attacks reward defenders who read danger repeatedly and reliably.",
            ),
            EmphasisRule(
                +1, ("reflexes", "oneOnOnes", "handling"), ("GK",),
                why="A side that creates repeatedly puts more weight on shot stopping.",
            ),
            EmphasisRule(
                -1, ("anticipation", "concentration"), _DEFENCE_AND_MIDFIELD,
                why="A low-output attack places less repeated decision pressure on the defensive unit.",
            ),
        ),
        floors=(
            FloorRule(
                +1,
                ({"defensiveCover": 5.0, "restDefence": 5.0}, {"defensiveCover": 6.5, "restDefence": 6.5}),
                why="A high-volume attack must be denied repeat entries by the whole defensive structure.",
            ),
        ),
    ),
    OpponentAxis(
        key="dribbling_quality",
        label="Dribbling",
        low="poor dribblers",
        high="dangerous dribblers",
        emphasis=(
            EmphasisRule(
                +1, ("tackling", "agility", "anticipation", "positioning"),
                _DEFENCE_AND_MIDFIELD,
                why="Dangerous carriers demand defenders who can stay with them and time a challenge.",
            ),
            EmphasisRule(
                -1, ("tackling", "agility"), _DEFENCE_AND_MIDFIELD,
                why="Poor dribblers reduce the premium on one-versus-one defending.",
            ),
        ),
        floors=(
            FloorRule(
                +1,
                ({"defensiveCover": 5.0}, {"defensiveCover": 6.0}),
                why="A beaten first defender needs reliable cover behind them.",
            ),
        ),
    ),
    OpponentAxis(
        key="finishing_quality",
        label="Finishing",
        low="wasteful finishers",
        high="clinical finishers",
        emphasis=(
            EmphasisRule(
                +1, ("reflexes", "oneOnOnes", "handling"), ("GK",),
                why="Clinical finishers increase the value of the goalkeeper's shot stopping.",
            ),
            EmphasisRule(
                +1, ("concentration", "anticipation", "marking"), ("DC", "DM"),
                why="Clinical forwards must be denied clean shots rather than given second chances.",
            ),
            EmphasisRule(
                -1, ("reflexes", "oneOnOnes"), ("GK",),
                why="Wasteful finishing slightly reduces the shot-stopping premium.",
            ),
        ),
        floors=(
            FloorRule(
                +1,
                ({"defensiveCover": 5.0}, {"defensiveCover": 6.0}),
                why="Against clinical finishers, the system must prevent clear chances rather than trade them.",
            ),
        ),
    ),
)

AXES = tuple(axis.key for axis in AXIS_DEFINITIONS)


def _check_profile_matches_axes() -> None:
    """Every `OpponentProfile` field must have an axis, and vice versa.

    This is the guardrail that makes adding a slider a two-step, not a
    one-step-that-silently-does-nothing, change: a field with no axis has no
    declared effect, and an axis with no field has nowhere to read its value
    from. Either half missing fails right here, at import, not in a test you
    might not run. Reads `AXIS_DEFINITIONS` fresh (rather than some cached
    derivative of it) so a test can also call this directly against a
    tampered module and see the same check the import ran.
    """
    profile_fields = frozenset(
        field.name
        for field in fields(OpponentProfile)
        if field.name not in {"formation", "attribute_levels", "position_levels"}
    )
    axis_keys = frozenset(axis.key for axis in AXIS_DEFINITIONS)
    if profile_fields != axis_keys:
        raise AssertionError(
            "OpponentProfile fields and AXIS_DEFINITIONS keys must match exactly: "
            f"fields only={sorted(profile_fields - axis_keys)} "
            f"axes only={sorted(axis_keys - profile_fields)}"
        )


_check_profile_matches_axes()


def _steps(profile: OpponentProfile, axis_key: str, sign: int) -> int:
    value = getattr(profile, axis_key)
    return value if sign > 0 and value > 0 else -value if sign < 0 and value < 0 else 0


def _axis_is_overridden(profile: OpponentProfile, axis_key: str) -> bool:
    observed = {key for key, _value in profile.attribute_levels}
    return bool(observed & AXIS_DETAIL_OVERRIDES.get(axis_key, frozenset()))


def _observation_blocks(levels, definitions) -> list[AttributeEmphasis]:
    blocks: list[AttributeEmphasis] = []
    for key, value in levels:
        definition = definitions[key]
        rules = definition.strong if value > 0 else definition.weak
        for rule in rules:
            blocks.append(
                AttributeEmphasis(
                    {
                        attribute: rule.per_step * abs(value)
                        for attribute in rule.attributes
                    },
                    rule.positions,
                )
            )
    return blocks


def attribute_emphasis(profile: OpponentProfile) -> tuple[AttributeEmphasis, ...]:
    """The position-scoped emphasis blocks this opponent asks for."""
    blocks = []
    for axis in AXIS_DEFINITIONS:
        if _axis_is_overridden(profile, axis.key):
            continue
        for rule in axis.emphasis:
            steps = _steps(profile, axis.key, rule.sign)
            if steps:
                blocks.append(
                    AttributeEmphasis(
                        {attribute: rule.per_step * steps for attribute in rule.attributes},
                        rule.positions,
                    )
                )
    formation = FORMATIONS_BY_KEY[profile.formation]
    for rule in formation.emphasis:
        blocks.append(
            AttributeEmphasis(
                {attribute: rule.per_step for attribute in rule.attributes},
                rule.positions,
            )
        )
    blocks.extend(_observation_blocks(profile.attribute_levels, ATTRIBUTES_BY_KEY))
    blocks.extend(_observation_blocks(profile.position_levels, POSITIONS_BY_KEY))
    return tuple(blocks)


def system_floors(profile: OpponentProfile) -> dict[str, float]:
    """What the eleven's roles must supply against this opponent."""
    floors: dict[str, float] = {}
    for axis in AXIS_DEFINITIONS:
        if _axis_is_overridden(profile, axis.key):
            continue
        for rule in axis.floors:
            steps = _steps(profile, axis.key, rule.sign)
            if not steps:
                continue
            for dimension, floor in rule.floors[steps - 1].items():
                floors[dimension] = max(floors.get(dimension, 0.0), floor)
    for rule in FORMATIONS_BY_KEY[profile.formation].floors:
        for dimension, floor in rule.floors[0].items():
            floors[dimension] = max(floors.get(dimension, 0.0), floor)
    return floors


def assess_opponent_fit(
    roles: Sequence[RoleDefinition], profile: OpponentProfile
) -> SystemAssessment:
    """Whether these roles jointly supply what this opponent asks of a system.

    Inactive for a neutral profile (and for any profile that asks for nothing),
    so it drops out of a blend instead of diluting it.
    """
    return assess_demands(roles, system_floors(profile))
