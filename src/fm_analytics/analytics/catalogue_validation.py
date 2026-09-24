"""Cross-object validation kept separate from catalogue data loading."""

from __future__ import annotations

from typing import Any


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
