"""Cross-object validation kept separate from catalogue data loading."""

from __future__ import annotations

from typing import Any


def validate_emphasis_scopes(tactic: Any, fielded: set[str]) -> None:
    """Reject emphasis filters that cannot match a permitted assignment."""
    used_roles = {role_key for slot in tactic.slots for role_key in slot.role_keys}
    for block in tactic.attribute_emphasis:
        unused_roles = sorted(set(block.roles) - used_roles)
        if unused_roles:
            raise ValueError(
                f"tactic {tactic.key!r} emphasises roles it does not use: "
                f"{unused_roles!r}"
            )
        if not any(
            block.applies_to(slot.position, role_key)
            for slot in tactic.slots
            for role_key in slot.role_keys
        ):
            raise ValueError(
                f"tactic {tactic.key!r} emphasis matches no permitted slot/role"
            )


def validate_introduced_attributes(tactic: Any, roles: Any) -> None:
    """An introduction must add a genuinely absent weight to every named role."""
    for block in tactic.attribute_emphasis:
        matched_role_keys = {
            role_key
            for slot in tactic.slots
            for role_key in slot.role_keys
            if block.applies_to(slot.position, role_key)
        }
        for attribute in block.introduce_attributes:
            already_weighted = sorted(
                role_key
                for role_key in matched_role_keys
                if attribute in {item.name for item in roles[role_key].attributes}
            )
            if already_weighted:
                raise ValueError(
                    f"tactic {tactic.key!r} introduces {attribute!r} for roles that "
                    f"already weight it: {already_weighted!r}"
                )


def validate_taper_scopes(tactic: Any, fielded: set[str]) -> None:
    """Reject taper scopes that are inert or overlap for an exact assignment."""
    used_roles = {role_key for slot in tactic.slots for role_key in slot.role_keys}
    for taper in tactic.attribute_taper:
        unfielded = sorted(set(taper.positions) - fielded)
        if unfielded:
            raise ValueError(
                f"tactic {tactic.key!r} tapers {taper.attribute!r} at positions it does "
                f"not field: {unfielded!r} (it fields {sorted(fielded)!r})"
            )
        unused_roles = sorted(set(taper.roles) - used_roles)
        if unused_roles:
            raise ValueError(
                f"tactic {tactic.key!r} tapers {taper.attribute!r} for roles it does "
                f"not use: {unused_roles!r}"
            )
        if not any(
            taper.applies_to(slot.position, role_key)
            for slot in tactic.slots
            for role_key in slot.role_keys
        ):
            raise ValueError(
                f"tactic {tactic.key!r} taper for {taper.attribute!r} matches no "
                "permitted slot/role"
            )

    for slot in tactic.slots:
        for role_key in slot.role_keys:
            seen: set[str] = set()
            for taper in tactic.attribute_taper:
                if not taper.applies_to(slot.position, role_key):
                    continue
                if taper.attribute in seen:
                    raise ValueError(
                        f"tactic {tactic.key!r} tapers {taper.attribute!r} more than "
                        f"once for slot {slot.key!r}, role {role_key!r}"
                    )
                seen.add(taper.attribute)
