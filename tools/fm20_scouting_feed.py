#!/usr/bin/env python3
"""Capture FM's manager-rooted Player Search pool for the Scouting page.

Reads the manager's own Player Search pool from FM's memory, removes players
contracted to the managed club, and writes ``--scouting-json`` input. It does
not replay FM's temporary search-form filters. It records derived non-owned
position labels under the product owner's documented accepted short-term
visibility gap, separately from manager-visible positions.

Visible attributes and interest (transfer/loan) are read for every candidate
via ``tools.fm20_sandbox_queries``, an emulator over a lazily-copied,
read-only view of FM's memory -- FM's own code decides both, nothing here
reimplements the formula, and nothing here can write to the live game. This
replaced the last two things this module ever ran inside FM itself
(``--hydrate-player-id``/``--hydrate-active-search``, Frida calls into the
live process) on 27 September 2026, the evening after those calls were
implicated in a second round of saves that wrote successfully and then failed
to reload; see ``docs/scouting-workspace.md``.

Candidates the sandbox could not read this run keep whatever attributes an
earlier capture (or, for a scouted player, this run's own read-only
visibility calculation) already had; consumers must call that state
uncaptured or historical, not claim that FM shows nothing. The raw position
capture stores its data as ``rawPositions``, so the Scouting page can keep it
off by default and require its own explicit accepted-gap checkbox before
displaying or using it. The page renders captured unknowns as "Scout first"
and uncaptured values as "Capture first" rather than manufacturing either
answer.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools.fm20_discoverability_cold_filter import _source_records
from tools.fm20_discoverability_cold_query import own_contracted_ids
from tools.fm20_discoverability_manager_builder import _live_context
from tools.fm20_frida_discoverability import (
    DiscoverabilityError,
    _active_manager,
    builder_agent_source,
    extract,
)
from tools.fm20_frida_server import FridaServerError, frida_server_session
from tools.fm20_frida_trace import FridaTraceError, preflight, process_alive
from tools.fm20_linux_probe import ProbeError, read_exact
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_cold_query_cache import resolve_player_interfaces
from tools.fm20_native_call_log import log_event, next_call_number
from tools.fm20_sandbox import SandboxError
from tools.fm20_sandbox_queries import (
    DEFAULT_INTEREST_MARGIN,
    SandboxQueryError,
    capture_players,
    resolve_sandbox_context,
    resolve_scout_persons,
)
from tools.fm20_scouted_attributes import capture_scouted_attributes
from tools.fm20_scouting_identity import (
    read_own_club_members,
    read_raw_external_positions,
    read_raw_position_familiarity,
    resolve_source_identity_facts,
    resolve_source_player_names,
)
from tools.fm20_scouting_feed_contract import (
    PoolNotBuiltError,
    PriorVisibility,
    ScoutingFeedError,
    feed_document,
    load_prior_visibility,
)


def connect_to_fm(remote_address: str) -> tuple[Any, int]:
    """Attach to the Windows Frida server and resolve the single FM process.

    Used only by the ``--allow-rebuild`` pool-builder path below: FM has not
    built its own Player Search pool structure yet in this process, and that
    structure has to be built by FM's own code running live. Nothing else in
    this module attaches to FM; visible attributes and interest are read
    through the sandbox instead (see the module docstring).
    """
    import importlib

    try:
        frida_api = importlib.import_module("frida")
        device = frida_api.get_device_manager().add_remote_device(remote_address)
        matches = [
            process for process in device.enumerate_processes()
            if process.name.casefold() == "fm.exe"
        ]
    except Exception as error:  # Frida has binding-specific error classes.
        raise ScoutingFeedError(f"cannot connect to the Windows Frida server: {error}") from error
    if len(matches) != 1:
        raise ScoutingFeedError(f"expected one remote 'fm.exe' process, found {len(matches)}")
    return device, matches[0].pid


def _sandbox_capture(
    pid: int,
    module_base: int,
    candidate_persons: Mapping[int, int],
    *,
    interest_margin: float,
    call_number: int,
) -> tuple[dict[int, dict[str, Any]], dict[int, str | None], dict[int, str | None]]:
    """FM's own visible attributes and interest for every live candidate.

    Never raises for an individual player: a player the sandbox could not
    read this run is simply absent from the returned maps, and the caller
    falls back to whatever it already had. Raises ``SandboxQueryError`` only
    if the sandbox could not be set up at all (an unrecognised search/filter
    identity), in which case the caller degrades the whole refresh to
    read-only-calculation attributes and no interest data, exactly as an
    unavailable Frida server used to.
    """
    context = resolve_sandbox_context(pid)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        interfaces = resolve_player_interfaces(pid, fd, module_base, list(candidate_persons))
        scout_by_id = resolve_scout_persons(fd, module_base, context.knowledge_context, list(candidate_persons))
    finally:
        os.close(fd)
    started = time.monotonic()
    results = capture_players(
        pid, context, interfaces, candidate_persons, scout_by_id, margin=interest_margin,
    )
    log_event(
        "scouting_sandbox_capture_completed", call_number=call_number, pid=pid,
        requested=len(candidate_persons), captured=len(results),
        duration_seconds=time.monotonic() - started,
    )
    attributes_by_id = {
        player_id: {name: obs.to_dict() for name, obs in capture.attributes.items()}
        for player_id, capture in results.items()
    }
    transfer_interest_by_id = {player_id: capture.interest.transfer for player_id, capture in results.items()}
    loan_interest_by_id = {player_id: capture.interest.loan for player_id, capture in results.items()}
    return attributes_by_id, transfer_interest_by_id, loan_interest_by_id


def _drop_future_dated(
    values: Mapping[int, Any], observed_at: Mapping[int, str], live_game_date: str
) -> tuple[dict[int, Any], dict[int, str]]:
    """Discard anything observed after today's live date, keyed to it.

    Reloading an earlier save moves the game date backwards. Without this, a
    fact observed in an abandoned later timeline could carry forward and be
    presented as current, even though that timeline no longer exists. Kept
    strict (``>``, not ``>=``): a fact observed on today's own date is not
    future-dated and must still carry forward normally.
    """
    kept_values = {
        player_id: value for player_id, value in values.items()
        if observed_at.get(player_id, live_game_date) <= live_game_date
    }
    kept_observed_at = {
        player_id: date for player_id, date in observed_at.items()
        if player_id in kept_values
    }
    return kept_values, kept_observed_at


def _lost_visible_attribute_detail(
    earlier: Mapping[str, Any], current: Mapping[str, Any]
) -> bool:
    """Whether an earlier sheet knew something the current sheet no longer does."""
    visibility_rank = {"unknown": 0, "range": 1, "known": 2}
    for name, old_observation in earlier.items():
        if not isinstance(old_observation, Mapping):
            continue
        old_rank = visibility_rank.get(old_observation.get("visibility"), 0)
        new_observation = current.get(name, {})
        new_rank = (
            visibility_rank.get(new_observation.get("visibility"), 0)
            if isinstance(new_observation, Mapping) else 0
        )
        if old_rank > new_rank:
            return True
    return False


def _resolve_knowledge_context(pid: int, module_base: int) -> int:
    """One short-lived, read-only attach just to find the knowledge context.

    Kept as its own function so tests can mock this single seam rather than
    ``os.open`` itself, which every other read-only pass in this module also
    uses for its own, unrelated purpose.
    """
    from tools.fm20_cold_query_cache import resolve_context_and_manager

    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        context, _manager_interface = resolve_context_and_manager(fd, module_base)
        return context
    finally:
        os.close(fd)


def capture_pool(
    pid: int,
    *,
    remote_address: str | None = None,
    allow_rebuild: bool = False,
    interest_margin: float = DEFAULT_INTEREST_MARGIN,
    prior_game_date: str | None = None,
    prior_attributes_by_id: Mapping[int, dict[str, Any]] | None = None,
    prior_attributes_observed_at: Mapping[int, str] | None = None,
    prior_last_known_attributes_by_id: Mapping[int, dict[str, Any]] | None = None,
    prior_last_known_attributes_observed_at: Mapping[int, str] | None = None,
    prior_footedness_by_id: Mapping[int, str] | None = None,
    prior_footedness_observed_at: Mapping[int, str] | None = None,
    prior_scouting_knowledge: Mapping[int, int] | None = None,
    prior_scout_reports: Iterable[int] | None = None,
    prior_names: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Read the manager's scouted players and, if available, the wider pool.

    Two independent things happen here. **Scouted-player attributes** --
    covered in full in ``tools.fm20_scouted_attributes`` -- never depend on
    Player Search: they come from the manager's own scouting-knowledge list
    and FM's own visibility formula, both read-only, and they work the
    instant a save loads. **The wider discovery pool** (used for browsing by
    position with no role chosen, and for anyone not yet scouted) still
    depends on Player Search having been opened -- see below.

    FM keeps the pool in process memory, so a session that has already used
    Player Search can be read with no native call at all -- the same
    read-only footing as the rest of the bridge. That is the normal case and
    it is what this function tries first.

    A freshly started FM has an empty pool: research report
    ``manager-rooted-source-20260913T185503Z.json`` recorded 0 players before
    the builder and 4340 after, on a new PID for the same manager and the same
    in-game date that read 4953 cold in the previous process. Only then is
    running FM's own builder worth considering, because that executes FM code
    inside the live game and can leave a save that will not reload. It
    therefore needs an explicit ``allow_rebuild``. Without it, an empty pool
    no longer refuses the whole refresh outright: if any player is currently
    scouted, that read-only data is still worth returning, with
    ``source.poolAvailable: false`` marking the wider pool as unread this time.
    Only when there is neither a pool nor any scouted player does it raise
    ``PoolNotBuiltError``, so the caller can offer the safer choice of opening
    Player Search in FM instead of approving a rebuild. This is the one
    remaining step that runs FM's own code live -- see the module docstring
    for why every other step here, including every player's visible
    attributes and interest, no longer does.

    Every external candidate's visible attributes and transfer/loan interest
    are read through the sandbox (``_sandbox_capture``), replacing the old
    bounded ``--hydrate-player-id``/``--hydrate-active-search`` Frida path,
    which only ever covered a hand-picked or currently-searched subset. A
    scouted player's own read-only calculation is still computed first and
    used as the floor if the sandbox could not read that particular player
    this run; the sandbox's answer, when available, always overrides it, the
    same "later layer wins" merge the old hydration path used.

    A base feed from an earlier in-game date no longer blocks the refresh --
    the game date always moves on and refusing here just left a stale file on
    disk until someone deleted it by hand. Prior footedness is carried forward
    (nothing here re-captures it live; see ``docs/scouting-workspace.md``);
    prior attributes that are no longer visible move to a separately dated
    last-known snapshot and are never used as current scoring inputs. The
    returned document's own ``gameDate`` is always today's live read. A drift is only logged, not
    enforced -- diagnosing a bad refresh from ``data/logs/fm20-native-calls.jsonl``
    should never require reading the live game by hand. Anything carried
    forward that was observed *after* today's live date is dropped rather than
    kept: loading an earlier save moves the date backwards, and a fact from an
    abandoned later timeline must not be presented as current (see
    ``_drop_future_dated``).
    """
    call_number = next_call_number()
    started_at = time.monotonic()
    log_event(
        "scouting_refresh_started", call_number=call_number, pid=pid,
        allow_rebuild=allow_rebuild, interest_margin=interest_margin,
        prior_game_date=prior_game_date,
    )
    try:
        before, arguments, before_ids = _live_context(pid)
        log_event(
            "scouting_pool_read", call_number=call_number, pid=pid,
            pool_count=len(before_ids), game_date=before.game_date,
        )
        manager = _active_manager(before)
        if manager.club is None:
            raise ScoutingFeedError("the active manager has no controlled club")
        module_base = int(before.module_base, 0)
        expected_base = int(preflight(pid)["moduleBase"], 0)
        if expected_base != module_base:
            raise ScoutingFeedError("probe and Frida preflight module bases differ")

        # Independent of the pool: the manager's own scouting knowledge.
        context = _resolve_knowledge_context(pid, module_base)
        scouted_players, scouted_issues = capture_scouted_attributes(
            pid, module_base, context, before.game_date
        )
        log_event(
            "scouting_knowledge_read", call_number=call_number, pid=pid,
            scouted_count=len(scouted_players), issue_count=len(scouted_issues),
            issues=scouted_issues,
        )

        pool_available = True
        if before_ids:
            after, pool_ids, rebuilt = before, before_ids, False
        elif not allow_rebuild:
            if scouted_players:
                pool_available = False
                after, pool_ids, rebuilt = before, [], False
                log_event(
                    "scouting_pool_unavailable_but_scouted_data_present",
                    call_number=call_number, pid=pid, scouted_count=len(scouted_players),
                )
            else:
                log_event(
                    "scouting_refresh_refused_pool_not_built",
                    call_number=call_number, pid=pid,
                    duration_seconds=time.monotonic() - started_at,
                )
                raise PoolNotBuiltError(
                    "FM has not built this manager's Player Search pool in this process yet, "
                    "and no player is currently scouted either. Open Player Search in FM once "
                    "and retry, or approve asking FM to build it."
                )
        else:
            if remote_address is None:
                raise ScoutingFeedError("a Frida server address is required to rebuild the pool")
            log_event(
                "scouting_pool_rebuild_started", call_number=call_number, pid=pid,
                remote_address=remote_address,
            )
            device, target_pid = connect_to_fm(remote_address)
            builder = extract(
                device,
                target_pid,
                builder_agent_source(before.module_base, arguments),
                script_name="fm20-scouting-pool-builder",
            )
            hook_info = builder.get("thread") or {}
            if not (
                builder["attached"]
                and builder["agentReady"]
                and builder["builderReturnValue"] is not None
                and builder["scriptUnloaded"]
                and builder["detached"]
                and not builder["agentErrors"]
            ):
                detail = next(
                    (item.get("description") for item in builder["agentErrors"] if item.get("description")),
                    "unknown Frida lifecycle failure",
                )
                log_event(
                    "scouting_pool_rebuild_failed", call_number=call_number, pid=pid,
                    hook=hook_info.get("hook"), resting_point=hook_info.get("restingPoint"),
                    agent_errors=builder["agentErrors"],
                    duration_seconds=time.monotonic() - started_at,
                )
                raise ScoutingFeedError(
                    f"Frida Player Search pool builder did not complete cleanly: {detail}"
                )
            after, after_arguments, pool_ids = _live_context(pid)
            if after_arguments != arguments:
                raise ScoutingFeedError("manager-rooted search arguments changed during pool capture")
            if _active_manager(after).id != manager.id:
                raise ScoutingFeedError("the active manager changed during pool capture")
            if after.game_date != before.game_date:
                raise ScoutingFeedError("the game date changed during pool capture")
            if not pool_ids:
                raise ScoutingFeedError("FM's builder returned an empty Player Search pool")
            rebuilt = True
            log_event(
                "scouting_pool_rebuild_completed", call_number=call_number, pid=pid,
                hook=hook_info.get("hook"), resting_point=hook_info.get("restingPoint"),
                thread=hook_info.get("id"), selection=hook_info.get("selection"),
                pool_count_before=len(before_ids), pool_count_after=len(pool_ids),
            )
        if prior_game_date is not None and after.game_date != prior_game_date:
            log_event(
                "scouting_refresh_date_drift", call_number=call_number, pid=pid,
                prior_game_date=prior_game_date, live_game_date=after.game_date,
            )
        if not process_alive(pid):
            raise ScoutingFeedError("FM is not healthy after its Player Search pool was read")

        if pool_available:
            fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
            try:
                records = _source_records(lambda address, size: read_exact(fd, address, size), arguments[0])
            finally:
                os.close(fd)
            if set(records) != set(pool_ids):
                raise ScoutingFeedError("rebuilt Player Search source records do not match its ID set")
        else:
            records = {}

        own_ids = own_contracted_ids(
            (
                (int(player.id), player.contract.contracted_club.id if player.contract and player.contract.contracted_club else None)
                for player in after.first_team_squad
            ),
            manager.club.id,
        )
        # The first team alone is not the whole club: FM's own search also
        # leaves out reserves, youth and non-contract players contracted here
        # (see read_own_club_members).
        own_ids |= read_own_club_members(
            pid,
            {**{player_id: player.person for player_id, player in scouted_players.items()}, **records},
            manager.club.id,
        )
        # A scouted player contracted to the manager's own club is not a
        # recruitment candidate, and a first-team one is exact via the
        # owned-squad path anyway; drop it here rather than publish a second,
        # approximate answer for the same player.
        scouted_players = {
            player_id: player for player_id, player in scouted_players.items()
            if player_id not in own_ids
        }

        if pool_available:
            external_ids = sorted(set(pool_ids) - own_ids)
            names = resolve_source_player_names(
                pid, {player_id: records[player_id] for player_id in external_ids}
            )
            raw_positions_by_id = read_raw_external_positions(
                pid,
                {player_id: records[player_id] for player_id in external_ids},
            )
            identity_facts_by_id = dict(resolve_source_identity_facts(
                pid,
                {player_id: records[player_id] for player_id in external_ids},
                after.game_date,
            ))
        else:
            external_ids = []
            names, raw_positions_by_id, identity_facts_by_id = {}, {}, {}
        for player_id, player in scouted_players.items():
            names[player_id] = player.name
            if player.age is not None:
                identity_facts_by_id.setdefault(player_id, {}).setdefault("age", player.age)
        # A scouted player the pool did not supply still has a Person in FM's
        # memory, so his club and positions can be read the same way as a pool
        # member's. This is what makes the Scouted tab usable before Player
        # Search has ever been opened. One unreadable player is skipped rather
        # than allowed to fail the whole refresh.
        for player_id, player in scouted_players.items():
            if player_id in records:
                continue
            single = {player_id: player.person}
            try:
                raw_positions_by_id.update(read_raw_external_positions(pid, single))
            except ScoutingFeedError:
                pass
            for key, value in resolve_source_identity_facts(pid, single, after.game_date).get(player_id, {}).items():
                identity_facts_by_id.setdefault(player_id, {}).setdefault(key, value)
        # The best known live Person address for every candidate: the pool's
        # own record where there is one, else the scouted player's own Person.
        # This is both the position-familiarity read's input and the sandbox
        # capture's candidate set below -- one definition of "who can we still
        # read live", reused for both.
        candidate_persons = {player_id: records[player_id] for player_id in external_ids}
        candidate_persons.update({
            player_id: player.person for player_id, player in scouted_players.items()
            if player_id not in candidate_persons
        })
        position_familiarity_by_id = read_raw_position_familiarity(pid, candidate_persons)

        prior_attributes_by_id, prior_attributes_observed_at = _drop_future_dated(
            dict(prior_attributes_by_id or {}), dict(prior_attributes_observed_at or {}), after.game_date,
        )
        prior_last_known_attributes_by_id, prior_last_known_attributes_observed_at = (
            _drop_future_dated(
                dict(prior_last_known_attributes_by_id or {}),
                dict(prior_last_known_attributes_observed_at or {}),
                after.game_date,
            )
        )
        prior_footedness_by_id, prior_footedness_observed_at = _drop_future_dated(
            dict(prior_footedness_by_id or {}), dict(prior_footedness_observed_at or {}), after.game_date,
        )
        scouted_attributes_by_id = {
            player_id: {name: obs.to_dict() for name, obs in player.observations.items()}
            for player_id, player in scouted_players.items()
            if player.observations is not None
        }
        attributes_by_id: dict[int, dict[str, Any]] = {}
        attributes_observed_at: dict[int, str] = {}
        # The floor: our own read-only calculation for scouted players, safe
        # but with known gaps (it has no baseline/reputation-knowledge model,
        # see docs/phases/03-information-visibility/03.2). The sandbox below
        # overrides it wherever it could read that player this run.
        attributes_by_id.update(scouted_attributes_by_id)
        attributes_observed_at.update(dict.fromkeys(scouted_attributes_by_id, after.game_date))

        sandboxed_attributes: dict[int, dict[str, Any]] = {}
        transfer_interest_by_id: dict[int, str | None] = {}
        loan_interest_by_id: dict[int, str | None] = {}
        sandbox_error: str | None = None
        if candidate_persons:
            try:
                sandboxed_attributes, transfer_interest_by_id, loan_interest_by_id = _sandbox_capture(
                    pid, module_base, candidate_persons,
                    interest_margin=interest_margin, call_number=call_number,
                )
            except (SandboxError, SandboxQueryError, ProbeError, OSError) as error:
                sandbox_error = str(error)
                log_event(
                    "scouting_sandbox_capture_failed", call_number=call_number, pid=pid,
                    exception_type=type(error).__name__, exception=sandbox_error,
                )
        attributes_by_id.update(sandboxed_attributes)
        attributes_observed_at.update(dict.fromkeys(sandboxed_attributes, after.game_date))

        last_known_attributes_by_id = dict(prior_last_known_attributes_by_id)
        last_known_attributes_observed_at = dict(
            prior_last_known_attributes_observed_at
        )
        # A prior observation is history, not a current fact, when this refresh
        # can no longer see at least one value it contained. Preserve the most
        # recent such sheet with its real observation date, but never feed it
        # into current scores or visibility counts.
        for player_id, earlier in prior_attributes_by_id.items():
            if not _lost_visible_attribute_detail(
                earlier, attributes_by_id.get(player_id, {})
            ):
                continue
            observed_at = prior_attributes_observed_at.get(player_id, after.game_date)
            if observed_at >= last_known_attributes_observed_at.get(player_id, ""):
                last_known_attributes_by_id[player_id] = earlier
                last_known_attributes_observed_at[player_id] = observed_at
        # Footedness is carried forward only; nothing here re-captures it
        # live (see the module docstring and docs/scouting-workspace.md).
        footedness_by_id = dict(prior_footedness_by_id)
        footedness_observed_at = dict(prior_footedness_observed_at)

        current_knowledge = {player_id: player.knowledge for player_id, player in scouted_players.items()}
        # A player whose knowledge record has gone -- retired, sold abroad, a
        # database-only entry now -- is exactly the case the user asked to
        # see flagged rather than silently lost: he must stay in the feed
        # with his last known facts, not just disappear from it.
        dropped_from_scout_reports_ids = set(prior_scouting_knowledge or {}) - set(current_knowledge)
        all_ids = set(external_ids) | set(scouted_players) | dropped_from_scout_reports_ids
        missing_dropped_names = dropped_from_scout_reports_ids - set(names) - set(prior_names or {})
        if missing_dropped_names:
            raise ScoutingFeedError(
                f"{len(missing_dropped_names)} player(s) dropped from scout reports have no "
                "name on record from either this run or the base feed"
            )
        for player_id in dropped_from_scout_reports_ids - set(names):
            names[player_id] = (prior_names or {})[player_id]

        attributes_by_id = {k: v for k, v in attributes_by_id.items() if k in all_ids}
        attributes_observed_at = {k: v for k, v in attributes_observed_at.items() if k in all_ids}
        last_known_attributes_by_id = {
            k: v for k, v in last_known_attributes_by_id.items() if k in all_ids
        }
        last_known_attributes_observed_at = {
            k: v for k, v in last_known_attributes_observed_at.items() if k in all_ids
        }
        footedness_by_id = {k: v for k, v in footedness_by_id.items() if k in all_ids}
        footedness_observed_at = {k: v for k, v in footedness_observed_at.items() if k in all_ids}
        raw_positions_by_id = {k: v for k, v in raw_positions_by_id.items() if k in all_ids}
        position_familiarity_by_id = {k: v for k, v in position_familiarity_by_id.items() if k in all_ids}
        transfer_interest_by_id = {k: v for k, v in transfer_interest_by_id.items() if k in all_ids}
        loan_interest_by_id = {k: v for k, v in loan_interest_by_id.items() if k in all_ids}

        scouting_knowledge_by_id = dict(prior_scouting_knowledge or {})
        scouting_knowledge_by_id.update(current_knowledge)
        scouting_knowledge_by_id = {k: v for k, v in scouting_knowledge_by_id.items() if k in all_ids}
        # FM's Scouted list is the players with a report, not everyone with a
        # knowledge level. A player who has since dropped out keeps whatever
        # the earlier capture said; a pre-schema-4 base feed could not say,
        # so its dropped players keep their old place on the Scouted tab.
        scout_report_ids = {
            player_id for player_id, player in scouted_players.items() if player.has_report
        } | (
            dropped_from_scout_reports_ids
            if prior_scout_reports is None
            else dropped_from_scout_reports_ids & set(prior_scout_reports)
        )

        final, final_arguments, final_pool_ids = _live_context(pid)
        if (
            _active_manager(final).id != manager.id
            or final.game_date != before.game_date
            or not process_alive(pid)
            or (pool_available and (final_arguments != arguments or set(final_pool_ids) != set(pool_ids)))
        ):
            raise ScoutingFeedError("FM state changed while visible attributes were captured")
        document = feed_document(
            all_ids,
            names,
            game_date=after.game_date,
            managed_club={"id": manager.club.id, "name": manager.club.name},
            source_count=len(set(pool_ids)),
            excluded_own_ids=set(pool_ids) & own_ids,
            attributes_by_id=attributes_by_id,
            attributes_observed_at=attributes_observed_at,
            last_known_attributes_by_id=last_known_attributes_by_id,
            last_known_attributes_observed_at=last_known_attributes_observed_at,
            footedness_by_id=footedness_by_id,
            footedness_observed_at=footedness_observed_at,
            raw_positions_by_id=raw_positions_by_id,
            identity_facts_by_id=identity_facts_by_id,
            position_familiarity_by_id=position_familiarity_by_id,
            scouting_knowledge_by_id=scouting_knowledge_by_id,
            dropped_from_scout_reports_ids=dropped_from_scout_reports_ids,
            scout_report_ids=scout_report_ids,
            in_player_search_ids=external_ids if pool_available else None,
            transfer_interest_by_id=transfer_interest_by_id,
            loan_interest_by_id=loan_interest_by_id,
            interest_margin=interest_margin,
            sandboxed_count=len(sandboxed_attributes),
            sandbox_error=sandbox_error,
            pool_available=pool_available,
            rebuilt=rebuilt,
        )
    except BaseException as error:
        log_event(
            "scouting_refresh_failed", call_number=call_number, pid=pid,
            duration_seconds=time.monotonic() - started_at,
            exception_type=type(error).__name__, exception=str(error),
        )
        raise
    log_event(
        "scouting_refresh_completed", call_number=call_number, pid=pid,
        rebuilt=rebuilt, pool_available=pool_available,
        player_count=len(document["players"]),
        scouted_count=len(scouted_players),
        duration_seconds=time.monotonic() - started_at,
    )
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-feed", type=Path,
        help=(
            "preserve visible fields from an earlier feed, even one from a different "
            "in-game date; each field keeps the date it was actually observed"
        ),
    )
    parser.add_argument("--replace", action="store_true", help="replace the explicit --output capture")
    parser.add_argument(
        "--interest-margin", type=float, default=DEFAULT_INTEREST_MARGIN,
        help=(
            "how far below FM's own computed transfer/loan interest cut-off a player "
            f"still counts as possibly interested (default {DEFAULT_INTEREST_MARGIN}, "
            "i.e. 15%% below FM's live cut-off); 1.0 uses FM's own cut-off exactly"
        ),
    )
    parser.add_argument(
        "--allow-rebuild", action="store_true",
        help=(
            "if FM has not built its Player Search pool yet, run FM's own builder "
            "inside the live game to build it. This executes FM code in your "
            "running save and has been observed to be the risky step; opening "
            "Player Search in FM once achieves the same thing without it. "
            "Without this flag an unbuilt pool exits 3 and changes nothing."
        ),
    )
    args = parser.parse_args(argv)
    if args.output.exists() and not args.replace:
        parser.error(f"output already exists: {args.output}")
    if args.replace and not args.output.exists():
        parser.error("--replace requires an existing --output file")
    try:
        prior = load_prior_visibility(args.base_feed) if args.base_feed else None
        pid = choose_pid(args.pid)
        capture = dict(
            allow_rebuild=args.allow_rebuild,
            interest_margin=args.interest_margin,
            prior_game_date=prior.game_date if prior else None,
            prior_attributes_by_id=prior.attributes if prior else {},
            prior_attributes_observed_at=prior.attributes_observed_at if prior else {},
            prior_last_known_attributes_by_id=(
                prior.last_known_attributes if prior else {}
            ),
            prior_last_known_attributes_observed_at=(
                prior.last_known_attributes_observed_at if prior else {}
            ),
            prior_footedness_by_id=prior.footedness if prior else {},
            prior_footedness_observed_at=prior.footedness_observed_at if prior else {},
            prior_scouting_knowledge=prior.scouting_knowledge if prior else {},
            prior_scout_reports=prior.scout_reports if prior else None,
            prior_names=prior.names if prior else {},
        )
        # Frida is needed only for a pool rebuild that will actually run --
        # the one remaining step that runs FM's own code live. A plain
        # refresh, including every player's attributes and interest, is
        # read-only and never starts a Frida server.
        _state, _arguments, pool_ids = _live_context(pid)
        if not pool_ids and args.allow_rebuild:
            executable = Path(preflight(pid)["executable"])
            with frida_server_session(executable) as address:
                document = capture_pool(pid, remote_address=address, **capture)
        else:
            document = capture_pool(pid, **capture)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w" if args.replace else "x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2)
            stream.write("\n")
    except PoolNotBuiltError as error:
        print(f"error: {error}", file=sys.stderr)
        return 3
    except (
        DiscoverabilityError,
        FridaServerError,
        FridaTraceError,
        ProbeError,
        ScoutingFeedError,
        OSError,
        ValueError,
        TimeoutError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    dropped_count = sum(1 for player in document["players"] if player.get("droppedFromScoutReports"))
    currently_scouted_count = sum(
        1 for player in document["players"]
        if player.get("scoutReport") and not player.get("droppedFromScoutReports")
    )
    known_unscouted_count = sum(
        1 for player in document["players"]
        if player.get("scoutReport") is False and not player.get("droppedFromScoutReports")
    )
    print(
        f"Captured {len(document['players'])} manager-discoverable players to {args.output}. "
        + (
            "FM's own builder was run inside the live game to build the pool."
            if document["source"]["poolRebuiltByCapture"]
            else (
                "Read from the pool FM had already built; nothing was written to FM."
                if document["source"]["poolAvailable"]
                else "The wider pool was not available this time; only scouted players were "
                "read. Nothing was written to FM."
            )
        )
        + f" {currently_scouted_count} player(s) with a scout report (FM's Scouted list) and "
        f"{known_unscouted_count} more known without one had visible attributes calculated read-only"
        + (f"; {dropped_count} previously-scouted player(s) no longer have a scout report and "
           "are flagged as such" if dropped_count else "")
        + f". Visible attributes and interest confirmed via the sandbox for "
        f"{document['source']['sandboxedCount']} player(s)"
        + (f" ({document['source']['sandboxError']})" if document["source"].get("sandboxError") else "")
        + "; raw external positions captured under the accepted visibility gap.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
