"""Detailed opponent observations and their declared tactical responses."""

from __future__ import annotations

from dataclasses import dataclass
import re

from fm_analytics.analytics.opponent_rules import (
    BACK_LINE,
    DEFENCE_AND_MIDFIELD,
    EmphasisRule,
)


@dataclass(frozen=True)
class OpponentAttribute:
    key: str
    group: str
    strong: tuple[EmphasisRule, ...]
    weak: tuple[EmphasisRule, ...]

    @property
    def label(self) -> str:
        spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", self.key)
        return spaced.title().replace("One On Ones", "One-on-ones")

    @property
    def query_key(self) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", self.key).lower()


@dataclass(frozen=True)
class OpponentPosition:
    key: str
    label: str
    strong: tuple[EmphasisRule, ...]
    weak: tuple[EmphasisRule, ...]


def _rule(sign: int, attributes: tuple[str, ...], positions: tuple[str, ...], why: str):
    return (EmphasisRule(sign, attributes, positions, why=why),)


def _attribute(key: str, group: str, family: str) -> OpponentAttribute:
    strong_attributes, strong_positions, weak_attributes, weak_positions, description = (
        _RESPONSE_FAMILIES[family]
    )
    return OpponentAttribute(
        key,
        group,
        _rule(+1, strong_attributes, strong_positions, f"Their strong {description} must be countered."),
        _rule(-1, weak_attributes, weak_positions, f"Their weak {description} can be exploited."),
    )


_WIDE_DEFENDERS = ("DL", "DR", "WBL", "WBR")
_CREATORS = ("MC", "AMC", "AML", "AMR")
_ATTACKERS = ("ST", "AMC", "AML", "AMR")

# Each family describes attributes we need when the opponent is strong and
# attributes that exploit them when weak. Observation attributes need not be
# role-scoring attributes themselves (leadership is the obvious example), but
# every response attribute must be one our role model can score.
_RESPONSE_FAMILIES = {
    "carrier": (
        ("tackling", "agility", "anticipation", "positioning"), DEFENCE_AND_MIDFIELD,
        ("dribbling", "pace", "offTheBall"), _ATTACKERS, "ball carrying",
    ),
    "movement": (
        ("marking", "anticipation", "concentration", "pace"), BACK_LINE,
        ("pace", "acceleration", "offTheBall"), _ATTACKERS, "movement",
    ),
    "finishing": (
        ("reflexes", "oneOnOnes", "handling"), ("GK",),
        ("finishing", "composure", "offTheBall"), _ATTACKERS, "finishing",
    ),
    "creation": (
        ("anticipation", "positioning", "concentration", "workRate"), DEFENCE_AND_MIDFIELD,
        ("passing", "vision", "offTheBall"), _CREATORS, "chance creation",
    ),
    "delivery": (
        ("marking", "positioning", "heading"), ("DC", "DL", "DR", "DM"),
        ("crossing", "heading", "jumpingReach"), ("ST", "AML", "AMR"), "delivery",
    ),
    "aerial": (
        ("heading", "jumpingReach", "strength"), ("DC",),
        ("crossing", "heading", "jumpingReach"), ("ST", "AML", "AMR"), "aerial play",
    ),
    "long_shots": (
        ("reflexes", "handling"), ("GK",),
        ("longShots", "technique", "composure"), ("MC", "AMC", "ST"), "long shooting",
    ),
    "defending": (
        ("dribbling", "technique", "offTheBall", "composure"), _ATTACKERS,
        ("pace", "dribbling", "offTheBall", "finishing"), _ATTACKERS, "defending",
    ),
    "pressing": (
        ("composure", "firstTouch", "passing"), ("DC", "DL", "DR", "DM", "MC"),
        ("aggression", "anticipation", "stamina", "workRate"), DEFENCE_AND_MIDFIELD,
        "collective intensity",
    ),
    "physical": (
        ("strength", "balance", "stamina"), DEFENCE_AND_MIDFIELD,
        ("pace", "acceleration", "agility"), _ATTACKERS, "physical strength",
    ),
    "set_piece": (
        ("anticipation", "concentration", "heading"), ("DC", "DM", "GK"),
        ("heading", "jumpingReach", "strength"), ("DC", "ST"), "set pieces",
    ),
    "gk_shot": (
        ("finishing", "composure", "offTheBall"), _ATTACKERS,
        ("finishing", "longShots", "technique"), ("ST", "AMC", "MC"), "shot stopping",
    ),
    "gk_area": (
        ("dribbling", "passing", "vision"), _CREATORS,
        ("crossing", "heading", "jumpingReach"), ("AML", "AMR", "ST"), "area control",
    ),
    "gk_distribution": (
        ("anticipation", "positioning", "workRate"), DEFENCE_AND_MIDFIELD,
        ("aggression", "anticipation", "stamina"), ("ST", "AMC", "MC"), "distribution",
    ),
}


_ATTRIBUTE_FAMILIES = {
    "Technical": {
        "corners": "set_piece", "crossing": "delivery", "dribbling": "carrier",
        "finishing": "finishing", "firstTouch": "creation", "freeKickTaking": "set_piece",
        "heading": "aerial", "longShots": "long_shots", "longThrows": "set_piece",
        "marking": "defending", "passing": "creation", "penaltyTaking": "finishing",
        "tackling": "defending", "technique": "carrier",
    },
    "Mental": {
        "aggression": "pressing", "anticipation": "defending", "bravery": "aerial",
        "composure": "finishing", "concentration": "defending", "decisions": "creation",
        "determination": "pressing", "flair": "carrier", "leadership": "pressing",
        "offTheBall": "movement", "positioning": "defending", "teamwork": "pressing",
        "vision": "creation", "workRate": "pressing",
    },
    "Physical": {
        "acceleration": "movement", "agility": "carrier", "balance": "physical",
        "jumpingReach": "aerial", "naturalFitness": "physical", "pace": "movement",
        "stamina": "pressing", "strength": "physical",
    },
    "Goalkeeping": {
        "aerialReach": "gk_area", "commandOfArea": "gk_area",
        "communication": "gk_area", "handling": "gk_shot", "kicking": "gk_distribution",
        "oneOnOnes": "gk_shot", "reflexes": "gk_shot", "rushingOut": "gk_shot",
        "throwing": "gk_distribution",
    },
}

ATTRIBUTE_DEFINITIONS = tuple(
    _attribute(key, group, family)
    for group, entries in _ATTRIBUTE_FAMILIES.items()
    for key, family in entries.items()
)
ATTRIBUTES_BY_KEY = {item.key: item for item in ATTRIBUTE_DEFINITIONS}
ATTRIBUTE_GROUPS = tuple(
    (group, tuple(key for key in entries)) for group, entries in _ATTRIBUTE_FAMILIES.items()
)


def _position(
    key: str, label: str, strong_attributes: tuple[str, ...], strong_positions: tuple[str, ...],
    weak_attributes: tuple[str, ...], weak_positions: tuple[str, ...],
) -> OpponentPosition:
    return OpponentPosition(
        key, label,
        _rule(+1, strong_attributes, strong_positions, f"Their strong {label.lower()} needs a response."),
        _rule(-1, weak_attributes, weak_positions, f"Their weak {label.lower()} is an opportunity."),
    )


POSITION_DEFINITIONS = (
    _position("GK", "Goalkeeper", ("finishing", "composure", "offTheBall"), _ATTACKERS,
              ("finishing", "longShots", "technique"), ("ST", "AMC", "MC")),
    _position("DR", "Right-back", ("dribbling", "technique", "offTheBall"), ("AML", "ML", "WBL"),
              ("pace", "dribbling", "crossing"), ("AML", "ML", "WBL")),
    _position("DL", "Left-back", ("dribbling", "technique", "offTheBall"), ("AMR", "MR", "WBR"),
              ("pace", "dribbling", "crossing"), ("AMR", "MR", "WBR")),
    _position("DC", "Centre-back", ("technique", "offTheBall", "composure"), ("ST", "AMC"),
              ("pace", "offTheBall", "finishing"), ("ST", "AMC")),
    _position("WBR", "Right wing-back", ("marking", "tackling", "positioning"), ("DL", "WBL", "DM"),
              ("pace", "dribbling", "crossing"), ("AML", "ML", "WBL")),
    _position("WBL", "Left wing-back", ("marking", "tackling", "positioning"), ("DR", "WBR", "DM"),
              ("pace", "dribbling", "crossing"), ("AMR", "MR", "WBR")),
    _position("DM", "Defensive midfield", ("firstTouch", "passing", "vision"), ("MC", "AMC"),
              ("dribbling", "offTheBall", "vision"), ("MC", "AMC")),
    _position("MC", "Central midfield", ("composure", "firstTouch", "passing"), ("DM", "MC", "AMC"),
              ("aggression", "workRate", "passing"), ("DM", "MC", "AMC")),
    _position("MR", "Right midfield", ("marking", "tackling", "positioning"), ("DL", "WBL"),
              ("pace", "dribbling", "crossing"), ("AML", "ML", "WBL")),
    _position("ML", "Left midfield", ("marking", "tackling", "positioning"), ("DR", "WBR"),
              ("pace", "dribbling", "crossing"), ("AMR", "MR", "WBR")),
    _position("AMR", "Right wing", ("marking", "tackling", "pace"), ("DL", "WBL", "DM"),
              ("pace", "dribbling", "crossing"), ("AML", "ML", "WBL")),
    _position("AML", "Left wing", ("marking", "tackling", "pace"), ("DR", "WBR", "DM"),
              ("pace", "dribbling", "crossing"), ("AMR", "MR", "WBR")),
    _position("AMC", "Attacking midfield", ("positioning", "anticipation", "tackling"), ("DC", "DM", "MC"),
              ("aggression", "anticipation", "passing"), ("DM", "MC")),
    _position("ST", "Striker", ("marking", "anticipation", "concentration"), ("DC", "DM"),
              ("passing", "vision", "offTheBall"), ("DM", "MC", "AMC")),
)
POSITIONS_BY_KEY = {item.key: item for item in POSITION_DEFINITIONS}

# Exact observations replace equivalent broad estimates. Other observations
# complement a broad axis because they describe a different thing: e.g. a
# team's chance volume is not the same fact as one player's passing quality.
AXIS_DETAIL_OVERRIDES = {
    "dribbling_quality": frozenset({"dribbling"}),
    "finishing_quality": frozenset({"finishing"}),
    "pace_in_behind": frozenset({"pace"}),
}
