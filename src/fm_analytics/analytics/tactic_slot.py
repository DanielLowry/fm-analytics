"""A tactic position, its permitted roles and extra player instructions."""

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class TacticSlot:
    key: str
    position: str
    role_key: str
    alternate_role_keys: tuple[str, ...] = ()
    # Manager-facing: why this role sits in this slot of this tactic. Not scoring input.
    why: str = ""
    # Per-attribute weight *deltas* for whoever fills this slot. Added to every
    # tactic-level block that covers the slot (see TacticDefinition); use it
    # to single out one slot when several share a position (the two DCs).
    attribute_emphasis: Mapping[str, int] = field(default_factory=dict)
    # Additional, verified FM player instructions; an empty tuple uses role defaults.
    instructions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.position or not self.role_key:
            raise ValueError("tactic slot key, position, and role are required")
        if self.role_key in self.alternate_role_keys:
            raise ValueError("a slot's default role cannot also be an alternate")
        if len(self.alternate_role_keys) != len(set(self.alternate_role_keys)):
            raise ValueError("slot alternate role keys must be unique")
        if not isinstance(self.instructions, tuple) or not all(isinstance(i, str) and i.strip() for i in self.instructions):
            raise ValueError("slot instructions must be a tuple of non-empty instruction names")
        if len(self.instructions) != len(set(self.instructions)):
            raise ValueError("slot instructions must be unique")

    @property
    def role_keys(self) -> tuple[str, ...]:
        """Every role the optimiser may choose for this slot.

        `role_key` is deliberately retained as the template's default: it is
        useful as a readable starting hypothesis and for an unfilled-slot
        explanation.  It is no longer a command to use that role.
        """

        return (self.role_key,) + self.alternate_role_keys


