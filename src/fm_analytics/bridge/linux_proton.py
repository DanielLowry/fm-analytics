from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from fm_analytics.domain import (
    AttributeObservation,
    Club,
    GameState,
    Manager,
    Player,
    PREFERRED_FOOT_VALUES,
    PlayerContract,
    SourceHealth,
    Squad,
    SquadTeam,
)

from .errors import BridgeSourceError


# Kept at the bridge boundary as an independent allowlist. The owned reader
# must supply exactly these proven FM20 display attributes for every player.
OWNED_ATTRIBUTE_ALLOWLIST = frozenset({
    "aerialReach", "acceleration", "aggression", "agility", "anticipation",
    "balance", "bravery", "commandOfArea", "communication", "composure",
    "concentration", "corners", "crossing", "decisions", "determination",
    "dribbling", "finishing", "firstTouch", "flair", "handling", "heading",
    "jumpingReach", "kicking", "longShots", "marking", "naturalFitness",
    "offTheBall", "oneOnOnes", "pace", "passing", "positioning",
    "reflexes", "rushingOut", "stamina", "strength", "tackling", "teamwork",
    "technique", "throwing", "vision", "workRate",
})


# The two attribute-scope modes the app is expected to offer as a user-facing
# toggle. "visible" is the default and, by a wide margin, the expected common
# case: exactly what the manager sees in FM, with unknown/range values kept
# as such rather than resolved. "true" -- every player's real underlying
# attribute regardless of the manager's knowledge -- is a deliberate,
# separately-gated mode this source does not implement yet. It fails at
# construction, not at first query, so a caller cannot silently build a page
# around a mode that does not exist. Building it requires its own decision
# about where hidden truth may flow (analytics/scoring must never see it
# implicitly): see docs/property-discovery-playbook.md and the safety model
# in docs/research-automation.md.
ATTRIBUTE_VISIBILITY_MODES = frozenset({"visible", "true"})


class LinuxProtonDataSource:
    """Adapt the read-only Python FM20 probe to the bridge contract."""

    name = "linux-proton"

    def __init__(
        self,
        probe_path: str | Path | None = None,
        python_executable: str | None = None,
        timeout_seconds: int | str | None = None,
        owned_source_path: str | Path | None = None,
        attribute_visibility: str = "visible",
    ):
        self.probe_path = Path(probe_path) if probe_path else _default_probe_path()
        self.owned_source_path = (
            Path(owned_source_path) if owned_source_path else _default_owned_source_path()
        )
        self.python_executable = python_executable or sys.executable
        try:
            configured_timeout = int(timeout_seconds) if timeout_seconds is not None else 10
        except (TypeError, ValueError):
            configured_timeout = 10
        self.timeout_seconds = max(1, min(60, configured_timeout))
        if attribute_visibility not in ATTRIBUTE_VISIBILITY_MODES:
            raise ValueError(
                f"attribute_visibility must be one of {sorted(ATTRIBUTE_VISIBILITY_MODES)}, "
                f"got {attribute_visibility!r}"
            )
        if attribute_visibility == "true":
            raise NotImplementedError(
                "attribute_visibility='true' is not implemented: this source only ever "
                "reads what the manager can see. A true-value mode needs its own gate "
                "so hidden attributes cannot reach analytics/scoring by accident."
            )
        self.attribute_visibility = attribute_visibility
        self._lock = threading.Lock()
        self._cached_document: dict[str, Any] | None = None
        self._cached_at = 0.0

    def get_health(self, *, force: bool = False) -> SourceHealth:
        del force  # The web server, not this low-level source, schedules checks.
        try:
            self._read_probe()
            if not self.owned_source_path.is_file():
                raise BridgeSourceError(
                    "misconfigured",
                    f"FM20 owned-squad source was not found at '{self.owned_source_path}'.",
                )
        except BridgeSourceError as exc:
            return SourceHealth(exc.status, self.name, str(exc))
        return SourceHealth("ready", self.name)

    def get_game(self) -> GameState:
        document = self._read_probe()
        return self._game_from_document(document)

    def read_snapshot(self) -> tuple[GameState, Squad]:
        """Read one coherent, immutable game-and-squad observation.

        This is the refresh entry point.  Unlike the old public sequence of
        ``get_health()``, ``get_game()``, then ``get_squad()``, it does not run
        a separate readiness probe before collecting the actual observation.
        ``_validate_owned_source`` still rejects mixed game/club/player data.
        """
        document = self._read_probe()
        return self._game_from_document(document), self._squad_from_document(document)

    @staticmethod
    def _game_from_document(document: Mapping[str, Any]) -> GameState:
        manager = _active_manager(document)
        return GameState(
            game_date=_parse_date(document["game_date"]),
            human_manager=Manager(str(manager["id"]), str(manager["name"])),
            controlled_club=_map_club(manager.get("club")),
        )

    def get_squad(self) -> Squad:
        document = self._read_probe()
        return self._squad_from_document(document)

    def _squad_from_document(self, document: Mapping[str, Any]) -> Squad:
        manager = _active_manager(document)
        club = _map_club(manager.get("club"))
        if club is None:
            raise BridgeSourceError("save_not_ready", "Active manager has no club.")
        owned = self._run_owned_source()
        observations = _validate_owned_source(owned, document, club.id)

        def _mapped(player: Mapping[str, Any]) -> Player:
            return replace(
                _map_player(player, club.id),
                attributes=observations[str(player["id"])],
            )

        players = tuple(_mapped(player) for player in document["first_team_squad"])
        other_teams = tuple(
            SquadTeam(
                marker=int(team["marker"]),
                players=tuple(_mapped(player) for player in team["players"]),
            )
            for team in document.get("other_club_teams", [])
        )
        return Squad(
            club=club,
            as_of_date=_parse_date(document["game_date"]),
            players=players,
            other_teams=other_teams,
        )

    def _read_probe(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if (
                self._cached_document is not None
                and now - self._cached_at < 1.0
            ):
                return self._cached_document
            document = self._run_probe()
            _validate_document(document)
            self._cached_document = document
            self._cached_at = time.monotonic()
            return document

    def _run_probe(self) -> dict[str, Any]:
        if not self.probe_path.is_file():
            raise BridgeSourceError(
                "misconfigured", f"FM20 probe was not found at '{self.probe_path}'."
            )
        try:
            process = subprocess.Popen(
                [self.python_executable, str(self.probe_path), "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise BridgeSourceError(
                "misconfigured", f"Could not start '{self.python_executable}': {exc}"
            ) from exc
        try:
            output, error = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise BridgeSourceError(
                "timeout", f"FM20 probe exceeded {self.timeout_seconds} seconds."
            ) from exc
        if process.returncode != 0:
            detail = error if error.strip() else output
            cleaned = _clean_detail(detail)
            raise BridgeSourceError(_classify_failure(cleaned), cleaned)
        try:
            document = json.loads(output)
        except json.JSONDecodeError as exc:
            raise BridgeSourceError(
                "invalid_payload", f"FM20 probe returned invalid JSON: {exc}"
            ) from exc
        if not isinstance(document, dict):
            raise BridgeSourceError(
                "invalid_payload", "FM20 probe returned a JSON object"
            )
        return document

    def _run_owned_source(self) -> dict[str, Any]:
        if not self.owned_source_path.is_file():
            raise BridgeSourceError(
                "misconfigured",
                f"FM20 owned-squad source was not found at '{self.owned_source_path}'.",
            )
        try:
            process = subprocess.Popen(
                [self.python_executable, str(self.owned_source_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise BridgeSourceError(
                "misconfigured", f"Could not start '{self.python_executable}': {exc}"
            ) from exc
        try:
            output, error = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise BridgeSourceError(
                "timeout", f"FM20 owned-squad source exceeded {self.timeout_seconds} seconds."
            ) from exc
        if process.returncode != 0:
            detail = _clean_detail(error if error.strip() else output)
            raise BridgeSourceError(_classify_failure(detail), detail)
        try:
            result = json.loads(output)
        except json.JSONDecodeError as exc:
            raise BridgeSourceError(
                "invalid_payload", f"FM20 owned-squad source returned invalid JSON: {exc}"
            ) from exc
        if not isinstance(result, dict):
            raise BridgeSourceError(
                "invalid_payload", "FM20 owned-squad source did not return a JSON object."
            )
        return result


def _default_probe_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tools" / "fm20_linux_probe.py"


def _default_owned_source_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tools" / "fm20_owned_visible_source.py"


def _validate_owned_source(
    owned: Mapping[str, Any],
    probe: Mapping[str, Any],
    club_id: str,
) -> dict[str, dict[str, AttributeObservation]]:
    if (
        owned.get("source") != "live-owned-squad"
        or owned.get("visibilityGuarantee") != "managed-player-exact"
        or owned.get("gameDate") != probe["game_date"]
    ):
        raise BridgeSourceError(
            "invalid_payload", "Owned-squad source provenance or game date disagrees with probe."
        )
    team = owned.get("team")
    if not isinstance(team, dict) or str(team.get("id")) != club_id:
        raise BridgeSourceError("invalid_payload", "Owned-squad source club disagrees with probe.")
    manager = owned.get("manager")
    active = _active_manager(probe)
    if not isinstance(manager, dict) or str(manager.get("id")) != str(active["id"]):
        raise BridgeSourceError("invalid_payload", "Owned-squad source manager disagrees with probe.")
    raw_players = owned.get("players")
    if not isinstance(raw_players, list):
        raise BridgeSourceError("invalid_payload", "Owned-squad source omitted players.")
    expected = {
        str(player["id"]): str(player["name"])
        for player in probe["first_team_squad"]
    }
    for team in probe.get("other_club_teams", []):
        for player in team.get("players", []):
            expected[str(player["id"])] = str(player["name"])
    observations: dict[str, dict[str, AttributeObservation]] = {}
    for player in raw_players:
        if not isinstance(player, dict):
            raise BridgeSourceError("invalid_payload", "Owned-squad player must be an object.")
        player_id = str(player.get("id"))
        if player_id not in expected or player_id in observations:
            raise BridgeSourceError("invalid_payload", "Owned-squad player IDs disagree with probe.")
        if player.get("name") != expected[player_id]:
            raise BridgeSourceError("invalid_payload", "Owned-squad player name disagrees with probe.")
        raw_attributes = player.get("attributes")
        if not isinstance(raw_attributes, dict) or set(raw_attributes) != OWNED_ATTRIBUTE_ALLOWLIST:
            raise BridgeSourceError(
                "invalid_payload", "Owned-squad player attributes disagree with the allowlist."
            )
        if any(
            not isinstance(value, dict) or set(value) != {"visibility", "value"}
            for value in raw_attributes.values()
        ):
            raise BridgeSourceError(
                "invalid_payload", "Owned-squad source returned an unexpected attribute field."
            )
        try:
            decoded = {
                name: AttributeObservation.from_dict(value)
                for name, value in raw_attributes.items()
            }
        except (TypeError, ValueError, KeyError) as exc:
            raise BridgeSourceError("invalid_payload", f"Invalid owned-squad attribute: {exc}") from exc
        if any(item.visibility.value != "known" for item in decoded.values()):
            raise BridgeSourceError(
                "invalid_payload", "Owned-squad source returned a non-exact attribute."
            )
        if any(item.value is None or not 1 <= item.value <= 20 for item in decoded.values()):
            raise BridgeSourceError(
                "invalid_payload", "Owned-squad source returned an out-of-range attribute."
            )
        observations[player_id] = decoded
    if set(observations) != set(expected):
        raise BridgeSourceError("invalid_payload", "Owned-squad player IDs disagree with probe.")
    return observations


def _validate_document(document: Mapping[str, Any]) -> None:
    managers = document.get("human_managers")
    players = document.get("first_team_squad")
    if not isinstance(managers, list) or not isinstance(players, list):
        raise BridgeSourceError(
            "invalid_payload", "Probe response omitted required collections."
        )
    _parse_date(document.get("game_date"))
    active_count = sum(bool(manager.get("active")) for manager in managers)
    if active_count != 1:
        raise BridgeSourceError(
            "save_not_ready",
            f"Expected one active human manager, found {active_count}.",
        )
    ids = [str(player.get("id")) for player in players]
    duplicate = next((item for item in ids if ids.count(item) > 1), None)
    if duplicate is not None:
        raise BridgeSourceError(
            "invalid_payload", f"Duplicate player ID '{duplicate}' in first-team squad."
        )
    for player in players:
        _validate_squad_player(player)
    # Absent is accepted for backward compatibility with an older probe that
    # predates other-club-team support; present but empty is a normal club
    # with no youth/reserve squads FM tracks, not a validation failure.
    other_teams = document.get("other_club_teams", [])
    if not isinstance(other_teams, list):
        raise BridgeSourceError("invalid_payload", "Probe's other-club-teams was not a list.")
    seen_markers: set[int] = set()
    for team in other_teams:
        if not isinstance(team, dict):
            raise BridgeSourceError("invalid_payload", "A club team entry was not an object.")
        marker = team.get("marker")
        if not isinstance(marker, int) or isinstance(marker, bool) or marker == 0:
            raise BridgeSourceError("invalid_payload", "A club team had an invalid marker.")
        if marker in seen_markers:
            raise BridgeSourceError("invalid_payload", f"Duplicate club team marker '{marker}'.")
        seen_markers.add(marker)
        team_players = team.get("players")
        if not isinstance(team_players, list):
            raise BridgeSourceError("invalid_payload", f"Club team '{marker}' omitted players.")
        for player in team_players:
            _validate_squad_player(player)
    all_ids = ids + [
        str(player.get("id")) for team in other_teams for player in team.get("players", [])
    ]
    duplicate = next((item for item in all_ids if all_ids.count(item) > 1), None)
    if duplicate is not None:
        raise BridgeSourceError(
            "invalid_payload", f"Duplicate player ID '{duplicate}' across the club's squads."
        )


def _validate_squad_player(player: Any) -> None:
    if not isinstance(player, dict):
        raise BridgeSourceError("invalid_payload", "A squad player was not an object.")
    _validate_percent(player.get("condition_percent"), player.get("id"), "condition")
    _validate_percent(
        player.get("match_fitness_percent"), player.get("id"), "match fitness"
    )
    if not isinstance(player.get("positions"), list) or not player["positions"]:
        raise BridgeSourceError(
            "invalid_payload", f"Player '{player.get('id')}' has no positions."
        )
    _validate_position_familiarity(
        player.get("position_familiarity"), player.get("id")
    )
    foot = player.get("preferred_foot")
    if foot is not None and foot not in PREFERRED_FOOT_VALUES:
        raise BridgeSourceError(
            "invalid_payload", f"Player '{player.get('id')}' has invalid preferred foot."
        )


def _active_manager(document: Mapping[str, Any]) -> Mapping[str, Any]:
    return next(manager for manager in document["human_managers"] if manager.get("active"))


def _map_club(raw: Any) -> Club | None:
    return Club(str(raw["id"]), str(raw["name"])) if raw is not None else None


def _map_player(raw: Mapping[str, Any], club_id: str) -> Player:
    contract = raw.get("contract")
    return Player(
        id=str(raw["id"]),
        name=str(raw["name"]),
        date_of_birth=_optional_date(raw.get("date_of_birth")),
        age=raw.get("age"),
        positions=tuple(raw["positions"]),
        position_familiarity=dict(raw.get("position_familiarity") or {}),
        preferred_foot=raw.get("preferred_foot"),
        club_id=club_id,
        condition_percent=raw.get("condition_percent"),
        match_fitness_percent=raw.get("match_fitness_percent"),
        availability=str(raw.get("availability", "unknown")),
        injured=raw.get("injured"),
        suspended=raw.get("suspended"),
        contract=_map_contract(contract) if contract is not None else None,
        attributes={},
    )


def _map_contract(raw: Mapping[str, Any]) -> PlayerContract:
    return PlayerContract(
        contract_type=raw.get("contract_type"),
        start_date=_optional_date(raw.get("start_date")),
        end_date=_optional_date(raw.get("end_date")),
        joined_date=_optional_date(raw.get("joined_date")),
        squad_status=raw.get("squad_status"),
        transfer_status=raw.get("transfer_status"),
        contracted_club=_map_club(raw.get("contracted_club")),
    )


def _parse_date(value: Any) -> date:
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BridgeSourceError(
            "invalid_payload", f"Probe returned invalid ISO date '{value}'."
        ) from exc


def _optional_date(value: Any) -> date | None:
    return _parse_date(value) if value is not None else None


def _validate_position_familiarity(value: Any, player_id: Any) -> None:
    """Validate the optional raw 1-20 position-rating map, if the probe sent one.

    Absent is accepted for backward compatibility with an older probe; the
    field is additive per the v1 contract. Present must be a complete, well
    formed rating map so a partial or malformed reading fails closed rather
    than silently degrading an analytics input.
    """
    if value is None:
        return
    if not isinstance(value, dict) or not value:
        raise BridgeSourceError(
            "invalid_payload",
            f"Player '{player_id}' has an invalid position-familiarity map.",
        )
    for position, rating in value.items():
        if not isinstance(position, str) or not position:
            raise BridgeSourceError(
                "invalid_payload",
                f"Player '{player_id}' has a non-string position-familiarity key.",
            )
        if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 20:
            raise BridgeSourceError(
                "invalid_payload",
                f"Player '{player_id}' has an out-of-range position-familiarity rating.",
            )


def _validate_percent(value: Any, player_id: Any, field: str) -> None:
    if value is not None and (not isinstance(value, int) or not 0 <= value <= 100):
        raise BridgeSourceError(
            "invalid_payload", f"Player '{player_id}' has invalid {field} percentage."
        )


def _classify_failure(detail: str) -> str:
    lowered = detail.casefold()
    if "no running fm20 process" in lowered:
        return "game_absent"
    if "year=1900" in lowered:
        return "save_not_loaded"
    if "multiple fm20 processes" in lowered:
        return "ambiguous_process"
    if "cannot open process" in lowered:
        return "permission_denied"
    if any(
        text in lowered
        for text in ("not a pe image", "unsupported executable", "invalid pointer collection")
    ):
        return "incompatible_build"
    return "unavailable"


def _clean_detail(detail: str) -> str:
    cleaned = detail.strip()
    return cleaned[7:] if cleaned.casefold().startswith("error: ") else cleaned
