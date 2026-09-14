#!/usr/bin/env python3
"""Serve a small local status page for the Linux/Proton FM20 probe."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

try:
    from tools.fm20_linux_probe import ProbeError, choose_pid, probe
    from tools.fm20_attribute_page import ATTRIBUTE_PAGE
    from tools.fm20_owned_visible_source import (
        list_full_team_players,
        list_full_visibility_teams,
        source_full_visibility_data,
        source_owned_visible_data,
    )
    from tools.fm20_discoverability_cold_query import run as discoverability_run
    from tools.fm20_player_visibility_query import query_visible_attributes
    from tools.fm20_native_call_log import log_event
except ModuleNotFoundError:  # Support `python3 tools/fm20_monitor.py`.
    from fm20_linux_probe import ProbeError, choose_pid, probe
    from fm20_attribute_page import ATTRIBUTE_PAGE
    from fm20_native_call_log import log_event
    from fm20_owned_visible_source import (
        list_full_team_players,
        list_full_visibility_teams,
        source_full_visibility_data,
        source_owned_visible_data,
    )
    from fm20_discoverability_cold_query import run as discoverability_run
    from fm20_player_visibility_query import query_visible_attributes


DASHBOARD = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FM Analytics Monitor</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #09130f; color: #e9f3ed; }
    main { width: min(920px, calc(100% - 32px)); margin: 48px auto; }
    header { display: flex; justify-content: space-between; gap: 24px; align-items: end; }
    h1 { margin: 0; font-size: clamp(2rem, 7vw, 4.4rem); letter-spacing: -.06em; }
    .eyebrow { color: #73e2a7; text-transform: uppercase; letter-spacing: .16em; font-size: .76rem; }
    .status { display: inline-flex; gap: 8px; align-items: center; color: #b9c9c0; }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: #f3b44d; }
    .online .dot { background: #54e391; box-shadow: 0 0 16px #54e39199; }
    .error .dot { background: #ff756f; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 32px; }
    .card { border: 1px solid #264438; border-radius: 16px; padding: 22px; background: #10221a; min-height: 132px; }
    .card.wide { grid-column: 1 / -1; }
    .label { color: #8eaa9c; font-size: .78rem; text-transform: uppercase; letter-spacing: .11em; }
    .value { margin-top: 12px; font-size: 1.55rem; overflow-wrap: anywhere; }
    .subtle { margin-top: 8px; color: #8eaa9c; font-size: .88rem; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin: 22px 0; }
    button, a.button { appearance: none; border: 1px solid #3b6955; background: #18372a; color: #e9f3ed; border-radius: 9px; padding: 10px 14px; font: inherit; cursor: pointer; text-decoration: none; }
    button:hover, a.button:hover { background: #214b39; }
    pre { display: none; white-space: pre-wrap; padding: 18px; border-radius: 12px; background: #050b08; color: #bce7cf; overflow: auto; }
    .table-wrap { margin-top: 14px; overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 11px 8px; border-bottom: 1px solid #264438; text-align: left; }
    th { color: #8eaa9c; font-size: .76rem; text-transform: uppercase; letter-spacing: .08em; }
    td:last-child { color: #bce7cf; }
    .player-id { color: #668176; font-size: .76rem; margin-top: 3px; }
    .nowrap { white-space: nowrap; }
    footer { color: #668176; margin-top: 28px; font-size: .82rem; }
    @media (max-width: 620px) { header { align-items: start; flex-direction: column; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <header>
    <div><div class="eyebrow">Read-only local source</div><h1>FM Monitor</h1></div>
    <div id="source-status" class="status"><span class="dot"></span><span>Connecting…</span></div>
  </header>
  <div class="actions">
    <button id="refresh">Refresh now</button>
    <button id="toggle-json">Show JSON</button>
    <a class="button" href="/attributes">Attribute proof</a>
    <a class="button" href="/api/status.json?download=1">Download JSON</a>
    <a class="button" href="/api/squad.json?download=1">Download squad</a>
  </div>
  <section class="grid">
    <article class="card"><div class="label">Game date</div><div id="game-date" class="value">—</div></article>
    <article class="card"><div class="label">Controlled club</div><div id="club" class="value">—</div><div id="club-id" class="subtle"></div></article>
    <article class="card"><div class="label">Human manager</div><div id="manager" class="value">—</div><div id="manager-id" class="subtle"></div></article>
    <article class="card"><div class="label">Process</div><div id="process" class="value">—</div><div id="version" class="subtle"></div></article>
    <article class="card wide"><div class="label">Last observation</div><div id="captured" class="value">—</div><div id="error" class="subtle"></div></article>
    <article class="card wide">
      <div class="label">First-team squad</div>
      <div id="squad-count" class="value">—</div>
      <div class="subtle">Visible basics only; per-player morale is not exposed until its mapping is verified.</div>
      <div class="table-wrap"><table><thead><tr><th>Player</th><th>Age</th><th>Positions</th><th>Condition</th><th>Match fitness</th><th>Availability</th><th>Contract</th></tr></thead><tbody id="squad"></tbody></table></div>
    </article>
  </section>
  <pre id="json"></pre>
  <footer>Phase 00 bridge monitor · manager-visible fields only · refreshes every 30 seconds</footer>
</main>
<script>
const byId = id => document.getElementById(id);
let latest = null;
function put(id, value) { byId(id).textContent = value ?? '—'; }
function words(value) {
  if (!value) return 'Unknown';
  const text = value.replaceAll('_', ' '); return text[0].toUpperCase() + text.slice(1);
}
function contractText(player, clubId) {
  const contract = player.contract;
  if (!contract) return 'Not found';
  if (contract.contracted_club && contract.contracted_club.id !== clubId) {
    return `Loan from ${contract.contracted_club.name}`;
  }
  const end = contract.end_date ? ` · to ${contract.end_date}` : '';
  return `${words(contract.contract_type)}${end}`;
}
function percent(value) { return value == null ? '—' : `${value}%`; }
function renderSquad(players, clubId) {
  const body = byId('squad'); body.replaceChildren();
  for (const player of players) {
    const row = document.createElement('tr');
    const playerCell = document.createElement('td'); playerCell.textContent = player.name;
    const id = document.createElement('div'); id.className = 'player-id'; id.textContent = `ID ${player.id}`;
    playerCell.appendChild(id); row.appendChild(playerCell);
    const values = [
      player.age ?? '—',
      player.positions.join(', '),
      percent(player.condition_percent),
      percent(player.match_fitness_percent),
      words(player.availability),
      contractText(player, clubId),
    ];
    for (const value of values) {
      const cell = document.createElement('td'); cell.className = 'nowrap';
      cell.textContent = value; row.appendChild(cell);
    }
    body.appendChild(row);
  }
  put('squad-count', `${players.length} players`);
}
async function refresh() {
  const status = byId('source-status');
  status.className = 'status'; status.lastElementChild.textContent = 'Reading…';
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    latest = await response.json();
    byId('json').textContent = JSON.stringify(latest, null, 2);
    if (!response.ok) throw new Error(latest.error || `HTTP ${response.status}`);
    status.className = 'status online'; status.lastElementChild.textContent = 'Live';
    const manager = latest.human_managers?.find(item => item.active) ?? latest.human_managers?.[0];
    put('game-date', latest.game_date);
    put('manager', manager?.name || 'Not found');
    put('manager-id', manager ? `ID ${manager.id}` : '');
    put('club', manager?.club?.name || 'Not resolved');
    put('club-id', manager?.club ? `ID ${manager.club.id}` : '');
    put('process', latest.pid ? `PID ${latest.pid}` : latest.source);
    put('version', latest.expected_product_version || 'Python bridge');
    put('captured', new Date(latest.observed_at).toLocaleString());
    put('error', '');
    renderSquad(latest.first_team_squad ?? [], manager?.club?.id);
  } catch (error) {
    status.className = 'status error'; status.lastElementChild.textContent = 'Unavailable';
    put('error', error.message);
  }
}
byId('refresh').addEventListener('click', refresh);
byId('toggle-json').addEventListener('click', () => {
  const output = byId('json'); const show = output.style.display !== 'block';
  output.style.display = show ? 'block' : 'none';
  byId('toggle-json').textContent = show ? 'Hide JSON' : 'Show JSON';
});
refresh(); setInterval(refresh, 30000);
</script>
</body>
</html>
"""


class StatusCache:
    def __init__(self, ttl_seconds: float = 10.0):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._document: dict[str, Any] | None = None

    def get(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if (
                not force
                and self._document is not None
                and time.monotonic() - self._loaded_at < self.ttl_seconds
            ):
                return self._document
            result = probe(choose_pid(None))
            self._document = {
                "status": "live",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                **asdict(result),
            }
            self._loaded_at = time.monotonic()
            return self._document


class MonitorSourceError(RuntimeError):
    """The configured monitor source is not ready."""

    def __init__(self, detail: str, status: str = "unavailable"):
        super().__init__(detail)
        self.status = status


class BridgeStatusCache:
    def __init__(self, base_url: str, ttl_seconds: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self._document: dict[str, Any] | None = None

    def get(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if (
                not force
                and self._document is not None
                and time.monotonic() - self._loaded_at < self.ttl_seconds
            ):
                return self._document
            health = self._read("health", accept_error=True)
            if health.get("status") != "ready":
                raise MonitorSourceError(
                    str(health.get("detail") or health.get("status") or "unavailable"),
                    str(health.get("status") or "unavailable"),
                )
            game = _snake_keys(self._read("game"))
            squad = _snake_keys(self._read("squad"))
            manager = {
                **game["human_manager"],
                "club": game.get("controlled_club"),
                "active": True,
            }
            self._document = {
                "status": "live",
                "source": health.get("source", "Python bridge"),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "game_date": game["game_date"],
                "human_managers": [manager],
                "first_team_squad": squad["players"],
            }
            self._loaded_at = time.monotonic()
            return self._document

    def _read(self, path: str, *, accept_error: bool = False) -> dict[str, Any]:
        url = f"{self.base_url}/{path}"
        try:
            with urlopen(url, timeout=10) as response:  # noqa: S310
                payload = json.load(response)
        except HTTPError as exc:
            if not accept_error:
                raise MonitorSourceError(f"FM bridge returned HTTP {exc.code}") from exc
            try:
                payload = json.load(exc)
            except json.JSONDecodeError as decode_error:
                raise MonitorSourceError(
                    f"FM bridge returned HTTP {exc.code}"
                ) from decode_error
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise MonitorSourceError(f"could not reach FM bridge at {url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise MonitorSourceError(f"FM bridge returned a non-object from {url}")
        return payload


def _snake_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): _snake_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_snake_keys(item) for item in value]
    return value


class MonitorHandler(BaseHTTPRequestHandler):
    cache = StatusCache()

    def do_GET(self) -> None:  # noqa: N802
        request = urlparse(self.path)
        if request.path == "/":
            self._send(DASHBOARD.encode(), "text/html; charset=utf-8")
            return
        if request.path == "/attributes":
            self._send(ATTRIBUTE_PAGE.encode(), "text/html; charset=utf-8")
            return
        if request.path == "/api/attributes/catalog":
            self._attribute_catalog()
            return
        if request.path in {
            "/api/status",
            "/api/status.json",
            "/api/squad",
            "/api/squad.json",
        }:
            try:
                source = self.cache.get(force="refresh" in parse_qs(request.query))
                document = (
                    self._squad_document(source)
                    if request.path.startswith("/api/squad")
                    else source
                )
                status = HTTPStatus.OK
            except MonitorSourceError as exc:
                document = {
                    "status": exc.status,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
                status = HTTPStatus.SERVICE_UNAVAILABLE
            except (OSError, ProbeError) as exc:
                document = {
                    "status": "unavailable",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
                status = HTTPStatus.SERVICE_UNAVAILABLE
            headers = {}
            if parse_qs(request.query).get("download") == ["1"]:
                filename = (
                    "fm20-squad.json"
                    if request.path.startswith("/api/squad")
                    else "fm20-status.json"
                )
                headers["Content-Disposition"] = (
                    f'attachment; filename="{filename}"'
                )
            self._send(
                json.dumps(document, indent=2).encode(),
                "application/json; charset=utf-8",
                status,
                headers,
            )
            return
        self._send(b"not found\n", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        started_at = time.monotonic()
        log_event("http_request_started", path=path, client=self.client_address[0])
        if path == "/api/attributes/query/team-stream":
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                log_event(
                    "http_request_failed", path=path, exception_type=type(exc).__name__,
                    exception=str(exc), duration_seconds=time.monotonic() - started_at,
                )
                self._send(
                    json.dumps({"error": str(exc)}).encode(),
                    "application/json; charset=utf-8",
                    HTTPStatus.BAD_REQUEST,
                )
                return
            self._send_ndjson_stream(self._attribute_query_team_stream(payload))
            log_event(
                "http_request_finished", path=path,
                duration_seconds=time.monotonic() - started_at,
            )
            return
        routes = {
            "/api/attributes/teams": self._full_team_search,
            "/api/attributes/players": self._full_team_players,
            "/api/attributes/query": self._attribute_query,
            "/api/discoverability/query": self._discoverability_query,
            "/api/discoverability/attributes": self._discoverability_attributes,
        }
        operation = routes.get(path)
        if operation is None:
            self._send(
                b"not found\n", "text/plain; charset=utf-8", HTTPStatus.NOT_FOUND
            )
            return
        try:
            payload = self._read_json_body()
            document = operation(payload)
            self._send(
                json.dumps(document, indent=2).encode(),
                "application/json; charset=utf-8",
            )
            log_event(
                "http_request_finished", path=path,
                duration_seconds=time.monotonic() - started_at,
            )
        except (KeyError, TypeError, ValueError, OSError, ProbeError) as exc:
            log_event(
                "http_request_failed", path=path, exception_type=type(exc).__name__,
                exception=str(exc), duration_seconds=time.monotonic() - started_at,
            )
            self._send(
                json.dumps({"error": str(exc)}).encode(),
                "application/json; charset=utf-8",
                HTTPStatus.BAD_REQUEST,
            )

    def _attribute_catalog(self) -> None:
        try:
            source = self.cache.get(force=True)
            managers = source.get("human_managers", [])
            manager = next(
                (item for item in managers if item.get("active")),
                managers[0] if managers else None,
            )
            if manager is None or manager.get("club") is None:
                raise MonitorSourceError("active managed team was not found")
            players = source.get("first_team_squad", [])
            club = manager["club"]
            document = {
                "mode": "in-game",
                "team": {
                    "id": club["id"],
                    "name": club["name"],
                    "playerCount": len(players),
                },
                "players": [
                    {"id": item["id"], "name": item["name"]} for item in players
                ],
            }
            status = HTTPStatus.OK
        except (KeyError, MonitorSourceError, OSError, ProbeError) as exc:
            document = {"error": str(exc)}
            status = HTTPStatus.SERVICE_UNAVAILABLE
        self._send(
            json.dumps(document, indent=2).encode(),
            "application/json; charset=utf-8",
            status,
        )

    @staticmethod
    def _require_full_ack(payload: dict[str, Any]) -> None:
        if payload.get("mode") != "full" or payload.get("acknowledged") is not True:
            raise ValueError("full visibility requires explicit acknowledgement")

    @staticmethod
    def _require_ack(payload: dict[str, Any]) -> None:
        if payload.get("acknowledged") is not True:
            raise ValueError("this diagnostic requires explicit acknowledgement")

    def _full_team_search(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_ack(payload)
        query = payload.get("query")
        if not isinstance(query, str):
            raise ValueError("team search query must be a string")
        return {
            "mode": payload.get("mode", "full"),
            "teams": list_full_visibility_teams(
                choose_pid(None), query=query
            ),
        }

    def _full_team_players(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_ack(payload)
        return list_full_team_players(
            choose_pid(None), team_id=self._required_id(payload, "teamId")
        )

    def _managed_club_id(self) -> str | None:
        source = self.cache.get(force=True)
        managers = source.get("human_managers", [])
        manager = next(
            (item for item in managers if item.get("active")),
            managers[0] if managers else None,
        )
        club = manager.get("club") if manager else None
        return club["id"] if club else None

    def _cold_visible_team_data(
        self, pid: int, team_id: str, player_id: int | None
    ) -> dict[str, object]:
        """Any team's players, read via the safe cold-call mechanism.

        Never reads a hidden value: each attribute is exact/range/unknown,
        the same as the manager's own squad. Discoverability of this team's
        players is not verified here -- use Discoverable mode for that.
        """
        found = list_full_team_players(pid, team_id=team_id)
        players = list(found["players"])
        if player_id is not None:
            players = [item for item in players if int(item["id"]) == player_id]
            if not players:
                raise ProbeError(f"player {player_id} was not found on this team")
        return {
            "team": found["team"],
            "players": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "positions": [],
                    "condition_percent": None,
                    "match_fitness_percent": None,
                    "attributes": query_visible_attributes(pid, int(item["id"])),
                }
                for item in players
            ],
        }

    def _attribute_query_team_stream(
        self, payload: dict[str, Any]
    ) -> Iterator[dict[str, object]]:
        """Whole-team cold in-game query, reporting real per-player progress.

        Every player still needs its own set of live calls into FM; this
        just makes that visible instead of leaving the caller staring at a
        blank screen for however long the team takes.
        """
        team_id = self._required_id(payload, "teamId")
        pid = choose_pid(None)
        try:
            found = list_full_team_players(pid, team_id=team_id)
        except (OSError, ProbeError) as exc:
            yield {"type": "error", "error": str(exc)}
            return
        players = list(found["players"])
        total = len(players)
        yield {"type": "start", "team": found["team"], "total": total}
        results = []
        for index, item in enumerate(players, start=1):
            try:
                attributes = query_visible_attributes(pid, int(item["id"]))
            except (OSError, ProbeError, ValueError) as exc:
                yield {"type": "error", "error": f"{item['name']}: {exc}"}
                return
            results.append({
                "id": item["id"],
                "name": item["name"],
                "positions": [],
                "condition_percent": None,
                "match_fitness_percent": None,
                "attributes": attributes,
            })
            yield {
                "type": "progress", "done": index, "total": total,
                "player": item["name"],
            }
        yield {"type": "result", "team": found["team"], "players": results}

    def _send_ndjson_stream(self, events: Iterable[dict[str, object]]) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for event in events:
                self.wfile.write((json.dumps(event) + "\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _attribute_query(self, payload: dict[str, Any]) -> dict[str, object]:
        mode = payload.get("mode", "in-game")
        team_id = self._required_id(payload, "teamId")
        player_id = self._optional_int_id(payload, "playerId")
        pid = choose_pid(None)
        if mode == "in-game":
            if team_id == self._managed_club_id():
                return source_owned_visible_data(
                    pid, team_id=team_id, player_id=player_id
                )
            return self._cold_visible_team_data(pid, team_id, player_id)
        self._require_full_ack(payload)
        return source_full_visibility_data(
            pid, team_id=team_id, player_id=player_id
        )

    def _discoverability_query(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_ack(payload)
        expected_count = self._optional_int_id(payload, "expectedCount")
        pid = choose_pid(None)
        result = discoverability_run(pid, True, True, expected_count, with_names=True)
        if result.get("error"):
            raise ProbeError(result["error"])
        return {
            "mode": "discoverable",
            "gameDate": result.get("gameDate"),
            "managedClub": result.get("managedClub"),
            "sourceCount": result.get("sourceCount"),
            "excludedCount": result.get("excludedCount"),
            "count": result.get("discoverableCount"),
            "players": result.get("discoverablePlayers") or [],
            "matchesExpectedCount": result.get("matchesExpectedCount"),
            "passed": result.get("passed"),
            "caveats": (
                "Research query, not a verified production source. Conservative: "
                "known to miss a small number of high-profile players FM's UI "
                "would list, but has shown no false inclusions in testing. "
                "Package and date sensitivity are not yet independently checked."
            ),
        }

    def _discoverability_attributes(self, payload: dict[str, Any]) -> dict[str, object]:
        self._require_ack(payload)
        player_id = self._optional_int_id(payload, "playerId")
        player_name = payload.get("playerName")
        if player_id is None:
            raise ValueError("playerId is required")
        pid = choose_pid(None)
        attributes = query_visible_attributes(pid, player_id)
        return {
            "mode": "discoverable",
            "team": {"name": "Discoverable pool"},
            "players": [{
                "id": str(player_id),
                "name": player_name or f"Player {player_id}",
                "positions": [],
                "condition_percent": None,
                "match_fitness_percent": None,
                "attributes": attributes,
            }],
        }

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if not 1 <= length <= 16_384:
            raise ValueError("JSON request body must be between 1 and 16384 bytes")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON request: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON request must be an object")
        return payload

    @staticmethod
    def _required_id(payload: dict[str, Any], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value.isdecimal():
            raise ValueError(f"{name} must be a numeric string")
        return value

    @classmethod
    def _optional_int_id(cls, payload: dict[str, Any], name: str) -> int | None:
        value = payload.get(name)
        if value is None:
            return None
        return int(cls._required_id(payload, name))

    @staticmethod
    def _squad_document(source: dict[str, Any]) -> dict[str, Any]:
        managers = source.get("human_managers", [])
        manager = next(
            (item for item in managers if item.get("active")),
            managers[0] if managers else None,
        )
        players = source.get("first_team_squad", [])
        return {
            "status": source["status"],
            "observed_at": source["observed_at"],
            "game_date": source["game_date"],
            "club": manager.get("club") if manager else None,
            "player_count": len(players),
            "players": players,
        }

    def _send(
        self,
        body: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Browsers can abandon a refresh while the live probe is reading.
            pass

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the local FM20 monitor")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--bridge-url",
        default="http://127.0.0.1:5072",
        help="FM bridge URL (default: %(default)s)",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="use the diagnostic memory probe directly instead of the Python bridge",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    MonitorHandler.cache = (
        StatusCache() if args.direct else BridgeStatusCache(args.bridge_url)
    )
    server = ThreadingHTTPServer((args.host, args.port), MonitorHandler)
    source = "direct probe" if args.direct else args.bridge_url
    print(f"FM20 monitor listening on http://{args.host}:{args.port} via {source}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
