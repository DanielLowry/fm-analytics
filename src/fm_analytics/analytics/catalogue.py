from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fm_analytics.analytics.role_scoring import (
    AttributePriority,
    RoleAttribute,
    RoleDefinition,
)


# The role and tactic definitions themselves live in versioned JSON data
# (data/catalogue.json) rather than as Python literals here, per the Phase 04
# decision that "the catalogue should be data/config, not hard-coded across
# the scoring implementation". This module owns loading that data into the
# same validated dataclasses below; every invariant that previously lived in
# hand-written Python construction still runs, just against loaded data.
_DATA_PATH = Path(__file__).with_name("data") / "catalogue.json"


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


def _role_from_json(raw: Mapping[str, Any], *, version: str) -> RoleDefinition:
    return RoleDefinition(
        key=_str(raw, "key"),
        name=_str(raw, "name"),
        eligible_positions=_str_tuple(raw, "positions"),
        attributes=_attributes(
            required=_str_tuple(raw, "required"),
            desirable=_str_tuple(raw, "desirable"),
        ),
        catalogue_version=version,
    )


def _slot_from_json(raw: Mapping[str, Any]) -> TacticSlot:
    return TacticSlot(
        key=_str(raw, "key"), position=_str(raw, "position"), role_key=_str(raw, "role")
    )


def _tactic_from_json(raw: Mapping[str, Any], *, version: str) -> TacticDefinition:
    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, list):
        raise ValueError(f"tactic {raw.get('key')!r} is missing its slots list")
    return TacticDefinition(
        key=_str(raw, "key"),
        name=_str(raw, "name"),
        formation=_str(raw, "formation"),
        mentality=_str(raw, "mentality"),
        instructions=_str_tuple(raw, "instructions"),
        slots=tuple(_slot_from_json(slot) for slot in slots_raw),
        catalogue_version=version,
    )


def load_catalogue(path: Path = _DATA_PATH) -> FootballCatalogue:
    """Load and validate a versioned football catalogue from JSON.

    Every structural rule (eleven unique slots, roles that exist, slots whose
    position the assigned role can actually play) is enforced by the
    dataclasses above exactly as it was when this data was Python literals;
    this function only does the JSON -> dataclass translation, so a malformed
    catalogue file still fails closed at import time rather than producing a
    silently broken recommendation later.
    """
    with path.open(encoding="utf-8") as data_file:
        document = json.load(data_file)
    version = _str(document, "version")
    roles_raw = document.get("roles")
    tactics_raw = document.get("tactics")
    if not isinstance(roles_raw, list) or not isinstance(tactics_raw, list):
        raise ValueError(f"catalogue file {path} must define roles and tactics arrays")
    roles = {
        role.key: role
        for role in (_role_from_json(entry, version=version) for entry in roles_raw)
    }
    if len(roles) != len(roles_raw):
        raise ValueError(f"catalogue file {path} has duplicate role keys")
    tactics = {
        tactic.key: tactic
        for tactic in (_tactic_from_json(entry, version=version) for entry in tactics_raw)
    }
    if len(tactics) != len(tactics_raw):
        raise ValueError(f"catalogue file {path} has duplicate tactic keys")
    return FootballCatalogue(version=version, roles=roles, tactics=tactics)


def _str(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name!r} must be a non-empty string, got {value!r}")
    return value


def _str_tuple(raw: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = raw.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name!r} must be an array of strings")
    return tuple(value)


MVP_CATALOGUE = load_catalogue()
# The version string lives in the JSON data (single source of truth); this
# alias exists only so code that wants "the current catalogue version" does
# not need to import MVP_CATALOGUE just to read one field off it.
CATALOGUE_VERSION = MVP_CATALOGUE.version
