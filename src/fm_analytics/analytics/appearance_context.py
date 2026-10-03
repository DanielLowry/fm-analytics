"""Which job each of our appearances was, and how far each part can be trusted.

Recent form may only count towards a player's score for the exact job it was
earned in: the tactic, the position, and the role with its duty (see
docs/tactic-role-form-plan.md §1). This works that job out for every
appearance with full stats, says where each part came from, and why an
appearance cannot be used. It changes no score.

* **Player:** FM's unique ID. A player without one is never matched by name.
* **Position:** FM's own record of where he played. A starter who ended
  somewhere else did two jobs, and one rating cannot be split between them.
* **Role:** the family of a role code the manager confirmed. The code does
  not record duty, so the duty comes from the tactic: the slot he filled must
  allow exactly one duty of his role, or, where it allows more (either
  Vertical 4-4-2 centre-back may play Cover), the manager must have said which
  he usually plays there in this save. The starting eleven are matched to the
  tactic's slots position by position, using which of a central pair each
  started in (ignored if the catalogue's sides cannot be reconciled with FM's);
  a substitute takes the slot of the player he replaced in the same position.
* **Tactic:** FM does not record it. It is the manager's note on the match if
  he added one, else the one catalogue tactic the starting eleven fits, as the
  match review and export show it (the manager's decision, 3 October 2026).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import permutations
from typing import Iterable, Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.match_roles import RoleCodes, role_family
from fm_analytics.domain.matches import MatchRecord, PlayerMatchStats

# Where the tactic came from.
NOTE = "your note"
LINE_UP = "the line-up"  # the one catalogue tactic the starting eleven fits
# Where a settled duty came from.
FROM_TACTIC = "the tactic"  # the slot allows one duty of his role
FROM_USUAL = "your usual set-up"  # the manager's usual pick for that slot
RECENT_GAME_DAYS = 90  # the form plan's window

# Why an appearance cannot count towards form, in the order they are checked.
FRIENDLY = "friendly"
NO_PLAYER_ID = "player not in the squad when captured"
NO_RATING = "FM gave no rating (too few minutes)"
NO_POSITION = "position not recorded (older capture)"
MOVED = "moved position during the match"
UNCONFIRMED_ROLE = "role not known (unconfirmed FM code)"
NO_TACTIC = "no tactic fits the line-up"
DOES_NOT_FIT = "role doesn't match the tactic there"
NEW_SHAPE = "came on as the shape changed"
DUTY_UNSETTLED = "duty unknown (the tactic allows two)"
EXCLUSIONS = (
    FRIENDLY, NO_PLAYER_ID, NO_RATING, NO_POSITION, MOVED, UNCONFIRMED_ROLE,
    NO_TACTIC, DOES_NOT_FIT, NEW_SHAPE, DUTY_UNSETTLED,
)

_SLOT_SIDES = {"L": "left", "C": "centre", "R": "right"}


@dataclass(frozen=True)
class AppearanceContext:
    match: MatchRecord
    player: PlayerMatchStats
    tactic_key: str | None
    tactic_source: str | None  # NOTE, LINE_UP, or None when not known
    role_family: str | None  # from a confirmed role code
    slot_key: str | None  # the tactic's slot he filled, when only one fits
    role_key: str | None  # his role with its duty, when the tactic settles it
    duty_source: str | None  # FROM_TACTIC or FROM_USUAL when role_key is set
    exclusions: tuple[str, ...]

    @property
    def position(self) -> str | None:
        return self.player.position

    @property
    def usable(self) -> bool:
        return not self.exclusions


@dataclass(frozen=True)
class _Placement:
    slot_key: str | None = None
    role_key: str | None = None
    duty_source: str | None = None
    problem: str | None = None  # DOES_NOT_FIT, NEW_SHAPE or DUTY_UNSETTLED


def appearance_contexts(
    matches: Iterable[MatchRecord],
    club_id: str,
    *,
    notes: Mapping[str, object],
    codes: RoleCodes,
    usual_roles: Mapping[tuple[str, str], str] = {},
) -> tuple[AppearanceContext, ...]:
    """Every appearance of ours in a match with full stats, oldest match first.

    `usual_roles` maps (tactic key, slot key) to the role the manager usually
    plays there, for slots that allow more than one duty of a role.
    """
    contexts = []
    for match in sorted(matches, key=lambda m: (m.date, m.key)):
        if match.detail is None:
            continue
        ours = [player for player in match.detail.players_for(match.side_of(club_id)) if player.played]
        tactic_key = getattr(notes.get(match.key), "tactic_key", None)
        source = NOTE if tactic_key else None
        if tactic_key is None:
            tactic_key = codes.infer_tactic(player for player in ours if player.started)
            source = LINE_UP if tactic_key else None
        tactic = codes.catalogue.tactics.get(tactic_key) if tactic_key else None
        usual = {slot: role for (key, slot), role in usual_roles.items() if key == tactic_key}
        placements = _place(tactic, codes, ours, usual) if tactic is not None else {}
        for player in ours:
            family = codes.family(player.role_code)
            placement = placements.get(player.short_id, _Placement(problem=DOES_NOT_FIT))
            contexts.append(AppearanceContext(
                match=match,
                player=player,
                tactic_key=tactic_key,
                tactic_source=source,
                role_family=family,
                slot_key=placement.slot_key if tactic else None,
                role_key=placement.role_key if tactic else None,
                duty_source=placement.duty_source if tactic else None,
                exclusions=_exclusions(match, player, family, source, placement),
            ))
    return tuple(contexts)


def _exclusions(match, player, family, source, placement) -> tuple[str, ...]:
    reasons = []
    if match.competition.is_friendly:
        reasons.append(FRIENDLY)
    if player.player_id is None:
        reasons.append(NO_PLAYER_ID)
    if player.rating is None:
        reasons.append(NO_RATING)
    if player.position is None:
        reasons.append(NO_POSITION)
    elif player.started and player.start_position not in (None, player.position):
        reasons.append(MOVED)
    if family is None:
        reasons.append(UNCONFIRMED_ROLE)
    if source is None:
        reasons.append(NO_TACTIC)
    elif player.position is not None and family is not None and placement.problem:
        reasons.append(placement.problem)
    return tuple(reasons)


def _place(
    tactic, codes: RoleCodes, ours: Sequence[PlayerMatchStats], usual: Mapping[str, str]
) -> dict[int, _Placement]:
    """Each player's slot and role in the tactic, by short ID, as far as the tactic settles them."""
    catalogue = codes.catalogue
    slots_at = defaultdict(list)
    for slot in tactic.slots:
        slots_at[slot.position].append(slot)
    placements: dict[int, _Placement] = {}

    starters_at = defaultdict(list)
    for player in ours:
        if player.started and player.start_position is not None:
            starters_at[player.start_position].append(player)
    for position, players in starters_at.items():
        placements.update(_place_group(catalogue, codes, slots_at.get(position, []), players, usual))

    slots_by_key = {slot.key: slot for slot in tactic.slots}
    for sub in sorted((p for p in ours if not p.started and p.position), key=lambda p: p.came_on or 0):
        replaced = [
            other for other in ours
            if other is not sub and other.went_off is not None and other.went_off == sub.came_on
            and other.position == sub.position
        ]
        if not replaced:
            placements[sub.short_id] = _Placement(problem=NEW_SHAPE)
            continue
        inherited = placements.get(replaced[0].short_id) if len(replaced) == 1 else None
        if inherited is not None and inherited.slot_key is not None:
            slots = [slots_by_key[inherited.slot_key]]
        else:
            slots = slots_at.get(sub.position, [])
        family = codes.family(sub.role_code)
        placements[sub.short_id] = _settled({slot.key: _family_roles(catalogue, slot, family) for slot in slots}, usual)
    return placements


def _place_group(catalogue: FootballCatalogue, codes: RoleCodes, slots, players, usual) -> dict[int, _Placement]:
    """Match the starters at one position to the tactic's slots there."""
    if len(slots) != len(players):
        return {player.short_id: _Placement(problem=DOES_NOT_FIT) for player in players}
    shared = len(slots) > 1
    families = [codes.family(player.role_code) for player in players]

    def fits(player, family, slot, sides: bool) -> bool:
        if family is not None and not _family_roles(catalogue, slot, family):
            return False
        if sides and shared:
            slot_side = _SLOT_SIDES.get(slot.key[-1])
            player_side = player.start_centre_side or "centre"
            if slot_side is not None and slot_side != player_side:
                return False
        return True

    def assignments(sides: bool) -> list[tuple[int, ...]]:
        return [
            order for order in permutations(range(len(slots)))
            if all(fits(player, family, slots[i], sides) for player, family, i in zip(players, families, order))
        ]

    valid = assignments(True) or assignments(False)
    if not valid:
        return {player.short_id: _Placement(problem=DOES_NOT_FIT) for player in players}
    placements = {}
    for index, (player, family) in enumerate(zip(players, families)):
        chosen = {slots[order[index]].key: slots[order[index]] for order in valid}
        options = {key: _family_roles(catalogue, slot, family) for key, slot in chosen.items()}
        placements[player.short_id] = _settled(options, usual)
    return placements


def _settled(options: Mapping[str, tuple[str, ...]], usual: Mapping[str, str]) -> _Placement:
    """A player's job from the slots he could have filled and the roles of his family each allows."""
    fitting = {key: roles for key, roles in options.items() if roles}
    slot_key = next(iter(fitting)) if len(fitting) == 1 else None
    roles = {role for allowed in fitting.values() for role in allowed}
    if not roles:
        return _Placement(slot_key, problem=DOES_NOT_FIT)
    if len(roles) == 1:
        return _Placement(slot_key, next(iter(roles)), FROM_TACTIC)
    # The tactic allows several duties of his role: the manager's usual pick settles it.
    picked = {usual.get(key) if usual.get(key) in allowed else None for key, allowed in fitting.items()}
    if len(picked) == 1 and None not in picked:
        return _Placement(slot_key, picked.pop(), FROM_USUAL)
    return _Placement(slot_key, problem=DUTY_UNSETTLED)


def duty_choices(catalogue: FootballCatalogue, tactic_key: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(slot key, roles) for each slot that allows two duties of one role, which FM's code cannot tell apart.

    Only these need the manager's usual pick: elsewhere the role code and
    the slot settle the duty on their own.
    """
    choices = []
    for slot in catalogue.tactics[tactic_key].slots:
        by_family = defaultdict(list)
        for key in catalogue.role_keys_for_slot(slot):
            by_family[role_family(catalogue, key)].append(key)
        shared = tuple(key for keys in by_family.values() if len(keys) > 1 for key in keys)
        if shared:
            choices.append((slot.key, shared))
    return tuple(choices)


def _family_roles(catalogue: FootballCatalogue, slot, family: str | None) -> tuple[str, ...]:
    """The roles of this family the slot allows (none for an unconfirmed code)."""
    if family is None:
        return ()
    return tuple(key for key in catalogue.role_keys_for_slot(slot) if role_family(catalogue, key) == family)


def role_label(context: AppearanceContext, codes: RoleCodes) -> str:
    """The role he played, as precisely as is known: with its duty when the slot
    he filled settles it, else as his role code names it."""
    if context.role_key is not None:
        return codes.catalogue.roles[context.role_key].name
    return codes.label(context.player.role_code)


def appearance_roles(
    matches: Iterable[MatchRecord],
    club_id: str,
    *,
    notes: Mapping[str, object],
    codes: RoleCodes,
    usual_roles: Mapping[tuple[str, str], str] = {},
) -> dict[tuple[str, str, int], str]:
    """(match key, side, short ID) -> the role each player who played had.

    Ours carry the duty their slot in the match's tactic settles (Bellamy as
    Central Midfielder (Support) beside Hargreaves at (Defend), both FM code
    `0x20`); the opposition's, whose tactic is unknown, are as the code names them.
    """
    matches = tuple(matches)
    labels = {
        (context.match.key, context.player.side, context.player.short_id): role_label(context, codes)
        for context in appearance_contexts(matches, club_id, notes=notes, codes=codes, usual_roles=usual_roles)
    }
    for match in matches:
        for player in match.detail.players if match.detail else ():
            if player.played:
                labels.setdefault((match.key, player.side, player.short_id), codes.label(player.role_code))
    return labels


# -- the coverage report ------------------------------------------------------


@dataclass(frozen=True)
class JobEvidence:
    tactic_key: str
    position: str
    role_key: str
    appearances: int


@dataclass(frozen=True)
class AppearanceCoverage:
    """How many of the window's appearances could count towards form, and what stops the rest."""

    since: date | None  # matches after this date; None for the whole history
    until: date | None
    appearances: tuple[AppearanceContext, ...]

    @property
    def matches(self) -> int:
        return len({context.match.key for context in self.appearances})

    @property
    def usable(self) -> tuple[AppearanceContext, ...]:
        return tuple(context for context in self.appearances if context.usable)

    @property
    def excluded(self) -> tuple[AppearanceContext, ...]:
        return tuple(context for context in self.appearances if not context.usable)

    def reasons(self) -> list[tuple[str, int]]:
        """Each reason and how many excluded appearances it applies to, in EXCLUSIONS order."""
        counts = Counter(reason for context in self.excluded for reason in context.exclusions)
        return [(reason, counts[reason]) for reason in EXCLUSIONS if counts[reason]]

    def unsettled_duties(self) -> list[tuple[str, str, str, int]]:
        """(tactic, position, role family, appearances) where the tactic allows several duties."""
        counts = Counter(
            (context.tactic_key, context.position, context.role_family)
            for context in self.excluded if DUTY_UNSETTLED in context.exclusions
        )
        return [(*job, count) for job, count in counts.most_common()]

    def jobs(self) -> tuple[JobEvidence, ...]:
        """The exact jobs (tactic, position, role) with usable appearances, most first."""
        counts = Counter((context.tactic_key, context.position, context.role_key) for context in self.usable)
        jobs = [JobEvidence(*job, count) for job, count in counts.items()]
        jobs.sort(key=lambda job: (-job.appearances, job.tactic_key, job.position, job.role_key))
        return tuple(jobs)


def summarise_coverage(
    contexts: Iterable[AppearanceContext], *, since: date | None, until: date | None
) -> AppearanceCoverage:
    """The coverage of appearances in matches after `since` and up to `until`."""
    return AppearanceCoverage(
        since=since,
        until=until,
        appearances=tuple(
            context for context in contexts
            if (since is None or context.match.date > since) and (until is None or context.match.date <= until)
        ),
    )
