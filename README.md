# FM Analytics

[![CI](https://github.com/DanielLowry/fm-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/DanielLowry/fm-analytics/actions/workflows/ci.yml)

An experimental analytics department for Football Manager 2020. The system is
intended to make recommendations from information visible to the human manager,
without using hidden Current Ability, Potential Ability, or other internal
values.

The repository now contains a live Phase 00 vertical slice for the proven
Linux/Proton environment, plus a deterministic fixture path:

```text
FM20 -> read-only Linux probe -> FMBridge HTTP API -> Python client/monitor
fixture -------------------------> FMBridge HTTP API -> Python client
```

## Repository layout

```text
src/FMBridge/       Small ASP.NET bridge and data-source boundary
src/fm_analytics/   Python client, domain objects, and CLI
tests/              Python contract/client tests
docs/               Architecture and delivery notes
```

## Tests and fixture mode

No third-party Python packages are required.

```bash
uv run fm-analytics --fixture src/FMBridge/fixtures/sample-game.json
uv run python -m unittest discover -s tests -v
```

CI runs the tests and builds the Python package on Python 3.11 and 3.14. It also
restores and builds FMBridge with the .NET 8 SDK. Live Proton/FM20 probes are
deliberately excluded because hosted runners do not have the game process.

To exercise the full HTTP path, install the .NET 8 SDK and use two terminals:

```bash
dotnet run --project src/FMBridge
uv run fm-analytics --base-url http://localhost:5072
```

Useful bridge endpoints are `GET /health`, `GET /game`, and `GET /squad`.

## Run against FM20 on Linux/Proton

The live adapter is proven against FM20 Steam build `20.4.4-1442341` running
through Proton on x86-64 Linux. Start FM20, load the save, then run:

```bash
FM_BRIDGE_SOURCE=linux-proton dotnet run --project src/FMBridge
```

In another terminal, either print the current squad or start the monitor:

```bash
uv run fm-analytics --base-url http://127.0.0.1:5072
python3 tools/fm20_monitor.py
```

Open `http://127.0.0.1:8765` for the monitor. It refreshes every 30 seconds and
offers approved JSON downloads at `/api/status` and `/api/squad`.

To capture a compact baseline and later check an in-game date or squad change:

```bash
python3 tools/phase00_validate.py capture data/phase00-baseline.json
python3 tools/phase00_validate.py compare data/phase00-baseline.json \
  --expect-date-change --expect-squad-change
```

`tools/fm20_linux_probe.py` remains available with `--json` as a direct
diagnostic. The monitor can also use it via `--direct`, but FMBridge is the
normal application boundary. All process memory access is opened read-only.
The live contract deliberately omits hidden Current Ability, Potential
Ability, raw fitness precision, and any field whose manager-visible meaning has
not been established.

## Current boundary

The public contract exposes manager-visible attribute observations as one of:

- a known exact value;
- a scouted minimum/maximum range; or
- unknown.

Hidden FM values should never cross the HTTP boundary. See
[the architecture notes](docs/architecture.md) for the design and the next
implementation step. The complete staged delivery plan starts at
[the phase roadmap](docs/phases/README.md).
