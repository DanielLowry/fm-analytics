# FM Analytics

An experimental analytics department for Football Manager 2020. The system is
intended to make recommendations from information visible to the human manager,
without using hidden Current Ability, Potential Ability, or other internal
values.

The repository currently contains a runnable first vertical slice:

```text
fixture data -> FMBridge HTTP API -> Python client -> terminal output
```

The fixture source is deliberate. It fixes the API boundary and lets analytics
work begin while the FM20/FMSCOUT memory adapter is investigated on a Windows
machine with the game running.

## Repository layout

```text
src/FMBridge/       Small ASP.NET bridge and data-source boundary
src/fm_analytics/   Python client, domain objects, and CLI
tests/              Python contract/client tests
docs/               Architecture and delivery notes
```

## Try the Python side

No third-party Python packages are required.

```bash
uv run fm-analytics --fixture src/FMBridge/fixtures/sample-game.json
uv run python -m unittest discover -s tests -v
```

To exercise the full HTTP path, install the .NET 8 SDK and use two terminals:

```bash
dotnet run --project src/FMBridge
uv run fm-analytics --base-url http://localhost:5072
```

Useful bridge endpoints are `GET /health`, `GET /game`, and `GET /squad`.

## Linux/Proton Phase 00 probe

On Linux, a narrow read-only probe can auto-detect FM20 running through Proton
and read the current in-game date:

```bash
python3 tools/fm20_linux_probe.py
```

This probe is feasibility tooling, not a second analytics data source. It reads
only the mapped PE signature and current-date field for the final FM20 20.4.4
executable. Live player extraction still belongs behind FMBridge.

## Current boundary

The public contract exposes manager-visible attribute observations as one of:

- a known exact value;
- a scouted minimum/maximum range; or
- unknown.

Hidden FM values should never cross the HTTP boundary. See
[the architecture notes](docs/architecture.md) for the design and the next
implementation step. The complete staged delivery plan starts at
[the phase roadmap](docs/phases/README.md).
