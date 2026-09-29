"""Which role each player played in a match, and which tactic that adds up to.

FM's player match record carries a role code for the position a player
filled: one bit per role, the same code on the same role in every match, and a
substitute takes the code of the player he replaced. FM does not name the
role, so a code is mapped to a catalogue role key:

* `CONFIRMED_ROLE_CODES` holds codes confirmed by the manager against FM's own
  tactics screen (29 September 2026, Vertical 4-4-2 in the Concord Rangers and
  Hampton & Richmond matches);
* codes the manager confirms later are stored in the match history and
  override these; and
* any other code is shown as an unconfirmed role, never guessed.

Whether a code distinguishes duty (Winger Support from Winger Attack) is not
yet known; it is labelled with the role and duty it was confirmed as.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.domain.matches import PlayerMatchStats

CONFIRMED_ROLE_CODES: Mapping[int, str] = {
    0x1: "gk_defend",
    0x2: "cd_defend",
    0x4: "fb_support",
    0x20: "cm_defend",
    0x80: "winger_ml_mr_support",
    0x800: "af_attack",
    0x10000: "b2b_support",
    0x80000000: "dlf_support",
}


@dataclass(frozen=True)
class RoleCodes:
    """FM role code -> catalogue role, confirmed codes merged with the manager's."""

    catalogue: FootballCatalogue
    codes: Mapping[int, str]

    @classmethod
    def build(cls, catalogue: FootballCatalogue, confirmed: Mapping[int, str] = {}) -> RoleCodes:
        codes = dict(CONFIRMED_ROLE_CODES)
        codes.update({code: key for code, key in confirmed.items() if key in catalogue.roles})
        return cls(catalogue, codes)

    def role_key(self, code: int) -> str | None:
        return self.codes.get(code)

    def label(self, code: int) -> str:
        key = self.codes.get(code)
        if key is None:
            return f"Unconfirmed role (FM code {code:#x})"
        return self.catalogue.roles[key].name

    def infer_tactic(self, starters: Iterable[PlayerMatchStats]) -> str | None:
        """The one catalogue tactic whose roles are exactly these eleven, if any.

        Uses each slot's own role, so a tactic is inferred only when the
        line-up matches it role for role, and only when no other tactic does.
        """
        roles = []
        for player in starters:
            key = self.codes.get(player.role_code)
            if key is None:
                return None
            roles.append(key)
        if len(roles) != 11:
            return None
        wanted = Counter(roles)
        matches = [
            tactic.key
            for tactic in self.catalogue.tactics.values()
            if Counter(slot.role_key for slot in tactic.slots) == wanted
        ]
        return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class RoleSummary:
    """What one role did across the matches reviewed (full-stats matches only)."""

    code: int
    role_key: str | None
    label: str
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
    def confirmed(self) -> bool:
        return self.role_key is not None

    @property
    def shot_share(self) -> float | None:
        return self.shots / self.team_shots if self.team_shots else None

    def per_90(self, value: int) -> float | None:
        """A count per 90 minutes played; None with no minutes to divide by."""
        return 90 * value / self.minutes if self.minutes else None


def summarise_roles(
    appearances: Iterable[tuple[PlayerMatchStats, str, int]], codes: RoleCodes
) -> tuple[RoleSummary, ...]:
    """Group (player line, match key, team shots) by role, most shots first.

    A role's share of shots is out of the team's shots in the matches it was
    played, counted once per match even when two players shared the role.
    """
    totals: dict[int, dict] = {}
    seen_matches: set[tuple[int, str]] = set()
    for player, match_key, team_shots in appearances:
        if not player.played or player.role_code == 0:
            continue
        row = totals.setdefault(player.role_code, Counter())
        row["appearances"] += 1
        row["starts"] += int(player.started)
        row["minutes"] += player.minutes
        if (player.role_code, match_key) not in seen_matches:
            seen_matches.add((player.role_code, match_key))
            row["team_shots"] += team_shots
        for key in ("goals", "assists", "shots", "shots_on_target", "clear_cut_chances",
                    "key_passes", "chances_created", "dribbles"):
            row[key] += player.stat(key)
        if player.rating is not None:
            row["rated"] += 1
            row["rating_total"] += player.rating
    summaries = [
        RoleSummary(
            code=code,
            role_key=codes.role_key(code),
            label=codes.label(code),
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
        for code, row in totals.items()
    ]
    summaries.sort(key=lambda summary: (-summary.shots, -summary.goals, summary.label))
    return tuple(summaries)
