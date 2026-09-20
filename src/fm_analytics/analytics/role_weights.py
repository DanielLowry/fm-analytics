from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

_DATA_DIR = Path(__file__).with_name("data")

# Weights run 0 (ignored) to 10 (defines the role at this position). Scoring
# divides each weight by the role's total, so only the ratios matter: the scale
# is a resolution for whoever writes the JSON, not something scoring depends on.
MAX_EFFECTIVE_WEIGHT = 10


@dataclass(frozen=True)
class AttributeWeightConfig:
    """Per-attribute weight data for one role, authored inline in its role file.

    Only `effective_weight` is currently consumed by scoring (see
    `catalogue._attributes_from_weights`, which reads nothing else off this
    type). The rest -- `duty_modifier`, `weight_tier`,
    `core_soft_floor_applies`, the `soft_floor_if_attr_lt_*` thresholds, and
    `normal_multiplier_if_attr_ge_10` -- are loaded and validated here but
    not yet applied anywhere: they are the data half of the nonlinear
    attribute-contribution and soft-threshold model described in
    docs/tactical-system-roadmap.md (#2 and #3), authored ahead of that
    work so the weights don't need a second pass later. Scoring today is
    linear in `effective_weight` alone; a role scored as "51" is a plain
    weighted average, not yet discounted for a catastrophically low core
    attribute.
    """

    effective_weight: int
    duty_modifier: int
    weight_tier: str
    core_soft_floor_applies: bool
    soft_floor_if_attr_lt_6: float | None = None
    soft_floor_if_attr_lt_8: float | None = None
    soft_floor_if_attr_lt_10: float | None = None
    normal_multiplier_if_attr_ge_10: float | None = None

    def __post_init__(self) -> None:
        if not (0 <= self.effective_weight <= MAX_EFFECTIVE_WEIGHT):
            raise ValueError(f"effective weight must be between 0 and {MAX_EFFECTIVE_WEIGHT}")
        # The tier is a label for the human reading the JSON; scoring never
        # reads it. It was a closed list while weights were 0-5 and each tier
        # mapped to one weight, but a finer scale has no such mapping, so a
        # rejected tier name would only ever be a loading failure over inert
        # data. Any non-empty label is accepted.
        if not self.weight_tier.strip():
            raise ValueError("weight tier label must not be empty")


@dataclass(frozen=True)
class RoleWeightEntry:
    """All attribute weights for a single role+duty combination.

    `position_group` and `duty` are descriptive labels, not scoring input;
    only `attributes` is read by `catalogue._attributes_from_weights`. The
    weights are authored inline in each role's entry under `data/roles/`.
    """

    catalogue_key: str
    position_group: str
    duty: str
    attributes: Mapping[str, AttributeWeightConfig]

    def __post_init__(self) -> None:
        if not self.attributes:
            raise ValueError(f"role {self.catalogue_key!r} must have at least one attribute weight")


@dataclass(frozen=True)
class RoleWeightsCatalogue:
    """Loaded collection of per-role attribute weights."""

    version: str
    roles: Mapping[str, RoleWeightEntry]

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("role weights catalogue version is required")
        for key, entry in self.roles.items():
            if key != entry.catalogue_key:
                raise ValueError(f"role weight entry key {key!r} does not match entry catalogue_key")


def role_documents(data_dir: Path = _DATA_DIR) -> list[Mapping[str, Any]]:
    """Every role entry under `data_dir/roles/*.json`, in sorted-filename order.

    One file per position group, each `{"roles": [...]}`. Discovery is a sorted
    glob so load order is deterministic; a file name that does not match its
    contents is a test failure, not something the loader guesses at.
    """

    entries: list[Mapping[str, Any]] = []
    for path in sorted((data_dir / "roles").glob("*.json")):
        with path.open(encoding="utf-8") as f:
            document = json.load(f)
        roles = document.get("roles")
        if not isinstance(roles, list):
            raise ValueError(f"role file {path} must define a 'roles' array")
        entries.extend(roles)
    return entries


def parse_attribute_weights(
    catalogue_key: str, attrs_raw: Any
) -> dict[str, AttributeWeightConfig]:
    if not isinstance(attrs_raw, dict) or not attrs_raw:
        raise ValueError(f"role {catalogue_key!r} must have non-empty 'attributes'")
    attributes: dict[str, AttributeWeightConfig] = {}
    for attr_name, attr_raw in attrs_raw.items():
        if not isinstance(attr_raw, dict):
            raise ValueError(f"attribute {attr_name!r} in role {catalogue_key!r} must be an object")
        attributes[attr_name] = AttributeWeightConfig(
            effective_weight=_required_int(attr_raw, "effectiveWeight"),
            duty_modifier=_required_int(attr_raw, "dutyModifier"),
            weight_tier=_required_string(attr_raw, "weightTier"),
            core_soft_floor_applies=_required_bool(attr_raw, "coreSoftFloorApplies"),
            soft_floor_if_attr_lt_6=_nullable_float(attr_raw, "softFloorIfAttrLt6"),
            soft_floor_if_attr_lt_8=_nullable_float(attr_raw, "softFloorIfAttrLt8"),
            soft_floor_if_attr_lt_10=_nullable_float(attr_raw, "softFloorIfAttrLt10"),
            normal_multiplier_if_attr_ge_10=_nullable_float(attr_raw, "normalMultiplierIfAttrGe10"),
        )
    return attributes


def _entry(catalogue_key: str, role_raw: Any) -> RoleWeightEntry:
    if not isinstance(role_raw, dict):
        raise ValueError(f"role {catalogue_key!r} must be an object")
    return RoleWeightEntry(
        catalogue_key=catalogue_key,
        position_group=_required_string(role_raw, "positionGroup"),
        duty=_required_string(role_raw, "duty"),
        attributes=parse_attribute_weights(catalogue_key, role_raw.get("attributes")),
    )


def load_role_weights(path: Path | None = None) -> RoleWeightsCatalogue:
    """Load and validate role attribute weights.

    With no `path` (or a directory) the weights come from the role files under
    `data/roles/`, where each role's weights sit beside its identity. A file
    `path` is the older standalone `{"version", "roles": {key: ...}}` document,
    kept so weights can be exercised in isolation.
    """

    if path is None or path.is_dir():
        data_dir = path or _DATA_DIR
        with (data_dir / "catalogue.json").open(encoding="utf-8") as f:
            version = json.load(f).get("version")
        if not isinstance(version, str) or not version:
            raise ValueError("catalogue.json must have a string 'version' field")
        roles = {}
        for role_raw in role_documents(data_dir):
            key = _required_string(role_raw, "key")
            if key in roles:
                raise ValueError(f"duplicate role key {key!r} in role files")
            roles[key] = _entry(key, role_raw)
        return RoleWeightsCatalogue(version=version, roles=roles)

    with path.open(encoding="utf-8") as f:
        document = json.load(f)

    version = document.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("role weights JSON must have a string 'version' field")

    roles_raw = document.get("roles")
    if not isinstance(roles_raw, dict):
        raise ValueError("role weights JSON must have a 'roles' object")

    return RoleWeightsCatalogue(
        version=version,
        roles={key: _entry(key, role_raw) for key, role_raw in roles_raw.items()},
    )


def _required_int(raw: Mapping[str, Any], name: str) -> int:
    value = raw.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _required_string(raw: Mapping[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name!r} must be a non-empty string")
    return value


def _required_bool(raw: Mapping[str, Any], name: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _nullable_float(raw: Mapping[str, Any], name: str) -> float | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a number or null")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result
