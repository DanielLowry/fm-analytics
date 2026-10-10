"""Which role each player played in a match, and which tactic that adds up to.

FM's player match record carries a role code for the job a player did: one
bit set, and usually the same code for the same role in every match. A
substitute carries the code of the job he did, which is not always that of the
player he replaced when the shape changed with the substitution (a winger off,
a Central Midfielder (Defend) on). One role can have more than one code: the
manager's left-sided Advanced Forward (Attack) is `0x800` up to 26 December
2019 and `0x80000` from 28 December, with nothing else in his record changing
(confirmed on 3 October 2026), so a code is a label to confirm, never an
identity to infer from. FM does not name the role, so a code is mapped to a
catalogue role key:

* `CONFIRMED_ROLE_CODES` holds codes confirmed by the manager against FM's own
  tactics screen (29 September 2026, Vertical 4-4-2 in the Concord Rangers and
  Hampton & Richmond matches). `0x80000000` was first taken from the
  catalogue's default role for that slot (Deep-Lying Forward); the manager
  corrected it on 30 September to the Pressing Forward he actually plays.
  The Ball-Winning Counter 4-3-3 DM's were confirmed on 7 October 2026 for
  the Havant & Waterlooville match (4 August 2020), each agreeing with the
  duty FM saved for the slot: `0x10` Collier's Defensive Midfielder (Defend)
  at DM, `0x8000` Sharpe's Deep-Lying Playmaker (Support) at MCL,
  `0x10000000` Bellamy's Ball-Winning Midfielder (Support) at MCR and
  `0x8000000` Holden's Inside Forward (Attack) at AML;
* codes the manager confirms later are stored in the match history and
  override these; and
* any other code is shown as an unconfirmed role, never guessed.

**A code does not record position or duty.** The same `0x80` winger code is
used at MR in Vertical 4-4-2 and at AMR in Ball-Winning Counter 4-3-3 DM;
the player's recorded position selects the catalogue's position-specific
family. On 28 March 2020 Bellamy played Central
Midfielder (Support) beside Hargreaves at Central Midfielder (Defend), and both
carry `0x20` (confirmed by the manager on 3 October 2026). A code is labelled
with the duty it was confirmed as, but it names a role *family*
(`role_family`): Central Midfielder, whatever the duty. A tactic is matched
by family, and which duty a player had can only come from the slot he filled
(see `analytics.appearance_context`).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Mapping

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.domain.matches import PlayerMatchStats

CONFIRMED_ROLE_CODES: Mapping[int, str] = {
    0x1: "gk_defend",
    0x2: "cd_defend",
    0x4: "fb_support",
    0x10: "dm_defend",
    0x20: "cm_defend",
    0x80: "winger_ml_mr_support",
    0x800: "af_attack",
    0x8000: "dlp_mc_support",
    0x10000: "b2b_support",
    0x8000000: "if_attack",
    0x10000000: "bwm_mc_support",
    0x80000000: "pf_support",
}

# "Central Midfielder (Defend)", "Winger (Support) [ML/MR]": every catalogue role
# name is a role, its duty in brackets, then any positions that tell it apart.
_ROLE_NAME = re.compile(r"^(?P<role>.+?) \((?P<duty>[^)]+)\)(?P<where> \[[^\]]+\])?$")


_SINGLE_DUTY: dict[int, tuple[FootballCatalogue, Mapping[str, str]]] = {}


def _single_duty_roles(catalogue: FootballCatalogue) -> Mapping[str, str]:
    """Roles that are the only duty of their family, which a code therefore names exactly."""
    cached = _SINGLE_DUTY.get(id(catalogue))
    if cached is None or cached[0] is not catalogue:
        sizes = Counter(role_family(catalogue, key) for key in catalogue.roles)
        cached = (catalogue, {
            role_family(catalogue, key): key
            for key in catalogue.roles if sizes[role_family(catalogue, key)] == 1
        })
        _SINGLE_DUTY[id(catalogue)] = cached
    return cached[1]


@lru_cache(maxsize=None)
def _split_name(name: str) -> tuple[str, str] | None:
    """(family, lower-case duty) from a role's name; None when it is not 'Role (Duty)'.

    Cached by name: a match review asks for the same few dozen names many
    thousands of times.
    """
    parts = _ROLE_NAME.match(name)
    return (parts["role"] + (parts["where"] or ""), parts["duty"].lower()) if parts else None


def role_family(catalogue: FootballCatalogue, role_key: str) -> str:
    """The role without its duty: "Central Midfielder", "Winger [ML/MR]"."""
    name = catalogue.roles[role_key].name
    parts = _split_name(name)
    if parts is None:
        raise ValueError(f"role {role_key!r} is not named 'Role (Duty)': {name!r}")
    return parts[0]


def role_duty(catalogue: FootballCatalogue, role_key: str) -> str:
    """The role's duty, lower case: "support" for "Central Midfielder (Support)"."""
    parts = _split_name(catalogue.roles[role_key].name)
    if parts is None:
        raise ValueError(f"role {role_key!r} is not named 'Role (Duty)'")
    return parts[1]


_BY_DUTY: dict[int, tuple[FootballCatalogue, Mapping[tuple[str, str], tuple[str, ...]]]] = {}


def roles_with_duty(catalogue: FootballCatalogue, family: str, duty: str) -> tuple[str, ...]:
    """Every catalogue role of this family with this duty, in catalogue order."""
    cached = _BY_DUTY.get(id(catalogue))
    if cached is None or cached[0] is not catalogue:
        index: dict[tuple[str, str], list[str]] = {}
        for key in catalogue.roles:
            index.setdefault((role_family(catalogue, key), role_duty(catalogue, key)), []).append(key)
        cached = (catalogue, {pair: tuple(keys) for pair, keys in index.items()})
        _BY_DUTY[id(catalogue)] = cached
    return cached[1].get((family, duty), ())


_POSITION_FAMILIES: dict[int, tuple[FootballCatalogue, Mapping[tuple[str, str], str]]] = {}


def _position_families(catalogue: FootballCatalogue) -> Mapping[tuple[str, str], str]:
    """(role name without its position qualifier, position) -> its unique catalogue family."""
    cached = _POSITION_FAMILIES.get(id(catalogue))
    if cached is None or cached[0] is not catalogue:
        families: dict[tuple[str, str], set[str]] = {}
        for key, role in catalogue.roles.items():
            family = role_family(catalogue, key)
            name = family.partition(" [")[0]
            for position in role.eligible_positions:
                families.setdefault((name, position), set()).add(family)
        cached = (catalogue, {pair: next(iter(found)) for pair, found in families.items() if len(found) == 1})
        _POSITION_FAMILIES[id(catalogue)] = cached
    return cached[1]


@dataclass(frozen=True)
class RoleCodes:
    """FM role code -> catalogue role, confirmed codes merged with the manager's."""

    catalogue: FootballCatalogue
    codes: Mapping[int, str]
    # What `infer_tactic` has found for each set of eleven role families: a
    # season repeats a handful of line-ups, and each is checked against every tactic.
    _inferred: dict[tuple[str, ...], str | None] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def build(cls, catalogue: FootballCatalogue, confirmed: Mapping[int, str] = {}) -> RoleCodes:
        codes = dict(CONFIRMED_ROLE_CODES)
        codes.update({code: key for code, key in confirmed.items() if key in catalogue.roles})
        return cls(catalogue, codes)

    def role_key(self, code: int) -> str | None:
        return self.codes.get(code)

    def family(self, code: int, position: str | None = None) -> str | None:
        """The confirmed role family at this position; its duty is not in the code.

        Older captures without positions retain the family originally confirmed.
        Only a unique position variant of that same role can replace it.
        """
        key = self.codes.get(code)
        if key is None:
            return None
        family = role_family(self.catalogue, key)
        if position is None:
            return family
        return _position_families(self.catalogue).get((family.partition(" [")[0], position), family)

    def label(self, code: int, position: str | None = None) -> str:
        """The role a code names: "Central Midfielder", with no duty, since the code
        records none; "Advanced Forward (Attack)" for a role that has only one duty.
        For one player in one match, `appearance_context.appearance_roles` gives
        the duty the slot he filled settles."""
        family = self.family(code, position)
        if family is None:
            return f"Unconfirmed role (FM code {code:#x})"
        key = _single_duty_roles(self.catalogue).get(family)
        if key is not None:
            return self.catalogue.roles[key].name
        return family

    def infer_tactic(self, starters: Iterable[PlayerMatchStats]) -> str | None:
        """The one catalogue tactic these eleven roles fill, if any.

        Each role must take a distinct slot that permits it: the slot's own
        role or an alternative the tactic lists for it, as FM lets a manager
        swap a Deep-Lying Forward for a Pressing Forward and keep the shape.
        A role is matched by family, since its code does not say its duty.
        Nothing is inferred when more than one tactic fits.
        """
        roles = []
        for player in starters:
            family = self.family(player.role_code, player.start_position or player.position)
            if family is None:
                return None
            roles.append(family)
        if len(roles) != 11:
            return None
        key = tuple(sorted(roles))
        if key not in self._inferred:
            matches = [
                tactic.key
                for tactic, permitted in _slot_families(self.catalogue)
                if _fills(permitted, roles)
            ]
            self._inferred[key] = matches[0] if len(matches) == 1 else None
        return self._inferred[key]


_SLOT_FAMILIES: dict[int, tuple[FootballCatalogue, tuple]] = {}


def _slot_families(catalogue: FootballCatalogue) -> tuple[tuple[object, tuple[frozenset[str], ...]], ...]:
    """(tactic, the role families each of its slots permits) for every tactic in the catalogue."""
    cached = _SLOT_FAMILIES.get(id(catalogue))
    if cached is None or cached[0] is not catalogue:
        cached = (catalogue, tuple(
            (tactic, tuple(
                frozenset(role_family(catalogue, key) for key in catalogue.role_keys_for_slot(slot))
                for slot in tactic.slots
            ))
            for tactic in catalogue.tactics.values()
        ))
        _SLOT_FAMILIES[id(catalogue)] = cached
    return cached[1]


def _fills(permitted: tuple[frozenset[str], ...], roles: list[str]) -> bool:
    """Whether every role family can take its own slot that permits it (a bipartite matching)."""
    if len(permitted) != len(roles):
        return False
    holder: dict[int, int] = {}  # slot index -> role index

    def place(role: int, tried: set[int]) -> bool:
        for slot, allowed in enumerate(permitted):
            if roles[role] in allowed and slot not in tried:
                tried.add(slot)
                if slot not in holder or place(holder[slot], tried):
                    holder[slot] = role
                    return True
        return False

    return all(place(role, set()) for role in range(len(roles)))


@dataclass(frozen=True)
class RoleSummary:
    """What one role did across the matches reviewed (full-stats matches only).

    Grouped by the role each player played (`appearance_context.appearance_roles`),
    not by FM code: one code covers every duty of a role, and one role can have
    two codes.
    """

    codes: tuple[int, ...]  # the FM codes its appearances carried
    role_key: str | None  # the exact role with its duty; None when only the role is known
    label: str
    confirmed: bool  # every code was confirmed (none is "Unconfirmed role")
    appearances: int
    starts: int
    minutes: int
    goals: int
    assists: int
    shots: int
    shots_on_target: int
    clear_cut_chances: int
    key_passes: int
    chances_created: int
    dribbles: int
    team_shots: int
    average_rating: float | None

    @property
    def shot_share(self) -> float | None:
        return self.shots / self.team_shots if self.team_shots else None

    def per_90(self, value: int) -> float | None:
        """A count per 90 minutes played; None with no minutes to divide by."""
        return 90 * value / self.minutes if self.minutes else None


def summarise_roles(
    appearances: Iterable[tuple[PlayerMatchStats, str, int, str]], codes: RoleCodes
) -> tuple[RoleSummary, ...]:
    """Group (player line, match key, team shots, his role) by role, most shots first.

    A role's share of shots is out of the team's shots in the matches it was
    played, counted once per match even when two players shared the role.
    """
    totals: dict[str, Counter] = {}
    role_codes: dict[str, set[int]] = {}
    seen_matches: set[tuple[str, str]] = set()
    for player, match_key, team_shots, label in appearances:
        if not player.played or player.role_code == 0:
            continue
        row = totals.setdefault(label, Counter())
        role_codes.setdefault(label, set()).add(player.role_code)
        row["appearances"] += 1
        row["starts"] += int(player.started)
        row["minutes"] += player.minutes
        if (label, match_key) not in seen_matches:
            seen_matches.add((label, match_key))
            row["team_shots"] += team_shots
        for key in ("goals", "assists", "shots", "shots_on_target", "clear_cut_chances",
                    "key_passes", "chances_created", "dribbles"):
            row[key] += player.stat(key)
        if player.rating is not None:
            row["rated"] += 1
            row["rating_total"] += player.rating
    by_name = {role.name: key for key, role in codes.catalogue.roles.items()}
    summaries = [
        RoleSummary(
            codes=tuple(sorted(role_codes[label])),
            role_key=by_name.get(label),
            label=label,
            confirmed=all(codes.role_key(code) is not None for code in role_codes[label]),
            appearances=row["appearances"],
            starts=row["starts"],
            minutes=row["minutes"],
            goals=row["goals"],
            assists=row["assists"],
            shots=row["shots"],
            shots_on_target=row["shots_on_target"],
            clear_cut_chances=row["clear_cut_chances"],
            key_passes=row["key_passes"],
            chances_created=row["chances_created"],
            dribbles=row["dribbles"],
            team_shots=row["team_shots"],
            average_rating=round(row["rating_total"] / row["rated"], 2) if row["rated"] else None,
        )
        for label, row in totals.items()
    ]
    summaries.sort(key=lambda summary: (-summary.shots, -summary.goals, summary.label))
    return tuple(summaries)
