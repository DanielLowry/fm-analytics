from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from itertools import product
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from fm_analytics.analytics.attribute_taper import AttributeTaper
from fm_analytics.analytics.catalogue_validation import (
    validate_emphasis_scopes,
    validate_taper_scopes,
)
from fm_analytics.analytics.role_scoring import (
    RoleAttribute,
    RoleDefinition,
)
from fm_analytics.analytics.role_weights import (
    MAX_EFFECTIVE_WEIGHT,
    parse_attribute_weights,
    role_documents,
)


# The role and tactic definitions themselves live in JSON data rather than as
# Python literals here, per the Phase 04 decision that "the catalogue should be
# data/config, not hard-coded across the scoring implementation". The layout is
#
#   data/catalogue.json     the version, exclusion groups, research notes
#   data/roles/<pos>.json   one file per position group: each role's identity
#                           and its attribute weights, together
#   data/tactics/<key>.json one file per tactic
#
# This module owns loading that data into the same validated dataclasses
# below; every invariant that previously lived in hand-written Python
# construction still runs, just against loaded data.
_DATA_PATH = Path(__file__).with_name("data")


@dataclass(frozen=True)
class AttributeEmphasis:
    """One block of "this tactic values these attributes more (or less)".

    `attributes` are *deltas* on each role's own weight. `positions` and `roles`
    are independent optional filters; when both are present, both must match.
    Every block that covers an assignment adds to it, so a tactic can combine a
    whole-team requirement with a role-specific one.
    """

    attributes: Mapping[str, int]
    positions: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.attributes:
            raise ValueError("an attribute emphasis block must name at least one attribute")
        for attribute, delta in self.attributes.items():
            if not isinstance(delta, int) or isinstance(delta, bool):
                raise ValueError(f"attribute emphasis {attribute!r} must be an integer")
            if not -MAX_EFFECTIVE_WEIGHT <= delta <= MAX_EFFECTIVE_WEIGHT:
                raise ValueError(
                    f"attribute emphasis {attribute!r} must be between "
                    f"-{MAX_EFFECTIVE_WEIGHT} and {MAX_EFFECTIVE_WEIGHT}"
                )
        if len(self.positions) != len(set(self.positions)) or not all(self.positions):
            raise ValueError("emphasis positions must be unique, non-empty names")
        if len(self.roles) != len(set(self.roles)) or not all(self.roles):
            raise ValueError("emphasis roles must be unique, non-empty keys")

    def applies_to(self, position: str, role_key: str | None = None) -> bool:
        return (
            (not self.positions or position in self.positions)
            and (not self.roles or role_key in self.roles)
        )


def _sum_emphasis(*emphases: Mapping[str, int]) -> dict[str, int]:
    total: dict[str, int] = {}
    for emphasis in emphases:
        for attribute, delta in emphasis.items():
            total[attribute] = total.get(attribute, 0) + delta
    return {a: d for a, d in total.items() if d}


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
    # Justification for a manager: what the shape does structurally, when it
    # suits and when it does not, and why each instruction is in it. All
    # optional and none of it scoring input.
    why_this_shape: str = ""
    when_to_use: str = ""
    when_not_to_use: str = ""
    instruction_rationale: Mapping[str, str] = field(default_factory=dict)
    # How much more (or less) this tactic values an attribute, as *deltas* on the
    # role's own weight, in blocks that cover the whole team or named positions.
    #
    # Deltas, not absolute weights: a block can cover several slots, and an
    # absolute "stamina: 8" would mean stamina 8 for the goalkeeper too. A delta
    # shifts an existing weight or starts from zero when the role did not
    # previously weight that attribute, allowing the tactic to add a genuine
    # contextual requirement.
    # Every block covering a slot is summed, then clamped to the 0-10 scale.
    attribute_emphasis: tuple[AttributeEmphasis, ...] = ()
    # Levels below which a player's fit tapers away, per attribute and optionally
    # per position. Unlike emphasis these are not deltas on a weight: they scale
    # the finished slot score, because a weighted average can never say "this
    # tactic does not work without passing" (a midfielder on passing 4 costs about
    # 8% of his score however much the role values passing).
    attribute_taper: tuple[AttributeTaper, ...] = ()

    @property
    def emphasised_attributes(self) -> tuple[str, ...]:
        """Every attribute this tactic leans on, whole-team blocks first."""
        ordered = sorted(
            self.attribute_emphasis,
            key=lambda block: bool(block.positions or block.roles),
        )
        return tuple(dict.fromkeys(name for block in ordered for name in block.attributes))

    def __post_init__(self) -> None:
        if not all(
            (self.key, self.name, self.formation, self.mentality, self.catalogue_version)
        ):
            raise ValueError("tactic identity, formation, mentality, and version are required")
        fielded = {slot.position for slot in self.slots}
        for block in self.attribute_emphasis:
            # A position the tactic does not field would silently do nothing.
            unfielded = sorted(set(block.positions) - fielded)
            if unfielded:
                raise ValueError(
                    f"tactic {self.key!r} emphasises positions it does not field: "
                    f"{unfielded!r} (it fields {sorted(fielded)!r})"
                )
        validate_emphasis_scopes(self, fielded)
        validate_taper_scopes(self, fielded)
        for slot in self.slots:
            for attribute, delta in slot.attribute_emphasis.items():
                if not isinstance(delta, int) or isinstance(delta, bool):
                    raise ValueError(
                        f"{self.key}/{slot.key}: attribute emphasis {attribute!r} must be an integer"
                    )
                if not -MAX_EFFECTIVE_WEIGHT <= delta <= MAX_EFFECTIVE_WEIGHT:
                    raise ValueError(
                        f"{self.key}/{slot.key}: attribute emphasis {attribute!r} must be "
                        f"between -{MAX_EFFECTIVE_WEIGHT} and {MAX_EFFECTIVE_WEIGHT}"
                    )
        stray = sorted(set(self.instruction_rationale) - set(self.instructions))
        if stray:
            raise ValueError(
                f"tactic {self.key!r} explains instructions it does not use: {stray!r}"
            )
        if len(self.slots) != 11:
            raise ValueError("an MVP tactic must define exactly eleven slots")
        slot_keys = [slot.key for slot in self.slots]
        if len(slot_keys) != len(set(slot_keys)):
            raise ValueError("tactic slot keys must be unique")


@dataclass(frozen=True)
class RoleExclusionGroup:
    """Roles of which a tactic may use at most one, among slots at one position.

    With no `position` the limit applies across the whole eleven, for roles that
    are a liability wherever they play (a Trequartista, an Enganche and a
    Raumdeuter all give little defensively, so two of them anywhere in one XI
    is not a workable system).

    Slot alternatives are chosen independently, so nothing stops two slots on
    the same line picking the same role. Some pairings are not a legitimate
    system: two Cover centre-backs leave nobody to be covered, so at most one
    slot at `position` may play a role in `role_keys`. The rule applies to
    every role version, whether the roles are pinned or chosen from
    alternatives.
    """

    name: str
    position: str | None
    role_keys: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name or not self.role_keys:
            raise ValueError("role exclusion group name and roles are required")
        if self.position is not None and not self.position:
            raise ValueError("role exclusion group position must be omitted or non-empty")

    def is_violated_by(
        self, slots: tuple[TacticSlot, ...], role_keys: tuple[str, ...]
    ) -> bool:
        return (
            sum(
                1
                for slot, role_key in zip(slots, role_keys)
                if (self.position is None or slot.position == self.position)
                and role_key in self.role_keys
            )
            > 1
        )


@dataclass(frozen=True)
class FootballCatalogue:
    version: str
    roles: Mapping[str, RoleDefinition]
    tactics: Mapping[str, TacticDefinition]
    exclusive_role_groups: tuple[RoleExclusionGroup, ...] = ()
    # Roles re-weighted for one slot of one tactic, keyed (slot key, role key).
    # Only populated on a catalogue returned by `for_tactic`.
    slot_roles: Mapping[tuple[str, str], RoleDefinition] = field(
        default_factory=dict, compare=False, repr=False
    )
    # Tapers that apply to each slot, keyed by slot key. Only populated on a
    # catalogue returned by `for_tactic`.
    slot_tapers: Mapping[str, tuple[AttributeTaper, ...]] = field(
        default_factory=dict, compare=False, repr=False
    )
    # True on a catalogue returned by `for_tactic`. Its roles are computed, not
    # authored: emphasis has already been applied and may have taken a weight to
    # zero, dropping that attribute. Re-checking authored emphasis names against
    # those narrowed roles would reject a catalogue whose data is perfectly
    # valid, so that one check is skipped here and runs on the authored data.
    tactic_view: bool = field(default=False, compare=False, repr=False)
    # Memoised `for_tactic` results. Excluded from equality (a catalogue is the
    # same catalogue whether or not it has derived a tactic's view yet) and from
    # __init__, so `dataclasses.replace` gives the copy a fresh cache instead of
    # sharing this one -- sharing it handed a modified catalogue the *original*
    # catalogue's derived views, silently ignoring the change.
    _derived: dict[str, "FootballCatalogue"] = field(
        default_factory=dict, compare=False, repr=False, init=False
    )

    def for_tactic(self, tactic_key: str) -> "FootballCatalogue":
        """This catalogue with every role re-weighted for one tactic.

        Role keys, names, positions, system traits and the catalogue version are
        all unchanged -- only attribute weights move -- so every lookup,
        exclusion group and version check keeps working on the result. A tactic
        that declares no emphasis returns this catalogue unchanged, which is
        what keeps the no-emphasis case exactly as it scored before.
        """
        if (cached := self._derived.get(tactic_key)) is not None:
            return cached
        tactic = self.tactics[tactic_key]
        # Worst case under threading is building this twice; both are equal.
        derived = self._derive_view(tactic, tactic.attribute_emphasis) or self
        self._derived[tactic_key] = derived
        return derived

    def for_context(
        self, tactic_key: str, *, extra_emphasis: tuple[AttributeEmphasis, ...] = ()
    ) -> "FootballCatalogue":
        """`for_tactic` plus more blocks on top (an opponent's; see
        `analytics/opponent.attribute_emphasis`). No extra is `for_tactic`,
        cache included; with some, uncached (analytics/CLAUDE.md Phase 7)."""
        if not extra_emphasis:
            return self.for_tactic(tactic_key)
        tactic = self.tactics[tactic_key]
        return self._derive_view(tactic, tuple(tactic.attribute_emphasis) + extra_emphasis) or self

    def _derive_view(
        self, tactic: TacticDefinition, blocks: tuple[AttributeEmphasis, ...]
    ) -> "FootballCatalogue | None":
        """Roles re-weighted by `blocks` (the tactic's, plus an opponent's if
        any), or None if unchanged. Tapers are always the tactic's own."""
        whole_team = _sum_emphasis(*(
            block.attributes for block in blocks if not block.positions and not block.roles
        ))
        assignment_totals = {}
        for slot in tactic.slots:
            for role_key in slot.role_keys:
                total = _sum_emphasis(
                    *(block.attributes for block in blocks
                      if block.applies_to(slot.position, role_key)),
                    slot.attribute_emphasis,
                )
                if total != whole_team:
                    assignment_totals[(slot.key, role_key)] = total
        slot_tapers = {
            slot.key: applicable
            for slot in tactic.slots
            if (applicable := tuple(
                t for t in tactic.attribute_taper if t.covers_position(slot.position)
            ))
        }
        if not whole_team and not assignment_totals and not slot_tapers:
            return None
        roles = {key: _emphasised(role, whole_team) for key, role in self.roles.items()}
        slot_roles = {
            assignment: _emphasised(self.roles[assignment[1]], total)
            for assignment, total in assignment_totals.items()
        }
        return replace(self, roles=roles, slot_roles=slot_roles, slot_tapers=slot_tapers, tactic_view=True)

    def tapers_for_slot(
        self, slot: TacticSlot, role_key: str
    ) -> tuple[AttributeTaper, ...]:
        """The attribute tapers that apply to this exact slot/role pairing."""
        return tuple(
            taper
            for taper in self.slot_tapers.get(slot.key, ())
            if taper.applies_to(slot.position, role_key)
        )

    def role_for_slot(self, slot: TacticSlot, role_key: str) -> RoleDefinition:
        """The role as this slot weights it: a slot override, else the role."""
        return self.slot_roles.get((slot.key, role_key)) or self.roles[role_key]

    def __post_init__(self) -> None:
        if not self.version or not self.roles or not self.tactics:
            raise ValueError("football catalogue version, roles, and tactics are required")
        for key, role in self.roles.items():
            if key != role.key or role.catalogue_version != self.version:
                raise ValueError("role keys and versions must match their catalogue")
        for group in self.exclusive_role_groups:
            unknown = sorted(group.role_keys - set(self.roles))
            if unknown:
                raise ValueError(
                    f"role exclusion group {group.name!r} references unknown roles {unknown!r}"
                )
        known_attributes = {
            attribute.name for role in self.roles.values() for attribute in role.attributes
        }
        for key, tactic in self.tactics.items():
            if key != tactic.key or tactic.catalogue_version != self.version:
                raise ValueError("tactic keys and versions must match their catalogue")
            if not self.tactic_view:
                misspelled = sorted(
                    {t.attribute for t in tactic.attribute_taper} - known_attributes
                )
                if misspelled:
                    raise ValueError(f"tactic {key!r} tapers unknown attributes {misspelled!r}")
            # A misspelled attribute would weight nothing and say nothing.
            for where, emphasis in () if self.tactic_view else (
                *((key, block.attributes) for block in tactic.attribute_emphasis),
                *((f"{key}/{s.key}", s.attribute_emphasis) for s in tactic.slots),
            ):
                unknown = sorted(set(emphasis) - known_attributes)
                if unknown:
                    raise ValueError(
                        f"tactic {where!r} emphasises unknown attributes {unknown!r}"
                    )
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
            if not any(
                self.role_version_is_legal(tactic, role_keys)
                for role_keys in product(
                    *(self.role_keys_for_slot(slot) for slot in tactic.slots)
                )
            ):
                raise ValueError(
                    f"tactic {key!r} has no role version that satisfies the "
                    "catalogue's role exclusion groups"
                )

    def role_version_is_legal(
        self, tactic: TacticDefinition, role_keys: tuple[str, ...]
    ) -> bool:
        """Whether one role per slot (in slot order) breaks no exclusion group."""
        return not any(
            group.is_violated_by(tactic.slots, role_keys)
            for group in self.exclusive_role_groups
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


def _emphasised(
    role: RoleDefinition, emphasis: Mapping[str, int]
) -> RoleDefinition:
    """`role` with each named attribute's weight shifted, clamped to 0-10.

    A missing base weight is zero, so positive emphasis can introduce a
    tactic-specific requirement. Non-positive final weights are omitted.
    """
    if not emphasis:
        return role
    weights = {attribute.name: attribute.weight for attribute in role.attributes}
    for name, delta in emphasis.items():
        weights[name] = min(MAX_EFFECTIVE_WEIGHT, max(0, weights.get(name, 0) + delta))
    attributes = tuple(
        RoleAttribute(name=name, weight=weight)
        for name, weight in weights.items()
        if weight > 0
    )
    if not attributes:
        raise ValueError(f"attribute emphasis leaves role {role.key!r} with no weighted attributes")
    return replace(role, attributes=attributes)


def _role_from_json(raw: Mapping[str, Any], *, version: str) -> RoleDefinition:
    _only_known_keys(raw, _ROLE_KEYS, f"role {raw.get('key')!r}")
    key = _str(raw, "key")
    return RoleDefinition(
        key=key,
        name=_str(raw, "name"),
        eligible_positions=_str_tuple(raw, "positions"),
        attributes=tuple(
            RoleAttribute(name=name, weight=weight)
            for name, weight in parse_attribute_weights(key, raw.get("attributes")).items()
            if weight > 0
        ),
        catalogue_version=version,
        description=_str(raw, "description") if "description" in raw else "",
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
    _only_known_keys(raw, _SLOT_KEYS, f"slot {raw.get('key')!r}")
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
        why=raw.get("why") or "",
        attribute_emphasis=_int_mapping(raw.get("attributeEmphasis"), "slot attributeEmphasis"),
    )


def _tactic_from_json(raw: Mapping[str, Any], *, version: str) -> TacticDefinition:
    _only_known_keys(raw, _TACTIC_KEYS, f"tactic {raw.get('key')!r}")
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
        why_this_shape=raw.get("whyThisShape") or "",
        when_to_use=raw.get("whenToUse") or "",
        when_not_to_use=raw.get("whenNotToUse") or "",
        instruction_rationale=_string_mapping(raw.get("instructionRationale"), "instructionRationale"),
        attribute_emphasis=_emphasis_blocks(raw.get("attributeEmphasis"), _str(raw, "key")),
        attribute_taper=_taper_blocks(raw.get("attributeTaper"), _str(raw, "key")),
    )


def load_catalogue(path: Path = _DATA_PATH) -> FootballCatalogue:
    """Load and validate a versioned football catalogue from JSON.

    `path` is either a data directory (`catalogue.json` plus `roles/` and
    `tactics/`, the shipped layout) or a single self-contained document with
    `roles` and `tactics` arrays, which keeps small hand-built catalogues
    easy to write in tests.

    Every structural rule (eleven unique slots, roles that exist, slots whose
    position the assigned role can actually play) is enforced by the
    dataclasses above exactly as it was when this data was Python literals;
    this function only does the JSON -> dataclass translation, so a malformed
    catalogue file still fails closed at import time rather than producing a
    silently broken recommendation later.
    """
    if path.is_dir():
        document = _read_json(path / "catalogue.json")
        roles_raw = role_documents(path)
        tactics_raw = _tactic_documents(path)
    else:
        document = _read_json(path)
        roles_raw = document.get("roles")
        tactics_raw = document.get("tactics")
    _only_known_keys(
        document,
        _CATALOGUE_KEYS if path.is_dir() else _CATALOGUE_KEYS | {"roles", "tactics"},
        f"catalogue {path.name}",
    )
    version = _str(document, "version")
    if not isinstance(roles_raw, list) or not isinstance(tactics_raw, list):
        raise ValueError(f"catalogue {path} must define roles and tactics")
    roles = {
        role.key: role
        for role in (
            _role_from_json(entry, version=version)
            for entry in roles_raw
        )
    }
    if len(roles) != len(roles_raw):
        raise ValueError(f"catalogue {path} has duplicate role keys")
    tactics = {
        tactic.key: tactic
        for tactic in (_tactic_from_json(entry, version=version) for entry in tactics_raw)
    }
    if len(tactics) != len(tactics_raw):
        raise ValueError(f"catalogue {path} has duplicate tactic keys")
    if path.is_dir():
        # A role with no traits contributes nothing to team balance, silently
        # dragging its tactic's score down. Hand-built test catalogues may omit
        # traits; the shipped data may not.
        untraited = sorted(
            {
                role_key
                for tactic in tactics.values()
                for slot in tactic.slots
                for role_key in slot.role_keys
                if role_key in roles and not roles[role_key].system_traits
            }
        )
        if untraited:
            raise ValueError(
                f"roles used by tactics have no system traits: {untraited!r}"
            )
    return FootballCatalogue(
        version=version,
        roles=roles,
        tactics=tactics,
        exclusive_role_groups=tuple(
            _exclusion_group_from_json(entry)
            for entry in document.get("exclusiveRoleGroups", [])
        ),
    )


def _read_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as data_file:
        return json.load(data_file)


def _tactic_documents(data_dir: Path) -> list[Mapping[str, Any]]:
    """One tactic per `tactics/<key>.json`; the file name must be the key."""
    tactics = []
    for path in sorted((data_dir / "tactics").glob("*.json")):
        tactic = _read_json(path)
        if tactic.get("key") != path.stem:
            raise ValueError(
                f"tactic file {path.name} declares key {tactic.get('key')!r}; "
                "the file name must match the key"
            )
        tactics.append(tactic)
    return tactics


def _exclusion_group_from_json(raw: Mapping[str, Any]) -> RoleExclusionGroup:
    _only_known_keys(raw, _EXCLUSION_KEYS, f"exclusion group {raw.get('name')!r}")
    return RoleExclusionGroup(
        name=_str(raw, "name"),
        position=_str(raw, "position") if "position" in raw else None,
        role_keys=frozenset(_str_tuple(raw, "roles")),
    )


# Every key the loader reads, per kind of entry. A key outside these is an error,
# not a silent no-op: config that nothing reads only misleads whoever edits it
# (a typo such as `whyThisShap` would otherwise be dropped without a word).
_ROLE_KEYS = frozenset({"key", "name", "description", "positions", "system", "attributes"})
_TACTIC_KEYS = frozenset({
    "key", "name", "formation", "mentality", "instructions", "slots", "system",
    "style", "description", "whyGood", "whyThisShape", "whenToUse", "whenNotToUse",
    "instructionRationale", "keyRequirements", "tags", "attributeEmphasis",
    "attributeTaper",
})
_TAPER_KEYS = frozenset({"attribute", "taperBelow", "positions", "roles"})
_SLOT_KEYS = frozenset({"key", "position", "role", "roles", "why", "attributeEmphasis"})
_SYSTEM_KEYS = frozenset({"minimums", "maximumAttackDuties", "maximumCreators"})
_EXCLUSION_KEYS = frozenset({"name", "position", "roles"})
_CATALOGUE_KEYS = frozenset({"version", "exclusiveRoleGroups"})


def _only_known_keys(raw: Mapping[str, Any], known: frozenset[str], where: str) -> None:
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s) {unknown!r}. Nothing reads them, so they are not "
            f"allowed (check the spelling). Known keys: {sorted(known)!r}"
        )


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


def _taper_blocks(value: Any, tactic_key: str) -> tuple[AttributeTaper, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(
            f"tactic {tactic_key!r}: attributeTaper must be a list, each entry "
            '{"attribute": "passing", "taperBelow": 12} with an optional "positions": [...]'
        )
    tapers = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"tactic {tactic_key!r}: attributeTaper entry {index} must be an object")
        _only_known_keys(raw, _TAPER_KEYS, f"tactic {tactic_key!r} attributeTaper entry {index}")
        tapers.append(
            AttributeTaper(
                attribute=_str(raw, "attribute"),
                below=raw.get("taperBelow"),
                positions=_str_tuple(raw, "positions") if "positions" in raw else (),
                roles=_str_tuple(raw, "roles") if "roles" in raw else (),
            )
        )
    return tuple(tapers)


def _emphasis_blocks(value: Any, tactic_key: str) -> tuple[AttributeEmphasis, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(
            f"tactic {tactic_key!r}: attributeEmphasis must be a list of blocks, each "
            '{"attributes": {...}} with optional "positions" and "roles" arrays'
        )
    blocks = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) - {"attributes", "positions", "roles"}:
            raise ValueError(
                f"tactic {tactic_key!r}: attributeEmphasis block {index} may only have "
                "'attributes', 'positions', and 'roles'"
            )
        blocks.append(
            AttributeEmphasis(
                attributes=_int_mapping(raw.get("attributes"), "emphasis attributes"),
                positions=_str_tuple(raw, "positions") if "positions" in raw else (),
                roles=_str_tuple(raw, "roles") if "roles" in raw else (),
            )
        )
    return tuple(blocks)


def _int_mapping(value: Any, name: str) -> Mapping[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
        for k, v in value.items()
    ):
        raise ValueError(f"{name!r} must be an object of whole-number deltas")
    return dict(value)


def _string_mapping(value: Any, name: str) -> Mapping[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ValueError(f"{name!r} must be an object of strings")
    return dict(value)


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
    _only_known_keys(value, _SYSTEM_KEYS, "tactic system")
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
        "Cautious": 4,
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


MVP_CATALOGUE = load_catalogue()
# The version string lives in the JSON data (single source of truth); this
# alias exists only so code that wants "the current catalogue version" does
# not need to import MVP_CATALOGUE just to read one field off it.
CATALOGUE_VERSION = MVP_CATALOGUE.version
