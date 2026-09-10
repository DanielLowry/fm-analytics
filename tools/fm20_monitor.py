#!/usr/bin/env python3
"""Serve a small local status page for the Linux/Proton FM20 probe."""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

try:
    from tools.fm20_linux_probe import ProbeError, choose_pid, probe
except ModuleNotFoundError:  # Support `python3 tools/fm20_monitor.py`.
    from fm20_linux_probe import ProbeError, choose_pid, probe


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
  <footer>Phase 00 probe · manager-visible fields only · refreshes every 30 seconds</footer>
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
    put('process', `PID ${latest.pid}`);
    put('version', latest.expected_product_version);
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


class MonitorHandler(BaseHTTPRequestHandler):
    cache = StatusCache()

    def do_GET(self) -> None:  # noqa: N802
        request = urlparse(self.path)
        if request.path == "/":
            self._send(DASHBOARD.encode(), "text/html; charset=utf-8")
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), MonitorHandler)
    print(f"FM20 monitor listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
