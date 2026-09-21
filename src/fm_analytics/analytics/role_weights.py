"""Role attribute weights, authored inline in each role's entry under data/roles/.

A role's `attributes` is a plain `{attribute: weight}` map, weights 0 (ignored)
to 10 (defines the role at this position). Scoring divides each weight by the
role's total, so only the ratios matter: the scale is a resolution for whoever
writes the JSON, not something scoring depends on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_DATA_DIR = Path(__file__).with_name("data")

MAX_EFFECTIVE_WEIGHT = 10


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


def parse_attribute_weights(role_key: str, raw: Any) -> dict[str, int]:
    """Validate a role's `{attribute: weight}` map and return it in file order."""

    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"role {role_key!r} must have a non-empty 'attributes' object")
    weights: dict[str, int] = {}
    for name, weight in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"role {role_key!r} has an attribute with no name")
        if not isinstance(weight, int) or isinstance(weight, bool):
            raise ValueError(
                f"role {role_key!r}: weight for {name!r} must be a whole number, got {weight!r}"
            )
        if not 0 <= weight <= MAX_EFFECTIVE_WEIGHT:
            raise ValueError(
                f"role {role_key!r}: weight for {name!r} must be between 0 and "
                f"{MAX_EFFECTIVE_WEIGHT}, got {weight}"
            )
        weights[name] = weight
    return weights
