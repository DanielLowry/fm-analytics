from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from fm_analytics.domain import (
    Club,
    GameState,
    Manager,
    Player,
    PlayerContract,
    SourceHealth,
    Squad,
)

from .errors import BridgeSourceError


class LinuxProtonDataSource:
    """Adapt the read-only Python FM20 probe to the bridge contract."""

    name = "linux-proton"

    def __init__(
        self,
        probe_path: str | Path | None = None,
        python_executable: str | None = None,
        timeout_seconds: int | str | None = None,
    ):
        self.probe_path = Path(probe_path) if probe_path else _default_probe_path()
        self.python_executable = python_executable or sys.executable
        try:
            configured_timeout = int(timeout_seconds) if timeout_seconds is not None else 10
        except (TypeError, ValueError):
            configured_timeout = 10
        self.timeout_seconds = max(1, min(60, configured_timeout))
        self._lock = threading.Lock()
        self._cached_document: dict[str, Any] | None = None
        self._cached_at = 0.0

    def get_health(self) -> SourceHealth:
        try:
            self._read_probe()
        except BridgeSourceError as exc:
            return SourceHealth(exc.status, self.name, str(exc))
        return SourceHealth("ready", self.name)

    def get_game(self) -> GameState:
        document = self._read_probe()
        manager = _active_manager(document)
        return GameState(
            game_date=_parse_date(document["game_date"]),
            human_manager=Manager(str(manager["id"]), str(manager["name"])),
            controlled_club=_map_club(manager.get("club")),
        )

    def get_squad(self) -> Squad:
        document = self._read_probe()
        manager = _active_manager(document)
        club = _map_club(manager.get("club"))
        players = tuple(
            _map_player(player, club.id if club else "")
            for player in document["first_team_squad"]
        )
        return Squad(
            club=club,
            as_of_date=_parse_date(document["game_date"]),
            players=players,
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


def _default_probe_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tools" / "fm20_linux_probe.py"


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
        _validate_percent(player.get("condition_percent"), player.get("id"), "condition")
        _validate_percent(
            player.get("match_fitness_percent"), player.get("id"), "match fitness"
        )
        if not isinstance(player.get("positions"), list) or not player["positions"]:
            raise BridgeSourceError(
                "invalid_payload", f"Player '{player.get('id')}' has no positions."
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
