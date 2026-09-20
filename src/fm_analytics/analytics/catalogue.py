from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from fm_analytics.analytics.role_scoring import (
    RoleAttribute,
    RoleDefinition,
)
from fm_analytics.analytics.role_weights import (
    RoleWeightsCatalogue,
    load_role_weights,
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
    alternate_role_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.position or not self.role_key:
            raise ValueError("tactic slot key, position, and role are required")
        if self.role_key in self.alternate_role_keys:
            raise ValueError("a slot's default role cannot also be an alternate")
        if len(self.alternate_role_keys) != len(set(self.alternate_role_keys)):
            raise ValueError("slot alternate role keys must be unique")

    @property
    def role_keys(self) -> tuple[str, ...]:
        """Every role the optimiser may choose for this slot.

        `role_key` is deliberately retained as the template's default: it is
        useful as a readable starting hypothesis and for an unfilled-slot
        explanation.  It is no longer a command to use that role.
        """

        return (self.role_key,) + self.alternate_role_keys


@dataclass(frozen=True)
class TacticSystemRequirements:
    """Minimum system contributions and explicit redundancy limits.

    Empty requirements mean that a synthetic/unit-test tactic has no system
    model; its overall score remains its XI-suitability score.
    """

    minimums: Mapping[str, float] = field(default_factory=dict)
    maximum_attack_duties: int | None = None
    maximum_creators: int | None = None

    def __post_init__(self) -> None:
        for name, value in self.minimums.items():
            if not isinstance(name, str) or not name:
                raise ValueError("system minimum names must be non-empty strings")
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError("system minimums must be non-negative numbers")
        for name, value in (
            ("maximum_attack_duties", self.maximum_attack_duties),
            ("maximum_creators", self.maximum_creators),
        ):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
                raise ValueError(f"{name} must be a positive integer when set")


@dataclass(frozen=True)
class TacticDefinition:
    key: str
    name: str
    formation: str
    mentality: str
    instructions: tuple[str, ...]
    slots: tuple[TacticSlot, ...]
    catalogue_version: str
    system_requirements: TacticSystemRequirements = TacticSystemRequirements()
    # Manager-facing explanation, not scoring input. Optional so catalogues
    # (and tests) that predate this field still load unchanged.
    style: str = ""
    description: str = ""
    why_good: str = ""
    key_requirements: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

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
                role_key
                for slot in tactic.slots
                for role_key in slot.role_keys
                if role_key not in self.roles
            }
            if unknown_roles:
                raise ValueError(
                    f"tactic {key!r} references unknown roles {sorted(unknown_roles)!r}"
                )
            incompatible_slots = [
                slot.key
                for slot in tactic.slots
                if any(
                    slot.position not in self.roles[role_key].eligible_positions
                    for role_key in slot.role_keys
                )
            ]
            if incompatible_slots:
                raise ValueError(
                    f"tactic {key!r} has role-incompatible slots {incompatible_slots!r}"
                )

    def role_keys_for_slot(self, slot: TacticSlot) -> tuple[str, ...]:
        """Return the slot's permitted roles after position compatibility.

        Only a slot's own declared `role` plus its explicit `roles`
        alternatives are ever tried. A slot with no alternatives is pinned:
        the optimiser will not substitute a different role into it, because
        that specific role is what makes this tactic the tactic it is
        (its own identity), not an interchangeable filler. Give a slot
        alternatives only when the tactic's author has deliberately decided
        that position can flex without changing what the system is.
        """

        candidates = slot.role_keys
        return tuple(
            role_key
            for role_key in candidates
            if role_key in self.roles
            and slot.position in self.roles[role_key].eligible_positions
        )


def _attributes_from_weights(
    *,
    catalogue_key: str,
    required: tuple[str, ...],
    desirable: tuple[str, ...],
    weight_catalogue: RoleWeightsCatalogue | None,
) -> tuple[RoleAttribute, ...]:
    """Build RoleAttribute tuple using CSV-derived weights when available.

    Only `effective_weight` feeds scoring; every other field
    `AttributeWeightConfig` carries (duty modifier, soft floors, ...) is
    reserved data for the not-yet-implemented nonlinear contribution model
    -- see that dataclass's docstring in `role_weights.py`.
    """
    if weight_catalogue is not None:
        # A catalogue role with no weights entry must fail here, not fall back.
        # The fallback below gives every attribute a flat 2.0, which scores
        # plausibly enough to look fine on a page while being badly wrong --
        # exactly what happened when role_weights split roles by position
        # (wb_support -> wb_dl_dr_support/wb_wbl_wbr_support) and the catalogue
        # still named the old keys.
        entry = weight_catalogue.roles.get(catalogue_key)
        if entry is None:
            raise ValueError(
                f"role {catalogue_key!r} has no entry in role weights "
                f"{weight_catalogue.version!r}; catalogue and weights disagree"
            )
        return tuple(
            RoleAttribute(name=name, weight=cfg.effective_weight)
            for name, cfg in entry.attributes.items()
            if cfg.effective_weight > 0
        )
    # Only reachable when no weight catalogue was supplied at all (tests that
    # build a catalogue from required/desirable alone).
    return tuple(
        RoleAttribute(name=name, weight=2.0)
        for name in required
    ) + tuple(
        RoleAttribute(name=name, weight=1.0)
        for name in desirable
    )


def _role_from_json(
    raw: Mapping[str, Any],
    *,
    version: str,
    weight_catalogue: RoleWeightsCatalogue | None = None,
) -> RoleDefinition:
    key = _str(raw, "key")
    return RoleDefinition(
        key=key,
        name=_str(raw, "name"),
        eligible_positions=_str_tuple(raw, "positions"),
        attributes=_attributes_from_weights(
            catalogue_key=key,
            required=_str_tuple(raw, "required"),
            desirable=_str_tuple(raw, "desirable"),
            weight_catalogue=weight_catalogue,
        ),
        catalogue_version=version,
        system_traits=_number_mapping(raw.get("system"), "role system"),
    )


def _slot_from_json(raw: Mapping[str, Any]) -> TacticSlot:
    """Build a slot from JSON.

    `role` is always the slot's one canonical role -- it is never inferred
    or overridden by anything else in the document. The optional `roles`
    array lists *additional* roles the optimiser may substitute in instead;
    it must not repeat `role` itself (that used to be silently accepted and
    silently ignored -- `role` was overwritten by `roles[0]` whenever both
    were present -- which made editing `role` on such a slot a no-op with
    no warning).
    """
    role_key = _str(raw, "role")
    alternate_role_keys = _str_tuple(raw, "roles") if "roles" in raw else ()
    if role_key in alternate_role_keys:
        raise ValueError(
            f"slot {raw.get('key')!r} lists {role_key!r} in both 'role' and 'roles'; "
            "'roles' should list only its additional alternatives"
        )
    return TacticSlot(
        key=_str(raw, "key"),
        position=_str(raw, "position"),
        role_key=role_key,
        alternate_role_keys=alternate_role_keys,
    )


def _tactic_from_json(raw: Mapping[str, Any], *, version: str) -> TacticDefinition:
    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, list):
        raise ValueError(f"tactic {raw.get('key')!r} is missing its slots list")
    slots = tuple(_slot_from_json(slot) for slot in slots_raw)
    return TacticDefinition(
        key=_str(raw, "key"),
        name=_str(raw, "name"),
        formation=_str(raw, "formation"),
        mentality=_str(raw, "mentality"),
        instructions=_str_tuple(raw, "instructions"),
        slots=slots,
        catalogue_version=version,
        system_requirements=(
            _system_requirements(raw["system"])
            if "system" in raw
            else _inferred_system_requirements(raw, slots)
        ),
        style=raw.get("style") or "",
        description=raw.get("description") or "",
        why_good=raw.get("whyGood") or "",
        key_requirements=_str_tuple(raw, "keyRequirements") if "keyRequirements" in raw else (),
        tags=_str_tuple(raw, "tags") if "tags" in raw else (),
    )


def load_catalogue(
    path: Path = _DATA_PATH,
    weight_catalogue: RoleWeightsCatalogue | None = None,
) -> FootballCatalogue:
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
        for role in (
            _role_from_json(entry, version=version, weight_catalogue=weight_catalogue)
            for entry in roles_raw
        )
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


def _number_mapping(value: Any, name: str) -> Mapping[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name!r} must be an object")
    result: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name!r} keys must be non-empty strings")
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"{name!r} values must be numbers")
        result[key] = float(item)
    return result


def _system_requirements(value: Any) -> TacticSystemRequirements:
    if value is None:
        return TacticSystemRequirements()
    if not isinstance(value, dict):
        raise ValueError("tactic system must be an object")
    return TacticSystemRequirements(
        minimums=_number_mapping(value.get("minimums"), "tactic system minimums"),
        maximum_attack_duties=value.get("maximumAttackDuties"),
        maximum_creators=value.get("maximumCreators"),
    )


def _inferred_system_requirements(
    raw: Mapping[str, Any], slots: tuple[TacticSlot, ...]
) -> TacticSystemRequirements:
    """Give the legacy MVP templates a visible, replaceable POC system model."""

    wide_slots = sum(
        slot.position in {"ML", "MR", "AML", "AMR", "WBL", "WBR"}
        for slot in slots
    )
    mentality = _str(raw, "mentality")
    attack_limit = {
        "Defensive": 3,
        "Balanced": 4,
        "Positive": 5,
        "Attacking": 6,
        "Counter": 4,
    }.get(mentality, 4)
    return TacticSystemRequirements(
        minimums={
            "width": 2.0 if wide_slots else 1.5,
            "defensiveCover": 3.0,
            "ballProgression": 2.0,
            "runners": 1.0,
            "penetration": 1.0,
            "boxPresence": 1.0,
            "restDefence": 3.0,
        },
        maximum_attack_duties=attack_limit,
        maximum_creators=3,
    )


_WEIGHT_CATALOGUE = load_role_weights()
MVP_CATALOGUE = load_catalogue(weight_catalogue=_WEIGHT_CATALOGUE)
# The version string lives in the JSON data (single source of truth); this
# alias exists only so code that wants "the current catalogue version" does
# not need to import MVP_CATALOGUE just to read one field off it.
CATALOGUE_VERSION = MVP_CATALOGUE.version
