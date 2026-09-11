from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from fm_analytics.analytics.role_scoring import (
    AttributePriority,
    RoleAttribute,
    RoleDefinition,
)


CATALOGUE_VERSION = "fm20-mvp-v1"


@dataclass(frozen=True)
class TacticSlot:
    key: str
    position: str
    role_key: str

    def __post_init__(self) -> None:
        if not self.key or not self.position or not self.role_key:
            raise ValueError("tactic slot key, position, and role are required")


@dataclass(frozen=True)
class TacticDefinition:
    key: str
    name: str
    formation: str
    mentality: str
    instructions: tuple[str, ...]
    slots: tuple[TacticSlot, ...]
    catalogue_version: str

    def __post_init__(self) -> None:
        if not all(
            (self.key, self.name, self.formation, self.mentality, self.catalogue_version)
        ):
            raise ValueError("tactic identity, formation, mentality, and version are required")
        if len(self.slots) != 11:
            raise ValueError("an MVP tactic must define exactly eleven slots")
        slot_keys = [slot.key for slot in self.slots]
        if len(slot_keys) != len(set(slot_keys)):
            raise ValueError("tactic slot keys must be unique")


@dataclass(frozen=True)
class FootballCatalogue:
    version: str
    roles: Mapping[str, RoleDefinition]
    tactics: Mapping[str, TacticDefinition]

    def __post_init__(self) -> None:
        if not self.version or not self.roles or not self.tactics:
            raise ValueError("football catalogue version, roles, and tactics are required")
        for key, role in self.roles.items():
            if key != role.key or role.catalogue_version != self.version:
                raise ValueError("role keys and versions must match their catalogue")
        for key, tactic in self.tactics.items():
            if key != tactic.key or tactic.catalogue_version != self.version:
                raise ValueError("tactic keys and versions must match their catalogue")
            unknown_roles = {
                slot.role_key for slot in tactic.slots if slot.role_key not in self.roles
            }
            if unknown_roles:
                raise ValueError(
                    f"tactic {key!r} references unknown roles {sorted(unknown_roles)!r}"
                )
            incompatible_slots = [
                slot.key
                for slot in tactic.slots
                if slot.position not in self.roles[slot.role_key].eligible_positions
            ]
            if incompatible_slots:
                raise ValueError(
                    f"tactic {key!r} has role-incompatible slots {incompatible_slots!r}"
                )


def _attributes(
    *, required: tuple[str, ...], desirable: tuple[str, ...]
) -> tuple[RoleAttribute, ...]:
    return tuple(
        RoleAttribute(name, 2, AttributePriority.REQUIRED) for name in required
    ) + tuple(
        RoleAttribute(name, 1, AttributePriority.DESIRABLE) for name in desirable
    )


def _role(
    key: str,
    name: str,
    positions: tuple[str, ...],
    *,
    required: tuple[str, ...],
    desirable: tuple[str, ...],
) -> RoleDefinition:
    return RoleDefinition(
        key=key,
        name=name,
        eligible_positions=positions,
        attributes=_attributes(required=required, desirable=desirable),
        catalogue_version=CATALOGUE_VERSION,
    )


_ROLE_LIST = (
    _role(
        "gk_defend",
        "Goalkeeper (Defend)",
        ("GK",),
        required=("aerialReach", "handling", "oneOnOnes", "reflexes"),
        desirable=("commandOfArea", "communication", "kicking", "throwing"),
    ),
    _role(
        "cd_defend",
        "Central Defender (Defend)",
        ("DC",),
        required=("heading", "marking", "tackling", "positioning"),
        desirable=(
            "anticipation",
            "concentration",
            "decisions",
            "jumpingReach",
            "strength",
        ),
    ),
    _role(
        "fb_support",
        "Full-Back (Support)",
        ("DL", "DR"),
        required=("marking", "tackling", "positioning", "workRate"),
        desirable=("crossing", "pace", "stamina", "teamwork"),
    ),
    _role(
        "dm_defend",
        "Defensive Midfielder (Defend)",
        ("DM",),
        required=("tackling", "positioning", "anticipation", "decisions"),
        desirable=("marking", "passing", "teamwork", "workRate"),
    ),
    _role(
        "cm_defend",
        "Central Midfielder (Defend)",
        ("MC",),
        required=("positioning", "tackling", "decisions", "teamwork"),
        desirable=("marking", "passing", "stamina", "workRate"),
    ),
    _role(
        "cm_support",
        "Central Midfielder (Support)",
        ("MC",),
        required=("passing", "firstTouch", "decisions", "teamwork"),
        desirable=("offTheBall", "stamina", "technique", "workRate"),
    ),
    _role(
        "dlp_support",
        "Deep-Lying Playmaker (Support)",
        ("DM", "MC"),
        required=("passing", "vision", "firstTouch", "decisions"),
        desirable=("composure", "positioning", "teamwork", "technique"),
    ),
    _role(
        "winger_support",
        "Winger (Support)",
        ("ML", "MR", "AML", "AMR"),
        required=("crossing", "dribbling", "acceleration", "pace"),
        desirable=("offTheBall", "technique", "teamwork", "workRate"),
    ),
    _role(
        "winger_attack",
        "Winger (Attack)",
        ("AML", "AMR"),
        required=("crossing", "dribbling", "acceleration", "pace"),
        desirable=("offTheBall", "technique", "flair", "finishing"),
    ),
    _role(
        "if_attack",
        "Inside Forward (Attack)",
        ("AML", "AMR"),
        required=("dribbling", "finishing", "offTheBall", "acceleration"),
        desirable=("composure", "firstTouch", "pace", "technique"),
    ),
    _role(
        "am_support",
        "Attacking Midfielder (Support)",
        ("AMC",),
        required=("passing", "vision", "firstTouch", "decisions"),
        desirable=("flair", "offTheBall", "teamwork", "technique"),
    ),
    _role(
        "dlf_support",
        "Deep-Lying Forward (Support)",
        ("ST",),
        required=("firstTouch", "passing", "offTheBall", "teamwork"),
        desirable=("anticipation", "composure", "finishing", "strength"),
    ),
    _role(
        "af_attack",
        "Advanced Forward (Attack)",
        ("ST",),
        required=("finishing", "offTheBall", "acceleration", "pace"),
        desirable=("anticipation", "composure", "dribbling", "firstTouch"),
    ),
)


def _slot(key: str, position: str, role_key: str) -> TacticSlot:
    return TacticSlot(key=key, position=position, role_key=role_key)


_TACTIC_LIST = (
    TacticDefinition(
        key="balanced_442",
        name="Balanced 4-4-2",
        formation="4-4-2",
        mentality="Balanced",
        instructions=(
            "Fairly Wide",
            "Slightly More Direct Passing",
            "Counter",
            "Regroup",
            "Standard Line of Engagement",
            "Standard Defensive Line",
        ),
        slots=(
            _slot("GK", "GK", "gk_defend"),
            _slot("DL", "DL", "fb_support"),
            _slot("DCL", "DC", "cd_defend"),
            _slot("DCR", "DC", "cd_defend"),
            _slot("DR", "DR", "fb_support"),
            _slot("ML", "ML", "winger_support"),
            _slot("MCL", "MC", "cm_defend"),
            _slot("MCR", "MC", "cm_support"),
            _slot("MR", "MR", "winger_support"),
            _slot("STL", "ST", "dlf_support"),
            _slot("STR", "ST", "af_attack"),
        ),
        catalogue_version=CATALOGUE_VERSION,
    ),
    TacticDefinition(
        key="positive_4231",
        name="Positive 4-2-3-1 Wide",
        formation="4-2-3-1 DM AM Wide",
        mentality="Positive",
        instructions=(
            "Shorter Passing",
            "Play Out Of Defence",
            "Higher Tempo",
            "Counter-Press",
            "Counter",
            "Higher Line of Engagement",
            "Standard Defensive Line",
        ),
        slots=(
            _slot("GK", "GK", "gk_defend"),
            _slot("DL", "DL", "fb_support"),
            _slot("DCL", "DC", "cd_defend"),
            _slot("DCR", "DC", "cd_defend"),
            _slot("DR", "DR", "fb_support"),
            _slot("DMCL", "DM", "dm_defend"),
            _slot("DMCR", "DM", "dlp_support"),
            _slot("AML", "AML", "if_attack"),
            _slot("AMC", "AMC", "am_support"),
            _slot("AMR", "AMR", "winger_attack"),
            _slot("ST", "ST", "af_attack"),
        ),
        catalogue_version=CATALOGUE_VERSION,
    ),
    TacticDefinition(
        key="positive_433dm",
        name="Positive 4-3-3 DM Wide",
        formation="4-3-3 DM Wide",
        mentality="Positive",
        instructions=(
            "Shorter Passing",
            "Play Out Of Defence",
            "Work Ball Into Box",
            "Counter-Press",
            "Counter",
            "Higher Line of Engagement",
            "Standard Defensive Line",
        ),
        slots=(
            _slot("GK", "GK", "gk_defend"),
            _slot("DL", "DL", "fb_support"),
            _slot("DCL", "DC", "cd_defend"),
            _slot("DCR", "DC", "cd_defend"),
            _slot("DR", "DR", "fb_support"),
            _slot("DM", "DM", "dm_defend"),
            _slot("MCL", "MC", "dlp_support"),
            _slot("MCR", "MC", "cm_support"),
            _slot("AML", "AML", "if_attack"),
            _slot("AMR", "AMR", "winger_attack"),
            _slot("ST", "ST", "af_attack"),
        ),
        catalogue_version=CATALOGUE_VERSION,
    ),
)


MVP_CATALOGUE = FootballCatalogue(
    version=CATALOGUE_VERSION,
    roles={role.key: role for role in _ROLE_LIST},
    tactics={tactic.key: tactic for tactic in _TACTIC_LIST},
)
